"""1단 · 분류 (README 3-1). 요청 나누기 → 분류 → 붙일 자리를 LLM 호출 한 번으로 받아요.

지난 대화를 불러올 때는 턴마다 부르면 너무 느리고 구독 한도를 많이 써서, 한 대화의 턴을 몇 개씩
묶어 한 번에 물어요. 프롬프트 원문은 backend/prompts/classify.txt (문구는 기획 담당).
"""
import collections
import json
import threading
from datetime import datetime, timezone

from .. import config, store
from ..engines import EngineError, get_engine, resolve_name

SYSTEM = (config.ROOT / "backend" / "prompts" / "classify.txt").read_text(encoding="utf-8")

_TEXT = {"type": ["string", "null"]}
SCHEMA = {
    "type": "object",
    "properties": {"turns": {"type": "array", "items": {
        "type": "object",
        "properties": {
            "id": {"type": "string"}, "title": {"type": "string"}, "depth": {"type": "integer", "enum": [0, 1, 2]},
            "seg": _TEXT, "topic": _TEXT, "chose": {"type": "boolean"}, "dec": _TEXT, "ref": _TEXT,
            "parts": {"type": "array", "items": {
                "type": "object",
                "properties": {"t": {"type": "string"}, "type": {"type": "string", "enum": ["q", "task", "rev"]},
                               "target": _TEXT},
                "required": ["t", "type", "target"], "additionalProperties": False,
            }},
        },
        "required": ["id", "title", "depth", "seg", "topic", "chose", "dec", "ref", "parts"],
        "additionalProperties": False,
    }}},
    "required": ["turns"], "additionalProperties": False,
}

CHUNK = 8                 # 한 번에 묻는 턴 수
USER_CLIP = 500           # 질문은 앞부분
AI_HEAD, AI_TAIL = 220, 220   # 답은 앞과 끝 (결론은 끝에 있어요)
STATE_MAINS, STATE_DECISIONS = 12, 8
TITLE_MAX, SEG_MAX, DEC_MAX, PART_MAX = 18, 12, 40, 60   # 역 라벨은 두 줄(12자 안팎)까지 보여요
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
        "turns": [{
            "id": str(r["seq"]), "user": _clip(r["user"], USER_CLIP),
            "ai": _clip_ends(r["ai"], AI_HEAD, AI_TAIL), "edited_files": files[r["id"]][:8],
        } for r in batch],
    }


def apply_output(conn, rows, batch, output) -> int:
    """LLM이 준 값을 그대로 믿지 않아요. 범위를 벗어난 값은 고치고, 없는 턴을 가리키면 버려요."""
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
                parts.append({"t": text, "type": part["type"], "target": earlier(part.get("target"))})
        store.set_classification(
            conn, row["id"], title=title, depth=depth,
            seg=_word(item.get("seg"), SEG_MAX), topic=_word(item.get("topic"), SEG_MAX),
            # 글 칸은 비워 두라고 해도 채우는 버릇이 있어서, 골랐는지(chose)를 먼저 묻고 아니면 정함을 버려요
            dec=_word(item.get("dec"), DEC_MAX) if item.get("chose", True) else None,
            ret=(depth == 0 and previous > 0), ref=earlier(item.get("ref")),
            parts=parts if len(parts) >= 2 else None,
        )
        depth_of[row["seq"]] = depth
        seen_main = seen_main or depth == 0
        done += 1
    return done


class Classifier:
    """분류할 대화를 줄 세워 하나씩 처리해요. 엔진은 한 번에 하나만 불러요."""

    def __init__(self, runtime, engine="auto", max_calls=None):
        self.rt = runtime
        self._engine = engine          # "auto" · 엔진 이름 · 엔진 객체 · None
        self.queue = collections.deque()
        self.wake = threading.Event()
        self.tries = collections.Counter()
        self.max_calls = config.MAX_CALLS if max_calls is None else max_calls
        self.status = {"engine": None, "running": None, "calls": 0, "turns": 0, "error": None, "paused": False}

    def engine(self):
        if isinstance(self._engine, str):
            name = resolve_name(None if self._engine == "auto" else self._engine)
            self._engine = get_engine(name)
            self.status["engine"] = name
        elif self.status["engine"] is None:
            self.status["engine"] = getattr(self._engine, "name", "none") if self._engine else "none"
        return self._engine

    def request(self, chat_id, front=False) -> None:
        if not chat_id or chat_id in self.queue:
            return
        if front:
            self.queue.appendleft(chat_id)
        else:
            self.queue.append(chat_id)
        self.wake.set()

    def resume(self) -> None:
        self.status.update(error=None, paused=False)
        self.wake.set()

    def pause(self) -> None:
        self.status["paused"] = True

    def classify_chat(self, conn, chat_id) -> int:
        """그 대화의 밀린 턴을 CHUNK개씩 분류해요. 분류한 턴 수를 돌려줘요."""
        engine = self.engine()
        chat = store.chat_row(conn, chat_id)
        if engine is None or chat is None:
            return 0
        total = 0
        while not self.status["paused"]:
            rows = store.chat_turns(conn, chat_id)
            batch = pending(rows)[:CHUNK]
            if not batch:
                break
            if self.status["calls"] >= self.max_calls:
                self.status.update(paused=True, error=f"이번에 켠 뒤로 정리 호출을 {self.max_calls}번 써서 멈췄어요.")
                break
            self.status["calls"] += 1
            payload = json.dumps(build_input(conn, chat, rows, batch), ensure_ascii=False)
            output = engine.complete_json(SYSTEM, payload, SCHEMA)
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
            self.rt.bump()
        return total

    def step(self, conn) -> bool:
        """줄 맨 앞의 대화 하나를 정리해요. 할 일이 없으면 False."""
        if not self.queue or self.status["paused"]:
            return False
        chat_id = self.queue.popleft()
        self.status["running"] = chat_id
        try:
            self.classify_chat(conn, chat_id)
        except EngineError as exc:
            # 로그인이 풀렸거나 한도에 걸렸을 수 있어요. 계속 두드리지 않고 멈춰요
            self.status.update(error=str(exc)[:200], paused=True)
        except Exception as exc:
            self.status["error"] = str(exc)[:200]
        self.status["running"] = None
        self.rt.bump()
        return True

    def run_forever(self, stop) -> None:
        conn = self.rt.connect()
        while not stop.is_set():
            if not self.step(conn):
                self.wake.wait(1.0)
                self.wake.clear()
        conn.close()
