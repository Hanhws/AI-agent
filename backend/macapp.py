"""macOS 앱(가닥.app)을 만들어요. 창 · Dock 아이콘 · 메뉴가 있는 보통 프로그램이에요.

python -m backend.macapp                   dist/가닥.app 을 만들어요 (만들어만 보기)
python -m backend.macapp --install         만들어 응용 프로그램 폴더에 넣어요 (/Applications, 안 되면 ~/Applications)
python -m backend.macapp --install 폴더    그 폴더에 넣어요
python -m backend.macapp --install --open  넣고 바로 켜요 (‘가닥 설치.command’가 이렇게 불러요)

앱의 겉은 mac/Gadak.swift(창 · 메뉴)와 mac/Float.swift(떠 있는 버튼)이고, 켜지면 이 저장소의 백엔드(python -m backend.launch --shell)를 뒤에서 돌려요.
그래서 앱은 이 폴더와 이 폴더의 .venv를 가리켜요. 폴더를 옮기면 다시 만들어 주세요.
Swift 컴파일러(Xcode 명령어 도구: xcode-select --install)가 있어야 해요.

남에게 건네는 앱 (설치하면 바로 켜지는 앱 · docs/usage-guide.md 1장)
python -m backend.macapp --bundle          dist/가닥.app — 백엔드와 파이썬까지 앱 안에 넣어요. 저장소 폴더 없이 돌아요
python -m backend.macapp --dmg             dist/가닥-<판>-<arm64|x86_64>.dmg — 위 앱을 담은 디스크 이미지
python -m backend.macapp --dmg --collect   사용 기록을 받을 서버 주소(내 backend/.env의 GADAK_COLLECT_URL)를 앱에 적어 넣어요
묶을 때는 PyInstaller를 써요: .venv/bin/python -m pip install pyinstaller. 만든 앱은 임시 서명이라, 받은 사람은 처음 한 번
‘확인되지 않은 개발자’ 경고를 넘겨야 해요(시스템 설정 → 개인정보 보호 및 보안 → 그래도 열기).
"""
import json
import os
import platform
import plistlib
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path

from . import config

NAME = "가닥"
EXECUTABLE = "Gadak"
BUNDLE_ID = "local.gadak.app"
VERSION = config.VERSION
MIN_MACOS = "12.0"
BACKEND = "gadak-backend"      # 앱 안에 묶는 백엔드 실행 파일. mac/Gadak.swift · backend/sources(HOOK_MARKS)가 이 이름을 알아요
ENTRY = "backend_main.py"      # mac/ 안의 그 실행 파일의 첫 줄
# 묶인 백엔드가 파일로 읽는 것들: (저장소 안의 자리, 앱 안의 폴더). backend/config.py의 ROOT가 이 폴더들의 위예요
BUNDLE_DATA = (
    ("shared/ui", "shared/ui"), ("backend/web", "backend/web"), ("backend/prompts", "backend/prompts"),
    ("data/demo_conversations.json", "data"), ("extension", "extension"),
    ("cursor-hooks/gadak-hook.py", "cursor-hooks"), ("cursor-hooks/install.py", "cursor-hooks"),
    ("cursor-hooks/hooks.json", "cursor-hooks"), ("cursor-hooks/claude-settings.json", "cursor-hooks"),
)
FIRST_OPEN = """가닥을 처음 여는 법

1. 가닥을 응용 프로그램 폴더로 끌어 넣어요.
2. 응용 프로그램 폴더에서 가닥을 열어요. “확인되지 않은 개발자” 또는 “Apple은 … 확인할 수 없습니다”라고 나오면 ‘완료’를 눌러요.
3. 시스템 설정 → 개인정보 보호 및 보안으로 가서, 아래쪽의 “가닥이(가) 차단되었습니다” 옆 ‘그래도 열기’를 눌러요.
   (macOS 14 이하에서는 가닥을 오른쪽 클릭 → 열기 → 열기로도 돼요.)
4. 한 번 열고 나면 다음부터는 그냥 열려요.
5. 가닥이 켜지면 ‘AI 연결’ 창이 떠요. Claude 구독 · ChatGPT 구독 · API 키 중 하나를 골라 ‘연결하기’를 누르면 돼요.
   터미널을 열 일은 없어요. 그림이 든 안내는 같이 들어 있는 ‘가닥 설치 안내.pdf’를 봐 주세요.

가닥은 학교 과제로 만든 앱이라 Apple의 개발자 서명(유료)이 없어요. 그래서 처음 한 번 이 확인이 필요해요.
대화는 이 Mac에만 저장돼요(~/.gadak). 지우려면 가닥을 휴지통에 넣고 그 폴더도 지워요.
"""
GUIDE = config.ROOT / "docs" / "가닥-설치-안내.pdf"      # 받은 사람이 보는 설명서 (docs/install-guide/에서 만들어요). 있으면 디스크 이미지에 같이 넣어요
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


