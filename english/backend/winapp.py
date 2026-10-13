"""Windows에 까는 가닥(설치 파일)을 만들어요. 받아서 폴더에 모으는 일이라 macOS에서도 만들 수 있어요.

python -m backend.winapp                dist/win/Gadak/ — 깔리는 폴더 그대로 (파이썬 · 필요한 꾸러미 · 가닥 코드)
python -m backend.winapp --zip          dist/가닥-<판>-windows-x64.zip — 설치 없이 풀어서 쓰는 묶음 (‘가닥 켜기.cmd’)
python -m backend.winapp --installer    dist/가닥-<판>-windows-x64-설치.exe — 설치 프로그램 (NSIS가 있어야 해요)
python -m backend.winapp --collect      사용 기록을 받을 서버 주소(내 backend/.env의 GADAK_COLLECT_URL)를 적어 넣어요
python -m backend.winapp --icon         win/gadak.ico를 다시 그려요 (macOS에서만 · mac/icon.swift의 그림으로)

들어가는 것
- 파이썬: python.org의 Windows용 ‘embeddable package’(PYTHON_URL · 받은 파일의 해시를 확인해요). 받는 사람의 PC에 파이썬이 없어도 돼요.
- 꾸러미: requirements.txt의 것과 그것들이 끌고 오는 것을 Windows용으로 PyPI에서 받아요. 판은 지금 이 파이썬에 깔린 것과 같게 맞춰요.
- 가닥: backend/의 코드 · 화면 · 프롬프트 · 예시 · 크롬 확장 (macapp.BUNDLE_DATA와 같아요). .env · 실제 대화 · 테스트는 넣지 않아요.
- 설명서: ‘처음 여는 법.txt’와 그림이 든 ‘가닥 설치 안내.pdf’(docs/가닥-설치-안내.pdf · Mac의 디스크 이미지에 넣는 것과 같은 파일).

깔린 가닥은 시작 메뉴의 ‘가닥’이 pythonw.exe -X utf8 -m backend.launch --app 으로 켜요 (가닥 창 하나 · 닫으면 꺼져요).
macOS 앱과 달리 실행 파일 하나로 묶지 않아요(PyInstaller는 Windows에서만 Windows용을 만들고, 서명 없는 묶음은 백신에 자주 걸려요).

설치 프로그램은 win/gadak.nsi를 NSIS 3의 makensis로 엮어요 (nsis.sourceforge.io · zip으로 받아 풀기만 하면 돼요).
Windows에서는 makensis.exe를 그대로, macOS · Linux에서는 그 makensis.exe를 Wine으로 돌려요(직접 깐 makensis가 있으면 그것을 써요):
  GADAK_MAKENSIS=<makensis.exe> [GADAK_WINE=<wine>] python -m backend.winapp --installer
서명이 없어서, 받은 사람은 처음 한 번 ‘Windows의 PC 보호’ 창에서 추가 정보 → 실행을 눌러야 해요 (묶음 안의 ‘처음 여는 법.txt’).
"""
import hashlib
import importlib.metadata
import json
import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import zipfile
import zlib
from datetime import datetime
from pathlib import Path

from . import config, win
from .macapp import BUNDLE_DATA, GUIDE

