"""가닥 배포 사이트를 만들어요 — 소개 · OS별 받기 · 바로 써 보는 데모, 한국어와 영어.

    ./.venv/bin/python -m homepage.build            # dist/site/ 에 만들어요
    ./.venv/bin/python -m homepage.build --serve    # 만들고 http://127.0.0.1:7398 에서 보여 줘요
    ./.venv/bin/python -m homepage.build --stamp    # dist/ 의 설치 파일로 downloads.json 을 다시 적어요
    ./.venv/bin/python -m homepage.build --artifact # Claude 아티팩트(비공개 미리보기)로 올릴 모양으로

사이트는 정적 파일뿐이에요(서버 코드가 없어요). 주소가 어디든 돌게 모든 길을 상대 경로로 적어요.

바로 써 보는 데모(app/)는 가닥 창(backend/web · shared/ui)을 그대로 복사해, 백엔드를 부르지 않고
만든 예시(data/demo_conversations.json)만 보여 주게 몇 줄을 바꾼 것이에요. 실제 대화는 들어가지 않아요.
바꾸는 줄은 PATCHES에 다 적혀 있고, 가닥 창의 코드가 달라져 그 줄을 못 찾으면 만들기를 멈춰요.

설치 파일은 사이트에 넣지 않아요. 받기 버튼은 GitHub Releases의 파일을 가리키고,
파일 이름 · 크기 · 확인 값은 homepage/downloads.json 에 적어 둬요(--stamp 가 다시 적어요).
"""
from __future__ import annotations

import argparse
import functools
import hashlib
import http.server
import json
import re
import shutil
import sys
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape
from markupsafe import Markup, escape

ROOT = Path(__file__).resolve().parent.parent
HERE = ROOT / "homepage"
OUT = ROOT / "dist" / "site"
PORT = 7398                      # 가닥(7311) · 시험용 가닥(7399)과 겹치지 않는 번호

REPO = "Hanhws/AI-agent"
LANGS = ("ko", "en")             # 앞의 것이 사이트의 뿌리에 놓여요. 나머지는 그 이름의 폴더에
PAGES = ("index", "download", "demo")
DOWNLOADS = HERE / "downloads.json"
GUIDE = ROOT / "docs" / "가닥-설치-안내.pdf"
GUIDE_NAME = "gadak-install-guide.pdf"
SHOTS = ROOT / "docs" / "install-guide" / "img"   # 설치 안내에 쓴 화면 그림(만든 예시). 아래 것만 사이트에 같이 써요
SITE_SHOTS = ("window.png", "map.png", "float-fan.png")

# 설치 파일: dist/ 에서의 이름 → 올릴 때의 이름. GitHub는 한글 파일 이름을 지워 버려서 로마자로 올려요
INSTALLERS = (
    ("mac-arm64", "가닥-{v}-arm64.dmg", "Gadak-{v}-mac-arm64.dmg"),
    ("mac-x86_64", "가닥-{v}-x86_64.dmg", "Gadak-{v}-mac-x86_64.dmg"),
    ("win-setup", "가닥-{v}-windows-x64-설치.exe", "Gadak-{v}-windows-x64-setup.exe"),
    ("win-zip", "가닥-{v}-windows-x64.zip", "Gadak-{v}-windows-x64.zip"),
)
EXTENSION = ("extension", "Gadak-{v}-chrome-extension.zip")

# 가닥 창을 데모로 옮길 때 가져오는 것
APP_WEB = ("index.html", "app.css", "app.js", "map.html", "help.html")
APP_DATA = "demo_conversations.json"
# (파일, 원래 글, 바꿀 글): 백엔드 없이 만든 예시만 보여 주게 하는 줄들
PATCHES = (
    ("index.html", "<title>가닥</title>", "<title>가닥 — 바로 써 보는 데모</title>"),
    ("web/app.js", "var S = { demo: params.has('demo'),", "var S = { demo: true,"),
    ("web/app.js", "R.mapFrame.src = 'map';", "R.mapFrame.src = 'map.html';"),   # /map 이 아니면 지도가 만든 예시를 그려요
    ("web/app.js", "window.open('help', 'gadak-help')", "window.open('help.html', 'gadak-help')"),
    ("map.html", '<script src="/ui/mark.js"></script>', '<script src="ui/mark.js"></script>'),
    ("map.html", "<title>가닥 전체 지도</title>",
     '<title>가닥 전체 지도 — 바로 써 보는 데모</title>\n<link rel="icon" href="../assets/gadak.svg" type="image/svg+xml">'),
)


class Stop(Exception):
    """만들 수 없을 때 — 사람이 읽을 한 줄을 담아요."""


def version() -> str:
    return json.loads(DOWNLOADS.read_text(encoding="utf-8"))["version"]


