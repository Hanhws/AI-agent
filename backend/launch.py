"""가닥을 켜요.

macOS에서는 가닥 앱이 켜요(만들기: python -m backend.launch --install-app, 또는 ‘Install Gadak.command’ 더블클릭).
Windows에서는 깔아 둔 가닥(시작 메뉴의 가닥)이 --app으로 켜요 (설치 파일 만들기: python -m backend.winapp).
앱 없이 켜거나 다른 운영체제에서는:

python -m backend.launch                켜고 브라우저 창을 띄워요 (이미 켜져 있으면 창만)
python -m backend.launch --no-window    창 없이 켜요
python -m backend.launch --app          창 하나로 켜요: 가닥만 쓰는 주소창 없는 창을 띄우고, 그 창을 닫으면 가닥도 꺼요
python -m backend.launch --install-app  가닥 앱을 만들어 응용 프로그램 폴더에 넣어요 (backend/macapp.py)
python -m backend.launch --shell        가닥 앱(mac/Gadak.swift)이 뒤에서 부르는 방식. 준비되면 주소를 한 줄로 알려요

켜지면: 내 PC에 남은 대화 기록을 찾아 읽고(backend/sources), 보는 대화부터 정리해서(backend/agent)
http://127.0.0.1:7311 화면에 노선도로 보여 줘요.
"""
import json
import logging
import os
import shutil
import subprocess
import sys
import threading
import time
import traceback
import urllib.request
import webbrowser
from pathlib import Path

from . import config, win

URL = f"http://{config.HOST}:{config.PORT}"
WINDOW = "1320,860"
# 주소창 없는 창으로 띄울 수 있는 브라우저 (--app). 없으면 기본 브라우저의 탭으로 열어요
MAC_BROWSERS = ("Google Chrome", "Microsoft Edge", "Brave Browser", "Chromium")
BROWSER_COMMANDS = ("google-chrome", "chromium", "chromium-browser", "microsoft-edge", "msedge", "chrome")
# 창 하나로 켤 때(--app) 브라우저가 쓰는 자리: ~/.gadak/window. 쓰던 브라우저 창과 섞이지 않고 가닥 창만 따로 떠서, 닫힌 때를 알 수 있어요
PROFILE = "window"
OWN_FLAGS = ("--no-first-run", "--no-default-browser-check", "--disable-background-mode")
BROWSER_ENV = "GADAK_BROWSER"     # 쓸 브라우저의 실행 파일을 직접 정할 때 (시험할 때)


def health():
    """이 주소에 떠 있는 것이 가닥이면 그 상태를, 아니면 None을 돌려줘요."""
    try:
        with urllib.request.urlopen(URL + "/health", timeout=1.5) as response:
            state = json.load(response)
    except Exception:
        return None
    return state if isinstance(state, dict) and state.get("app") == "gadak" else None


def running() -> bool:
    """이 주소에 떠 있는 것이 가닥인지 봐요."""
    return health() is not None


def stop_old(wait=8.0) -> bool:
    """예전 코드로 켜져 있는 가닥을 꺼요(화면의 ‘끄기’와 같은 길). 꺼졌으면 True."""
    request = urllib.request.Request(URL + "/quit", data=b"{}", headers={"Content-Type": "application/json"})
    try:
        urllib.request.urlopen(request, timeout=3).read()
    except Exception:
        pass
    end = time.time() + wait
    while time.time() < end:
        if not running():
            return True
        time.sleep(0.2)
    return False


def window_command(own=False):
    """주소창 없는 창으로 여는 명령. 그런 브라우저가 없으면 None.
    own이면 가닥만 쓰는 자리(PROFILE)에서 브라우저를 바로 띄워요. 그래야 그 창이 닫힌 것을 알 수 있어요 (--app)."""
    args = [f"--app={URL}", f"--window-size={WINDOW}"]
    if own:
        args += [f"--user-data-dir={config.HOME / PROFILE}", *OWN_FLAGS]
    named = os.environ.get(BROWSER_ENV)
    if named:
        return [named] + args
    if sys.platform == "darwin":
        for name in MAC_BROWSERS:
            for base in (Path("/Applications"), Path.home() / "Applications"):
                if (base / f"{name}.app").exists():
                    if own:
                        return [str(base / f"{name}.app" / "Contents" / "MacOS" / name)] + args
                    return ["open", "-na", name, "--args"] + args
        return None
    if win.WINDOWS:
        found = win.browsers()         # Edge는 Windows 10 · 11에 들어 있어요
        return [found[0][1]] + args if found else None
    command = next((c for c in BROWSER_COMMANDS if shutil.which(c)), None)
    return [command] + args if command else None