NAME = "Gadak"
FOLDER = "Gadak"                 # 깔리는 폴더 · 묶음 안의 폴더 이름. 한글 경로를 못 다루는 도구를 피하려고 로마자로 둬요
VERSION = config.VERSION
PYTHON_VERSION = "3.14.6"        # 넣는 파이썬. 판을 올리면 아래 해시도 python.org에서 받은 파일의 것으로 바꿔요
PYTHON_URL = "https://www.python.org/ftp/python/{version}/python-{version}-embed-amd64.zip"
PYTHON_SHA256 = "df901e84a896ff1ee720ad03377e0c8d8c2244fda79808aeeaff6316df1cb75c"
WHEELS = "win_amd64"             # 받는 꾸러미의 종류 (64비트 Windows. ARM Windows 11도 이것을 돌려요)
LAUNCH = "-X utf8 -m backend.launch --app"      # 깔린 가닥을 켜는 말 (win/gadak.nsi · ‘가닥 켜기.cmd’가 써요)
START = "Start Gadak.cmd"
FIRST = "How to open Gadak.txt"
MANUAL = "Gadak install guide.pdf"     # 그림이 든 설명서 (docs/가닥-설치-안내.pdf · Mac의 디스크 이미지에 넣는 것과 같은 파일)
ICON = "gadak.ico"
ICON_SIZES = (16, 24, 32, 48, 64, 128, 256)
SOURCES = config.ROOT / "win"
DIST = config.ROOT / "dist"
WORK = DIST / "win"              # 받은 것(cache)과 모은 폴더가 여기에 남아요. 다시 만들 때 또 받지 않아요
SETUP = "gadak-setup.exe"        # makensis가 내는 파일 이름. 한글 이름은 그 뒤에 붙여요
SCRIPT = "gadak.nsi"
NSIS_SPOTS = (r"C:\Program Files (x86)\NSIS\makensis.exe", r"C:\Program Files\NSIS\makensis.exe")
PACKAGES = ("backend", "backend/agent", "backend/engines", "backend/sources")      # 가닥 코드가 든 폴더 (.py만 넣어요)

FIRST_OPEN = """How to open Gadak the first time (Windows)

1. Open ‘{setup}’. If a blue “Windows protected your PC” window appears, press More info → Run anyway.
2. In the installer press Install, then Finish when it is done. It installs for your account only, so no administrator password is needed.
3. Start Gadak from the Start menu or the desktop. The Gadak window opens on its own (an Edge or Chrome window without an address bar).
4. Pick one under Connect AI at the bottom left.
   - If Claude Code or Codex is installed on this PC and signed in, just pick it.
   - If not, paste an LLM API key (Anthropic · OpenAI · Gemini). The key is kept only in Windows Credential Manager on this PC.
5. Closing the Gadak window turns Gadak off. To start it again, use Gadak in the Start menu.

To use it without installing, unzip ‘{zip}’ and run ‘{start}’ inside it.
For an illustrated guide, see page 3 of ‘{manual}’ (in the installed folder and in the zip).

What the Mac app has that Windows does not yet
- The Gadak button floating over other apps
- One-click download of Claude Code or Codex (install them yourself and Gadak finds them)
- Cursor connection, auto-run for approved kinds, the Claude usage gauge

Gadak is an app made for a class project and has no paid signature. That is why the check above is needed once.
The Windows version was first made in {version}. If it does not start or behaves oddly, please send the team the gadak.log below.
Chats are stored only on this PC (C:\\Users\\your name\\.gadak). To remove them, uninstall Gadak under Settings → Apps and delete that folder too.
Log file: C:\\Users\\your name\\.gadak\\gadak.log
"""


class BuildError(RuntimeError):
    pass


def names() -> dict:
    """만들어지는 파일의 이름들."""
    base = f"{NAME}-{VERSION}-windows-x64"
    return {"zip": base + ".zip", "setup": base + "-setup.exe"}


# ---------- 무엇을 받을지 ----------

