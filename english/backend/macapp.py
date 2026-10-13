"""macOS 앱(가닥.app)을 만들어요. 창 · Dock 아이콘 · 메뉴가 있는 보통 프로그램이에요.

python -m backend.macapp                   dist/가닥.app 을 만들어요 (만들어만 보기)
python -m backend.macapp --install         만들어 응용 프로그램 폴더에 넣어요 (/Applications, 안 되면 ~/Applications)
python -m backend.macapp --install 폴더    그 폴더에 넣어요
python -m backend.macapp --install --open  넣고 바로 켜요 (‘Install Gadak.command’가 이렇게 불러요)

앱의 겉은 mac/Gadak.swift(창 · 메뉴)와 mac/Float.swift(떠 있는 버튼)이고, 켜지면 이 저장소의 백엔드(python -m backend.launch --shell)를 뒤에서 돌려요.
그래서 앱은 이 폴더와 이 폴더의 .venv를 가리켜요. 폴더를 옮기면 다시 만들어 주세요.
Swift 컴파일러(Xcode 명령어 도구: xcode-select --install)가 있어야 해요.

남에게 건네는 앱 (설치하면 바로 켜지는 앱 · docs/usage-guide.md 1장)
python -m backend.macapp --bundle          dist/가닥.app — 백엔드와 파이썬까지 앱 안에 넣어요. 저장소 폴더 없이 돌아요
python -m backend.macapp --dmg             dist/가닥-<판>-<arm64|x86_64>.dmg — 위 앱을 담은 디스크 이미지
python -m backend.macapp --dmg --collect   사용 기록을 받을 서버 주소(내 backend/.env의 GADAK_COLLECT_URL)를 앱에 적어 넣어요
묶을 때는 PyInstaller를 써요: .venv/bin/python -m pip install pyinstaller. 만든 앱은 임시 서명이라, 받은 사람은 처음 한 번
‘확인되지 않은 개발자’ 경고를 넘겨야 해요(시스템 설정 → 개인정보 보호 및 보안 → 그래도 열기).

앱은 만드는 Mac과 같은 종류(arm64 · x86_64)로 나와요. Apple Silicon Mac에서 Intel Mac용을 만들려면 --arch x86_64를 붙여요.
그때 백엔드는 Rosetta로 묶어요. Intel용 꾸러미가 깔린 파이썬이 따로 있어야 해서(.venv에는 Apple Silicon용이 깔려 있어요)
그 자리를 GADAK_BUILD_PYTHON으로 알려 줘요. 앱은 dist/x86_64/에, 디스크 이미지는 dist/에 생겨요 (이렇게 만든 것은 macOS 13부터 돌아요):
  arch -x86_64 /Library/Frameworks/Python.framework/Versions/3.14/bin/python3 -m venv <폴더>
  arch -x86_64 <폴더>/bin/python -m pip install -r requirements.txt pyinstaller
  GADAK_BUILD_PYTHON=<폴더>/bin/python .venv/bin/python -m backend.macapp --dmg --arch x86_64
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

NAME = "Gadak"
EXECUTABLE = "Gadak"
BUNDLE_ID = "local.gadak.app.en"   # 한글판(local.gadak.app)과 한 Mac에 같이 깔 수 있게
VERSION = config.VERSION
MIN_MACOS = "12.0"
# Apple Silicon Mac에서 Intel Mac용을 만들 때의 가장 낮은 macOS. 요즘 Swift 도구에는 macOS 12에서 돌 Intel용 호환 라이브러리가
# 들어 있지 않아서(libswiftCompatibility56이 arm64뿐) 13부터예요. Intel Mac에서 직접 만들면 위의 값 그대로예요
MIN_MACOS_INTEL_FROM_ARM = "13.0"
BACKEND = "gadak-backend"      # 앱 안에 묶는 백엔드 실행 파일. mac/Gadak.swift · backend/sources(HOOK_MARKS)가 이 이름을 알아요
ENTRY = "backend_main.py"      # mac/ 안의 그 실행 파일의 첫 줄
# 묶인 백엔드가 파일로 읽는 것들: (저장소 안의 자리, 앱 안의 폴더). backend/config.py의 ROOT가 이 폴더들의 위예요
BUNDLE_DATA = (
    ("shared/ui", "shared/ui"), ("backend/web", "backend/web"), ("backend/prompts", "backend/prompts"),
    ("data/demo_conversations.json", "data"), ("extension", "extension"),
    ("cursor-hooks/gadak-hook.py", "cursor-hooks"), ("cursor-hooks/install.py", "cursor-hooks"),
    ("cursor-hooks/hooks.json", "cursor-hooks"), ("cursor-hooks/claude-settings.json", "cursor-hooks"),
)
FIRST_OPEN = """How to open Gadak the first time

