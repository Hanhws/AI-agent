"""대화 내보내기 파일(Claude · ChatGPT의 conversations.json 또는 그 zip)을 불러와요.

웹과 데스크톱 앱의 채팅은 대화가 서버에 있어서 내 PC에서 바로 읽을 수 없어요. 각 서비스의
설정 → 데이터 내보내기로 받은 파일을 여기로 넣으면 같은 노선도에 놓여요 (README 4장 · 불러오기).
"""
import io
import json
import zipfile

from .. import store

MAX_TEXT = 20000


class BadExport(ValueError):
    pass


def _conversations(data: bytes) -> list:
    if data[:2] == b"PK":
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                name = next((n for n in archive.namelist() if n.split("/")[-1] == "conversations.json"), None)
                if name is None:
                    raise BadExport("zip 안에 conversations.json이 없어요")
                data = archive.read(name)
        except zipfile.BadZipFile as exc:
            raise BadExport("zip 파일을 열지 못했어요") from exc
    try:
        parsed = json.loads(data.decode("utf-8-sig"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise BadExport("JSON으로 읽지 못했어요") from exc
    if isinstance(parsed, dict) and isinstance(parsed.get("conversations"), list):
        parsed = parsed["conversations"]
    if not isinstance(parsed, list):
        raise BadExport("대화 목록이 아니에요")
    return [c for c in parsed if isinstance(c, dict)]


def _claude(conv) -> dict:
    """Claude: chat_messages[{sender: human|assistant, text, content[], created_at, attachments, files}]"""
    turns, current = [], None
    for message in conv.get("chat_messages") or []:
        if not isinstance(message, dict):
            continue
        text = message.get("text") or "\n".join(
            b.get("text") or "" for b in message.get("content") or [] if isinstance(b, dict) and b.get("type") == "text"
        )
        text = text.strip()
        if message.get("sender") == "human":
            names = [
                f.get("file_name") for f in (message.get("attachments") or []) + (message.get("files") or [])
                if isinstance(f, dict) and f.get("file_name")
            ]
            current = {"ref": message.get("uuid"), "user": text, "ai": "", "created_at": message.get("created_at"),
                       "files": names}
            turns.append(current)
        elif current is not None and text:
            current["ai"] = (current["ai"] + "\n\n" + text).strip()
    return {"site": "claude", "id": conv.get("uuid"), "title": conv.get("name"),
            "created_at": conv.get("created_at"), "turns": turns}


def _chatgpt(conv) -> dict:
    """ChatGPT: mapping{id: {message, parent}} 을 current_node에서 거슬러 올라가면 지금 보이는 가지예요."""
    mapping = conv.get("mapping") or {}
    chain, node, guard = [], conv.get("current_node"), 0
    while node in mapping and guard < 100000:
        chain.append(mapping[node])
        node, guard = mapping[node].get("parent"), guard + 1
    turns, current = [], None
    for entry in reversed(chain):
        message = entry.get("message") or {}
        content = message.get("content") or {}
        if content.get("content_type") not in ("text", "multimodal_text"):
            continue
        if (message.get("metadata") or {}).get("is_visually_hidden_from_conversation"):
            continue
        text = "\n".join(p for p in content.get("parts") or [] if isinstance(p, str)).strip()
        role = (message.get("author") or {}).get("role")
        if role == "user" and text:
            current = {"ref": message.get("id"), "user": text, "ai": "", "created_at": message.get("create_time"),
                       "files": []}
            turns.append(current)
        elif role == "assistant" and current is not None and text:
            current["ai"] = (current["ai"] + "\n\n" + text).strip()
    return {"site": "chatgpt", "id": conv.get("conversation_id") or conv.get("id"), "title": conv.get("title"),
            "created_at": conv.get("create_time"), "turns": turns}


def read(data: bytes) -> list:
    """파일 내용을 대화 목록으로 바꿔요. 어느 서비스 것인지는 모양을 보고 알아내요."""
    out = []
    for conv in _conversations(data):
        if "chat_messages" in conv:
            chat = _claude(conv)
        elif "mapping" in conv:
            chat = _chatgpt(conv)
        else:
            continue
        chat["turns"] = [t for t in chat["turns"] if t["ref"] and (t["user"] or t["ai"])]
        if chat["id"] and chat["turns"]:
            out.append(chat)
    if not out:
        raise BadExport("Claude나 ChatGPT의 대화 내보내기 파일이 아니에요")
    return out


def ingest(conn, chats) -> dict:
    """같은 파일을 다시 넣어도 대화가 겹치지 않아요 (대화 id + 메시지 id로 덮어씀)."""
    turns = 0
    with conn:
        for chat in chats:
            store.upsert_chat(conn, project=None, chat_id=chat["id"], site=chat["site"],
                              title=chat["title"] or None, created_at=chat["created_at"])
            for turn in chat["turns"]:
                row = store.upsert_turn(
                    conn, chat_id=chat["id"], message_ref=turn["ref"], user=turn["user"][:MAX_TEXT],
                    ai=turn["ai"][:MAX_TEXT], state="done", created_at=turn["created_at"],
                )
                for name in turn["files"]:
                    store.add_file(conn, row["id"], name)
                turns += 1
    return {"chats": len(chats), "turns": turns, "ids": [chat["id"] for chat in chats]}