def _key(name) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def needed() -> tuple:
    """requirements.txt의 꾸러미와 그것들이 끌고 오는 것. ({이름: 지금 깔린 판}, [Windows에서만 필요한 이름])
    여기에 깔려 있지 않은 것은 이 파이썬에 필요 없는 것이라 빼요. 다만 ‘Windows에서만’이라고 적힌 것은 판을 정하지 않고 받아요."""
    wanted = [line.split("#")[0].strip() for line in (config.ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines()]
    todo = [(re.match(r"[A-Za-z0-9_.\-]+", line).group(0), "") for line in wanted if line]
    pinned, extra = {}, []
    while todo:
        name, marker = todo.pop()
        name = _key(name)
        if name in pinned or name in extra:
            continue
        try:
            found = importlib.metadata.distribution(name)
        except importlib.metadata.PackageNotFoundError:
            if re.search(r"win32|windows", marker, re.I) and not re.search(r"!=\s*[\"'](win32|windows)", marker, re.I):
                extra.append(name)
            continue
        pinned[name] = found.version
        for line in found.requires or []:
            requirement, _, marks = line.partition(";")
            if "extra ==" in marks or "extra==" in marks:
                continue                                    # 골라서 까는 덧붙임은 넣지 않아요
            todo.append((re.match(r"\s*[A-Za-z0-9_.\-]+", requirement).group(0).strip(), marks))
    return pinned, sorted(extra)


# ---------- 받기 ----------

def _download(url, target) -> None:
    import httpx2
    part = target.with_name(target.name + ".part")
    try:
        with httpx2.stream("GET", url, follow_redirects=True, timeout=120.0) as response:
            response.raise_for_status()
            with open(part, "wb") as out:
                for chunk in response.iter_bytes():
                    out.write(chunk)
    except Exception as exc:
        part.unlink(missing_ok=True)
        raise BuildError(f"받지 못했어요: {url}\n{str(exc)[:200]}") from exc
    part.replace(target)


def fetch_python(cache) -> Path:
    """Windows용 파이썬 묶음. 받아 둔 것이 있으면 그것을 써요. 해시가 다르면 쓰지 않아요."""
    target = Path(cache) / f"python-{PYTHON_VERSION}-embed-amd64.zip"
    if not target.is_file():
        target.parent.mkdir(parents=True, exist_ok=True)
        _download(PYTHON_URL.format(version=PYTHON_VERSION), target)
    seen = hashlib.sha256(target.read_bytes()).hexdigest()
    if seen != PYTHON_SHA256:
        target.unlink()
        raise BuildError(f"받은 파이썬이 적어 둔 것과 달라요({seen[:12]}…). 다시 돌려 보고, 그래도 다르면 PYTHON_SHA256을 확인해 주세요.")
    return target


def fetch_wheels(cache, pinned, extra) -> list:
    """Windows용 꾸러미(wheel)를 PyPI에서 받아요. 소스를 받아 여기서 엮지 않아요(--only-binary)."""
    folder = Path(cache) / "wheels"
    folder.mkdir(parents=True, exist_ok=True)
    wanted = [f"{name}=={version}" for name, version in sorted(pinned.items())] + list(extra)
    minor = ".".join(PYTHON_VERSION.split(".")[:2])
    command = [sys.executable, "-m", "pip", "download", "--quiet", "--disable-pip-version-check", "--no-deps",
               "--only-binary=:all:", "--platform", WHEELS, "--python-version", minor, "--implementation", "cp",
               "--dest", str(folder), *wanted]
    done = subprocess.run(command, capture_output=True, text=True)
    if done.returncode != 0:
        raise BuildError("Windows용 꾸러미를 받지 못했어요.\n" + (done.stderr or done.stdout).strip()[-1500:])
    found = []
    for name in list(pinned) + list(extra):
        mine = [w for w in folder.glob("*.whl") if _key(w.name.split("-")[0]) == name
                and (name not in pinned or w.name.split("-")[1] == pinned[name])]
        if not mine:
            raise BuildError(f"받은 것 가운데 {name}이(가) 없어요.")
        found.append(sorted(mine)[-1])
    return found


# ---------- 폴더에 모으기 ----------

def _unpack_wheel(wheel, site) -> None:
    with zipfile.ZipFile(wheel) as archive:
        for item in archive.infolist():
            parts = Path(item.filename).parts
            if len(parts) > 1 and parts[0].endswith(".data"):
                if parts[1] not in ("purelib", "platlib") or len(parts) < 3:
                    continue                                # 명령 · 머리 파일은 필요 없어요
                target = site.joinpath(*parts[2:])
            else:
                target = site.joinpath(*parts)
            if site.resolve() not in target.resolve().parents:
                raise BuildError(f"꾸러미 안에 이상한 경로가 있어요: {item.filename}")
            if item.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(archive.read(item))


def copy_app(app) -> None:
    """가닥 코드와 그것이 읽는 파일들. 코드는 .py만 넣어요(.env 같은 내 설정이 딸려 가지 않게)."""
    for package in PACKAGES:
        (app / package).mkdir(parents=True, exist_ok=True)
        for source in sorted((config.ROOT / package).glob("*.py")):
            shutil.copy2(source, app / package / source.name)
    for source, folder in BUNDLE_DATA:
        source, target = config.ROOT / source, app / folder
        if source.is_dir():
            shutil.copytree(source, target, dirs_exist_ok=True, ignore=shutil.ignore_patterns("__pycache__", ".DS_Store", ".env*"))
        else:
            target.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target / source.name)


