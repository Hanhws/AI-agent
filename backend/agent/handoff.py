"""노선도 끝의 ‘환승하기’: 이 대화까지를 다음 대화에 붙일 글로 써요. 가닥은 보내지 않고 복사만 해요(README 3-2).

엔진이 있으면 정리된 기록(역 제목 · 풀어 쓴 정함 · 남은 일 · 바뀐 파일 · 마지막 턴)만 읽혀서 쓰게 해요. 대화 원문을
통째로 넣지 않아서 긴 대화도 한 번에 몇천 토큰이에요. 엔진이 없거나 실패하면 정한 것 · 남은 일을 그대로 늘어놔요.
프롬프트는 prompts/handoff.txt.
"""
import json

from .. import config, store
from ..engines import EngineError
from . import tools
from .investigate import handoff_summary

SYSTEM = (config.ROOT / "backend" / "prompts" / "handoff.txt").read_text(encoding="utf-8")
SCHEMA = {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"], "additionalProperties": False}
TASKS = ("missing", "yours", "open", "next")   # 다음 대화에서 할 일. 요청 외 변경 · 제안 같은 알림은 빼요
ROUTE_MAX, FILES_MAX, LAST_USER, LAST_AI = 80, 30, 1500, 2500


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
    payload = json.dumps({
        "chat": {"title": chat["title"], "folder": chat["cwd"], "started": store.display_date(chat["created_at"])},
        "route": [{"n": t["seq"], "side": t["depth"] > 0, "title": t["title"], "dec": t["dec_note"] or t["dec"]}
                  for t in turns[-ROUTE_MAX:]],
        "left": [i["text"] for i in leftovers],
        "files": files,
        "last": {"user": (last["user"] or "")[:LAST_USER], "ai": (last["ai"] or "")[-LAST_AI:]},
    }, ensure_ascii=False)
    try:
        text = (call(SYSTEM, payload, SCHEMA).get("text") or "").strip()
    except EngineError:
        return plain
    return text or plain
