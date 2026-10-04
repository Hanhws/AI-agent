"""승인한 종류의 자동 실행 (README 3-2 · 4장 ‘입구별 실행 방법’).

가닥은 기본으로 글을 넣어 주기만 하고, 보내는 것은 사용자가 정해요. 사용자가 종류별로 ‘앞으로는 알아서’를
켠 것만 가닥이 직접 보내요. 자동으로 할 수 있는 종류는 둘뿐이에요.

- unasked  요청 외 변경 되돌리기: 턴이 끝날 때(stop hook) 그 턴에서 확인된 요청 외 변경이 있으면
           ‘원래대로’ 요청을 이어서 보내요. 2단이 바뀐 곳을 직접 보고 만든 한마디만 보내요.
- handoff  이어 가기 요약 넣기: 같은 프로젝트에 새 대화가 시작될 때(sessionStart hook)
           지난 대화에서 정한 것을 맥락으로 넣어요.

보낸 것은 auto_log에 남고 할 일 장부에 ‘가닥이 보냄’으로 보여요. 종류별로 다시 끌 수 있어요.
실제로 보내는 것은 hook이에요(cursor-hooks/gadak-hook.py): 여기서는 보낼 글이 있는지만 답해요.
"""
import json
import time

from . import store, usage
from .agent import investigate

KINDS = store.AUTO_KINDS
WAIT_MAX = 45.0       # 턴이 끝난 뒤 확인(1단 + 2단)이 끝나기를 기다리는 가장 긴 시간(초). hook이 이만큼 붙잡혀요
ARRIVE = 6.0          # 방금 끝난 턴이 저장소에 들어오기를 기다리는 시간 (기록 파일은 2.5초마다 읽어요)
POLL = 0.4
HANDOFF_MAX = 9       # 새 대화에 넣는 지난 결정 수
SENT_BY = "[가닥이 대신 보냄] "


def state(conn) -> dict:
    return {kind: store.setting(conn, "auto." + kind) == "1" for kind in KINDS}


def set_enabled(conn, kind, on) -> dict:
    if kind not in KINDS:
        raise ValueError(kind)
    with conn:
        store.set_setting(conn, "auto." + kind, "1" if on else "0")
    return state(conn)


def _same(a, b) -> bool:
    return " ".join((a or "").split()) == " ".join((b or "").split())


def _open_unasked(conn, turn_id) -> list:
    """그 턴에서 아직 열려 있는 ‘요청 외 변경’ 한마디와, 되돌려 달라고 보낼 글."""
    out = []
    for r in conn.execute(
        "SELECT i.id, i.pop_json, COALESCE(s.state, i.state) AS state FROM items i"
        " LEFT JOIN item_states s ON s.id = i.id WHERE i.turn_id = ? AND i.kind = 'unasked' ORDER BY i.rowid",
        (turn_id,),
    ):
        prompt = (json.loads(r["pop_json"]) if r["pop_json"] else {}).get("prompt")
        if r["state"] == "open" and prompt:
            out.append((r["id"], prompt))
    return out


def _verdict(rt, conn, chat_id, message_ref):
    """방금 끝난 턴에 대해: (보낼 한마디들, 더 기다려 볼지, 그 턴이 저장소에 들어왔는지)."""
    rows = store.chat_turns(conn, chat_id)
    row = next((r for r in rows if message_ref and r["message_ref"] == message_ref), None) or (rows[-1] if rows else None)
    if row is None or row["state"] == "open":
        return [], True, False
    if any(_same(row["user"], sent["text"]) for sent in store.auto_sent(conn, chat_id)):
        return [], False, True          # 가닥이 보낸 글로 시작한 턴이에요. 거기에 또 보내지 않아요
    if not conn.execute("SELECT 1 FROM files WHERE turn_id = ? LIMIT 1", (row["id"],)).fetchone():
        return [], False, True          # 바뀐 파일이 없으면 요청 외 변경도 없어요
    if row["classified"] == 0:
        rt.classifier.request(chat_id, front=True)
        return [], True, True
    if row["classified"] != 1:
        return [], False, True
    if "unasked" in (row["look"] or "").split(",") and row["checked"] == 0:
        rt.classifier.checker.request(chat_id)
        return [], True, True
    return _open_unasked(conn, row["id"]), False, True


def on_stop(rt, conn, body) -> dict:
    """턴이 끝났을 때 hook이 물어요. 이어서 보낼 글이 있으면 send에 담아 줘요.
    확인이 아직 안 끝났으면 body.wait(초)까지 기다려요. 승인하지 않았거나 볼 것이 없으면 바로 답해요."""
    chat_id = body.get("chat_id")
    nothing = {"send": None}
    if not isinstance(chat_id, str) or not chat_id or body.get("again") is True or not state(conn)["unasked"]:
        return nothing
    clf = rt.classifier
    if clf.engine() is None or clf.status["paused"]:
        return nothing                  # 정리가 돌지 않으면 기다려도 한마디가 생기지 않아요
    try:
        wait = min(max(float(body.get("wait") or 0), 0.0), WAIT_MAX)
    except (TypeError, ValueError):
        wait = 0.0
    began = time.time()
    while True:
        found, pending, arrived = _verdict(rt, conn, chat_id, body.get("message_ref"))
        if found:
            with conn:
                for item_id, prompt in found:
                    store.set_item_state(conn, item_id, "done")
                    store.log_auto(conn, chat_id, "unasked", SENT_BY + prompt, item_id=item_id)
            for _ in found:
                usage.record(conn, "item", kind="unasked", did="run", at="auto")
            rt.bump()
            return {"send": SENT_BY + "\n".join(prompt for _, prompt in found), "items": [item_id for item_id, _ in found]}
        waited = time.time() - began
        if not pending or waited >= wait or (not arrived and waited >= ARRIVE) or clf.status["paused"]:
            return nothing
        time.sleep(POLL)


def on_start(conn, body) -> dict:
    """새 대화가 시작될 때 hook이 물어요. 같은 프로젝트의 지난 대화에서 정한 것이 있으면 context에 담아 줘요."""
    chat_id, project = body.get("chat_id"), store.project_key(body.get("project"))
    nothing = {"context": None}
    if not isinstance(chat_id, str) or not chat_id or not isinstance(project, str) or not project:
        return nothing
    if not state(conn)["handoff"] or body.get("source") not in (None, "startup"):
        return nothing                  # 이어서 여는 세션(resume · compact · clear)에는 넣지 않아요
    if store.chat_turns(conn, chat_id) or store.auto_sent(conn, chat_id, "handoff"):
        return nothing                  # 이미 시작한 대화거나, 이미 넣었어요
    decisions = conn.execute(
        "SELECT t.id, t.dec, c.id AS chat_id, c.title AS chat_title, c.created_at FROM turns t"
        " JOIN chats c ON c.id = t.chat_id WHERE c.project_id = ? AND c.id != ? AND t.dec IS NOT NULL"
        " ORDER BY t.created_at DESC, t.seq DESC LIMIT ?", (project, chat_id, HANDOFF_MAX),
    ).fetchall()
    if not decisions:
        return nothing
    text = investigate.handoff_summary(decisions[::-1], [])
    with conn:
        store.log_auto(conn, chat_id, "handoff", text)
    usage.record(conn, "item", kind="handoff", did="run", at="auto")
    return {"context": text}