def downloads() -> dict:
    """받기 버튼에 쓸 것: 파일마다 올린 이름 · 크기 · 확인 값과 받는 주소."""
    info = json.loads(DOWNLOADS.read_text(encoding="utf-8"))
    base = f"https://github.com/{REPO}/releases/download/{info['tag']}/"
    for item in info["files"].values():
        item["url"] = base + item["asset"]
        item["mb"] = f"{item['bytes'] / 1_000_000:.0f}"
    info["page"] = f"https://github.com/{REPO}/releases/tag/{info['tag']}"
    info["repo"] = f"https://github.com/{REPO}"
    return info


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def extension_zip(out: Path) -> Path:
    """크롬 확장 폴더를 zip으로 묶어요. 같은 내용이면 늘 같은 파일이 나오게 시각과 차례를 고정해요."""
    import zipfile

    folder, name = ROOT / EXTENSION[0], EXTENSION[1].format(v=version())
    target = out / name
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as z:
        for path in sorted(p for p in folder.rglob("*") if p.is_file() and p.name != ".DS_Store"):
            entry = zipfile.ZipInfo(f"gadak-extension/{path.relative_to(folder).as_posix()}", (2026, 10, 12, 0, 0, 0))
            entry.compress_type = zipfile.ZIP_DEFLATED
            entry.external_attr = 0o644 << 16
            z.writestr(entry, path.read_bytes())
    return target


