"""앞길 살피기 (README 3-1 · 2단의 한 갈래). ‘생각 못 한 방법 추천’이에요.

길이 갈리는 순간에, 사용자가 하려는 일을 읽고 앞으로 갈 수 있는 길을 미리 찾아봐서 ‘다음 할 일’(next)로 내밀어요.

다섯 걸음
1. 갈림길 잡기   턴마다 돌지 않아요. 코드가 정해요(due): 방금 정함 · 구간이 바뀜 · “다음에 뭐 하지”를 물음. 추가 호출이 없어요
2. 먼저 보기     가닥이 늘 먼저 보는 것을 코드가 바로 찾아 둬요(opening): 정해 둔 것 · 열린 할 일 · 작업 폴더의 계획과 일정
3. 목적지 읽기   지금까지의 노선과 먼저 본 것에서 ‘이 대화가 향하는 곳’을 한 줄로. 사용자에게도 보여 줘요
4. 미리 가 보기   엔진이 더 찾아볼 것을 골라요: 내 기록(tools.py) → 작업 폴더의 파일 · 웹(outside.py)
5. 내밀기       성격이 다른 길 셋까지 — 이어 가기(onward) · 다른 길(other) · 미리 챙길 것(check). 길 하나가 한마디 하나

규칙
- 가닥은 대답하지 않아요. 길은 답이 아니라 사용자가 쓰는 LLM에게 가져갈 물음이에요. 가닥이 대신 보내지 않아요(store.AUTO_KINDS에 없어요).
- 길마다 근거가 된 턴(basis)이 있어야 해요. 이번에 보여 준 턴이 아니면 그 길을 버려요.
- ‘찾아본 것’은 이번에 도구가 실제로 돌려준 것만 실어요. 출처(턴 · 파일 · 웹 주소)가 도구 결과에 없으면 그 줄을 빼요.
- ‘찾아본 것’은 지금 대화 밖에서 와야 해요. 이 대화의 최근 NEAR턴은 사용자가 이미 아는 것이라 출처로 치지 않아요
  (다른 대화 · 한참 앞의 턴 · 파일 · 웹만). 가닥이 내밀 것은 둘이 지금 보고 있지 않은 것이에요.
  열린 할 일도 방금 것이면 치지 않아요: 그건 할 일 목록이 이미 보여 줘요.
- 찾아본 줄의 글은 엔진이 간추린 말이에요. 파일 · 웹에서 찾았다는 줄에 든 수(두 자리 넘는 수 · #번호 · 퍼센트)가
  그 출처의 글에 없으면 그 줄을 빼요(간추리다 번호를 틀리게 옮긴 일이 있었어요).
- 찾아본 것이 하나도 없는 길은 버려요. 길이 하나도 안 남으면 아무 말도 하지 않아요.
- 사용자가 ‘앞길 보기’를 눌렀을 때만 돌아요(POST /chats/<id>/ahead · 그 대화의 마지막 턴에서). 길이 갈리는 순간에 저절로 도는 것(due)은
  꺼 뒀어요(GADAK_AHEAD_AUTO=1): 켜면 지금 하고 있는 대화의 마지막 턴에서만, 한 대화에서 AHEAD_EVERY턴에 한 번까지 돌아요.
- 그 턴에 서서 앞을 보는 것이라 그 턴 뒤의 기록은 보지 않아요(Context.until).
- 버튼을 감추려면 GADAK_AHEAD=0. 쓸모는 eval/ahead.py로 재요. 프롬프트는 prompts/ahead.txt.
"""
import json
import re
from datetime import datetime, timedelta, timezone

from .. import config, store
from ..engines.claude_cli import same_page
from . import outside, tools

SYSTEM = (config.ROOT / "backend" / "prompts" / "ahead.txt").read_text(encoding="utf-8")

