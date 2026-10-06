"""2단 · 확인 (README 3-1). 조건이 걸린 턴에서만 돌아요.

에이전트가 도구를 골라 쓰고, 결과를 보고, 더 볼지 끝낼지 스스로 정해요. 엔진에는 한 걸음씩 물어요:
지금까지 본 것을 주면 엔진이 다음 도구(또는 끝)를 고르고, 가닥이 그 도구를 돌려(tools.py) 본 것을 붙여
다시 물어요. 그래서 구조화 출력(complete_json)만 되면 어느 엔진이든 같아요. 프롬프트는 prompts/investigate.txt.

2단을 켜는 조건 — 1단이 분류할 때 정해서 turns.look에 적어요 (triggers)
- missing: 1단이 빠진 것 같은 요청을 냄 (parts.open = 2)
- unasked: 이 턴에서 파일이 바뀌었고, 1단이 요청보다 넓게 바뀐 것 같다고 봄 (wide)
- handoff: 같은 프로젝트에 새 대화가 열림 — 그 프로젝트에서 가장 새 대화의 첫 턴이고, 앞 대화에 정한 것이 있을 때
어느 턴을 볼지는 정해 둔 개수가 아니라 이 조건으로 정해요. 보는 대화가 먼저, 그 안에서는 지금에 가까운 턴부터.
얼마나 멀리 볼지(앞 턴 · 지난 대화)는 에이전트가 도구로 정해요.

규칙
- 걸음은 MAX_STEPS번까지(초깃값 5). 마지막 걸음에서는 끝내는 것만 고를 수 있어요.
- 근거를 도구로 직접 보지 못한 한마디는 버려요 (missing은 get_request, unasked는 get_diff, handoff는 search_decisions).
- 한마디의 버튼 · 바뀐 곳 · 다시 보낼 글은 엔진의 말이 아니라 저장된 기록으로 만들어요.
- 판단 기록(agent_runs)에 쓴 도구와 순서, 본 것, 결론을 남겨요 (trace.py, /trace).
"""
import collections
import json
import time

from .. import config, store, usage
from ..engines import EngineError
from . import tools, trace

SYSTEM = (config.ROOT / "backend" / "prompts" / "investigate.txt").read_text(encoding="utf-8")

TRIGGERS = ("missing", "unasked", "handoff")
MAX_TRIES = 2
OUTLINE = 40          # 노선 상태로 보여 주는 역 수 (지금 턴 둘레). 그 밖의 역은 도구로 찾아 봐요
USER_CLIP = 600
TEXT_MAX, WHY_MAX, NOUN_MAX, ARG_MAX = 60, 200, 30, 200
DIFF_SHOWN = 40       # ‘바뀐 곳 보기’ 창에 보이는 줄
EARLIER_CHATS = 10

