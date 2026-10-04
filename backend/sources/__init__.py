"""대화를 읽어 오는 곳.

사용자가 무엇으로 LLM을 쓰는지 찾아서, 내 PC에 기록이 남는 것은 알아서 읽어요.
- auto    기록 파일이 내 PC에 있어요. 켜 두면 읽어요 (Claude Code · Codex)
- connect 한 번 연결하면 그 뒤로 읽어요 (Cursor hook)
- extension 크롬 확장을 한 번 넣으면, 크롬에서 연 대화를 그 뒤로 읽어요 (Claude · ChatGPT 웹)
- file    대화가 서버에 있어요. 내보내기 파일을 넣어야 해요 (지난 대화 한꺼번에 · 데스크톱 앱 채팅)
"""
import contextlib
import importlib.util
import io
import os
from pathlib import Path

from .. import config, store

APP_DIRS = (Path("/Applications"), Path.home() / "Applications")
BROWSERS = ("Google Chrome", "Chromium", "Microsoft Edge", "Brave Browser", "Arc", "Whale")   # 크롬 확장을 넣을 수 있는 것


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


def detect(counts=None, extension=None) -> list:
    """무엇을 찾았고 어떻게 읽는지. counts는 저장소에 들어온 대화 수(site별), extension은 pages.status()."""
    from . import claude_code, codex
    counts, extension = counts or {}, extension or {}
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
    seen = extension.get("seen")
    rows.append({
        "key": "extension", "name": "Claude · ChatGPT 웹", "where": "크롬 확장", "mode": "extension",
        "found": any(_app(name) for name in BROWSERS), "connected": bool(seen),
        "seen": store.display_date(seen) if seen else None, "chats": extension.get("chats", 0),
        "folder": str(config.ROOT / "extension"),
    })
    rows.append({
        "key": "export", "name": "Claude · ChatGPT 웹과 데스크톱 앱", "where": "채팅", "mode": "file",
        "found": True, "apps": [name for name in ("Claude", "ChatGPT") if _app(name)],
        # 확장이 읽은 대화는 위 줄에서 세요
        "chats": max(0, counts.get("claude", 0) + counts.get("chatgpt", 0) - extension.get("chats", 0)),
    })
    return rows
