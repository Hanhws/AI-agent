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
import json
import os
import shlex
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


CLAUDE_HOOK_EVENTS = (("Stop", 60), ("SessionStart", 10))    # (이벤트, hook을 기다려 주는 초)
HOOK_MARK = "gadak-hook.py"


def claude_settings() -> Path:
    return Path(os.environ.get("GADAK_CLAUDE_SETTINGS", Path.home() / ".claude" / "settings.json")).expanduser()


def _claude_hook_command() -> str:
    # --auto: 대화는 기록 파일로 읽고 있으니 hook은 자동 실행만 맡아요 (같은 턴이 두 번 들어오지 않게)
    return f"python3 {shlex.quote(str(config.ROOT / 'cursor-hooks' / 'gadak-hook.py'))} --auto"


def _read_claude_settings():
    """설정을 읽어요. 파일이 없으면 빈 설정, 읽을 수 없는 모양이면 None."""
    path = claude_settings()
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or not isinstance(data.get("hooks", {}), dict):
        return None
    if any(not isinstance(v, list) for v in data.get("hooks", {}).values()):
        return None
    return data


def _is_ours(entry) -> bool:
    return HOOK_MARK in json.dumps(entry, ensure_ascii=False)


def claude_connected() -> bool:
    data = _read_claude_settings()
    hooks = (data or {}).get("hooks", {})
    return all(any(_is_ours(e) for e in hooks.get(event, [])) for event, _ in CLAUDE_HOOK_EVENTS)


def connect_claude() -> dict:
    """Claude Code의 사용자 설정에 가닥 hook 둘을 더해요. 있던 설정은 그대로 두고, 고치기 전의 파일을 옆에 남겨요."""
    path, data = claude_settings(), _read_claude_settings()
    if data is None:
        return {"ok": False, "reason": "Claude Code 설정 파일을 읽지 못해서 건드리지 않았어요. docs/usage-guide.md 4-1을 봐 주세요."}
    if claude_connected():
        return {"ok": True, "already": True}
    hooks = data.setdefault("hooks", {})
    for event, timeout in CLAUDE_HOOK_EVENTS:
        entries = hooks.setdefault(event, [])
        if not any(_is_ours(e) for e in entries):
            entries.append({"hooks": [{"type": "command", "command": _claude_hook_command(), "timeout": timeout}]})
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        path.with_name(path.name + ".gadak-backup").write_bytes(path.read_bytes())
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"ok": True}


def disconnect_claude() -> dict:
    """가닥이 더한 hook만 떼요."""
    path, data = claude_settings(), _read_claude_settings()
    if data is None:
        return {"ok": False, "reason": "Claude Code 설정 파일을 읽지 못해서 건드리지 않았어요."}
    hooks = data.get("hooks", {})
    if not any(_is_ours(e) for entries in hooks.values() for e in entries):
        return {"ok": True, "already": True}
    for event in list(hooks):
        hooks[event] = [e for e in hooks[event] if not _is_ours(e)]
        if not hooks[event]:
            del hooks[event]
    if not hooks:
        data.pop("hooks", None)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"ok": True}


def auto_ways() -> dict:
    """가닥이 직접 보낼 수 있는 길이 붙어 있는 입구 (승인한 종류의 자동 실행 · backend/auto.py)."""
    return {"claude-code": claude_connected(), "cursor": cursor_connected()}


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
        if reader.KEY == "claude-code":
            rows[-1]["hooks"] = claude_connected()     # 자동 실행에 쓰는 hook이 붙어 있는지
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
