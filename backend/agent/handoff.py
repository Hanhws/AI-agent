"""노선도 끝의 ‘환승하기’: 이 대화까지를 다음 대화에 붙일 글로 써요. 가닥은 보내지 않고 복사만 해요(README 3-2).

엔진이 있으면 정리된 기록(역 제목 · 풀어 쓴 정함 · 남은 일 · 바뀐 파일)과 고른 턴 몇 개(최근 본류 · 정함이 나온 턴)의
답 끝부분만 읽혀서 쓰게 해요. 대화 원문을 통째로 넣지 않아서 긴 대화도 한 번에 1만 토큰 안팎이에요. 엔진이 없거나 실패하면 정한 것 · 남은 일을 그대로 늘어놔요.
프롬프트는 prompts/handoff.txt.
"""
import json

from .. import config, store
from ..engines import BadOutput, EngineError
from . import tools
from .investigate import handoff_summary

SYSTEM = (config.ROOT / "backend" / "prompts" / "handoff.txt").read_text(encoding="utf-8")
SCHEMA = {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"], "additionalProperties": False}
TASKS = ("missing", "yours", "open", "next")   # 다음 대화에서 할 일. 요청 외 변경 · 제안 같은 알림은 빼요
ROUTE_MAX, FILES_MAX, LAST_USER, LAST_AI = 80, 30, 1500, 2500
RECENT, DECIDED, TURN_USER, TURN_AI = 4, 6, 300, 1000   # 무엇을 만들었고 무엇을 남겼는지는 답의 끝에 있어요


def write(conn, chat_id, call=None):
    """다음 대화에 붙일 글. 쓸 게 없으면 None. call은 엔진 호출(Classifier.call), 없으면 엔진 없이."""
    chat = store.chat_row(conn, chat_id)
    turns = conn.execute(
        "SELECT seq, depth, title, dec, dec_note, user, ai FROM turns WHERE chat_id = ? ORDER BY seq", (chat_id,),
    ).fetchall()
    decisions = conn.execute(
        "SELECT t.id, t.dec, t.dec_note, c.id AS chat_id, c.title AS chat_title, c.created_at FROM turns t"
        " JOIN chats c ON c.id = t.chat_id WHERE c.id = ? AND t.dec IS NOT NULL ORDER BY t.seq", (chat_id,),
    ).fetchall()
    leftovers = [i for i in tools.open_items(conn, "c.id = ?", [chat_id]) if i["kind"] in TASKS]
    plain = handoff_summary(decisions, leftovers) if decisions or leftovers else None
    if call is None or not turns:
        return plain
    files = [r[0] for r in conn.execute(
        "SELECT DISTINCT e.file FROM edits e JOIN turns t ON t.id = e.turn_id WHERE t.chat_id = ?"
        " UNION SELECT DISTINCT f.name FROM files f JOIN turns t ON t.id = f.turn_id WHERE t.chat_id = ?", (chat_id, chat_id),
    )][-FILES_MAX:]
    last = turns[-1]
    picked = [t for t in turns if t["depth"] == 0][-RECENT - 1:] + [t for t in turns if t["dec"]][-DECIDED:]
    picked = sorted({t["seq"]: t for t in picked if t["seq"] != last["seq"]}.values(), key=lambda t: t["seq"])
    payload = json.dumps({
        "chat": {"title": chat["title"], "folder": chat["cwd"], "started": store.display_date(chat["created_at"])},
        "route": [{"n": t["seq"], "side": t["depth"] > 0, "title": t["title"], "dec": t["dec_note"] or t["dec"]}
                  for t in turns[-ROUTE_MAX:]],
        "left": [i["text"] for i in leftovers],
        "files": files,
        "turns": [{"n": t["seq"], "user": (t["user"] or "")[:TURN_USER], "ai": (t["ai"] or "")[-TURN_AI:]} for t in picked],
        "last": {"user": (last["user"] or "")[:LAST_USER], "ai": (last["ai"] or "")[-LAST_AI:]},
    }, ensure_ascii=False)
    try:
        text = _unwrap((call(SYSTEM, payload, SCHEMA).get("text") or "").strip())
    except (EngineError, BadOutput):      # 엔진이 멈췄거나, 형식 대신 글로 답했어요. 정한 것 · 남은 일을 그대로 늘어놔요
        return plain
    return text or plain


def _unwrap(text):
    """엔진이 text 칸 안에 {"text": …}를 한 번 더 감싸 넣기도 해요(10/6 실제로 봄). 벗겨서 글만 남겨요."""
    if text.startswith("{"):
        try:
            inner = json.loads(text)
        except ValueError:
            return text
        if isinstance(inner, dict) and isinstance(inner.get("text"), str):
            return inner["text"].strip()
    return text