def stamp(staged: Path | None = None) -> dict:
    """dist/ 의 설치 파일을 읽어 downloads.json 의 크기 · 확인 값을 다시 적어요.
    staged 를 주면 올릴 이름으로 복사한 파일(과 확장 zip)을 그 폴더에 모아요."""
    info = json.loads(DOWNLOADS.read_text(encoding="utf-8"))
    v = info["version"]
    for key, local, asset in INSTALLERS:
        path = ROOT / "dist" / local.format(v=v)
        if not path.exists():
            raise Stop(f"설치 파일이 없어요: dist/{path.name} (먼저 backend.macapp · backend.winapp 으로 만들어요)")
        info["files"][key].update(asset=asset.format(v=v), bytes=path.stat().st_size, sha256=_sha256(path))
        if staged:
            shutil.copyfile(path, staged / asset.format(v=v))
    if staged:
        packed = extension_zip(staged)
        info["files"]["extension"].update(asset=packed.name, bytes=packed.stat().st_size, sha256=_sha256(packed))
    DOWNLOADS.write_text(json.dumps(info, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return info


def demo(out: Path) -> Path:
    """가닥 창을 out/app/ 에 복사해 만든 예시만 보여 주는 정적 페이지로 만들어요."""
    app = out / "app"
    (app / "web").mkdir(parents=True)
    (app / "data").mkdir()
    for name in APP_WEB:
        # index · map · help 는 가닥에서 뿌리 주소(/ · /map · /help)로 열리던 것이라 app/ 바로 아래에 둬요
        target = app / name if name.endswith(".html") else app / "web" / name
        shutil.copyfile(ROOT / "backend" / "web" / name, target)
    shutil.copytree(ROOT / "shared" / "ui", app / "ui")
    shutil.copyfile(ROOT / "data" / APP_DATA, app / "data" / APP_DATA)
    for name, old, new in PATCHES:
        path = app / name
        text = path.read_text(encoding="utf-8")
        if text.count(old) != 1:
            raise Stop(f"데모로 옮길 줄을 못 찾았어요: {name} 의 「{old}」 (가닥 창 코드가 바뀌었으면 homepage/build.py 의 PATCHES 를 맞춰요)")
        path.write_text(text.replace(old, new), encoding="utf-8")
    return app


def _strings(lang: str) -> dict:
    return json.loads((HERE / "strings" / f"{lang}.json").read_text(encoding="utf-8"))


def _where(lang: str, page: str) -> Path:
    """그 말 · 그 쪽이 놓이는 자리 (사이트 뿌리에서부터)."""
    parts = [] if lang == LANGS[0] else [lang]
    if page != "index":
        parts.append(page)
    return Path(*parts, "index.html")


def _png_size(path: Path) -> tuple[int, int]:
    head = path.read_bytes()[:24]
    if head[:8] != b"\x89PNG\r\n\x1a\n":
        raise Stop(f"PNG 그림이 아니에요: {path}")
    return int.from_bytes(head[16:20], "big"), int.from_bytes(head[20:24], "big")


def _shot(up: str, name: str, alt: str) -> Markup:
    """화면 그림 한 장. 크기를 같이 적어 두면 그림이 뜨기 전에도 자리가 잡혀요."""
    path = next((p for p in (HERE / "static" / "shots" / name, SHOTS / name) if p.exists()), None)
    if path is None:
        raise Stop(f"화면 그림이 없어요: {name}")
    width, height = _png_size(path)
    # --ratio(너비 ÷ 높이)는 옆 그림을 화면 높이에 맞춰 줄일 때 써요 (site.css의 .feat-media)
    return Markup(f'<img src="{escape(up)}assets/shots/{escape(name)}" width="{width}" height="{height}" '
                  f'style="--ratio: {width / height:.4f}" alt="{escape(alt)}" loading="lazy">')


def _date(lang: str, iso: str) -> str:
    year, month, day = (int(part) for part in iso.split("-"))
    if lang == "ko":
        return f"{year}.{month}.{day}"
    return f"{day} {('Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec').split()[month - 1]} {year}"


def pages(out: Path) -> list[Path]:
    env = Environment(loader=FileSystemLoader(HERE / "pages"), autoescape=select_autoescape(["html"]),
                      undefined=StrictUndefined, trim_blocks=True, lstrip_blocks=True)
    info, made = downloads(), []
    for lang in LANGS:
        text = _strings(lang)
        for page in PAGES:
            where = _where(lang, page)
            up = "../" * (len(where.parts) - 1)            # 이 쪽에서 사이트 뿌리까지
            other = next(l for l in LANGS if l != lang)
            html = env.get_template(f"{page}.html").render(
                t=text, lang=lang, page=page, root=up, dl=info, files=info["files"], other=other,
                link={name: up + _where(lang, name).as_posix() for name in PAGES},
                other_link=up + _where(other, page).as_posix(), guide=up + GUIDE_NAME,
                shot=functools.partial(_shot, up), date=_date(lang, info["date"]))
            target = out / where
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(html.strip() + "\n", encoding="utf-8")
            made.append(target)
    return made


def assets(out: Path) -> None:
    shutil.copytree(HERE / "static", out / "assets")
    shots = out / "assets" / "shots"
    shots.mkdir(exist_ok=True)
    for name in SITE_SHOTS:
        shutil.copyfile(SHOTS / name, shots / name)
    shutil.copyfile(GUIDE, out / GUIDE_NAME)
    (out / ".nojekyll").write_text("", encoding="utf-8")   # GitHub Pages가 파일을 그대로 내보내게


ARTIFACT_TITLE = "가닥 배포 사이트"
OUTSIDE_FONT = re.compile(r'<link rel="stylesheet" href="https://cdn\.jsdelivr\.net/[^"]+">\n?')


def for_artifact(out: Path) -> None:
    """Claude 아티팩트(비공개 미리보기)로 올릴 수 있게 고쳐요.
    첫 쪽은 <html> · <head> · <body> 없이 둬요(올릴 때 감싸 줘요). 바깥 글꼴 링크는 거기서 막혀 있어서 빼요."""
    for path in out.rglob("*.html"):
        html = OUTSIDE_FONT.sub("", path.read_text(encoding="utf-8"))
        if path == out / "index.html":
            head = html[html.index("<head>") + len("<head>"):html.index("</head>")]
            body = html[html.index(">", html.index("<body")) + 1:html.index("</body>")]
            keep = [line for line in head.splitlines() if line.startswith(('<link rel="stylesheet"', "<script"))]
            html = f"<title>{ARTIFACT_TITLE}</title>\n" + "\n".join(keep) + "\n" + body.strip() + "\n"
        path.write_text(html, encoding="utf-8")


def build(out: Path = OUT, artifact: bool = False) -> Path:
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    assets(out)
    demo(out)
    pages(out)
    if artifact:
        for_artifact(out)
    return out


def serve(out: Path, port: int = PORT) -> None:
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(out))
    with http.server.ThreadingHTTPServer(("127.0.0.1", port), handler) as server:
        print(f"http://127.0.0.1:{port}/ 에서 보여 주고 있어요 (끄려면 Ctrl+C)", flush=True)
        server.serve_forever()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="python -m homepage.build", description="가닥 배포 사이트 만들기")
    parser.add_argument("--out", type=Path, default=OUT, help="만들 폴더 (기본 dist/site)")
    parser.add_argument("--serve", action="store_true", help=f"만든 뒤 127.0.0.1:{PORT} 에서 보여 주기")
    parser.add_argument("--port", type=int, default=PORT)
    parser.add_argument("--stamp", action="store_true", help="dist/ 의 설치 파일로 downloads.json 다시 적기")
    parser.add_argument("--stage", type=Path, help="--stamp 와 같이: 올릴 이름으로 복사한 파일을 모을 폴더")
    parser.add_argument("--artifact", action="store_true", help="Claude 아티팩트로 올릴 모양으로 (기본 폴더는 dist/site-artifact)")
    args = parser.parse_args(argv)
    try:
        if args.stamp:
            if args.stage:
                args.stage.mkdir(parents=True, exist_ok=True)
            info = stamp(args.stage)
            for item in info["files"].values():
                print(f"{item['sha256'][:16]}…  {item['bytes']:>10,}  {item['asset']}")
        out = build(args.out if args.out != OUT or not args.artifact else OUT.with_name("site-artifact"), args.artifact)
    except Stop as stop:
        print(stop, file=sys.stderr)
        return 1
    print(f"만들었어요: {out}")
    if args.serve:
        serve(out, args.port)
    return 0


if __name__ == "__main__":
    sys.exit(main())
