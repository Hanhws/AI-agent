"""입구가 보낸 것을 Turn으로 모아요.

hook 입구(Cursor · Claude Code)는 질문 · 파일 수정 · 답변이 따로따로 와요. 같은
(chat_id, message_ref)끼리 모아 역 하나로 만들어요. 완성된 턴을 보내는 입구는 ingest_turn.
"""
import uuid

from . import store

KINDS = {"prompt", "edit", "answer", "stop", "session_start"}


class BadEvent(ValueError):
    pass


def _target_turn(conn, chat_id, message_ref):
    """message_ref가 없는 이벤트는 그 대화에서 답을 기다리는 마지막 턴에 붙여요."""
    if message_ref:
        return store.upsert_turn(conn, chat_id=chat_id, message_ref=message_ref)
    row = store.latest_open_turn(conn, chat_id)
    if row is not None:
        return row
    return store.upsert_turn(conn, chat_id=chat_id, message_ref="auto-" + uuid.uuid4().hex[:12])


def ingest_event(conn, event):
    if not isinstance(event, dict):
        raise BadEvent("이벤트는 JSON 객체여야 해요")
    kind, site, chat_id = event.get("kind"), event.get("site"), event.get("chat_id")
    if kind not in KINDS or not site or not chat_id:
        raise BadEvent("kind · site · chat_id가 필요해요")
    if kind == "session_start":
        return None

    message_ref = event.get("message_ref")
    with conn:
        store.upsert_chat(conn, project=event.get("project"), chat_id=chat_id, site=site)
        if kind == "prompt":
            ref = message_ref or "auto-" + uuid.uuid4().hex[:12]
            row = store.upsert_turn(conn, chat_id=chat_id, message_ref=ref, user=event.get("text") or "")
        else:
            row = _target_turn(conn, chat_id, message_ref)
            if kind == "edit":
                store.add_edits(conn, row["id"], event.get("edits"))
            elif kind == "answer":
                text = event.get("text") or ""
                # 한 턴에 답이 여러 번 오면 이어 붙이고, 같은 답이 다시 오면 그대로 둬요
                if text and text not in row["ai"]:
                    text = (row["ai"] + "\n\n" + text) if row["ai"] else text
                    row = store.upsert_turn(conn, chat_id=chat_id, message_ref=row["message_ref"], ai=text)
                row = store.upsert_turn(conn, chat_id=chat_id, message_ref=row["message_ref"], state="done")
            elif kind == "stop":
                row = store.upsert_turn(conn, chat_id=chat_id, message_ref=row["message_ref"], state="done")
        row = store.find_turn(conn, chat_id, row["message_ref"])
        return store.turn_public(conn, row)


def ingest_turn(conn, body):
    """docs/schema.md의 POST /turns 요청."""
    if not isinstance(body, dict):
        raise BadEvent("요청은 JSON 객체여야 해요")
    chat, turn = body.get("chat") or {}, body.get("turn") or {}
    if not chat.get("id") or not chat.get("site") or not turn.get("messageRef"):
        raise BadEvent("chat.id · chat.site · turn.messageRef가 필요해요")
    with conn:
        store.upsert_chat(
            conn, project=body.get("project"), chat_id=chat["id"], site=chat["site"], title=chat.get("title")
        )
        row = store.upsert_turn(
            conn, chat_id=chat["id"], message_ref=turn["messageRef"],
            user=turn.get("user") or "", ai=turn.get("ai") or "", state="done",
        )
        store.add_edits(conn, row["id"], turn.get("edits"))
        for name in turn.get("edited_files") or []:
            store.add_file(conn, row["id"], name)
        return store.turn_public(conn, store.find_turn(conn, chat["id"], turn["messageRef"]))
