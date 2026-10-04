"""가닥을 켜요.

macOS에서는 가닥 앱이 켜요(만들기: python -m backend.launch --install-app, 또는 ‘가닥 설치.command’ 더블클릭).
앱 없이 켜거나 다른 운영체제에서는:

python -m backend.launch                켜고 브라우저 창을 띄워요 (이미 켜져 있으면 창만)
python -m backend.launch --no-window    창 없이 켜요
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
import urllib.request
import webbrowser
from pathlib import Path

from . import config

URL = f"http://{config.HOST}:{config.PORT}"
WINDOW = "1320,860"
# 주소창 없는 창으로 띄울 수 있는 브라우저 (--app). 없으면 기본 브라우저의 탭으로 열어요
MAC_BROWSERS = ("Google Chrome", "Microsoft Edge", "Brave Browser", "Chromium")
BROWSER_COMMANDS = ("google-chrome", "chromium", "chromium-browser", "microsoft-edge", "msedge", "chrome")


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


def window_command():
    """주소창 없는 창으로 여는 명령. 그런 브라우저가 없으면 None."""
    args = [f"--app={URL}", f"--window-size={WINDOW}"]
    if sys.platform == "darwin":
        for name in MAC_BROWSERS:
            if any((base / f"{name}.app").exists() for base in (Path("/Applications"), Path.home() / "Applications")):
                return ["open", "-na", name, "--args"] + args
        return None
    command = next((c for c in BROWSER_COMMANDS if shutil.which(c)), None)
    return [command] + args if command else None


def open_window() -> None:
    command = window_command()
    try:
        if command and command[0] == "open":
            if subprocess.run(command, timeout=15).returncode == 0:
                return
        elif command:
            subprocess.Popen(command)
            return
    except (OSError, subprocess.SubprocessError):
        pass
    webbrowser.open(URL)  # 안 되면 기본 브라우저의 탭으로


READY = "GADAK_READY"  # 가닥 앱이 이 말을 듣고 화면을 띄워요 (mac/Gadak.swift의 listen)
BIND_TRIES = 6


def serve(window=True, shell=False, parent=None) -> int:
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
        print(f"{config.PORT}번 포트를 다른 프로그램이 쓰고 있어요. GADAK_PORT로 다른 번호를 정해 주세요.")
        return 1
    rt.on_quit = server.shutdown
    rt.via = "app" if shell else "browser"
    rt.start()
    if parent:
        rt.watch_parent(parent)
    if shell:
        print(f"{READY} {URL}", flush=True)
    else:
        print(f"가닥을 켰어요: {URL}")
        print("내 PC에 남은 대화 기록을 찾아 읽는 중이에요. 화면의 ‘찾은 곳’에서 무엇을 읽었는지 볼 수 있어요.")
        print("끄려면 화면의 ‘끄기’를 누르거나 이 창에서 Ctrl+C.")
    if window:
        threading.Timer(0.4, open_window).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    print("가닥을 껐어요.")
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
    shell = "--shell" in argv
    window = not shell and "--no-window" not in argv and os.environ.get("GADAK_NO_WINDOW") != "1"
    state = health()
    if state is not None and state.get("code") != config.CODE and stop_old():
        # 켜져 있던 가닥이 예전 코드예요(코드를 고친 뒤에도 뒤에서 계속 돌던 것). 끄고 지금 코드로 다시 켜요
        if not shell:
            print("켜져 있던 가닥이 예전 코드라서 끄고 다시 켜요.")
        state = None
    if state is not None:
        # 같은 코드의 가닥이 이미 켜져 있으면 하나 더 켜지 않아요. 앱에는 그 주소에 붙으라고 알려요
        print(f"{READY} {URL} attached" if shell else f"가닥이 이미 켜져 있어요: {URL}", flush=True)
        if window:
            open_window()
        return 0
    return serve(window=window, shell=shell, parent=_number_after(argv, "--parent"))


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
