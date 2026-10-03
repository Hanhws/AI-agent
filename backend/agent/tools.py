"""2단 도구 넷 (README 3-1). 모두 가닥이 저장한 기록을 읽기만 해요.

- get_request: 그 턴의 요청 원문 · 나눈 요청(parts) · 답변 전체
- get_diff: 그 턴에서 바뀐 파일과 줄 (hook · 세션 파일이 넘긴 변경 내용)
- search_decisions: 프로젝트의 정한 것(dec)과 관련 턴. 지난 대화까지 통틀어 찾아요
- list_open_items: 장부에 열려 있는 할 일

에이전트는 턴을 id로 가리켜요. 비우면 지금 턴, 숫자면 이 대화 안의 차례 번호예요.
찾는 범위는 같은 프로젝트예요. 프로젝트가 없는 대화끼리는 서로 상관이 없어서 그 대화 안에서만 찾아요.
"""
import difflib

from .. import store

NAMES = ("get_request", "get_diff", "search_decisions", "list_open_items")
LABELS = {"get_request": "요청 원문 보기", "get_diff": "바뀐 곳 보기",
          "search_decisions": "정한 것 찾기", "list_open_items": "열린 할 일 보기"}
KIND_LABELS = {"missing": "빠진 요청", "unasked": "요청 외 변경", "yours": "내가 할 일", "branch": "숨은 가지",
               "open": "끝나지 않은 곁길", "check": "이해 확인", "topic": "주제 전환", "repeat": "반복 질문",
               "handoff": "이어 가기", "next": "다음 할 일"}

USER_MAX = 4000
AI_HEAD, AI_TAIL = 3000, 3000      # 답은 앞과 끝 (결론은 끝에 있어요)
FILE_LINES, DIFF_LINES = 60, 200   # 바뀐 줄을 한 파일에서 · 한 번에 보여 주는 만큼
FOUND_MAX, RELATED_MAX, OPEN_MAX = 15, 6, 20
SNIP = 160


def _clip(text, limit):
    text = text or ""
    return text if len(text) <= limit else text[:limit] + "…"


def _ends(text, head, tail):
    text = text or ""
    return text if len(text) <= head + tail + 1 else text[:head] + "\n…(가운데 줄임)…\n" + text[-tail:]


def _like(word):
    return "%" + word.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


def diff_lines(old, new, context=1) -> list:
    """바뀐 곳을 [종류, 줄]로. 종류는 ' ' 그대로 · 'd' 지움 · 'a' 더함 — 한마디 ‘바뀐 곳 보기’ 창(pop.diff)과 같은 모양."""
    after = (new or "").splitlines()
    if not old:
        return [["a", "+" + line] for line in after]
    before = old.splitlines()
    out = []
    for group in difflib.SequenceMatcher(None, before, after, autojunk=False).get_grouped_opcodes(context):
        if out:
            out.append([" ", "…"])
        for tag, i1, i2, j1, j2 in group:
            if tag == "equal":
                out.extend([" ", line] for line in before[i1:i2])
            else:
                out.extend(["d", "-" + line] for line in before[i1:i2])
                out.extend(["a", "+" + line] for line in after[j1:j2])
    return out


def file_diff(edits) -> list:
    """한 파일의 변경 여러 번을 이어서. 사이는 …로 띄워요."""
    out = []
    for old, new in edits:
        lines = diff_lines(old, new)
        if out and lines:
            out.append([" ", "…"])
        out.extend(lines)
    return out


def changed_count(old, new) -> int:
    return sum(1 for kind, _ in diff_lines(old, new) if kind != " ")


class Context:
    """지금 확인하는 턴과, 도구가 찾아볼 범위."""

    def __init__(self, conn, row):
        self.conn, self.row = conn, row
        self.chat = store.chat_row(conn, row["chat_id"])
        self.only_chat = self.chat["project_id"] == store.NO_PROJECT

    @property
    def turn_id(self):
        return self.row["id"]

    def scope(self):
        if self.only_chat:
            return "c.id = ?", [self.chat["id"]]
        return "c.project_id = ?", [self.chat["project_id"]]

    def turn(self, arg):
        if arg is None or str(arg).strip() in ("", "this", "지금"):
            return self.row
        arg = str(arg).strip()
        where, values = self.scope()
        row = self.conn.execute(
            f"SELECT t.* FROM turns t JOIN chats c ON c.id = t.chat_id WHERE t.id = ? AND {where}", [arg] + values
        ).fetchone()
        if row is None and arg.isdigit():
            row = self.conn.execute(
                "SELECT * FROM turns WHERE chat_id = ? AND seq = ?", (self.row["chat_id"], int(arg))
            ).fetchone()
        return row

    def edits(self, turn_id) -> dict:
        """파일마다 [(old, new)]. 파일 순서는 처음 바뀐 순서."""
        files = {}
        for r in self.conn.execute("SELECT file, old, new FROM edits WHERE turn_id = ? ORDER BY idx", (turn_id,)):
            files.setdefault(r["file"], []).append((r["old"], r["new"]))
        return files

    def shown(self, name, chat_id=None):
        chat = self.chat if chat_id in (None, self.chat["id"]) else store.chat_row(self.conn, chat_id)
        return store.shown_name(name, chat["cwd"] if chat else None)