KINDS = ("onward", "other", "check")
LABELS = {"onward": "이어 가기", "other": "다른 길", "check": "미리 챙길 것"}
WHYS = ("decided", "stage", "asked", "button")
# 사용자가 다음에 할 일이나 나아갈 길을 묻는 말
ASKED = re.compile(
    r"다음(엔|에는|에|은|으로)? ?(뭐|뭘|무엇|무슨|어떤|할 ?(거|것|일))|이제 ?(뭐|뭘|무엇|어떻게|어떡)|뭐부터|뭘 ?먼저"
    r"|해야 ?(할|될) ?(거|것|게|일)|할 ?(거|것|일)이? ?(뭐|뭔|남)|남은 ?(거|것|게|일)|앞으로 ?(어떻게|뭐|뭘|어떤)"
    r"|어떻게 ?(나아|진행|가야|풀어)|(어떤|무슨|어느) ?방향|방향(성)?을? ?(잡|정해|추천|제시)"
    r"|what('s| is)? next|next steps?|what should (i|we) do|where (do|should) (i|we) go", re.I)
RECORD_TOOLS = ("get_request", "search_decisions", "search_turns", "list_open_items")
RUN = {"get_request": tools.get_request, "search_decisions": tools.search_decisions, "search_turns": tools.search_turns,
       "list_open_items": tools.list_open_items, **outside.RUN}

# 가닥이 먼저 작업 폴더에서 찾는 말: 계획 · 일정 · 남은 일 · 정해 둔 규칙이 적힌 제목 (없으면 그런 줄)
PLAN_WORDS = ("일정", "계획", "기한", "마감", "남은", "미정", "안 정한", "할 일", "위험", "규칙", "순서",
              "todo", "plan", "roadmap", "deadline", "milestone", "next", "rule")
NEAR = 10             # 이 대화에서 이만큼 안쪽의 턴은 방금 일이라 ‘찾아본 것’의 출처로 치지 않아요
MIN_BEFORE = 2        # 앞에 이만큼은 있어야 읽을 노선이 있어요
ASK_GAP = 2           # 사용자가 물어서 살핀 뒤에는 이만큼의 턴 안에 다시 살피지 않아요
LOOKUPS = 2           # 한 번 살필 때 웹에서 찾아보는 횟수의 한도
OUTLINE, RECENT, DECIDED, EARLIER = 40, 4, 12, 6
USER_NOW, USER_RECENT, ANSWER_END = 800, 300, 700
GOAL_MAX, TITLE_MAX, TEXT_MAX, WHY_MAX, LINE_MAX, ASK_MAX, ARG_MAX = 80, 44, 60, 200, 120, 600, 200
BASIS_KEEP, FOUND_KEEP = 3, 4
NOTE = "가닥이 미리 찾아본 길이에요. 답이 아니라 물어볼 거리라서, 고쳐서 보내도 돼요."

_TEXT = {"type": ["string", "null"]}
PATH = {
    "type": "object",
    "properties": {
        "kind": {"type": "string", "enum": list(KINDS)},
        "title": {"type": "string"}, "why": {"type": "string"},
        "basis": {"type": "array", "items": {"type": "string"}},
        "found": {"type": "array", "items": {
            "type": "object", "properties": {"line": {"type": "string"}, "source": {"type": "string"}},
            "required": ["line", "source"], "additionalProperties": False}},
        "ask": {"type": "string"},
    },
    "required": ["kind", "title", "why", "basis", "found", "ask"],
    "additionalProperties": False,
}


def _schema(choices) -> dict:
    return {
        "type": "object",
        "properties": {
            "think": {"type": "string"},
            "tool": {"type": "string", "enum": list(choices)},
            "arg": _TEXT, "goal": _TEXT,
            "paths": {"type": "array", "items": PATH},
        },
        "required": ["think", "tool", "arg", "goal", "paths"],
        "additionalProperties": False,
    }


def _line(value, limit):
    value = " ".join(value.split()) if isinstance(value, str) else ""
    return value[:limit - 1].rstrip() + "…" if len(value) > limit else value


