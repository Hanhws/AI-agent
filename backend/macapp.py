"""macOS 앱(가닥.app)을 만들어요. 창 · Dock 아이콘 · 메뉴가 있는 보통 프로그램이에요.

python -m backend.macapp                   dist/가닥.app 을 만들어요 (만들어만 보기)
python -m backend.macapp --install         만들어 응용 프로그램 폴더에 넣어요 (/Applications, 안 되면 ~/Applications)
python -m backend.macapp --install 폴더    그 폴더에 넣어요
python -m backend.macapp --install --open  넣고 바로 켜요 (‘가닥 설치.command’가 이렇게 불러요)

앱의 겉은 mac/Gadak.swift(창 · 메뉴)와 mac/Float.swift(떠 있는 버튼)이고, 켜지면 이 저장소의 백엔드(python -m backend.launch --shell)를 뒤에서 돌려요.
그래서 앱은 이 폴더와 이 폴더의 .venv를 가리켜요. 폴더를 옮기면 다시 만들어 주세요.
Swift 컴파일러(Xcode 명령어 도구: xcode-select --install)가 있어야 해요.
"""
import os
import platform
import plistlib
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from . import config

NAME = "가닥"
EXECUTABLE = "Gadak"
BUNDLE_ID = "local.gadak.app"
VERSION = "0.1.0"
MIN_MACOS = "12.0"
SOURCES = config.ROOT / "mac"
APP_SOURCES = ("Gadak.swift", "Float.swift", "FloatCheck.swift")     # 창 · 메뉴 · 백엔드 켜기 / 떠 있는 버튼 / 그 버튼을 스스로 확인
DIST = config.ROOT / "dist"


class BuildError(RuntimeError):
    pass


def search_path() -> str:
    """앱이 백엔드에 넘길 PATH. Finder에서 켠 앱은 PATH가 짧아서, 지금 터미널의 PATH를 적어 둬요."""
    seen, kept = set(), []
    for folder in os.environ.get("PATH", "").split(":"):
        if folder and folder not in seen and Path(folder).is_dir():
            seen.add(folder)
            kept.append(folder)
    return ":".join(kept)


def backend_python() -> Path:
    """백엔드를 돌릴 파이썬. 이 폴더의 .venv(Flask가 깔린 곳)가 있으면 그것을 써요."""
    venv = config.ROOT / ".venv" / "bin" / "python"
    return venv if venv.exists() else Path(sys.executable)


def info_plist(root=None, python=None) -> dict:
    return {
        "CFBundleName": NAME,
        "CFBundleDisplayName": NAME,
        "CFBundleIdentifier": BUNDLE_ID,
        "CFBundleExecutable": EXECUTABLE,
        "CFBundleIconFile": "AppIcon",
        "CFBundlePackageType": "APPL",
        "CFBundleShortVersionString": VERSION,
        "CFBundleVersion": "1",
        "CFBundleDevelopmentRegion": "ko",
        "CFBundleLocalizations": ["ko"],
        "LSMinimumSystemVersion": MIN_MACOS,
        "LSApplicationCategoryType": "public.app-category.productivity",
        "NSHighResolutionCapable": True,
        "NSPrincipalClass": "NSApplication",
        "NSHumanReadableCopyright": "긴 대화도 가닥을 잡아 드려요.",
        # 화면은 내 PC 안의 백엔드(http://127.0.0.1)에서 받아요
        "NSAppTransportSecurity": {"NSAllowsLocalNetworking": True},
        # mac/Gadak.swift 가 읽는 값: 어디의 백엔드를 어떤 파이썬으로 돌릴지
        "GadakRoot": str(root or config.ROOT),
        "GadakPython": str(python or backend_python()),
        "GadakPath": search_path(),
    }


def _run(command, what) -> None:
    done = subprocess.run(command, capture_output=True, text=True)
    if done.returncode != 0:
        raise BuildError(f"{what}에 실패했어요.\n{(done.stderr or done.stdout).strip()[-1500:]}")


def build(out=None) -> Path:
    """dist/가닥.app 을 만들어 그 경로를 돌려줘요."""
    if sys.platform != "darwin":
        raise BuildError("앱은 macOS에서만 만들어요. 다른 곳에서는 python -m backend.launch 로 켜세요.")
    swiftc = shutil.which("swiftc")
    if not swiftc:
        raise BuildError("Swift 컴파일러가 없어요. 터미널에서 xcode-select --install 로 Xcode 명령어 도구를 깔아 주세요.")
    app = Path(out or DIST) / f"{NAME}.app"
    target = f"{platform.machine()}-apple-macos{MIN_MACOS}"
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        _run([swiftc, "-O", "-swift-version", "5", "-parse-as-library", "-target", target, "-o", str(work / EXECUTABLE),
              *(str(SOURCES / name) for name in APP_SOURCES)], "앱 컴파일")
        _run([swiftc, "-O", "-swift-version", "5", "-o", str(work / "icon"), str(SOURCES / "icon.swift")], "아이콘 도구 컴파일")
        _run([str(work / "icon"), str(work / "AppIcon.iconset")], "아이콘 그리기")
        _run(["iconutil", "-c", "icns", str(work / "AppIcon.iconset"), "-o", str(work / "AppIcon.icns")], "아이콘 묶기")

        if app.exists():
            shutil.rmtree(app)
        contents = app / "Contents"
        (contents / "MacOS").mkdir(parents=True)
        (contents / "Resources").mkdir()
        shutil.copy2(work / EXECUTABLE, contents / "MacOS" / EXECUTABLE)
        shutil.copy2(work / "AppIcon.icns", contents / "Resources" / "AppIcon.icns")
        (contents / "Info.plist").write_bytes(plistlib.dumps(info_plist()))
        (contents / "PkgInfo").write_text("APPL????", encoding="ascii")
    # 내 PC에서 만든 앱이라 임시 서명(ad-hoc)이면 충분해요
    _run(["codesign", "--force", "--sign", "-", str(app)], "서명")
    return app


def install_folder(folder=None) -> Path:
    if folder:
        return Path(folder).expanduser()
    system = Path("/Applications")
    return system if os.access(system, os.W_OK) else Path.home() / "Applications"


def install(app, folder=None) -> Path:
    """만든 앱을 응용 프로그램 폴더에 넣어요. 같은 이름의 앱이 있으면 바꿔 넣어요."""
    where = install_folder(folder)
    where.mkdir(parents=True, exist_ok=True)
    target = where / app.name
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(app, target, symlinks=True)
    return target


def main(argv) -> int:
    try:
        if "--install" not in argv:
            print(f"만들었어요: {build()}")
            return 0
        folder = next((a for a in argv if not a.startswith("--")), None)
        with tempfile.TemporaryDirectory() as tmp:   # 저장소 안에 같은 앱이 하나 더 남지 않게 임시 폴더에서 만들어요
            target = install(build(tmp), folder)
        print(f"가닥 앱을 넣었어요: {target}")
        print("Launchpad나 Spotlight에서 ‘가닥’을 찾아 켜세요. Dock에 두려면 켠 뒤 아이콘을 오른쪽 클릭 → 옵션 → Dock에 유지.")
        if "--open" in argv:
            subprocess.run(["open", str(target)])
    except BuildError as exc:
        print(exc)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
