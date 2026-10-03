"""Codex 세션 파일(~/.codex/sessions/…/rollout-*.jsonl)을 읽어요.

터미널의 Codex와 VS Code의 Codex 확장이 같은 자리에 남겨요. 읽기만 해요.
파일 형식은 공식 약속이 아니라서 모르는 줄은 건너뛰어요.
"""
import json
import os
from pathlib import Path

from .. import store

KEY = "codex"
SITE = "codex"
NAME = "Codex"
WHERE = "터미널 · VS Code 확장"

MAX_TEXT = 20000


def home() -> Path:
    return Path(os.environ.get("GADAK_CODEX_HOME", Path.home() / ".codex")).expanduser()


def session_files() -> list:
    base = home() / "sessions"
    return sorted(base.glob("**/rollout-*.jsonl")) if base.is_dir() else []


def chat_id(path) -> str:
    # rollout-2026-09-30T23-13-49-<세션 id 36자>.jsonl
    return Path(path).stem[-36:]


def new_state() -> dict:
    return {"open": None, "refs": [], "cwd": None, "via": None, "started": None, "turn": None}


def parse(lines, state) -> list:
    """claude_code.parse와 같은 모양의 할 일 목록을 돌려줘요."""
    ops = []
    for raw in lines:
        try:
            line = json.loads(raw)
        except ValueError:
            continue
        payload = line.get("payload") if isinstance(line, dict) else None
        if not isinstance(payload, dict):
            continue
        kind, sub = line.get("type"), payload.get("type")
        if kind == "session_meta" and not state["cwd"] and payload.get("cwd"):
            via = "VS Code" if "vscode" in str(payload.get("originator") or payload.get("source")) else "터미널"
            state.update(cwd=payload["cwd"], via=via, started=payload.get("timestamp"))
        elif kind != "event_msg":
            continue
        elif sub == "task_started":
            state["turn"] = payload.get("turn_id")
        elif sub == "user_message":
            text = (payload.get("message") or "").strip()
            ref = state["turn"] or payload.get("client_id")
            if not text or not ref or ref in state["refs"]:
                continue
            state["refs"].append(ref)
            state["open"] = ref
            ops.append(("prompt", ref, text[:MAX_TEXT], line.get("timestamp")))
        elif sub == "agent_message" and state["open"]:
            text = (payload.get("message") or "").strip()
            if text:
                ops.append(("answer", state["open"], text))
        elif sub == "task_complete" and state["open"]:
            ops.append(("done", state["open"]))
    return ops


def after_scan(conn) -> bool:
    """대화 제목은 세션 파일이 아니라 session_index.jsonl에 있어요."""
    index = home() / "session_index.jsonl"
    if not index.is_file():
        return False
    changed = False
    for raw in index.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            entry = json.loads(raw)
        except ValueError:
            continue
        name = entry.get("thread_name") if isinstance(entry, dict) else None
        chat = store.chat_row(conn, entry.get("id")) if name else None
        if chat is not None and chat["site"] == SITE and chat["title"] != name:
            store.set_chat_title(conn, chat["id"], name)
            changed = True
    return changed