def _block(value, limit):
    """여러 줄 글. 줄바꿈은 살리고 빈 줄과 끝의 공백만 정리해요."""
    lines = [" ".join(line.split()) for line in value.splitlines()] if isinstance(value, str) else []
    text = "\n".join(line for line in lines if line)
    return text[:limit - 1].rstrip() + "…" if len(text) > limit else text


def _arg(value):
    if isinstance(value, int) and not isinstance(value, bool):
        value = str(value)
    return _line(value, ARG_MAX) or None


# ---------- 갈림길 잡기 ----------

def reason(user, dec, seg, depth):
    """이 턴이 갈림길인 까닭. 아니면 None. 물은 것이 먼저예요(사용자가 바라는 순간이라)."""
    if ASKED.search(user or ""):
        return "asked"
    if depth:
        return None            # 곁길에서 정한 것은 본류의 갈림길이 아니에요
    if dec:
        return "decided"
    if seg:
        return "stage"
    return None


def fresh(created_at, now=None) -> bool:
    """지금 하고 있는 일인지. 지난 대화를 한꺼번에 정리할 때 대화마다 뒤늦게 살피지 않으려고 봐요."""
    if not config.AHEAD_FRESH:
        return True
    try:
        made = datetime.fromisoformat(str(created_at).replace("Z", "+00:00"))
    except ValueError:
        return False
    if made.tzinfo is None:
        made = made.replace(tzinfo=timezone.utc)
    return (now or datetime.now(timezone.utc)) - made <= timedelta(minutes=config.AHEAD_FRESH)


def due(chat, rows, row, made, now=None):
    """1단이 이 턴을 분류하며 물어요: 지금 앞길을 살필 순간인가. 까닭이나 None. 저절로 살피기를 켰을 때만이에요(AHEAD_AUTO).
    made는 1단이 방금 붙인 값(dec · seg · depth)이에요. rows는 그 대화의 턴들(분류하기 전에 읽은 것)."""
    if not (config.AHEAD and config.AHEAD_AUTO) or chat is None or chat["hidden"] or not rows or row["seq"] != rows[-1]["seq"]:
        return None
    before = [r for r in rows if r["seq"] < row["seq"]]
    if len(before) < MIN_BEFORE or not fresh(row["created_at"], now):
        return None
    why = reason(row["user"], made.get("dec"), made.get("seg"), made.get("depth") or 0)
    if why is None:
        return None
    gap = ASK_GAP if why == "asked" else config.AHEAD_EVERY
    if any(row["seq"] - r["seq"] < gap and "ahead" in (r["look"] or "").split(",") for r in before):
        return None
    return why


# ---------- 엔진에 주는 것 ----------

def tool_names(ctx) -> tuple:
    names = list(RECORD_TOOLS)
    if config.AHEAD_FILES and outside.root(ctx) is not None:
        names += list(outside.FILE_TOOLS)
    if ctx.lookup is not None:
        names.append("look_up")
    return tuple(names)


def summary(tool, data) -> str:
    return outside.summary(tool, data) if tool in outside.RUN else tools.summary(tool, data)


def _gist(row) -> list:
    return json.loads(row["gist"]) if row["gist"] else []


def _said(row) -> str:
    return row["dec_note"] or row["dec"]


def _route(ctx) -> list:
    """이 대화에서 지금 턴까지."""
    return [r for r in store.chat_turns(ctx.conn, ctx.row["chat_id"]) if r["seq"] <= ctx.row["seq"]]


def earlier_chats(ctx) -> list:
    if ctx.only_chat:
        return []
    rows = ctx.conn.execute(
        "SELECT c.title, c.created_at, COUNT(t.id) AS turns, COUNT(t.dec) AS decisions FROM chats c"
        " LEFT JOIN turns t ON t.chat_id = c.id WHERE c.project_id = ? AND c.id != ? AND c.created_at <= ? AND c.hidden = 0"
        " GROUP BY c.id ORDER BY c.created_at DESC LIMIT ?",
        (ctx.chat["project_id"], ctx.chat["id"], ctx.chat["created_at"], EARLIER),
    ).fetchall()
    return [{"title": r["title"], "date": store.display_date(r["created_at"]), "turns": r["turns"],
             "decisions": r["decisions"]} for r in rows]


