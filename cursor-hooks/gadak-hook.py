#!/usr/bin/env python3
"""Cursor · Claude Code가 같이 쓰는 가닥 hook.

hook이 stdin으로 넘긴 JSON을 가닥 이벤트로 맞춰 백엔드(/events)에 보내요. 표준 라이브러리만 써요.
어떤 경우에도 에디터를 막지 않아요: 백엔드가 꺼져 있으면 ~/.gadak/spool.jsonl에 쌓아 두고 넘어가요.

승인한 종류의 자동 실행 (README 3-2): 턴이 끝날 때(stop)와 새 대화가 시작될 때(sessionStart)는
가닥에 “이어서 보낼 글이 있나요?”를 묻고, 있으면 도구가 알아듣는 모양으로 돌려줘요.
사용자가 그 종류에 ‘앞으로는 알아서’를 켜 두지 않았으면 가닥은 바로 “없어요”라고 답해요.

--auto 를 붙이면 이벤트는 보내지 않고 자동 실행만 맡아요 (대화를 기록 파일로 읽는 Claude Code에 붙일 때).
"""
import json
import os
import sys
import unicodedata
import urllib.request
from pathlib import Path

URL = os.environ.get("GADAK_URL", "http://127.0.0.1:7311")
HOME = Path(os.environ.get("GADAK_HOME", Path.home() / ".gadak")).expanduser()
TIMEOUT = 1.5
AUTO_WAIT = 40            # 자동 실행을 켠 종류가 있을 때만: 턴이 끝난 뒤 가닥의 확인을 기다려 주는 시간(초)
MAX_TEXT = 20000          # 파일 전체를 쓰는 변경이 너무 커지지 않게
MAX_SPOOL = 20 * 1024 * 1024

CURSOR_KINDS = {
    "beforeSubmitPrompt": "prompt",
    "afterAgentResponse": "answer",
    "afterFileEdit": "edit",
    "stop": "stop",
    "sessionStart": "session_start",
}
CLAUDE_EDIT_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}


def _clip(text):
    if isinstance(text, str) and len(text) > MAX_TEXT:
        return text[:MAX_TEXT] + "\n…(잘림)"
    return text


def _project(path):
    # macOS는 한글 폴더 이름을 자모가 풀린 형태로 넘기기도 해서 한 가지 형태로 맞춰요
    return unicodedata.normalize("NFC", Path(path).name) if path else None


def from_cursor(p):
    kind = CURSOR_KINDS.get(p.get("hook_event_name"))
    if kind is None:
        return None
    roots = p.get("workspace_roots") or []
    # user_email 같은 개인 식별 필드는 옮기지 않아요
    event = {
        "site": "cursor",
        "project": _project(roots[0]) if roots else None,
        "cwd": roots[0] if roots else None,
        "chat_id": p.get("conversation_id"),
        "message_ref": p.get("generation_id"),
        "kind": kind,
    }
    if kind == "prompt":
        event["text"] = p.get("prompt") or ""
    elif kind == "answer":
        event["text"] = p.get("text") or ""
    elif kind == "edit":
        event["edits"] = [
            {"file": p.get("file_path"), "old": _clip(e.get("old_string")), "new": _clip(e.get("new_string"))}
            for e in p.get("edits") or []
        ]
    return event


def _claude_edits(tool, args):
    file = args.get("file_path") or args.get("notebook_path")
    if tool == "MultiEdit":
        pairs = [(e.get("old_string"), e.get("new_string")) for e in args.get("edits") or []]
    elif tool == "Write":
        pairs = [(None, args.get("content"))]
    elif tool == "NotebookEdit":
        pairs = [(None, args.get("new_source"))]
    else:
        pairs = [(args.get("old_string"), args.get("new_string"))]
    return [{"file": file, "old": _clip(old), "new": _clip(new)} for old, new in pairs]


def from_claude_code(p):
    name = p.get("hook_event_name")
    event = {
        "site": "claude-code",
        "project": _project(p.get("cwd")),
        "cwd": p.get("cwd"),
        "chat_id": p.get("session_id"),
        "message_ref": p.get("prompt_id") or p.get("user_prompt_id"),
    }
    if name == "UserPromptSubmit":
        event.update(kind="prompt", text=p.get("prompt") or "")
    elif name == "PostToolUse" and p.get("tool_name") in CLAUDE_EDIT_TOOLS:
        event.update(kind="edit", edits=_claude_edits(p["tool_name"], p.get("tool_input") or {}))
    elif name == "Stop":
        event.update(kind="answer", text=p.get("last_assistant_message") or "")
    elif name == "SessionStart":
        event.update(kind="session_start")
    else:
        return None
    return event