def open_window(own=False):
    """가닥 창을 띄워요. 따라 지켜볼 수 있는 브라우저를 직접 띄웠으면 그것을 돌려주고, 아니면 None."""
    command = window_command(own)
    try:
        if command and command[0] == "open":
            if subprocess.run(command, timeout=15).returncode == 0:
                return None
        elif command:
            return subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError):
        pass
    webbrowser.open(URL)  # 안 되면 기본 브라우저의 탭으로
    return None


def own_window(rt) -> None:
    """창 하나로 켜요(--app): 가닥만 쓰는 창을 띄우고, 그 창이 닫히면 가닥도 꺼요 (backend/runtime.py의 watch_window).
    그런 창을 띄울 브라우저가 없으면 기본 브라우저의 탭으로 열고, 화면의 ‘끄기’를 누를 때까지 돌아요."""
    process = open_window(own=True)
    if process is not None:
        rt.watch_window(process)


READY = "GADAK_READY"  # 가닥 앱이 이 말을 듣고 화면을 띄워요 (mac/Gadak.swift의 listen)
BIND_TRIES = 6


def serve(window=True, shell=False, parent=None, own=False) -> int:
    from werkzeug.serving import make_server

    from .app import create_app

    logging.getLogger("werkzeug").setLevel(logging.ERROR)  # 화면이 1.5초마다 묻는 기록으로 창이 넘치지 않게
    app = create_app()
    rt = app.config["GADAK"]
    server = None
    for _ in range(BIND_TRIES):       # 방금 끈 예전 가닥이 포트를 놓는 데 잠깐 걸릴 수 있어요
        try:
            server = make_server(config.HOST, config.PORT, app, threaded=True)
            break
        except OSError:
            time.sleep(0.5)
    if server is None:
        busy = f"Another program is using port {config.PORT}. Set a different number with GADAK_PORT."
        print(busy)
        if own:
            win.alert(busy)
        return 1
    rt.on_quit = server.shutdown
    rt.via = "app" if shell else "browser"
    rt.start()
    if parent:
        rt.watch_parent(parent)
    if shell:
        print(f"{READY} {URL}", flush=True)
    else:
        print(f"Gadak is on: {URL}")
        print("Finding and reading the chat records on this computer. See what was read under Sources in the window.")
        print("To stop, press Quit in the window or Ctrl+C here.")
    if own:
        threading.Timer(0.4, own_window, args=(rt,)).start()
    elif window:
        threading.Timer(0.4, open_window).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    print("Gadak is off.")
    return 0


def _number_after(argv, flag):
    try:
        return int(argv[argv.index(flag) + 1])
    except (ValueError, IndexError):
        return None


def main(argv) -> int:
    if "--install-app" in argv:
        from . import macapp
        return macapp.main(["--install"] + [a for a in argv if not a.startswith("--")])
    if "--app" not in argv:
        return run(argv)
    # 창 하나로 켜는 방식 (Windows에 깐 가닥). 창 없이 켜져서(pythonw) 하는 말은 ~/.gadak/gadak.log에, 켜지 못하면 작은 알림 창으로
    win.log_streams(config.HOME)
    win.hold()
    try:
        return run(argv)
    except Exception:
        traceback.print_exc()
        win.alert(f"Gadak could not start. What happened is written here:\n{config.HOME / 'gadak.log'}")
        return 1


def run(argv) -> int:
    shell = "--shell" in argv
    quiet = "--no-window" in argv or os.environ.get("GADAK_NO_WINDOW") == "1"
    own = "--app" in argv and not shell and not quiet
    window = not shell and not own and not quiet
    state = health()
    if state is not None and state.get("code") != config.CODE and stop_old():
        # 켜져 있던 가닥이 예전 코드예요(코드를 고친 뒤에도 뒤에서 계속 돌던 것). 끄고 지금 코드로 다시 켜요
        if not shell:
            print("The running Gadak is an older version, so restarting it.")
        state = None
    if state is not None:
        # 같은 코드의 가닥이 이미 켜져 있으면 하나 더 켜지 않아요. 앱에는 그 주소에 붙으라고 알려요
        print(f"{READY} {URL} attached" if shell else f"Gadak is already running: {URL}", flush=True)
        if window or own:
            open_window(own=own)      # 가닥만 쓰는 창이 이미 떠 있으면 브라우저가 그쪽에 창을 하나 더 열어요
        return 0
    return serve(window=window, shell=shell, parent=_number_after(argv, "--parent"), **({"own": True} if own else {}))


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