def step_input(ctx, why, names, steps, left, lookups) -> dict:
    row, rows = ctx.row, _route(ctx)
    project = ctx.conn.execute("SELECT name FROM projects WHERE id = ?", (ctx.chat["project_id"],)).fetchone()
    now = {"id": row["id"], "seq": row["seq"], "title": row["title"], "user": _line(row["user"], USER_NOW)}
    if row["ai"].strip():
        # LLM이 방금 한 답(사용자가 이미 본 것). 끝에는 결론과 LLM이 하겠다고 했거나 권한 다음 걸음이 있어요: 그건 길로 내지 않아요
        now["llm_answer"] = {"summary": _gist(row), "ending": row["ai"].strip()[-ANSWER_END:]}
    recent = []
    for r in rows[:-1][-RECENT:]:
        turn = {"id": r["id"], "seq": r["seq"], "title": r["title"], "user": _line(r["user"], USER_RECENT)}
        if _gist(r):
            turn["answer"] = _gist(r)
        recent.append(turn)
    payload = {
        "ahead": {"why": why},
        "project": None if ctx.only_chat or project is None else project["name"],
        "chat": {"title": ctx.chat["title"] or (rows[0]["title"] if rows else None), "turns": len(rows)},
        "now": now,
        "recent": recent,
        "stages": [r["seg"] for r in rows if r["seg"]][-12:],          # 이 대화가 지나온 구간들 (목적지를 읽는 데 써요)
        "outline": [dict({"id": r["id"], "seq": r["seq"], "title": r["title"], "depth": r["depth"]},
                         **({"dec": r["dec"]} if r["dec"] else {}), **({"seg": r["seg"]} if r["seg"] else {}))
                    for r in rows[-OUTLINE:]],
        "decided": [{"id": r["id"], "seq": r["seq"], "what": _said(r)} for r in rows if r["dec"]][-DECIDED:],
        "earlier": earlier_chats(ctx),
        "tools": list(names),
        "steps": [dict({"tool": s["tool"], "arg": s["arg"], "think": s["think"], "saw": s["data"]},
                       **({"by": "gadak"} if s.get("by") else {})) for s in steps],
        "left": left,
    }
    if "look_up" in names:
        payload["lookups_left"] = lookups
    return payload


# ---------- 루프 ----------

def opening(ctx, names) -> list:
    """가닥이 늘 먼저 보는 것. 엔진에게 묻지 않고 도구를 바로 돌려요 (걸음 수 · 호출 수에 들지 않아요).
    엔진이 스스로 찾아보게만 두면 방금 대화만 보고 길을 내요(10/7 시범). 그래서 바깥을 먼저 보여 주고 시작해요."""
    moves = [("search_decisions", None, tools.search_decisions(ctx)), ("list_open_items", None, tools.list_open_items(ctx))]
    if "search_files" in names:
        heads = outside.headings(ctx, PLAN_WORDS)       # 문서의 목차: 계획 · 일정 · 미정 · 규칙이 적힌 제목과 줄 번호
        if not heads.get("hits"):
            heads = outside.find_lines(ctx, PLAN_WORDS)  # 그런 제목이 없으면(코드뿐인 폴더) 그런 낱말이 든 줄
        moves.append(("search_files", "계획 · 일정 · 미정 · 규칙이 적힌 곳", heads))
    return [{"tool": tool, "arg": arg, "think": "가닥이 늘 먼저 보는 것이에요.", "saw": summary(tool, data), "data": data, "by": "gadak"}
            for tool, arg, data in moves]


