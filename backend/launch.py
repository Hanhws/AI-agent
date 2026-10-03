"""가닥을 프로그램처럼 켜요.

python -m backend.launch                켜고 창을 띄워요 (이미 켜져 있으면 창만)
python -m backend.launch --no-window    창 없이 켜요
python -m backend.launch --install-app  ~/Applications/가닥.app 을 만들어요 (macOS · Spotlight, Dock에서 켜기)

켜지면: 내 PC에 남은 대화 기록을 찾아 읽고(backend/sources), 보는 대화부터 정리해서(backend/agent)
http://127.0.0.1:7311 화면에 노선도로 보여 줘요. Finder에서는 저장소의 `가닥.command`를 더블클릭.
"""
import json
import logging
import os
import shlex
import shutil
import subprocess
import sys
import threading
import urllib.request
import webbrowser
from pathlib import Path

from . import config

URL = f"http://{config.HOST}:{config.PORT}"
WINDOW = "1320,860"
# 주소창 없는 창으로 띄울 수 있는 브라우저 (--app). 없으면 기본 브라우저의 탭으로 열어요
MAC_BROWSERS = ("Google Chrome", "Microsoft Edge", "Brave Browser", "Chromium")
BROWSER_COMMANDS = ("google-chrome", "chromium", "chromium-browser", "microsoft-edge", "msedge", "chrome")


def running() -> bool:
    """이 주소에 떠 있는 것이 가닥인지 봐요."""
    try:
        with urllib.request.urlopen(URL + "/health", timeout=1.5) as response:
            return json.load(response).get("app") == "gadak"
    except Exception:
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


def install_app(folder=None) -> Path:
    """Spotlight · Dock에서 켤 수 있게 작은 앱 묶음을 만들어요. 창을 닫으면 조금 뒤 스스로 꺼져요."""
    app = Path(folder or Path.home() / "Applications") / "가닥.app"
    binary = app / "Contents" / "MacOS" / "gadak"
    binary.parent.mkdir(parents=True, exist_ok=True)
    log = config.HOME / "launch.log"
    binary.write_text(
        "#!/bin/sh\n"
        "# backend/launch.py --install-app 이 만든 파일. 저장소 폴더를 옮기면 다시 만들어 주세요.\n"
        f"export PATH={shlex.quote(os.environ.get('PATH', '/usr/bin:/bin'))}\n"
        f"mkdir -p {shlex.quote(str(config.HOME))}\n"
        f"cd {shlex.quote(str(config.ROOT))} || exit 1\n"
        f"exec {shlex.quote(sys.executable)} -m backend.launch --app >> {shlex.quote(str(log))} 2>&1\n",
        encoding="utf-8",
    )
    binary.chmod(0o755)
    (app / "Contents" / "Info.plist").write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n'
        '<plist version="1.0"><dict>\n'
        "  <key>CFBundleName</key><string>가닥</string>\n"
        "  <key>CFBundleDisplayName</key><string>가닥</string>\n"
        "  <key>CFBundleIdentifier</key><string>local.gadak.launcher</string>\n"
        "  <key>CFBundleExecutable</key><string>gadak</string>\n"
        "  <key>CFBundlePackageType</key><string>APPL</string>\n"
        "  <key>CFBundleVersion</key><string>1</string>\n"
        "  <key>LSUIElement</key><true/>\n"
        "</dict></plist>\n",
        encoding="utf-8",
    )
    return app


def serve(window=True, as_app=False) -> int:
    from werkzeug.serving import make_server

    from .app import create_app

    logging.getLogger("werkzeug").setLevel(logging.ERROR)  # 화면이 1.5초마다 묻는 기록으로 창이 넘치지 않게
    app = create_app()
    rt = app.config["GADAK"]
    rt.exit_when_idle = as_app
    try:
        server = make_server(config.HOST, config.PORT, app, threaded=True)
    except OSError:
        print(f"{config.PORT}번 포트를 다른 프로그램이 쓰고 있어요. GADAK_PORT로 다른 번호를 정해 주세요.")
        return 1
    rt.on_quit = server.shutdown
    rt.start()
    print(f"가닥을 켰어요: {URL}")
    print("내 PC에 남은 대화 기록을 찾아 읽는 중이에요. 화면의 ‘찾은 곳’에서 무엇을 읽었는지 볼 수 있어요.")
    print("끄려면 화면의 ‘끄기’를 누르거나 이 창에서 Ctrl+C." if not as_app else "창을 닫으면 3분 뒤 스스로 꺼져요.")
    if window:
        threading.Timer(0.4, open_window).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    print("가닥을 껐어요.")
    return 0


def main(argv) -> int:
    if "--install-app" in argv:
        if sys.platform != "darwin":
            print("앱 묶음은 macOS에서만 만들어요. 다른 곳에서는 python -m backend.launch 로 켜세요.")
            return 1
        folder = next((a for a in argv if not a.startswith("--")), None)
        print(f"만들었어요: {install_app(folder)}\nSpotlight에서 ‘가닥’을 찾거나 Dock에 끌어다 두고 켜세요.")
        return 0
    window = "--no-window" not in argv and os.environ.get("GADAK_NO_WINDOW") != "1"
    if running():
        print(f"가닥이 이미 켜져 있어요: {URL}")
        if window:
            open_window()
        return 0
    return serve(window=window, as_app="--app" in argv)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
