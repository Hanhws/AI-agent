#!/usr/bin/env python3
"""Cursor · Claude Code가 같이 쓰는 가닥 hook.

hook이 stdin으로 넘긴 JSON을 가닥 이벤트로 맞춰 백엔드(/events)에 보내요. 표준 라이브러리만 써요.
어떤 경우에도 에디터를 막지 않아요: 백엔드가 꺼져 있으면 ~/.gadak/spool.jsonl에 쌓아 두고 넘어가요.
"""
import json
import os
import sys
import urllib.request
from pathlib import Path

URL = os.environ.get("GADAK_URL", "http://127.0.0.1:7311")
HOME = Path(os.environ.get("GADAK_HOME", Path.home() / ".gadak")).expanduser()
TIMEOUT = 1.5
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
    return Path(path).name if path else None


def from_cursor(p):
    kind = CURSOR_KINDS.get(p.get("hook_event_name"))
    if kind is None:
        return None
    roots = p.get("workspace_roots") or []
    # user_email 같은 개인 식별 필드는 옮기지 않아요
    event = {
        "site": "cursor",
        "project": _project(roots[0]) if roots else None,
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


def spool(event):
    try:
        HOME.mkdir(parents=True, exist_ok=True)
        path = HOME / "spool.jsonl"
        if path.exists() and path.stat().st_size > MAX_SPOOL:
            return
        with open(path, "a", encoding="utf-8") as out:
            out.write(json.dumps(event, ensure_ascii=False) + "\n")
    except OSError:
        pass


def main():
    # 가닥 엔진이 스스로 부른 Claude Code는 읽지 않아요
    if os.environ.get("GADAK_INTERNAL") == "1":
        return 0
    try:
        payload = json.load(sys.stdin)
    except ValueError:
        return 0
    event = normalize(payload)
    if event and not send(event):
        spool(event)
    # Cursor의 beforeSubmitPrompt는 계속 진행하라는 답을 기다려요.
    # Claude Code는 stdout에 쓴 글이 대화에 들어가므로 아무것도 쓰지 않아요.
    if isinstance(payload, dict) and payload.get("hook_event_name") == "beforeSubmitPrompt":
        print(json.dumps({"continue": True}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