def info_plist(root=None, python=None, bundled=False) -> dict:
    """bundled: 백엔드를 앱 안에 넣은 앱. 저장소 폴더 · 파이썬 · 내 PATH를 적지 않아요(받은 사람의 Mac에는 없으니까요)."""
    info = {
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
    }
    if not bundled:
        # mac/Gadak.swift 가 읽는 값: 어디의 백엔드를 어떤 파이썬으로 돌릴지
        info.update(GadakRoot=str(root or config.ROOT), GadakPython=str(python or backend_python()), GadakPath=search_path())
    return info


def _run(command, what) -> None:
    done = subprocess.run(command, capture_output=True, text=True)
    if done.returncode != 0:
        raise BuildError(f"{what}에 실패했어요.\n{(done.stderr or done.stdout).strip()[-1500:]}")


def freeze(work, collect=None) -> Path:
    """백엔드를 파이썬째로 실행 파일 묶음으로 만들어요 (PyInstaller). work/dist/gadak-backend 폴더를 돌려줘요."""
    python = str(backend_python())
    if subprocess.run([python, "-m", "PyInstaller", "--version"], capture_output=True).returncode != 0:
        raise BuildError("PyInstaller가 없어요. 이렇게 깔아 주세요: .venv/bin/python -m pip install pyinstaller")
    work = Path(work)
    built = {"built": datetime.now().strftime("%Y%m%d-%H%M%S"), "version": VERSION, "collect": collect or None}
    (work / "BUILD.json").write_text(json.dumps(built, ensure_ascii=False), encoding="utf-8")
    command = [python, "-m", "PyInstaller", "--noconfirm", "--clean", "--log-level", "ERROR", "--onedir", "--name", BACKEND,
               "--distpath", str(work / "dist"), "--workpath", str(work / "build"), "--specpath", str(work),
               "--paths", str(config.ROOT), "--add-data", f"{work / 'BUILD.json'}:.",
               "--collect-submodules", "anthropic",        # SDK가 필요할 때 불러오는 모듈까지
               "--exclude-module", "tkinter", "--exclude-module", "eval", "--exclude-module", "tests"]
    for source, folder in BUNDLE_DATA:
        command += ["--add-data", f"{config.ROOT / source}:{folder}"]
    _run(command + [str(SOURCES / ENTRY)], "백엔드 묶기")
    return work / "dist" / BACKEND


def build(out=None, bundled=False, collect=None) -> Path:
    """dist/가닥.app 을 만들어 그 경로를 돌려줘요. bundled면 백엔드까지 앱 안에 넣어요(저장소 폴더 없이 도는 앱)."""
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
        (contents / "Info.plist").write_bytes(plistlib.dumps(info_plist(bundled=bundled)))
        (contents / "PkgInfo").write_text("APPL????", encoding="ascii")
        if bundled:
            shutil.copytree(freeze(work, collect), contents / "Resources" / "backend", symlinks=True)
    # Apple 개발자 서명이 없어서 임시 서명(ad-hoc)이에요. 묶인 앱은 안의 실행 파일까지 같이 서명해요
    _run(["codesign", "--force", "--sign", "-"] + (["--deep"] if bundled else []) + [str(app)], "서명")
    return app


def dmg(app, out=None) -> Path:
    """앱을 디스크 이미지로. 열면 가닥과 응용 프로그램 폴더로 가는 길, 처음 여는 법이 보여요."""
    out = Path(out or DIST)
    out.mkdir(parents=True, exist_ok=True)
    target = out / f"{NAME}-{VERSION}-{platform.machine()}.dmg"
    with tempfile.TemporaryDirectory() as tmp:
        stage = Path(tmp) / NAME
        stage.mkdir()
        shutil.copytree(app, stage / app.name, symlinks=True)
        (stage / "Applications").symlink_to("/Applications")
        (stage / "처음 여는 법.txt").write_text(FIRST_OPEN, encoding="utf-8")
        if GUIDE.is_file():
            shutil.copy2(GUIDE, stage / "가닥 설치 안내.pdf")
        target.unlink(missing_ok=True)
        _run(["hdiutil", "create", "-volname", NAME, "-srcfolder", str(stage), "-ov", "-format", "UDZO", str(target)], "디스크 이미지 만들기")
    return target


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
        if "--bundle" in argv or "--dmg" in argv:
            collect = config.COLLECT_URL if "--collect" in argv else None
            if "--collect" in argv and not collect:
                raise BuildError("backend/.env에 GADAK_COLLECT_URL이 없어요. --collect를 빼거나 주소를 적어 주세요.")
            print("백엔드를 앱 안에 묶고 있어요. 1~2분 걸려요…", flush=True)
            app = build(bundled=True, collect=collect)
            print(f"만들었어요: {app} (저장소 폴더 · 파이썬 없이 돌아요" + (", 사용 기록 서버 주소 포함)" if collect else ")"))
            if "--dmg" in argv:
                print(f"만들었어요: {dmg(app)}")
                print("받은 사람은 처음 한 번 시스템 설정 → 개인정보 보호 및 보안 → ‘그래도 열기’를 눌러야 해요 (디스크 이미지 안의 ‘처음 여는 법.txt’).")
            return 0
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