1. Drag Gadak into the Applications folder.
2. Open Gadak from the Applications folder. If it says “unidentified developer” or “Apple could not verify …”, press Done.
3. Go to System Settings → Privacy & Security, and near the bottom, next to “Gadak was blocked”, press Open Anyway.
   (On macOS 14 or earlier you can also right-click Gadak → Open → Open.)
4. After opening it once, it opens normally from then on.
5. When Gadak starts, the Connect AI window appears. Pick a Claude subscription, a ChatGPT subscription or an API key and press Connect.
   There is no need to open a terminal. For an illustrated guide, see ‘Gadak install guide.pdf’ in the same window.

Gadak is an app made for a class project and has no paid Apple developer signature. That is why this check is needed once.
Chats are stored only on this Mac (~/.gadak). To remove them, move Gadak to the Trash and delete that folder too.
"""
GUIDE = config.ROOT / "docs" / "gadak-install-guide.pdf"      # 받은 사람이 보는 설명서 (docs/install-guide/에서 만들어요). 있으면 디스크 이미지에 같이 넣어요
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
        # 영어판: 여기가 ko면 macOS가 그리는 것(파일 고르기 창 · 기본 메뉴 항목)이 영어 사용자에게도 한글로 떠요
        "CFBundleDevelopmentRegion": "en",
        "CFBundleLocalizations": ["en"],
        "LSMinimumSystemVersion": MIN_MACOS,
        "LSApplicationCategoryType": "public.app-category.productivity",
        "NSHighResolutionCapable": True,
        "NSPrincipalClass": "NSApplication",
        "NSHumanReadableCopyright": "Keep the thread of every long chat.",
        # 화면은 내 PC 안의 백엔드(http://127.0.0.1)에서 받아요
        "NSAppTransportSecurity": {"NSAllowsLocalNetworking": True},
    }
    if not bundled:
        # mac/Gadak.swift 가 읽는 값: 어디의 백엔드를 어떤 파이썬으로 돌릴지
        info.update(GadakRoot=str(root or config.ROOT), GadakPython=str(python or backend_python()), GadakPath=search_path())
    return info


def _run(command, what, env=None) -> None:
    done = subprocess.run(command, capture_output=True, text=True, env=env)
    if done.returncode != 0:
        raise BuildError(f"{what}에 실패했어요.\n{(done.stderr or done.stdout).strip()[-1500:]}")


def tools_first() -> dict:
    """개발 도구의 진짜 자리를 PATH 맨 앞에 둔 환경. Rosetta로 도는 PyInstaller가 lipo를 부를 때 써요:
    /usr/bin의 lipo는 진짜 도구를 찾아 주는 껍데기인데, 요즘 것은 Intel 쪽에서 불리면 켜지지 않아요."""
    try:
        home = subprocess.run(["/usr/bin/xcode-select", "-p"], capture_output=True, text=True, timeout=5).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        home = ""
    spots = [str(Path(home) / tail) for tail in ("usr/bin", "Toolchains/XcodeDefault.xctoolchain/usr/bin") if home and (Path(home) / tail).is_dir()]
    return dict(os.environ, PATH=os.pathsep.join(spots + [os.environ.get("PATH", "")]))


def freeze(work, collect=None, arch=None) -> Path:
    """백엔드를 파이썬째로 실행 파일 묶음으로 만들어요 (PyInstaller). work/dist/gadak-backend 폴더를 돌려줘요.
    묶을 파이썬을 따로 정하려면 GADAK_BUILD_PYTHON. arch가 이 Mac과 다르면 그 파이썬을 그 종류로 돌려요 (Intel Mac용 · 위의 설명)."""
    named = os.environ.get("GADAK_BUILD_PYTHON")
    python, env = [named or str(backend_python())], None
    if arch and arch != platform.machine():
        if not named:
            raise BuildError(f"{arch}용 꾸러미가 깔린 파이썬이 따로 있어야 해요. 그 자리를 GADAK_BUILD_PYTHON에 적어 주세요 (backend/macapp.py 머리말).")
        python, env = ["arch", f"-{arch}"] + python, tools_first()
    if subprocess.run(python + ["-m", "PyInstaller", "--version"], capture_output=True).returncode != 0:
        raise BuildError("PyInstaller가 없어요. 이렇게 깔아 주세요: .venv/bin/python -m pip install pyinstaller")
    work = Path(work)
    built = {"built": datetime.now().strftime("%Y%m%d-%H%M%S"), "version": VERSION, "collect": collect or None}
    (work / "BUILD.json").write_text(json.dumps(built, ensure_ascii=False), encoding="utf-8")
    command = python + ["-m", "PyInstaller", "--noconfirm", "--clean", "--log-level", "ERROR", "--onedir", "--name", BACKEND,
               "--distpath", str(work / "dist"), "--workpath", str(work / "build"), "--specpath", str(work),
               "--paths", str(config.ROOT), "--add-data", f"{work / 'BUILD.json'}:.",
               "--collect-submodules", "anthropic",        # SDK가 필요할 때 불러오는 모듈까지
               "--exclude-module", "tkinter", "--exclude-module", "eval", "--exclude-module", "tests"]
    for source, folder in BUNDLE_DATA:
        command += ["--add-data", f"{config.ROOT / source}:{folder}"]
    _run(command + [str(SOURCES / ENTRY)], "백엔드 묶기", env)
    return work / "dist" / BACKEND


def build(out=None, bundled=False, collect=None, arch=None) -> Path:
    """dist/가닥.app 을 만들어 그 경로를 돌려줘요. bundled면 백엔드까지 앱 안에 넣어요(저장소 폴더 없이 도는 앱).
    arch(arm64 · x86_64)를 주면 그 종류의 Mac용으로 만들어요. 비우면 이 Mac과 같은 종류예요."""
    if sys.platform != "darwin":
        raise BuildError("앱은 macOS에서만 만들어요. 다른 곳에서는 python -m backend.launch 로 켜세요.")
    swiftc = shutil.which("swiftc")
    if not swiftc:
        raise BuildError("Swift 컴파일러가 없어요. 터미널에서 xcode-select --install 로 Xcode 명령어 도구를 깔아 주세요.")
    app = Path(out or DIST) / f"{NAME}.app"
    crossed = bool(arch) and arch != platform.machine()
    minimum = MIN_MACOS_INTEL_FROM_ARM if crossed and arch == "x86_64" else MIN_MACOS
    target = f"{arch or platform.machine()}-apple-macos{minimum}"
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
        (contents / "Info.plist").write_bytes(plistlib.dumps(dict(info_plist(bundled=bundled), LSMinimumSystemVersion=minimum)))
        (contents / "PkgInfo").write_text("APPL????", encoding="ascii")
        if bundled:
            shutil.copytree(freeze(work, collect, arch), contents / "Resources" / "backend", symlinks=True)
    # Apple 개발자 서명이 없어서 임시 서명(ad-hoc)이에요. 묶인 앱은 안의 실행 파일까지 같이 서명해요
    _run(["codesign", "--force", "--sign", "-"] + (["--deep"] if bundled else []) + [str(app)], "서명")
    return app


def dmg(app, out=None, arch=None) -> Path:
    """앱을 디스크 이미지로. 열면 가닥과 응용 프로그램 폴더로 가는 길, 처음 여는 법이 보여요."""
    out = Path(out or DIST)
    out.mkdir(parents=True, exist_ok=True)
    target = out / f"{NAME}-{VERSION}-{arch or platform.machine()}.dmg"
    with tempfile.TemporaryDirectory() as tmp:
        stage = Path(tmp) / NAME
        stage.mkdir()
        shutil.copytree(app, stage / app.name, symlinks=True)
        (stage / "Applications").symlink_to("/Applications")
        (stage / "How to open Gadak.txt").write_text(FIRST_OPEN, encoding="utf-8")
        if GUIDE.is_file():
            shutil.copy2(GUIDE, stage / "Gadak install guide.pdf")
        target.unlink(missing_ok=True)
        _run(["hdiutil", "create", "-volname", NAME, "-srcfolder", str(stage), "-ov", "-format", "UDZO", str(target)], "making the disk image")
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
                raise BuildError("GADAK_COLLECT_URL is not in backend/.env. Drop --collect or add the address.")
            arch = argv[argv.index("--arch") + 1] if "--arch" in argv and argv.index("--arch") + 1 < len(argv) else None
            if arch not in (None, "arm64", "x86_64"):
                raise BuildError("Put arm64 or x86_64 after --arch.")
            other = arch if arch and arch != platform.machine() else None      # 이 Mac과 다른 종류면 dist/<종류>/에 따로 둬요
            print("Bundling the backend into the app. This takes 1–2 minutes…", flush=True)
            app = build(DIST / other if other else None, bundled=True, collect=collect, arch=other)
            print(f"Built: {app} (runs without the repo folder or Python" + (", with the usage server address)" if collect else ")"))
            if "--dmg" in argv:
                print(f"Built: {dmg(app, arch=other)}")
                print("Recipients need to press System Settings → Privacy & Security → Open Anyway once (see ‘How to open Gadak.txt’ in the disk image).")
            return 0
        if "--install" not in argv:
            print(f"Built: {build()}")
            return 0
        folder = next((a for a in argv if not a.startswith("--")), None)
        with tempfile.TemporaryDirectory() as tmp:   # 저장소 안에 같은 앱이 하나 더 남지 않게 임시 폴더에서 만들어요
            target = install(build(tmp), folder)
        print(f"Installed the Gadak app: {target}")
        print("Find ‘Gadak’ in Launchpad or Spotlight to start it. To keep it in the Dock, right-click its icon → Options → Keep in Dock.")
        if "--open" in argv:
            subprocess.run(["open", str(target)])
    except BuildError as exc:
        print(exc)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
