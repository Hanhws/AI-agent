"""1단 · 분류 (README 3-1). 요청 나누기 → 분류 → 붙일 자리를 LLM 호출 한 번으로 받아요.

지난 대화를 불러올 때는 턴마다 부르면 너무 느리고 구독 한도를 많이 써서, 한 대화의 턴을 몇 개씩
묶어 한 번에 물어요. 프롬프트 원문은 backend/prompts/classify.txt (문구는 기획 담당).
같은 호출에서 2단(investigate.py)이 확인할 후보도 받아요: 빠진 것 같은 요청(open) · 요청보다 넓은 변경(wide).
답을 간추린 두세 줄(gist)도 같은 호출에서 받아요. 화면이 턴을 접어 보여 줄 때 써요 (호출 수는 그대로, 출력만 조금 늘어요).
"""
import collections
import json
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from .. import config, store, usage
from ..engines import BadOutput, EngineError, OutOfCalls, get_engine, resolve_name
from . import investigate, tools

SYSTEM = (config.ROOT / "backend" / "prompts" / "classify.txt").read_text(encoding="utf-8")

_TEXT = {"type": ["string", "null"]}
SCHEMA = {
    "type": "object",
    "properties": {"turns": {"type": "array", "items": {
        "type": "object",
        "properties": {
            "id": {"type": "string"}, "title": {"type": "string"}, "depth": {"type": "integer", "enum": [0, 1, 2]},
            "seg": _TEXT, "topic": _TEXT, "chose": {"type": "boolean"}, "dec": _TEXT, "dec_note": _TEXT, "ref": _TEXT,
            "parts": {"type": "array", "items": {
                "type": "object",
                "properties": {"t": {"type": "string"}, "type": {"type": "string", "enum": ["q", "task", "rev"]},
                               "target": _TEXT, "open": {"type": "boolean"}},
                "required": ["t", "type", "target", "open"], "additionalProperties": False,
            }},
            "wide": {"type": "boolean"},
            "gist": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["id", "title", "depth", "seg", "topic", "chose", "dec", "dec_note", "ref", "parts", "wide", "gist"],
        "additionalProperties": False,
    }}},
    "required": ["turns"], "additionalProperties": False,
}

CHUNK = 8                 # 한 번에 묻는 턴 수
USER_CLIP = 500           # 질문은 앞부분
AI_HEAD, AI_TAIL = 500, 400   # 답은 앞과 끝 (결론은 끝에 있어요). 간추리려면 분류할 때(220 · 220)보다 넉넉히 봐야 해요
GIST_LINES, GIST_MAX = 4, 70  # 답 간추림: 줄 수 · 한 줄 길이
STATE_MAINS, STATE_DECISIONS = 12, 8
TITLE_MAX, SEG_MAX, DEC_MAX, PART_MAX = 18, 12, 40, 60   # 역 라벨은 두 줄(12자 안팎)까지 보여요
DEC_NOTE_MAX = 120        # 정한 것을 풀어 쓴 한 문장 (이어 가기 요약에 써요)
MAX_TRIES = 2
STALE = 600               # 답이 끝났다는 표시 없이 이만큼(초) 지난 턴은 끝난 것으로 봐요


def _clip(text, limit):
    text = " ".join((text or "").split())
    return text if len(text) <= limit else text[:limit] + "…"


def _clip_ends(text, head, tail):
    text = " ".join((text or "").split())
    return text if len(text) <= head + tail + 1 else text[:head] + " … " + text[-tail:]


def _word(value, limit):
    value = " ".join(value.split()) if isinstance(value, str) else ""
    if len(value) > limit:
        value = value[:limit - 1].rstrip() + "…"
    return value or None


def gist_lines(value) -> list:
    """엔진이 준 답 간추림을 화면에 실을 모양으로: 글 줄만, 너무 긴 줄은 자르고, 네 줄까지."""
    lines = [_word(line, GIST_MAX) for line in value] if isinstance(value, list) else []
    return [line for line in lines if line][:GIST_LINES]


def _age(row) -> float:
    return (datetime.now(timezone.utc) - datetime.fromisoformat(row["created_at"])).total_seconds()


def pending(rows) -> list:
    """아직 분류하지 않은 턴. 답이 오는 중인 마지막 턴은 끝날 때까지 기다려요."""
    out = []
    for index, row in enumerate(rows):
        if row["classified"] != 0:
            continue
        last = index == len(rows) - 1
        if last and row["state"] == "open" and _age(row) < STALE:
            continue
        out.append(row)
    return out


def build_input(conn, chat, rows, batch) -> dict:
    """docs/agent-prompt.md 1번의 입력을 턴 여러 개에 맞게 넓힌 것. id는 그 대화 안의 차례 번호예요."""
    before = [r for r in rows if r["seq"] < batch[0]["seq"]]
    mains = [r for r in before if r["depth"] == 0]
    chain = []
    for row in reversed(before):
        if row["depth"] == 0:
            break
        chain.insert(0, row)
    project = conn.execute("SELECT name FROM projects WHERE id = ?", (chat["project_id"],)).fetchone()
    files = collections.defaultdict(list)
    for r in conn.execute(
        "SELECT turn_id, base_name FROM files WHERE turn_id IN (%s)" % ",".join("?" * len(batch)),
        [row["id"] for row in batch],
    ):
        files[r["turn_id"]].append(r["base_name"])
    # 바뀐 줄 수: 같은 파일 안에서 요청보다 넓게 바뀐 것도 짐작할 수 있게 (wide)
    lines = collections.defaultdict(collections.Counter)
    for r in conn.execute(
        "SELECT turn_id, file, old, new FROM edits WHERE turn_id IN (%s)" % ",".join("?" * len(batch)),
        [row["id"] for row in batch],
    ):
        lines[r["turn_id"]][Path(r["file"]).name] += tools.changed_count(r["old"], r["new"])

    def turn_input(r):
        out = {"id": str(r["seq"]), "user": _clip(r["user"], USER_CLIP),
               "ai": _clip_ends(r["ai"], AI_HEAD, AI_TAIL), "edited_files": files[r["id"]][:8]}
        if lines[r["id"]]:
            out["changed_lines"] = dict(lines[r["id"]].most_common(8))
        return out

    return {
        "project": project["name"] if project else None,
        "chat": {"title": chat["title"]},
        "state": {
            "main": [{"id": str(r["seq"]), "title": r["title"], "dec": r["dec"]} for r in mains[-STATE_MAINS:]],
            "open_side_chain": {
                "anchor": str(mains[-1]["seq"]),
                "nodes": [{"id": str(r["seq"]), "depth": r["depth"], "title": r["title"]} for r in chain],
            } if chain and mains else None,
            "current_segment": next((r["seg"] for r in reversed(before) if r["seg"]), None),
            "recent_decisions": [r["dec"] for r in before if r["dec"]][-STATE_DECISIONS:],
        },
        "turns": [turn_input(r) for r in batch],
    }


def apply_output(conn, rows, batch, output) -> int:
    """LLM이 준 값을 그대로 믿지 않아요. 범위를 벗어난 값은 고치고, 없는 턴을 가리키면 버려요.
    빠진 것 같은 요청과 넓은 변경은 후보로만 적고, 2단이 확인해요(turns.look)."""
    chat = store.chat_row(conn, rows[0]["chat_id"]) if rows else None
    by_seq = {str(r["seq"]): r for r in rows}
    wanted = {str(r["seq"]) for r in batch}
    depth_of = {r["seq"]: r["depth"] for r in rows if r["classified"] == 1}
    seen_main = any(r["depth"] == 0 and r["classified"] != 0 for r in rows if r["seq"] < batch[0]["seq"])
    answers = {}
    for item in (output or {}).get("turns") or []:
        if isinstance(item, dict) and str(item.get("id")) in wanted:
            answers.setdefault(str(item["id"]), item)
    done = 0
    for row in batch:
        item = answers.get(str(row["seq"]))
        if item is None:
            continue
        title = _word(item.get("title"), TITLE_MAX)
        if not title:
            continue
        previous = depth_of.get(row["seq"] - 1, 0)
        depth = item.get("depth") if item.get("depth") in (0, 1, 2) else 0
        if not seen_main:
            depth = 0                          # 갈라질 본류가 아직 없어요
        elif depth == 2 and previous == 0:
            depth = 1                          # 곁길 없이 곁길 안의 곁길이 될 수 없어요

        def earlier(ref):
            target = by_seq.get(str(ref)) if ref is not None else None
            return target["id"] if target is not None and target["seq"] < row["seq"] else None

        parts = []
        for part in item.get("parts") or []:
            text = _word(part.get("t"), PART_MAX) if isinstance(part, dict) else None
            if text and part.get("type") in ("q", "task", "rev"):
                parts.append({"t": text, "type": part["type"], "target": earlier(part.get("target")),
                              "open": store.MAYBE_MISSING if part.get("open") is True else 0})
        parts = parts if len(parts) >= 2 else None    # 요청이 하나면 나누지 않아요 (빠질 것도 없어요)
        chose = item.get("chose", True)
        dec = _word(item.get("dec"), DEC_MAX) if chose else None
        store.set_classification(
            conn, row["id"], title=title, depth=depth,
            seg=_word(item.get("seg"), SEG_MAX), topic=_word(item.get("topic"), SEG_MAX),
            # 글 칸은 비워 두라고 해도 채우는 버릇이 있어서, 골랐는지(chose)를 먼저 묻고 아니면 정함을 버려요
            dec=dec, dec_note=_word(item.get("dec_note"), DEC_NOTE_MAX) if dec else None,
            ret=(depth == 0 and previous > 0), ref=earlier(item.get("ref")),
            parts=parts, look=investigate.triggers(conn, chat, rows, row, parts, item.get("wide") is True),
            gist=gist_lines(item.get("gist")) if row["ai"].strip() else [],      # 답이 없는 턴은 간추릴 것도 없어요
        )
        depth_of[row["seq"]] = depth
        seen_main = seen_main or depth == 0
        done += 1
    return done


class Classifier:
    """분류할 대화를 줄 세워 하나씩 처리하고, 분류가 끝난 대화는 2단(checker)에 넘겨요.
    엔진은 한 번에 하나만 불러요. 1단을 기다리는 대화가 있으면 그것이 먼저예요."""

    def __init__(self, runtime, engine="auto", max_calls=None):
        self.rt = runtime
        self._engine = engine          # "auto" · 엔진 이름 · 엔진 객체 · None
        self._asked = engine           # 처음에 받은 그대로. 엔진을 다시 고를 때 써요
        self.queue = collections.deque()
        self.wake = threading.Event()
        self.tries = collections.Counter()
        self.max_calls = config.MAX_CALLS if max_calls is None else max_calls
        self.status = {"engine": None, "running": None, "calls": 0, "turns": 0, "error": None, "paused": False,
                       "checking": None, "checks": 0}
        self.checker = investigate.Investigator(self)
        self.gist_wanted = set()       # 예전에 분류한 턴에도 답 간추림을 채워 달라는 대화들 (화면이 부탁해요)

    def engine(self):
        if isinstance(self._engine, str):
            name = resolve_name(None if self._engine == "auto" else self._engine)
            self._engine = get_engine(name)
            self.status["engine"] = name
        elif self.status["engine"] is None:
            self.status["engine"] = getattr(self._engine, "name", "none") if self._engine else "none"
        return self._engine

    def reset_engine(self) -> None:
        """엔진을 다시 골라요 (API 키를 넣거나 지운 뒤). 멈춰 있었으면 다시 돌아요."""
        if isinstance(self._asked, str):
            self._engine = self._asked
            self.status["engine"] = None
            self.checker.forget_engine()
        self.resume()

    def request(self, chat_id, front=False) -> None:
        if not chat_id or chat_id in self.queue:
            return
        if front:
            self.queue.appendleft(chat_id)
        else:
            self.queue.append(chat_id)
        self.wake.set()

    def want_gist(self, chat_id) -> None:
        """이 대화의 이미 분류한 턴에 답 간추림이 없으면 채워 달라고 줄을 세워요. 분류 · 할 일은 건드리지 않아요."""
        if chat_id:
            self.gist_wanted.add(chat_id)
            self.request(chat_id, front=True)

    def resume(self) -> None:
        self.status.update(error=None, paused=False)
        self.wake.set()

    def pause(self) -> None:
        self.status["paused"] = True

    def call(self, system, payload, schema, engine=None):
        """엔진 호출 한 번. 1단 · 2단이 같은 한도를 써요."""
        engine = engine or self.engine()
        if self.status["calls"] >= self.max_calls:
            self.status.update(paused=True, error=f"이번에 켠 뒤로 정리 호출을 {self.max_calls}번 써서 멈췄어요.")
            raise OutOfCalls()
        self.status["calls"] += 1
        return engine.complete_json(system, payload, schema)

    def classify_chat(self, conn, chat_id) -> int:
        """그 대화의 밀린 턴을 CHUNK개씩 분류해요. 분류한 턴 수를 돌려줘요."""
        engine = self.engine()
        chat = store.chat_row(conn, chat_id)
        if engine is None or chat is None or chat["hidden"]:
            return 0                     # 목록에서 뺀 대화에는 정리 호출을 쓰지 않아요
        total = 0
        while not self.status["paused"]:
            rows = store.chat_turns(conn, chat_id)
            batch = pending(rows)[:CHUNK]
            if not batch:
                break
            payload = json.dumps(build_input(conn, chat, rows, batch), ensure_ascii=False)
            began = time.time()
            try:
                output = self.call(SYSTEM, payload, SCHEMA, engine)
            except OutOfCalls:
                break
            except BadOutput:
                output = None            # 형식이 틀린 답. 이 묶음만 실패로 세요 (거듭되면 임시 제목 그대로 둬요)
            with conn:
                done = apply_output(conn, rows, batch, output)
                for row in batch:
                    self.tries[row["id"]] += 1
                    if self.tries[row["id"]] >= MAX_TRIES:
                        conn.execute(
                            "UPDATE turns SET classified = -1 WHERE id = ? AND classified = 0", (row["id"],)
                        )
            total += done
            self.status["turns"] += done
            usage.record(conn, "classify", turns=len(batch), done=done, seconds=time.time() - began)
            self.rt.bump()
        if total:
            usage.note_chat(conn, chat_id)
        if chat_id in self.gist_wanted and not self.status["paused"]:
            self.gist_wanted.discard(chat_id)
            self.fill_gist(conn, chat, engine)
        return total

    def fill_gist(self, conn, chat, engine) -> int:
        """gist 칸이 생기기 전에 분류한 턴에 답 간추림만 채워요. 같은 정리 호출을 쓰되 간추림만 받아 적어요
        (제목 · 곁길 · 정함 · 할 일은 그대로). 한 묶음에 한 번만 물어요: 못 받은 턴은 빈 것으로 두고 다시 묻지 않아요."""
        filled = 0
        while not self.status["paused"]:
            rows = store.chat_turns(conn, chat["id"])
            batch = store.without_gist(conn, chat["id"])[:CHUNK]
            if not batch:
                break
            payload = json.dumps(build_input(conn, chat, rows, batch), ensure_ascii=False)
            try:
                output = self.call(SYSTEM, payload, SCHEMA, engine)
            except OutOfCalls:
                break
            except BadOutput:
                output = None
            answers = {str(item.get("id")): item for item in (output or {}).get("turns") or [] if isinstance(item, dict)}
            with conn:
                for row in batch:
                    lines = gist_lines((answers.get(str(row["seq"])) or {}).get("gist")) if row["ai"].strip() else []
                    store.set_gist(conn, row["id"], lines)
                    filled += 1 if lines else 0
            self.rt.bump()
        return filled

    def step(self, conn) -> bool:
        """줄 맨 앞의 대화 하나를 정리(1단)하거나, 1단이 기다리는 대화가 없으면 2단 확인을 턴 하나만큼 해요.
        할 일이 없으면 False."""
        if self.status["paused"]:
            return False
        if self.queue:
            chat_id = self.queue.popleft()
        elif self.checker.queue:
            chat_id = None
        else:
            return False
        self.status["running"] = chat_id
        did, stopped = True, None
        try:
            if chat_id is not None:
                self.classify_chat(conn, chat_id)
                self.checker.request(chat_id)      # 분류가 끝난 대화는 2단이 이어서 봐요
            else:
                did = self.checker.step(conn)
        except OutOfCalls:
            stopped = "limit"
        except EngineError as exc:
            # 로그인이 풀렸거나 한도에 걸렸을 수 있어요. 계속 두드리지 않고 멈춰요
            self.status.update(error=str(exc)[:200], paused=True)
            stopped = "engine"
        except Exception as exc:
            self.status["error"] = str(exc)[:200]
            stopped = "other"
        if stopped:
            usage.record(conn, "stop", where="classify" if chat_id is not None else "check", why=stopped)
        self.status["running"] = None
        if did:
            self.rt.bump()
        return did

    def run_forever(self, stop) -> None:
        conn = self.rt.connect()
        while not stop.is_set():
            if not self.step(conn):
                self.wake.wait(1.0)
                self.wake.clear()
        conn.close()