def first_open() -> str:
    made = names()
    return FIRST_OPEN.format(setup=made["setup"], zip=made["zip"], start=START, version=VERSION, manual=MANUAL)


def stage(out=None, collect=None, cache=None) -> Path:
    """깔리는 폴더를 그대로 만들어요: python/ · site-packages/ · app/ · 아이콘 · 켜는 파일 · 처음 여는 법."""
    out = Path(out or WORK) / FOLDER
    cache = Path(cache or WORK / "cache")
    python = fetch_python(cache)
    pinned, extra = needed()
    wheels = fetch_wheels(cache, pinned, extra)
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)

    with zipfile.ZipFile(python) as archive:
        archive.extractall(out / "python")
    paths = list((out / "python").glob("python*._pth"))
    if len(paths) != 1:
        raise BuildError("받은 파이썬 묶음의 모양이 평소와 달라요 (._pth 파일).")
    # 이 파이썬이 볼 곳은 이 넷뿐이에요. PC에 깔린 다른 파이썬 · 환경 변수 PYTHONPATH는 보지 않아요
    library = next(p.name for p in (out / "python").glob("python*.zip"))
    paths[0].write_text("\n".join([library, ".", "..\\app", "..\\site-packages"]) + "\n", encoding="ascii")

    site = out / "site-packages"
    site.mkdir()
    for wheel in wheels:
        _unpack_wheel(wheel, site)

    app = out / "app"
    copy_app(app)
    built = {"built": datetime.now().strftime("%Y%m%d-%H%M%S"), "version": VERSION, "collect": collect or None,
             "folder": True, "os": "windows", "python": PYTHON_VERSION,
             "packages": dict(sorted(pinned.items())), "windows_only": [w.name for w in wheels if _key(w.name.split("-")[0]) in extra]}
    (app / "BUILD.json").write_text(json.dumps(built, ensure_ascii=False, indent=1), encoding="utf-8")

    icon = SOURCES / ICON
    if not icon.is_file():
        raise BuildError(f"{icon}이 없어요. macOS에서 python -m backend.winapp --icon 으로 그려 주세요.")
    shutil.copy2(icon, out / ICON)
    # 켜는 파일은 로마자만 써요: cmd.exe는 이 파일을 PC마다 다른 글자표로 읽어요
    (out / START).write_bytes(("@echo off\r\n" f'start "" "%~dp0python\\pythonw.exe" {LAUNCH}\r\n').encode("ascii"))
    (out / FIRST).write_bytes(first_open().replace("\n", "\r\n").encode("utf-8-sig"))     # 메모장이 한글을 바로 읽게
    if GUIDE.is_file():
        shutil.copy2(GUIDE, out / MANUAL)
    return out


def zipped(folder, out=None) -> Path:
    """설치 없이 풀어서 쓰는 묶음. 풀면 Gadak 폴더 하나가 나와요."""
    out = Path(out or DIST)
    out.mkdir(parents=True, exist_ok=True)
    target = out / names()["zip"]
    target.unlink(missing_ok=True)
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in sorted(Path(folder).rglob("*")):
            if path.is_file():
                archive.write(path, (Path(FOLDER) / path.relative_to(folder)).as_posix())
    return target


# ---------- 설치 프로그램 (NSIS) ----------

def find_makensis() -> list:
    """makensis를 부르는 낱말들. Windows용 makensis.exe를 Windows가 아닌 곳에서 쓸 때는 앞에 wine이 붙어요. 없으면 []."""
    named = os.environ.get("GADAK_MAKENSIS")
    found = (named if named and Path(named).is_file() else None) if named is not None else (
        shutil.which("makensis") or next((spot for spot in NSIS_SPOTS if Path(spot).is_file()), None))
    if not found:
        return []
    if win.WINDOWS or not found.lower().endswith(".exe"):
        return [found]
    wine = os.environ.get("GADAK_WINE") or shutil.which("wine")
    return [wine, found] if wine else []