_TEXT = {"type": ["string", "null"]}
ITEM = {
    "type": "object",
    "properties": {
        "kind": {"type": "string", "enum": list(TRIGGERS)},
        "text": {"type": "string"}, "why": {"type": "string"},
        "part": {"type": ["integer", "null"]}, "file": _TEXT, "asked": _TEXT, "what": _TEXT,
        "use": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["kind", "text", "why", "part", "file", "asked", "what", "use"],
    "additionalProperties": False,
}


def _schema(choices) -> dict:
    return {
        "type": "object",
        "properties": {
            "think": {"type": "string"},
            "tool": {"type": "string", "enum": list(choices)},
            "arg": _TEXT,
            "items": {"type": "array", "items": ITEM},
        },
        "required": ["think", "tool", "arg", "items"],
        "additionalProperties": False,
    }


STEP_SCHEMA = _schema(tools.NAMES + ("finish",))
LAST_SCHEMA = _schema(("finish",))   # 마지막 걸음: 끝내는 것만


def _line(value, limit):
    value = " ".join(value.split()) if isinstance(value, str) else ""
    return value[:limit - 1].rstrip() + "…" if len(value) > limit else value


def _noun(value):
    """한마디 틀에 끼울 짧은 말. 너무 길면 쓰지 않아요."""
    value = _line(value, 200).strip("“”‘’\"' ")
    return value if 0 < len(value) <= NOUN_MAX else None


def _arg(value):
    if isinstance(value, int) and not isinstance(value, bool):
        value = str(value)
    return _line(value, ARG_MAX) or None


# ---------- 2단을 켜는 조건 ----------

def handoff_due(conn, chat) -> bool:
    """같은 프로젝트에서 가장 새 대화이고, 앞 대화에서 정한 것이 있으면."""
    if chat is None or chat["project_id"] == store.NO_PROJECT:
        return False
    newer = conn.execute(
        "SELECT 1 FROM chats WHERE project_id = ? AND id != ? AND created_at > ? AND hidden = 0 LIMIT 1",
        (chat["project_id"], chat["id"], chat["created_at"]),
    ).fetchone()
    if newer:
        return False
    return conn.execute(
        "SELECT 1 FROM turns t JOIN chats c ON c.id = t.chat_id"
        " WHERE c.project_id = ? AND c.id != ? AND c.created_at <= ? AND c.hidden = 0 AND t.dec IS NOT NULL LIMIT 1",
        (chat["project_id"], chat["id"], chat["created_at"]),
    ).fetchone() is not None


def triggers(conn, chat, rows, row, parts, wide) -> list:
    """1단이 이 턴을 분류할 때 부르는 곳. 걸린 조건이 없으면 빈 목록이고, 그 턴은 2단을 건너뛰어요."""
    look = []
    if any(part.get("open") == store.MAYBE_MISSING for part in parts or []):
        look.append("missing")
    if wide and conn.execute("SELECT 1 FROM files WHERE turn_id = ? LIMIT 1", (row["id"],)).fetchone():
        look.append("unasked")
    # 가닥이 시작할 때 이미 요약을 넣은 대화(승인한 자동 실행)에는 다시 권하지 않아요
    if rows and row["seq"] == rows[0]["seq"] and handoff_due(conn, chat) and not store.auto_sent(conn, chat["id"], "handoff"):
        look.append("handoff")
    return look


# ---------- 엔진에 주는 것 ----------

def earlier_chats(conn, chat) -> list:
    rows = conn.execute(
        "SELECT c.title, c.created_at, COUNT(t.id) AS turns, COUNT(t.dec) AS decisions FROM chats c"
        " LEFT JOIN turns t ON t.chat_id = c.id WHERE c.project_id = ? AND c.id != ? AND c.created_at <= ? AND c.hidden = 0"
        " GROUP BY c.id ORDER BY c.created_at DESC LIMIT ?",
        (chat["project_id"], chat["id"], chat["created_at"], EARLIER_CHATS),
    ).fetchall()
    return [{"title": r["title"], "date": store.display_date(r["created_at"]), "turns": r["turns"],
             "decisions": r["decisions"]} for r in rows]


def step_input(ctx, looks, steps, left) -> dict:
    conn, row = ctx.conn, ctx.row
    rows = store.chat_turns(conn, row["chat_id"])
    at = next((i for i, r in enumerate(rows) if r["id"] == row["id"]), 0)
    start = max(0, min(at - OUTLINE // 2, len(rows) - OUTLINE))
    turn = {"id": row["id"], "seq": row["seq"], "title": row["title"], "user": _line(row["user"], USER_CLIP)}
    parts = [{"no": r["idx"], "t": r["t"], "type": r["type"], "maybe_missing": r["open"] == store.MAYBE_MISSING}
             for r in conn.execute("SELECT idx, t, type, open FROM parts WHERE turn_id = ? ORDER BY idx", (row["id"],))]
    if parts:
        turn["parts"] = parts
    names = [ctx.shown(r["name"]) for r in conn.execute("SELECT name FROM files WHERE turn_id = ? ORDER BY rowid", (row["id"],))]
    if names:
        turn["edited_files"] = names[:20]
    lines = {ctx.shown(name): sum(tools.changed_count(old, new) for old, new in pairs)
             for name, pairs in ctx.edits(row["id"]).items()}
    if lines:
        turn["changed_lines"] = lines
    project = conn.execute("SELECT name FROM projects WHERE id = ?", (ctx.chat["project_id"],)).fetchone()
    payload = {
        "project": None if ctx.only_chat else project["name"],
        "chat": {"title": ctx.chat["title"] or (rows[0]["title"] if rows else None), "turns": len(rows)},
        "turn": turn,
        "trigger": looks,
        "outline": [dict({"id": r["id"], "seq": r["seq"], "title": r["title"], "depth": r["depth"]},
                         **({"dec": r["dec"]} if r["dec"] else {})) for r in rows[start:start + OUTLINE]],
        "steps": [{"tool": s["tool"], "arg": s["arg"], "think": s["think"], "saw": s["data"]} for s in steps],
        "left": left,
    }
    if "handoff" in looks:
        payload["earlier_chats"] = earlier_chats(conn, ctx.chat)
    return payload


# ---------- 루프 ----------

def check(ctx, looks, call, max_steps=None) -> dict:
    """한 턴을 확인해요. call(system, payload, schema)은 엔진 호출 한 번이에요."""
    max_steps = max(1, max_steps or config.MAX_STEPS)
    steps, out, calls, ended = [], {}, 0, "limit"
    for n in range(max_steps):
        left = max_steps - n - 1
        payload = json.dumps(step_input(ctx, looks, steps, left), ensure_ascii=False)
        out = call(SYSTEM, payload, STEP_SCHEMA if left else LAST_SCHEMA) or {}
        calls += 1
        tool = out.get("tool")
        if tool == "finish":
            ended = "finish"
            break
        if tool not in tools.NAMES:
            ended = "odd"
            break
        arg = _arg(out.get("arg"))
        data = tools.run(ctx, tool, arg)
        steps.append({"tool": tool, "arg": arg, "think": _line(out.get("think"), WHY_MAX),
                      "saw": tools.summary(tool, data), "data": data})
    result = conclude(ctx, looks, steps, out if ended == "finish" else None)
    result.update(steps=steps, calls=calls, ended=ended,
                  think=_line(out.get("think"), WHY_MAX) if ended == "finish" else None)
    return result


def conclude(ctx, looks, steps, out) -> dict:
    """엔진이 낸 결론을 기록과 맞춰 봐요. 근거를 직접 보지 않았거나 기록에 없는 것을 가리키면 버려요."""
    def looked(tool, own=True):
        return any(s["tool"] == tool and not s["data"].get("error")
                   and (not own or s["data"].get("id") == ctx.turn_id) for s in steps)

    parts = {r["idx"]: r["t"] for r in ctx.conn.execute("SELECT idx, t FROM parts WHERE turn_id = ?", (ctx.turn_id,))}
    missing, made, dropped, files = [], [], [], set()

    def drop(kind, why):
        dropped.append({"kind": kind, "why": why})

    for raw in (out or {}).get("items") or []:
        if not isinstance(raw, dict):
            continue
        kind, why = raw.get("kind"), _line(raw.get("why"), WHY_MAX)
        if kind == "missing":
            no = raw.get("part")
            if not looked("get_request"):
                drop(kind, "요청 원문을 보지 않고 낸 결론이라 버렸어요")
            elif not isinstance(no, int) or isinstance(no, bool) or no not in parts:
                drop(kind, "이 턴에 없는 요청 번호라 버렸어요")
            elif all(m["no"] != no for m in missing):
                missing.append({"no": no, "t": parts[no], "why": why})
        elif kind == "unasked":
            path, pairs = match_file(ctx, raw.get("file"))
            if not looked("get_diff"):
                drop(kind, "바뀐 곳을 보지 않고 낸 결론이라 버렸어요")
            elif pairs is None:
                drop(kind, "이 턴에서 바뀐 파일이 아니라 버렸어요")
            elif path not in files:
                files.add(path)
                made.append(unasked_item(ctx, path, pairs, raw, why))
        elif kind == "handoff":
            item = handoff_item(ctx, raw.get("use"), why) if "handoff" in looks else None
            if "handoff" not in looks:
                drop(kind, "새 대화의 첫 턴이 아니라 버렸어요")
            elif not looked("search_decisions", own=False):
                drop(kind, "정한 것을 찾아보지 않고 낸 결론이라 버렸어요")
            elif item is None:
                drop(kind, "붙일 만한 지난 결정이나 남은 일이 없어서 버렸어요")
            elif not any(i["kind"] == "handoff" for i in made):
                made.append(item)
        else:
            drop(str(kind), "모르는 종류라 버렸어요")
    return {"missing": missing, "items": made, "dropped": dropped}


def match_file(ctx, given):
    """엔진이 말한 파일 이름을 이 턴의 실제 변경과 맞춰요. 없으면 (None, None)."""
    given = (given or "").strip() if isinstance(given, str) else ""
    if not given:
        return None, None
    edits = ctx.edits(ctx.turn_id)
    for path, pairs in edits.items():
        if given in (path, ctx.shown(path)):
            return path, pairs
    for path, pairs in edits.items():
        if path.endswith("/" + given) or path.rsplit("/", 1)[-1] == given.rsplit("/", 1)[-1]:
            return path, pairs
    return None, None


def unasked_item(ctx, path, pairs, raw, why) -> dict:
    shown = ctx.shown(path)
    asked, what = _noun(raw.get("asked")), _noun(raw.get("what"))
    text = _line(raw.get("text"), 200)
    if not text or len(text) > TEXT_MAX:
        if asked and what:
            text = f"“{asked}”만 요청했는데 “{what}”도 바뀌었어요"
        else:
            text = f"요청하지 않은 “{what}”도 바뀌었어요" if what else f"요청하지 않은 {shown}도 바뀌었어요"
    lines = tools.file_diff(pairs)
    diff = lines[:DIFF_SHOWN]
    if len(lines) > DIFF_SHOWN:
        diff.append([" ", f"…(바뀐 곳 {len(lines) - DIFF_SHOWN}줄 더)"])
    part = f"“{what}” 부분" if what else "바뀐 부분"
    prompt = f"{shown}에서 {part}은 내가 요청하지 않았어. " + (
        f"원래대로 되돌리고, “{asked}” 변경만 남겨 줘." if asked else "원래대로 되돌려 줘.")
    return {
        "kind": "unasked", "text": text,
        "why": why or f"{shown}에서 요청과 상관없어 보이는 곳이 바뀌었어요.",
        "btn": "바뀐 곳 보기",
        "pop": {"title": f"요청 외 변경 · {shown}", "diff": diff,
                "note": f"요청한 범위(“{asked}”) 밖에서 바뀐 곳이에요." if asked else "요청한 범위 밖에서 바뀐 곳이에요.",
                "btn": "원래대로 요청", "prompt": prompt},
    }


def _said(decision) -> str:
    """정한 것: 풀어 쓴 문장이 있으면 그걸로 (역 이름은 대화 밖에서 읽으면 뜻이 흐려요)."""
    return (decision["dec_note"] if "dec_note" in decision.keys() else None) or decision["dec"]


def handoff_summary(decisions, leftovers) -> str:
    """이어 가기 요약의 글. 한마디의 ‘요약 붙이기’와, 승인한 자동 실행이 새 대화에 넣는 글이 같아요."""
    lines = []
    if decisions:
        chats = {d["chat_id"] for d in decisions}
        if len(chats) == 1:
            first = decisions[0]
            lines.append(f"지난 대화({store.display_date(first['created_at'])} {first['chat_title']})에서 정한 것")
            lines += [f"{n}. {_said(d)}" for n, d in enumerate(decisions, 1)]
        else:
            lines.append("지난 대화에서 정한 것")
            lines += [f"{n}. {_said(d)} ({store.display_date(d['created_at'])} {d['chat_title']})"
                      for n, d in enumerate(decisions, 1)]
    if leftovers:
        lines.append("아직 남은 일")
        lines += [f"- {i['text']}" for i in leftovers]
    lines.append("이 결정을 그대로 두고 이어서 진행해 줘." if decisions else "이 일을 이어서 진행해 줘.")
    return "\n".join(lines)


def handoff_item(ctx, use, why):
    """지난 대화에서 정한 것 · 남은 일 중 엔진이 고른 것으로 이어 가기 요약을 만들어요. 고른 게 없으면 None."""
    ids = [u for u in (use or []) if isinstance(u, str)][:30]
    if not ids:
        return None
    conn, chat = ctx.conn, ctx.chat
    decisions = conn.execute(
        "SELECT t.id, t.dec, t.dec_note, c.id AS chat_id, c.title AS chat_title, c.created_at FROM turns t"
        " JOIN chats c ON c.id = t.chat_id WHERE t.id IN (%s) AND c.project_id = ? AND c.id != ? AND c.hidden = 0"
        " AND t.dec IS NOT NULL ORDER BY c.created_at, t.seq" % ",".join("?" * len(ids)),
        ids + [chat["project_id"], chat["id"]],
    ).fetchall()
    wanted = set(ids)
    leftovers = [i for i in tools.open_items(conn, "c.project_id = ? AND c.id != ? AND c.hidden = 0", [chat["project_id"], chat["id"]])
                 if i["id"] in wanted]
    if not decisions and not leftovers:
        return None
    summary = handoff_summary(decisions, leftovers)
    if decisions and leftovers:
        text = f"지난 대화에서 정한 것 {len(decisions)}개와 남은 일 {len(leftovers)}개를 이 대화에 붙일까요?"
    elif decisions:
        text = f"지난 대화에서 정한 것 {len(decisions)}개를 이 대화에 붙일까요?"
    else:
        text = f"지난 대화의 남은 일 {len(leftovers)}개를 이 대화에 붙일까요?"
    return {
        "kind": "handoff", "text": text,
        "why": why or "같은 프로젝트의 새 대화예요. 지난 대화에서 정한 것을 모르고 시작해요.",
        "btn": "요약 붙이기",
        "pop": {"title": "이어 가기 요약", "text": summary,
                "note": "새 대화는 지난 결정을 모르고 시작해요. 붙여 넣으면 같은 설명을 다시 하지 않아도 돼요.",
                "btn": "요약 붙이기", "prompt": summary},
    }


# ---------- 일꾼 ----------

class Investigator:
    """2단을 기다리는 대화를 줄 세워, 한 번에 턴 하나씩 확인해요.
    엔진 호출은 1단과 같은 일꾼 · 같은 한도(Classifier.call)를 써요. 엔진은 한 번에 하나만 불러요."""

    def __init__(self, classifier):
        self.clf = classifier
        self.queue = collections.deque()
        self.tries = collections.Counter()
        self._engine = None

    def engine(self):
        """2단 모델을 따로 정했으면(GADAK_CHECK_MODEL) 그 모델로, 아니면 1단과 같은 엔진."""
        base = self.clf.engine()
        model = config.CHECK_MODEL
        if base is None or not model or getattr(base, "model", model) == model:
            return base
        if self._engine is None or type(self._engine) is not type(base):
            self._engine = type(base)(model=model)
        return self._engine

    def request(self, chat_id, front=True) -> None:
        if not chat_id:
            return
        if chat_id in self.queue:
            self.queue.remove(chat_id)
        if front:
            self.queue.appendleft(chat_id)
        else:
            self.queue.append(chat_id)
        self.clf.wake.set()

    def step(self, conn) -> bool:
        """줄 맨 앞 대화에서 확인할 턴 하나를 봐요. 볼 것이 없으면 False."""
        if self.engine() is None:
            self.queue.clear()     # 엔진이 없으면 기록만 해요
            return False
        while self.queue:
            waiting = store.waiting_checks(conn, self.queue[0])
            if not waiting:
                self.queue.popleft()
                continue
            self.check_turn(conn, waiting[0])
            return True
        return False

    def check_turn(self, conn, row):
        looks = [t for t in (row["look"] or "").split(",") if t in TRIGGERS]
        if not looks or self.tries[row["id"]] >= MAX_TRIES:
            with conn:   # 볼 까닭이 없거나 거듭 실패한 턴은 다시 보지 않아요
                store.set_checked(conn, row["id"], 1 if not looks else -1)
            return None
        engine = self.engine()
        self.clf.status["checking"] = row["id"]
        began = time.time()
        try:
            result = check(tools.Context(conn, row), looks,
                           lambda system, payload, schema: self.clf.call(system, payload, schema, engine))
        except EngineError:
            raise        # 로그인 · 한도 문제는 턴 탓이 아니라서 실패로 세지 않아요. 일꾼이 멈추고, 다시 켜면 처음부터 봐요
        except Exception:
            self.tries[row["id"]] += 1
            raise
        finally:
            self.clf.status["checking"] = None
        with conn:
            store.confirm_missing(conn, row["id"], [m["no"] for m in result["missing"]])
            ids = store.set_items(conn, row["id"], result["items"])
            result["saved"] = [{"id": i, "kind": item["kind"], "text": item["text"]}
                               for i, item in zip(ids, result["items"])]
            trace.save(conn, row["id"], looks, result, engine)
            store.set_checked(conn, row["id"], 1)
        self.clf.status["checks"] += 1
        used = collections.Counter(s["tool"] for s in result["steps"])
        usage.record(conn, "check", {name: True for name in looks}, steps=len(result["steps"]), calls=result["calls"],
                     made=len(ids), dropped=len(result["dropped"]), ended=result["ended"],
                     seconds=time.time() - began, **used)
        for item in result["items"]:
            usage.record(conn, "item", kind=item["kind"], did="made", at="auto")
        self.clf.rt.bump()
        return result