def scout(ctx, why, call, max_steps=None) -> dict:
    """한 턴에 서서 앞길을 살펴요. call(system, payload, schema)은 엔진 호출 한 번이에요."""
    max_steps = max(1, max_steps or config.AHEAD_STEPS)
    if ctx.until is None:
        ctx.until = ctx.row["created_at"]
    names = tool_names(ctx)
    step, last = _schema(names + ("finish",)), _schema(("finish",))
    steps, out, calls, ended, looked = opening(ctx, names), {}, 0, "limit", 0
    for n in range(max_steps):
        left = max_steps - n - 1
        payload = json.dumps(step_input(ctx, why, names, steps, left, LOOKUPS - looked), ensure_ascii=False)
        out = call(SYSTEM, payload, step if left else last) or {}
        calls += 1
        tool = out.get("tool")
        if tool == "finish":
            ended = "finish"
            break
        if tool not in names:
            ended = "odd"
            break
        arg = _arg(out.get("arg"))
        if tool == "look_up" and looked >= LOOKUPS:
            data = {"error": "이번에는 웹에서 더 찾아볼 수 없어요."}
        else:
            data = RUN[tool](ctx, arg)
            looked += tool == "look_up"
        steps.append({"tool": tool, "arg": arg, "think": _line(out.get("think"), WHY_MAX),
                      "saw": summary(tool, data), "data": data})
    result = conclude(ctx, steps, out if ended == "finish" else None)
    result.update(steps=steps, calls=calls, ended=ended, why=why, missing=[], lookups=looked,
                  think=_line(out.get("think"), WHY_MAX) if ended == "finish" else None)
    return result


def _shown_turns(ctx) -> set:
    """엔진이 받은 턴들 (지금 · 최근 · 노선 · 이 대화에서 정한 것)."""
    return {r["id"] for r in _route(ctx)[-OUTLINE:]} | {r["id"] for r in _route(ctx) if r["dec"]}


def _far(ctx, row) -> bool:
    """지금 대화의 방금 일이 아닌지: 다른 대화이거나, 이 대화에서 NEAR턴보다 앞."""
    return row["chat_id"] != ctx.chat["id"] or ctx.row["seq"] - row["seq"] >= NEAR


def _looked_turns(steps) -> set:
    """이번에 도구가 돌려준 턴들 — ‘찾아본 것’의 출처가 될 수 있는 것."""
    seen = set()
    for s in steps:
        data = s["data"]
        if data.get("error"):
            continue
        if s["tool"] == "get_request":
            seen.add(data["id"])
        elif s["tool"] == "search_decisions":
            seen.update(d["id"] for d in data.get("decisions") or [])
            seen.update(d["id"] for d in data.get("related") or [])
        elif s["tool"] == "search_turns":
            seen.update(t["id"] for t in data.get("turns") or [])
        elif s["tool"] == "list_open_items":
            seen.update(i["turn"] for i in data.get("items") or [])
    return seen


def _turn(ctx, ref, seen):
    """엔진이 가리킨 턴(id나 이 대화의 차례 번호). 이번에 보여 준 턴이 아니면 None."""
    if not isinstance(ref, (str, int)) or isinstance(ref, bool) or not str(ref).strip():
        return None
    row = ctx.turn(str(ref).strip())
    return row if row is not None and row["id"] in seen else None


def _where(ctx, row) -> str:
    if row["chat_id"] == ctx.chat["id"]:
        return "이 대화"
    chat = store.chat_row(ctx.conn, row["chat_id"])
    return f"{store.display_date(chat['created_at'])} {chat['title'] or '지난 대화'}"


def _host(url) -> str:
    host = same_page(url).partition("://")[2].split("/", 1)[0]
    return host[4:] if host.startswith("www.") else host


TURN_ID = re.compile(r"(?<![0-9A-Za-z])t[0-9a-f]{10}(?![0-9A-Za-z])")