def _missing_turn(arg) -> dict:
    return {"error": f"‘{arg}’ 턴을 찾지 못했어요. outline이나 search_decisions에 나온 id를 쓰세요."}


def get_request(ctx, arg=None) -> dict:
    row = ctx.turn(arg)
    if row is None:
        return _missing_turn(arg)
    chat = store.chat_row(ctx.conn, row["chat_id"])
    out = {"id": row["id"], "seq": row["seq"], "chat": chat["title"], "this_chat": row["chat_id"] == ctx.chat["id"],
           "title": row["title"], "user": _clip(row["user"], USER_MAX), "ai": _ends(row["ai"], AI_HEAD, AI_TAIL)}
    if row["dec"]:
        out["dec"] = row["dec"]
    parts = [{"no": r["idx"], "t": r["t"], "type": r["type"], "maybe_missing": r["open"] == store.MAYBE_MISSING}
             for r in ctx.conn.execute("SELECT idx, t, type, open FROM parts WHERE turn_id = ? ORDER BY idx", (row["id"],))]
    if parts:
        out["parts"] = parts
    files = [ctx.shown(r["name"], row["chat_id"])
             for r in ctx.conn.execute("SELECT name FROM files WHERE turn_id = ? ORDER BY rowid", (row["id"],))]
    if files:
        out["files"] = files[:20]
    if row["state"] != "done":
        out["note"] = "답이 아직 오는 중일 수 있어요"
    return out


def get_diff(ctx, arg=None) -> dict:
    row = ctx.turn(arg)
    if row is None:
        return _missing_turn(arg)
    edits = ctx.edits(row["id"])
    if not edits:
        names = [ctx.shown(r["name"], row["chat_id"])
                 for r in ctx.conn.execute("SELECT name FROM files WHERE turn_id = ? ORDER BY rowid", (row["id"],))]
        note = "이 턴에는 바뀐 줄 기록이 없어요"
        return {"id": row["id"], "files": [], "note": note + (" (파일 이름만 있어요: " + ", ".join(names[:10]) + ")" if names else "")}
    out, left = [], DIFF_LINES
    for name, pairs in edits.items():
        lines = file_diff(pairs)
        shown = lines[:max(0, min(FILE_LINES, left))]
        left -= len(shown)
        entry = {"file": ctx.shown(name, row["chat_id"]), "edits": len(pairs),
                 "changed": sum(1 for kind, _ in lines if kind != " "), "diff": "\n".join(text for _, text in shown)}
        if len(shown) < len(lines):
            entry["more_lines"] = len(lines) - len(shown)
        out.append(entry)
    return {"id": row["id"], "files": out}