def installer(folder, out=None) -> Path:
    """설치 프로그램을 엮어요. 한글이 든 경로를 피하려고 임시 폴더에서 엮고, 다 된 파일에 이름을 붙여요."""
    makensis = find_makensis()
    if not makensis:
        raise BuildError("NSIS의 makensis를 찾지 못했어요. NSIS 3을 받아 GADAK_MAKENSIS에 makensis.exe의 경로를 적어 주세요 "
                         "(nsis.sourceforge.io). Windows가 아닌 곳에서는 GADAK_WINE에 wine의 경로도 적어 주세요.")
    out = Path(out or DIST)
    out.mkdir(parents=True, exist_ok=True)
    target = out / names()["setup"]
    # Windows용 makensis는 /로 시작하는 말을, 직접 깐 것(macOS · Linux)은 -로 시작하는 말을 받아요
    mark = "/" if makensis[-1].lower().endswith(".exe") else "-"
    with tempfile.TemporaryDirectory(prefix="gadak-win-") as tmp:
        work = Path(tmp)
        shutil.copytree(folder, work / "stage")
        shutil.copy2(SOURCES / SCRIPT, work / SCRIPT)
        command = makensis + [f"{mark}INPUTCHARSET", "UTF8", f"{mark}V2", f"{mark}DVERSION={VERSION}", f"{mark}DLAUNCH={LAUNCH}",
                              f"{mark}DOUTFILE={SETUP}", SCRIPT]
        done = subprocess.run(command, cwd=work, capture_output=True, text=True, errors="replace")
        made = work / SETUP
        if done.returncode != 0 or not made.is_file():
            raise BuildError("설치 프로그램을 엮지 못했어요.\n" + (done.stdout + done.stderr).strip()[-1500:])
        target.unlink(missing_ok=True)
        shutil.move(str(made), str(target))
    return target


# ---------- 아이콘 (.ico) ----------