def _plain(ctx, text):
    """사람이 읽을 글에 섞인 턴 id(t9fd083009a)를 그 턴의 제목으로 바꿔요. 가닥 안에서만 쓰는 번호가 화면에 보이지 않게요.
    (10/7 평가에서 까닭에 “t9fd083009a에서 …”가 그대로 나왔어요.) 찾을 수 없는 id는 지워요."""
    if not isinstance(text, str):
        return text

    def name(match):
        row = ctx.turn(match.group(0))
        return f"‘{row['title']}’" if row is not None else ""

    return TURN_ID.sub(name, text)


def _figures(text) -> set:
    """글에 든 수 가운데 간추리다 틀리기 쉬운 것: 두 자리 넘는 수 · #번호 · 퍼센트."""
    return set(re.findall(r"#\d+|\d+(?:\.\d+)?%|\d{2,}", text or ""))


def _seen_text(steps) -> tuple:
    """이번에 도구가 보여 준 글을 출처별로 모아요: (파일 경로 → 글, 웹 주소 → 글). 찾아본 줄의 수를 대조하는 데 써요."""
    files, pages = {}, {}
    for s in steps:
        data = s["data"]
        if s["tool"] == "read_file" and not data.get("error"):
            name = outside.nfc(data["path"])
            files[name] = files.get(name, "") + "\n" + data.get("text", "")
        elif s["tool"] == "search_files":
            for hit in data.get("hits") or []:
                name = outside.nfc(hit["path"])
                files[name] = files.get(name, "") + "\n" + hit.get("text", "")
        elif s["tool"] == "look_up":
            for item in data.get("found") or []:
                page = same_page(item["source"])
                pages[page] = pages.get(page, "") + "\n" + item.get("line", "")
    return files, pages


def conclude(ctx, steps, out) -> dict:
    """엔진이 낸 길을 기록과 맞춰 봐요. 근거가 된 턴을 이번에 보여 준 적이 없으면 그 길을 버리고,
    찾아본 것의 출처가 도구 결과에 없거나 방금 대화의 것이면 그 줄을 빼요. 찾아본 것이 하나도 남지 않은 길도 버려요(머리말의 규칙)."""
    looked = _looked_turns(steps) - {ctx.turn_id}          # 지금 턴은 찾아본 것이 아니에요
    seen = _shown_turns(ctx) | looked
    files = {outside.nfc(s["data"]["path"]) for s in steps if s["tool"] == "read_file" and not s["data"].get("error")}
    files |= {outside.nfc(h["path"]) for s in steps if s["tool"] == "search_files" for h in s["data"].get("hits") or []}
    pages = {same_page(f["source"]): f["source"] for s in steps if s["tool"] == "look_up"
             for f in s["data"].get("found") or []}
    file_text, page_text = _seen_text(steps)
    goal = _line((out or {}).get("goal"), GOAL_MAX) or None
    paths, dropped, cut = [], [], 0

    def drop(kind, why):
        dropped.append({"kind": str(kind), "why": why})

    for raw in (out or {}).get("paths") or []:
        if not isinstance(raw, dict):
            continue
        kind = raw.get("kind")
        title, ask = _line(_plain(ctx, raw.get("title")), TITLE_MAX), _block(_plain(ctx, raw.get("ask")), ASK_MAX)
        basis = []
        for ref in raw.get("basis") or []:
            row = _turn(ctx, ref, seen)
            if row is not None and all(row["id"] != b["id"] for b in basis):
                basis.append(row)
        if kind not in KINDS:
            drop(kind, "모르는 종류라 버렸어요")
        elif any(p["kind"] == kind for p in paths):
            drop(kind, "같은 종류의 길이 이미 있어서 버렸어요")
        elif not title or not ask:
            drop(kind, "길의 이름이나 보낼 글이 없어서 버렸어요")
        elif not basis:
            drop(kind, "근거가 된 턴이 이번에 본 기록에 없어서 버렸어요")
        else:
            found, lost = [], 0
            for item in raw.get("found") or []:
                line = _line(_plain(ctx, item.get("line")), LINE_MAX) if isinstance(item, dict) else ""
                source = str(item.get("source") or "").strip() if isinstance(item, dict) else ""
                turn = _turn(ctx, re.sub(r":p?\d+$", "", source) if source.startswith("t") else source, looked)   # 할 일의 id로 가리켜도 그 턴이에요
                name = outside.nfc(re.sub(r":\d+(-\d+)?$", "", source))          # ‘경로:줄’로 적어도 그 파일이에요
                if not line:
                    continue
                if name in files and _figures(line) <= _figures(file_text.get(name)):
                    found.append({"line": line, "from": "file", "source": source, "label": source})
                elif same_page(source) in pages and _figures(line) <= _figures(page_text.get(same_page(source))):
                    found.append({"line": line, "from": "web", "source": pages[same_page(source)], "label": _host(source)})
                elif turn is not None and _far(ctx, turn):
                    found.append({"line": line, "from": "turn", "source": turn["id"],
                                  "label": f"{_where(ctx, turn)} ‘{turn['title']}’"})
                else:
                    lost += 1          # 출처가 도구 결과에 없거나, 방금 대화에 있던 것이거나, 출처에 없는 수가 든 줄
            cut += lost
            if not found:
                drop(kind, "찾아본 것이 없는 길이라 버렸어요" + (f" (출처로 칠 수 없는 줄 {lost}개)" if lost else ""))
                continue
            if lost:
                drop(kind, f"출처로 칠 수 없는 줄 {lost}개를 뺐어요 (길은 남겼어요)")
            paths.append({"kind": kind, "title": title, "why": _line(_plain(ctx, raw.get("why")), WHY_MAX), "ask": ask,
                          "basis": basis[:BASIS_KEEP], "found": found[:FOUND_KEEP]})
    return {"goal": goal, "paths": [public(p) for p in paths], "items": [path_item(ctx, goal, p) for p in paths],
            "dropped": dropped, "cut": cut}


