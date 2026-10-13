"""Windows에서만 다른 것들. macOS 앱의 겉은 mac/에, Windows 설치 파일을 만드는 것은 backend/winapp.py에 있어요.

- QUIET · TEXT 창 없이 도는 가닥(pythonw)이 claude · codex · git 같은 명령을 부를 때마다 검은 창이 번쩍이지 않게, 글은 UTF-8로
- command()  npm이 만든 껍데기(claude.cmd)는 cmd.exe를 거쳐서 여러 줄짜리 글을 넘기지 못해요. 껍데기가 부르는 진짜 프로그램을 바로 불러요
- browsers() 주소창 없는 창(--app)을 띄울 수 있는 브라우저. Edge는 Windows 10 · 11에 들어 있어요
- installed() 깔린 앱 찾기 (찾은 곳의 안내에 써요)
- 창 없는 가닥이 하는 말을 적을 곳(log) · 켜지 못했을 때 알림(alert) · 설치 프로그램이 ‘켜져 있음’을 알아보는 표시(hold)
"""
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

WINDOWS = sys.platform == "win32"
# subprocess.run · Popen에 **QUIET로 넘겨요. Windows가 아니면 비어 있어서 아무것도 바꾸지 않아요
QUIET = {"creationflags": subprocess.CREATE_NO_WINDOW} if WINDOWS else {}
# 글을 주고받는 명령(text=True)에 **TEXT로 넘겨요. 한국어 Windows의 기본 글자표(cp949)가 아니라 UTF-8로 주고받게 해요
TEXT = {"encoding": "utf-8", "errors": "replace"} if WINDOWS else {}

SHIMS = (".cmd", ".bat")
SCRIPTS = (".js", ".cjs", ".mjs")
# npm이 만든 껍데기의 마지막 줄:  "%_prog%"  "%dp0%\node_modules\@anthropic-ai\claude-code\cli.js" %*
_SHIM_TARGET = re.compile(r'"%(?:~dp0|dp0%)[\\/]?([^"%]+)"')

# (이름, Program Files 아래의 자리). 위에서부터 골라요
BROWSERS = (
    ("Microsoft Edge", "Microsoft/Edge/Application/msedge.exe"),
    ("Google Chrome", "Google/Chrome/Application/chrome.exe"),
    ("Brave", "BraveSoftware/Brave-Browser/Application/brave.exe"),
    ("Naver Whale", "Naver/Naver Whale/Application/whale.exe"),
)
# 찾은 곳의 안내에 쓰는 앱. (환경 변수, 그 아래에서 찾는 모양)
APPS = {
    "Cursor": (("LocalAppData", "Programs/cursor/Cursor.exe"), ("ProgramFiles", "cursor/Cursor.exe")),
    "Claude": (("LocalAppData", "AnthropicClaude/claude.exe"), ("LocalAppData", "Packages/Claude_*"),
               ("LocalAppData", "Packages/AnthropicPBC.Claude*")),
    "ChatGPT": (("LocalAppData", "Packages/OpenAI.ChatGPT-Desktop_*"), ("LocalAppData", "Programs/ChatGPT/ChatGPT.exe")),
}
LOG_MAX = 1_000_000       # 바이트. 이보다 커진 기록은 켤 때 새로 시작해요
RUNNING = "GadakAppRunning"      # 켜져 있는 동안 쥐고 있는 표시. 설치 프로그램(win/gadak.iss의 AppMutex)이 이 이름을 봐요
_held = []


def program_roots() -> list:
    """프로그램이 깔리는 자리들 (Program Files · Program Files (x86) · 내 계정에만 깐 것)."""
    roots = []
    for name in ("ProgramFiles", "ProgramFiles(x86)", "LocalAppData"):
        value = os.environ.get(name)
        if value and Path(value) not in roots:
            roots.append(Path(value))
    return roots


def browsers() -> list:
    """주소창 없는 창을 띄울 수 있는 브라우저의 실행 파일들. [(이름, 경로)]"""
    found = []
    for name, tail in BROWSERS:
        spot = next((root / tail for root in program_roots() if (root / tail).is_file()), None)
        if spot:
            found.append((name, str(spot)))
    return found


def installed(name) -> bool:
    for variable, tail in APPS.get(name, ()):
        base = os.environ.get(variable)
        if base and any(Path(base).glob(tail)):
            return True
    return False


def unshim(shim):
    """npm 껍데기(.cmd)가 부르는 진짜 프로그램. [node, 스크립트] 또는 [실행 파일]. 알아보지 못하면 None."""
    shim = Path(shim)
    try:
        text = shim.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    targets = [t for t in _SHIM_TARGET.findall(text) if Path(t.replace("\\", "/")).name.lower() != "node.exe"]
    if not targets:
        return None
    target = shim.parent.joinpath(*targets[-1].replace("\\", "/").split("/"))
    if not target.is_file():
        return None
    if target.suffix.lower() not in SCRIPTS:
        return [str(target)]
    beside = shim.parent / "node.exe"
    node = str(beside) if beside.is_file() else shutil.which("node")
    return [node, str(target)] if node else None


def command(found) -> list:
    """명령을 부르는 낱말들. 보통은 [found] 그대로예요. Windows의 npm 껍데기면 그 안의 진짜 프로그램으로 바꿔요."""
    if not found:
        return []
    if WINDOWS and Path(found).suffix.lower() in SHIMS:
        return unshim(found) or [str(found)]
    return [str(found)]


def which(name, extra=()):
    """PATH와 더 찾아볼 자리(extra)에서 명령을 찾아요. Windows에서는 진짜 실행 파일(.exe)을 껍데기(.cmd)보다 먼저 봐요."""
    paths = [None] + ([os.pathsep.join(str(p) for p in extra)] if extra else [])
    names = [name + ".exe", name] if WINDOWS else [name]
    for wanted in names:
        for path in paths:
            found = shutil.which(wanted, path=path)
            if found:
                return found
    return None


def log_streams(home) -> None:
    """창 없이 켜면(pythonw) 말할 곳이 없어요. 가닥이 하는 말과 오류를 <home>/gadak.log에 적어요. 대화 글은 적지 않아요."""
    if sys.stdout is not None and sys.stderr is not None:
        return
    try:
        home = Path(home)
        home.mkdir(parents=True, exist_ok=True)
        path = home / "gadak.log"
        if path.is_file() and path.stat().st_size > LOG_MAX:
            path.unlink()
        stream = open(path, "a", encoding="utf-8", buffering=1)
    except OSError:
        stream = open(os.devnull, "w", encoding="utf-8")
    sys.stdout = sys.stdout or stream
    sys.stderr = sys.stderr or stream


def alert(text, title="가닥") -> None:
    """켜지 못했을 때 알리는 작은 창. 창 없이 도는 가닥은 이것 말고는 알릴 길이 없어요."""
    if not WINDOWS:
        return
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(None, str(text), title, 0x30)      # MB_ICONWARNING
    except Exception:
        pass


def hold(name=RUNNING) -> None:
    """켜져 있다는 표시(이름 붙은 mutex)를 쥐어요. 설치 프로그램이 가닥을 끄고 다시 하라고 알려 줄 수 있어요."""
    if not WINDOWS:
        return
    try:
        import ctypes
        handle = ctypes.windll.kernel32.CreateMutexW(None, False, name)
        if handle:
            _held.append(handle)        # 가닥이 꺼질 때까지 놓지 않아요
    except Exception:
        pass