def _png_pixels(data) -> tuple:
    """PNG(8비트 RGBA · RGB, 엇갈림 없음)를 풀어요. (너비, 높이, 줄마다 RGBA 바이트)"""
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise BuildError("PNG가 아니에요.")
    spot, packed, head = 8, b"", None
    while spot < len(data):
        size, kind = struct.unpack(">I4s", data[spot:spot + 8])
        body = data[spot + 8:spot + 8 + size]
        if kind == b"IHDR":
            head = struct.unpack(">IIBBBBB", body)
        elif kind == b"IDAT":
            packed += body
        spot += 12 + size
    width, height, depth, color, _, _, interlace = head
    if depth != 8 or color not in (2, 6) or interlace:
        raise BuildError("이 PNG는 풀지 못해요 (8비트 RGB · RGBA만).")
    step = 4 if color == 6 else 3
    raw, line, rows, before = zlib.decompress(packed), width * step, [], bytearray(width * step)
    for y in range(height):
        kind, row = raw[y * (line + 1)], bytearray(raw[y * (line + 1) + 1:(y + 1) * (line + 1)])
        for i in range(line):
            left = row[i - step] if i >= step else 0
            up = before[i]
            corner = before[i - step] if i >= step else 0
            if kind == 1:
                row[i] = (row[i] + left) & 255
            elif kind == 2:
                row[i] = (row[i] + up) & 255
            elif kind == 3:
                row[i] = (row[i] + (left + up) // 2) & 255
            elif kind == 4:
                guess = left + up - corner
                near = min((abs(guess - left), 0, left), (abs(guess - up), 1, up), (abs(guess - corner), 2, corner))[2]
                row[i] = (row[i] + near) & 255
        before = row
        rows.append(bytes(row) if step == 4 else b"".join(bytes(row[i:i + 3]) + b"\xff" for i in range(0, line, 3)))
    return width, height, rows


def ico(pngs) -> bytes:
    """크기별 PNG들 → .ico 하나. 256은 PNG 그대로, 작은 것은 예전 프로그램도 읽는 모양(BMP)으로 넣어요."""
    images = []
    for data in pngs:
        width, height, rows = _png_pixels(data)
        if width != height or width > 256:
            raise BuildError("아이콘은 256 이하의 정사각형이어야 해요.")
        if width == 256:
            images.append((width, data))
            continue
        pixels = b"".join(bytes(b for i in range(0, len(row), 4) for b in (row[i + 2], row[i + 1], row[i], row[i + 3]))
                          for row in reversed(rows))
        mask_line = (width + 31) // 32 * 4
        mask = b"".join(bytes(sum((1 << (7 - bit)) for bit in range(8) if x + bit < width and row[(x + bit) * 4 + 3] == 0)
                              for x in range(0, width, 8)).ljust(mask_line, b"\0") for row in reversed(rows))
        header = struct.pack("<IiiHHIIiiII", 40, width, height * 2, 1, 32, 0, len(pixels) + len(mask), 0, 0, 0, 0)
        images.append((width, header + pixels + mask))
    images.sort(key=lambda item: item[0])
    out, offset = struct.pack("<HHH", 0, 1, len(images)), 6 + 16 * len(images)
    for width, body in images:
        out += struct.pack("<BBBBHHII", width % 256, width % 256, 0, 0, 1, 32, len(body), offset)
        offset += len(body)
    return out + b"".join(body for _, body in images)


def draw_icon() -> Path:
    """win/gadak.ico를 다시 그려요. mac/icon.swift가 그린 그림에서 둘레의 빈 자리를 덜어 내고(Windows 아이콘은 칸을 꽉 채워요) 크기별로 줄여요."""
    if sys.platform != "darwin" or not shutil.which("swiftc"):
        raise BuildError("아이콘은 macOS에서 그려요 (swiftc · sips가 있어야 해요). 그려 둔 win/gadak.ico가 저장소에 있어요.")
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        steps = [(["swiftc", "-O", "-swift-version", "5", "-o", str(work / "icon"), str(config.ROOT / "mac" / "icon.swift")], "아이콘 도구 컴파일"),
                 ([str(work / "icon"), str(work / "set")], "아이콘 그리기"),
                 (["sips", "-c", "872", "872", str(work / "set" / "icon_512x512@2x.png"), "--out", str(work / "tile.png")], "둘레 덜어 내기")]
        steps += [(["sips", "-z", str(size), str(size), str(work / "tile.png"), "--out", str(work / f"{size}.png")], f"{size}px로 줄이기")
                  for size in ICON_SIZES]
        for command, what in steps:
            done = subprocess.run(command, capture_output=True, text=True)
            if done.returncode != 0:
                raise BuildError(f"{what}에 실패했어요.\n{(done.stderr or done.stdout).strip()[-600:]}")
        SOURCES.mkdir(exist_ok=True)
        (SOURCES / ICON).write_bytes(ico([(work / f"{size}.png").read_bytes() for size in ICON_SIZES]))
    return SOURCES / ICON


def main(argv) -> int:
    try:
        if "--icon" in argv:
            print(f"Drew: {draw_icon()}")
            return 0
        collect = config.COLLECT_URL if "--collect" in argv else None
        if "--collect" in argv and not collect:
            raise BuildError("GADAK_COLLECT_URL is not in backend/.env. Drop --collect or add the address.")
        print("Downloading and gathering Python and packages for Windows. The first time takes 1–2 minutes…", flush=True)
        folder = stage(collect=collect)
        print(f"Gathered: {folder}" + (" (with the usage server address)" if collect else ""))
        if "--zip" in argv:
            print(f"Built: {zipped(folder)}")
        if "--installer" in argv:
            print(f"Built: {installer(folder)}")
            print("Recipients need to press More info → Run anyway once in the ‘Windows protected your PC’ window (see ‘How to open Gadak.txt’ in the bundle).")
    except BuildError as exc:
        print(exc)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