def public(path) -> dict:
    """판단 기록 · 평가에 남기는 길의 모양 (행 객체 대신 id와 제목만)."""
    return {"kind": path["kind"], "title": path["title"], "why": path["why"], "ask": path["ask"],
            "basis": [{"id": b["id"], "title": b["title"]} for b in path["basis"]],
            "found": [{"line": f["line"], "from": f["from"], "source": f["source"]} for f in path["found"]]}


def path_item(ctx, goal, path) -> dict:
    """길 하나를 ‘다음 할 일’ 한마디로. 버튼을 누르면 근거 · 찾아본 것 · 보낼 글이 보이고, 보내기는 사용자가 정해요."""
    label = LABELS[path["kind"]]
    detail = []
    if goal:
        detail += ["지금 하려는 일", goal, ""]
    detail += [f"{label}: {path['title']}"]
    if path["why"]:
        detail.append(path["why"])
    detail += ["", "근거"] + [f"· ‘{b['title']}’ ({_where(ctx, b)})" for b in path["basis"]]
    if path["found"]:
        detail += ["", "찾아본 것"] + [f"· {f['line']} ({f['label']})" for f in path["found"]]
    detail += ["", "보낼 글", path["ask"]]
    prompt = path["ask"]
    if path["found"]:
        prompt += "\n\n참고로 미리 찾아본 것이야. 맞는지도 같이 봐 줘.\n" + "\n".join(
            f"- {f['line']} ({f['source'] if f['from'] != 'turn' else f['label']})" for f in path["found"])
    return {
        "kind": "next", "text": _line(f"{label} · {path['title']}", TEXT_MAX),
        "why": path["why"] or "지금 자리에서 갈 수 있는 길이에요.",
        "btn": "이 길 보기",
        "pop": {"title": f"앞길 · {label}", "text": "\n".join(detail), "note": NOTE, "btn": "이 길로 묻기", "prompt": prompt},
    }