def normalize(payload):
    """어느 도구가 보낸 것인지 보고 가닥 이벤트로 맞춰요. 모르는 이벤트는 None."""
    if not isinstance(payload, dict):
        return None
    if "conversation_id" in payload or payload.get("hook_event_name") in CURSOR_KINDS:
        event = from_cursor(payload)
    elif "session_id" in payload:
        event = from_claude_code(payload)
    else:
        return None
    return event if event and event.get("chat_id") else None


def send(event):
    data = json.dumps(event, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        URL + "/events", data=data, headers={"Content-Type": "application/json"}, method="POST"
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT):
            return True
    except Exception:
        return False


def ask(path, body, timeout=TIMEOUT):
    """가닥에 묻고 답을 받아요. 가닥이 꺼져 있거나 늦으면 None."""
    data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        URL + path, data=data, headers={"Content-Type": "application/json"}, method="POST"
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.load(response)
    except Exception:
        return None


def auto_reply(payload):
    """가닥이 이어서 보낼 글이 있으면, 도구가 알아듣는 답을 만들어요. 없으면 None.
    Cursor: stop → followup_message · sessionStart → additional_context
    Claude Code: Stop → decision block + reason · SessionStart → additionalContext"""
    name = payload.get("hook_event_name")
    cursor = "conversation_id" in payload or name in CURSOR_KINDS
    chat = payload.get("conversation_id") if cursor else payload.get("session_id")
    if not chat:
        return None
    site = "cursor" if cursor else "claude-code"
    if name in ("stop", "Stop"):
        # 가닥이 보낸 글 때문에 이어진 턴이면 또 보내지 않아요 (되풀이 막기)
        again = bool(payload.get("loop_count")) if cursor else bool(payload.get("stop_hook_active"))
        ref = payload.get("generation_id") if cursor else (payload.get("prompt_id") or payload.get("user_prompt_id"))
        got = ask("/auto/stop", {"site": site, "chat_id": chat, "message_ref": ref, "again": again, "wait": AUTO_WAIT},
                  AUTO_WAIT + 5)
        text = (got or {}).get("send")
        if not text:
            return None
        return {"followup_message": text} if cursor else {"decision": "block", "reason": text}
    if name in ("sessionStart", "SessionStart"):
        folder = (payload.get("workspace_roots") or [None])[0] if cursor else payload.get("cwd")
        got = ask("/auto/start", {"site": site, "chat_id": chat, "project": _project(folder), "source": payload.get("source")})
        text = (got or {}).get("context")
        if not text:
            return None
        if cursor:
            return {"additional_context": text}
        return {"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": text}}
    return None


def _append(name, record):
    try:
        HOME.mkdir(parents=True, exist_ok=True)
        path = HOME / name
        if path.exists() and path.stat().st_size > MAX_SPOOL:
            return
        with open(path, "a", encoding="utf-8") as out:
            out.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError:
        pass


def spool(event):
    _append("spool.jsonl", event)


def keep_raw(payload):
    """GADAK_DEBUG=1 일 때만. 도구가 실제로 무엇을 넘기는지 확인하려고 원본을 남겨요."""
    if isinstance(payload, dict):
        _append("raw.jsonl", {k: v for k, v in payload.items() if k != "user_email"})


def main():
    # 가닥 엔진이 스스로 부른 Claude Code는 읽지 않아요
    if os.environ.get("GADAK_INTERNAL") == "1":
        return 0
    try:
        payload = json.load(sys.stdin)
    except ValueError:
        return 0
    if os.environ.get("GADAK_DEBUG") == "1":
        keep_raw(payload)
    event = None if "--auto" in sys.argv[1:] else normalize(payload)
    if event and not send(event):
        spool(event)
    reply = auto_reply(payload) if isinstance(payload, dict) else None
    if reply:
        print(json.dumps(reply, ensure_ascii=False))
    # Cursor의 beforeSubmitPrompt는 계속 진행하라는 답을 기다려요.
    # Claude Code는 stdout에 쓴 글이 대화에 들어가므로, 보낼 것이 없으면 아무것도 쓰지 않아요.
    elif isinstance(payload, dict) and payload.get("hook_event_name") == "beforeSubmitPrompt":
        print(json.dumps({"continue": True}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