def search_decisions(ctx, arg=None) -> dict:
    query = " ".join(str(arg or "").split())
    words = query.split(" ")[:6] if query else []
    where, values = ctx.scope()

    def match(columns):
        if not words:
            return "", []
        any_word = " OR ".join("(" + " OR ".join(f"{c} LIKE ? ESCAPE '\\'" for c in columns) + ")" for _ in words)
        return f" AND ({any_word})", [_like(w) for w in words for _ in columns]

    cond, more = match(("t.dec", "t.title", "t.user"))
    rows = ctx.conn.execute(
        "SELECT t.id, t.seq, t.title, t.dec, t.created_at, c.id AS chat_id, c.title AS chat_title"
        f" FROM turns t JOIN chats c ON c.id = t.chat_id WHERE {where} AND t.dec IS NOT NULL{cond}"
        " ORDER BY t.created_at DESC, t.seq DESC LIMIT ?", values + more + [FOUND_MAX],
    ).fetchall()
    out = {"query": query or None, "decisions": [{
        "id": r["id"], "chat": r["chat_title"], "date": store.display_date(r["created_at"]),
        "this_chat": r["chat_id"] == ctx.chat["id"], "seq": r["seq"], "title": r["title"], "dec": r["dec"],
    } for r in rows]}
    if words:
        cond, more = match(("t.title", "t.user"))
        related = ctx.conn.execute(
            "SELECT t.id, t.seq, t.title, t.user, t.created_at, c.id AS chat_id, c.title AS chat_title"
            f" FROM turns t JOIN chats c ON c.id = t.chat_id WHERE {where} AND t.dec IS NULL AND t.id != ?{cond}"
            " ORDER BY t.created_at DESC, t.seq DESC LIMIT ?", values + [ctx.turn_id] + more + [RELATED_MAX],
        ).fetchall()
        if related:
            out["related"] = [{
                "id": r["id"], "chat": r["chat_title"], "date": store.display_date(r["created_at"]),
                "this_chat": r["chat_id"] == ctx.chat["id"], "seq": r["seq"], "title": r["title"],
                "user": _clip(" ".join(r["user"].split()), SNIP),
            } for r in related]
    if not out["decisions"]:
        out["note"] = "맞는 정한 것이 없어요" + (". arg를 비우면 최근에 정한 것부터 보여 줘요" if words else "")
    return out


def open_items(conn, where, values) -> list:
    """장부에 열려 있는(열림 · 나중에) 할 일. 2단이 적은 것 + 빠진 요청."""
    out = []
    for r in conn.execute(
        "SELECT i.id, i.kind, i.text, t.id AS turn_id, t.seq, t.title, c.title AS chat_title,"
        " COALESCE(s.state, i.state) AS state FROM items i JOIN turns t ON t.id = i.turn_id"
        " JOIN chats c ON c.id = t.chat_id LEFT JOIN item_states s ON s.id = i.id"
        f" WHERE {where} ORDER BY t.created_at DESC, i.rowid", values,
    ):
        if r["state"] in ("open", "later"):
            out.append({"id": r["id"], "kind": r["kind"], "label": KIND_LABELS.get(r["kind"], r["kind"]),
                        "text": r["text"], "turn": r["turn_id"], "chat": r["chat_title"], "seq": r["seq"],
                        "title": r["title"], "state": r["state"]})
    for r in conn.execute(
        "SELECT p.turn_id, p.idx, p.t, t.seq, t.title, c.title AS chat_title, s.state FROM parts p"
        " JOIN turns t ON t.id = p.turn_id JOIN chats c ON c.id = t.chat_id"
        " LEFT JOIN item_states s ON s.id = p.turn_id || ':p' || p.idx"
        f" WHERE {where} AND p.open = {store.MISSING} ORDER BY t.created_at DESC, p.idx", values,
    ):
        if (r["state"] or "open") in ("open", "later"):
            out.append({"id": f"{r['turn_id']}:p{r['idx']}", "kind": "missing", "label": KIND_LABELS["missing"],
                        "text": f"“{r['t']}” 답이 안 왔어요", "turn": r["turn_id"], "chat": r["chat_title"],
                        "seq": r["seq"], "title": r["title"], "state": r["state"] or "open"})
    return out


def list_open_items(ctx, arg=None) -> dict:
    where, values = ctx.scope()
    items = open_items(ctx.conn, where, values)
    out = {"items": items[:OPEN_MAX]}
    if len(items) > OPEN_MAX:
        out["more"] = len(items) - OPEN_MAX
    return out


RUN = {"get_request": get_request, "get_diff": get_diff,
       "search_decisions": search_decisions, "list_open_items": list_open_items}


def run(ctx, tool, arg=None) -> dict:
    return RUN[tool](ctx, arg)


def summary(tool, result) -> str:
    """판단 기록에 남기는 ‘본 것’ 한 줄."""
    if result.get("error"):
        return result["error"]
    if tool == "get_request":
        bits = [f"요청 {len(result['user'])}자"]
        if result.get("parts"):
            bits.append(f"나눈 요청 {len(result['parts'])}개")
        bits.append(f"답 {len(result['ai'])}자")
        return " · ".join(bits)
    if tool == "get_diff":
        files = result["files"]
        if not files:
            return "바뀐 줄 기록 없음"
        return f"파일 {len(files)}개 · 바뀐 줄 {sum(f['changed'] for f in files)}줄"
    if tool == "search_decisions":
        text = f"정한 것 {len(result['decisions'])}개"
        if result.get("related"):
            text += f" · 관련 턴 {len(result['related'])}개"
        return text
    return f"열린 할 일 {len(result['items']) + result.get('more', 0)}개"
