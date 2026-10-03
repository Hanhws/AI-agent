"""대화를 읽어 오는 곳.

사용자가 무엇으로 LLM을 쓰는지 찾아서, 내 PC에 기록이 남는 것은 알아서 읽어요.
- auto    기록 파일이 내 PC에 있어요. 켜 두면 읽어요 (Claude Code · Codex)
- connect 한 번 연결하면 그 뒤로 읽어요 (Cursor hook)
- file    대화가 서버에 있어요. 내보내기 파일을 넣어야 해요 (웹 · 데스크톱 앱 채팅)
"""
import contextlib
import importlib.util
import io
import os
from pathlib import Path

from .. import config

APP_DIRS = (Path("/Applications"), Path.home() / "Applications")


def _app(name) -> bool:
    return any((base / f"{name}.app").exists() for base in APP_DIRS)


def cursor_home() -> Path:
    return Path(os.environ.get("GADAK_CURSOR_HOME", Path.home() / ".cursor")).expanduser()


def cursor_connected() -> bool:
    try:
        return "gadak" in (cursor_home() / "hooks.json").read_text(encoding="utf-8")
    except OSError:
        return False


def connect_cursor() -> dict:
    """모든 Cursor 프로젝트에 가닥 hook을 붙여요. 이미 있는 hooks.json은 덮어쓰지 않아요."""
    base = cursor_home()
    if cursor_connected():
        return {"ok": True, "already": True}
    if (base / "hooks.json").exists():
        return {"ok": False, "reason": "쓰고 계신 hooks.json이 있어서 덮어쓰지 않았어요. docs/usage-guide.md 4-2를 봐 주세요."}
    spec = importlib.util.spec_from_file_location("gadak_install", config.ROOT / "cursor-hooks" / "install.py")
    install = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(install)
    with contextlib.redirect_stdout(io.StringIO()):
        done = install.write_cursor(base, f"sh hooks/{install.LAUNCHER}")
    return {"ok": bool(done)}


def detect(counts=None) -> list:
    """무엇을 찾았고 어떻게 읽는지. counts는 저장소에 들어온 대화 수(site별)."""
    from . import claude_code, codex
    counts = counts or {}
    rows = []
    for reader in (claude_code, codex):
        files = len(reader.session_files())
        rows.append({
            "key": reader.KEY, "name": reader.NAME, "where": reader.WHERE, "mode": "auto",
            "found": files > 0, "files": files, "chats": counts.get(reader.SITE, 0),
        })
    rows.append({
        "key": "cursor", "name": "Cursor", "where": "Agent 채팅", "mode": "connect",
        "found": _app("Cursor") or cursor_home().is_dir(), "connected": cursor_connected(),
        "chats": counts.get("cursor", 0),
    })
    rows.append({
        "key": "export", "name": "Claude · ChatGPT 웹과 데스크톱 앱", "where": "채팅", "mode": "file",
        "found": True, "apps": [name for name in ("Claude", "ChatGPT") if _app(name)],
        "chats": counts.get("claude", 0) + counts.get("chatgpt", 0),
    })
    return rows
