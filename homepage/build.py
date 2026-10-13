"""가닥 배포 사이트를 만들어요 — 소개 · OS별 받기 · 바로 써 보는 데모, 한국어와 영어.

    ./.venv/bin/python -m homepage.build            # dist/site/ 에 만들어요
    ./.venv/bin/python -m homepage.build --serve    # 만들고 http://127.0.0.1:7398 에서 보여 줘요
    ./.venv/bin/python -m homepage.build --stamp    # dist/ 의 설치 파일(한국어판)로 downloads.json 을 다시 적어요
    ./.venv/bin/python -m homepage.build --artifact # Claude 아티팩트(비공개 미리보기)로 올릴 모양으로

영어판 — english/ 폴더 (english 브랜치를 통째로 가져다 둔 사본)
    ./.venv/bin/python -m homepage.build --stamp-english          # english/dist/ 에 만든 설치 파일로 다시 적어요
    ./.venv/bin/python -m homepage.build --stamp-english <폴더>   # english 브랜치를 다른 곳에 받아 거기서 만들었으면 그 폴더

사이트는 정적 파일뿐이에요(서버 코드가 없어요). 주소가 어디든 돌게 모든 길을 상대 경로로 적어요.

말마다 그 말의 가닥을 줘요. 한국어 쪽(뿌리)은 한국어판을, 영어 쪽(en/)은 영어판을 받게 하고, 데모 · 화면 그림 · 설치 안내도
그 판의 것이에요. 영어판은 english 브랜치에서 고치고(같은 자리의 파일을 영어로 바꾼 것), 그 브랜치를 통째로 가져다 둔 사본이
이 브랜치의 english/ 폴더예요. 사이트의 영어 쪽은 그 폴더의 가닥 창 · 그림을 써요. 사이트는 이 브랜치(main)에서만 만들어요.
폴더를 다시 가져오는 법은 docs/handoff-english.md 에 있어요.

바로 써 보는 데모(app/ · en/app/)는 가닥 창(backend/web · shared/ui)을 그대로 복사해, 백엔드를 부르지 않고
만든 예시(data/demo_conversations.json)만 보여 주게 몇 줄을 바꾼 것이에요. 실제 대화는 들어가지 않아요.
바꾸는 줄은 PATCHES · TITLES에 다 적혀 있고, 가닥 창의 코드가 달라져 그 줄을 못 찾으면 만들기를 멈춰요.

설치 파일은 사이트에 넣지 않아요. 받기 버튼은 GitHub Releases의 파일을 가리키고,
파일 이름 · 크기 · 확인 값은 homepage/downloads.json 에 판마다 적어 둬요(--stamp · --stamp-english 가 다시 적어요).
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
ENGLISH = ROOT / "english"       # 영어판: english 브랜치를 통째로 가져다 둔 사본. 여기서 고치지 않아요 (docs/handoff-english.md)
ENGLISH_BRANCH = "english"
TREE = {"ko": ROOT, "en": ENGLISH}      # 말마다 그 판의 가닥 창 · 화면 그림이 있는 곳
GUIDE = {"ko": Path("docs", "가닥-설치-안내.pdf"), "en": Path("docs", "gadak-install-guide.pdf")}      # 판마다의 설치 안내 (이 폴더에서의 경로)
GUIDE_NAME = "gadak-install-guide.pdf"      # 사이트에서의 이름. 영어판은 en/ 아래에 같은 이름으로
USAGE = {"ko": "docs/usage-guide.md", "en": "docs/usage-guide.en.md"}      # 발치의 ‘쓰는 법 자세히’가 가리키는 문서
SHOTS = Path("docs", "install-guide", "img")      # 설치 안내에 쓴 화면 그림(만든 예시). 아래 것만 사이트에 같이 써요
SITE_SHOTS = ("window.png", "map.png", "float-fan.png")

# 설치 파일: 판마다 (열쇠, 만든 폴더의 dist/ 에서의 이름, 올릴 때의 이름)
INSTALLERS = {
    # GitHub는 한글 파일 이름을 지워 버려서 로마자로 올려요
    "ko": (
        ("mac-arm64", "가닥-{v}-arm64.dmg", "Gadak-{v}-mac-arm64.dmg"),
        ("mac-x86_64", "가닥-{v}-x86_64.dmg", "Gadak-{v}-mac-x86_64.dmg"),
        ("win-setup", "가닥-{v}-windows-x64-설치.exe", "Gadak-{v}-windows-x64-setup.exe"),
        ("win-zip", "가닥-{v}-windows-x64.zip", "Gadak-{v}-windows-x64.zip"),
    ),
    # 영어판은 만든 이름 그대로 올려요 (영어 설치 안내 · ‘How to open Gadak.txt’에 적힌 이름과 같게)
    "en": (
        ("mac-arm64", "Gadak-{v}-arm64.dmg", "Gadak-{v}-arm64.dmg"),
        ("mac-x86_64", "Gadak-{v}-x86_64.dmg", "Gadak-{v}-x86_64.dmg"),
        ("win-setup", "Gadak-{v}-windows-x64-setup.exe", "Gadak-{v}-windows-x64-setup.exe"),
        ("win-zip", "Gadak-{v}-windows-x64.zip", "Gadak-{v}-windows-x64.zip"),
    ),
}
EXTENSION = ("extension", "Gadak-{v}-chrome-extension.zip")
SUMS = "SHA256SUMS.txt"

# 가닥 창을 데모로 옮길 때 가져오는 것
APP_WEB = ("index.html", "app.css", "app.js", "map.html", "help.html")
APP_DATA = "demo_conversations.json"
# (파일, 원래 글, 바꿀 글): 백엔드 없이 만든 예시만 보여 주게 하는 줄들. 두 판의 코드에서 같은 줄이에요
PATCHES = (
    ("web/app.js", "var S = { demo: params.has('demo'),", "var S = { demo: true,"),
    ("web/app.js", "R.mapFrame.src = 'map';", "R.mapFrame.src = 'map.html';"),   # /map 이 아니면 지도가 만든 예시를 그려요
    ("web/app.js", "window.open('help', 'gadak-help')", "window.open('help.html', 'gadak-help')"),
    ("map.html", '<script src="/ui/mark.js"></script>', '<script src="ui/mark.js"></script>'),
)
# 제목은 판마다 달라요: (파일, 가닥 창의 제목, 데모의 제목)
TITLES = {
    "ko": (("index.html", "가닥", "가닥 — 바로 써 보는 데모"), ("map.html", "가닥 전체 지도", "가닥 전체 지도 — 바로 써 보는 데모"),
           ("help.html", "가닥 도움말", "가닥 도움말")),
    "en": (("index.html", "Gadak", "Gadak — live demo"), ("map.html", "Gadak System Map", "Gadak System Map — live demo"),
           ("help.html", "Gadak Help", "Gadak Help")),
}
ICONLESS = ("map.html", "help.html")      # 가닥에서는 아이콘 없이 뜨던 쪽. 데모에서는 사이트의 아이콘을 붙여요 (없으면 브라우저가 /favicon.ico를 찾다 404)


class Stop(Exception):
    """만들 수 없을 때 — 사람이 읽을 한 줄을 담아요."""


def edition(tree: Path = ROOT) -> str:
    """그 폴더의 가닥이 어느 말의 판인지 (가닥 창의 <html lang>)."""
    page = tree / "backend" / "web" / "index.html"
    found = re.search(r'<html lang="([a-z]+)"', page.read_text(encoding="utf-8")[:400]) if page.is_file() else None
    return found.group(1) if found else ""


def downloads(lang: str = LANGS[0]) -> dict:
    """받기 버튼에 쓸 것: 그 판의 파일마다 올린 이름 · 크기 · 확인 값과 받는 주소."""
    info = json.loads(DOWNLOADS.read_text(encoding="utf-8"))[lang]
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


def extension_zip(out: Path, folder: Path | None = None, version: str | None = None) -> Path:
    """크롬 확장 폴더를 zip으로 묶어요. 같은 내용이면 늘 같은 파일이 나오게 시각과 차례를 고정해요."""
    import zipfile

    folder = folder or ROOT / EXTENSION[0]
    target = out / EXTENSION[1].format(v=version or downloads()["version"])
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as z:
        for path in sorted(p for p in folder.rglob("*") if p.is_file() and p.name != ".DS_Store"):
            entry = zipfile.ZipInfo(f"gadak-extension/{path.relative_to(folder).as_posix()}", (2026, 10, 12, 0, 0, 0))
            entry.compress_type = zipfile.ZIP_DEFLATED
            entry.external_attr = 0o644 << 16
            z.writestr(entry, path.read_bytes())
    return target


def stamp(lang: str = LANGS[0], staged: Path | None = None, source: Path | None = None) -> dict:
    """그 판의 설치 파일을 읽어 downloads.json 의 크기 · 확인 값을 다시 적어요. source 는 그 판을 만든 폴더예요
    (dist/ 와 extension/ 이 있는 곳 · 비우면 이 폴더). staged 를 주면 올릴 이름으로 복사한 파일 · 확장 zip · 확인 값 목록을 거기에 모아요."""
    source = Path(source or ROOT)
    if edition(source) != lang:
        raise Stop(f"{source} 는 {lang} 판이 아니에요 (가닥 창의 말: {edition(source) or '모름'}). 영어판은 --stamp-english 로 적어요.")
    everything = json.loads(DOWNLOADS.read_text(encoding="utf-8"))
    info = everything[lang]
    v = info["version"]
    for key, local, asset in INSTALLERS[lang]:
        path = source / "dist" / local.format(v=v)
        if not path.exists():
            raise Stop(f"설치 파일이 없어요: {path} (먼저 backend.macapp · backend.winapp 으로 만들어요)")
        info["files"][key].update(asset=asset.format(v=v), bytes=path.stat().st_size, sha256=_sha256(path))
        if staged:
            shutil.copyfile(path, staged / asset.format(v=v))
    if staged:
        packed = extension_zip(staged, source / EXTENSION[0], v)
        info["files"]["extension"].update(asset=packed.name, bytes=packed.stat().st_size, sha256=_sha256(packed))
        lines = [f"{item['sha256']}  {item['asset']}" for item in sorted(info["files"].values(), key=lambda item: item["asset"])]
        (staged / SUMS).write_text("\n".join(lines) + "\n", encoding="utf-8")
    DOWNLOADS.write_text(json.dumps(everything, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return info


def _site(lang: str, *parts: str) -> Path:
    """그 말의 것이 놓이는 자리 (사이트 뿌리에서부터): 첫 말은 뿌리에, 나머지는 그 이름의 폴더에."""
    return Path(*(() if lang == LANGS[0] else (lang,)), *parts)


def demo(out: Path, lang: str = LANGS[0]) -> Path:
    """그 판의 가닥 창을 out/app/ (영어판은 out/en/app/) 에 복사해 만든 예시만 보여 주는 정적 페이지로 만들어요."""
    tree, app = TREE[lang], out / _site(lang, "app")
    up = "../" * len(_site(lang, "app").parts)             # 데모에서 사이트 뿌리까지
    (app / "web").mkdir(parents=True)
    (app / "data").mkdir()
    for name in APP_WEB:
        # index · map · help 는 가닥에서 뿌리 주소(/ · /map · /help)로 열리던 것이라 app/ 바로 아래에 둬요
        target = app / name if name.endswith(".html") else app / "web" / name
        shutil.copyfile(tree / "backend" / "web" / name, target)
    shutil.copytree(tree / "shared" / "ui", app / "ui", ignore=shutil.ignore_patterns(".DS_Store"))
    shutil.copyfile(tree / "data" / APP_DATA, app / "data" / APP_DATA)
    icon = f'\n<link rel="icon" href="{up}assets/gadak.svg" type="image/svg+xml">'
    titles = tuple((name, f"<title>{old}</title>", f"<title>{new}</title>" + (icon if name in ICONLESS else ""))
                   for name, old, new in TITLES[lang])
    for name, old, new in PATCHES + titles:
        path = app / name
        text = path.read_text(encoding="utf-8")
        if text.count(old) != 1:
            raise Stop(f"데모로 옮길 줄을 못 찾았어요: {lang} 판 {name} 의 「{old}」 (가닥 창 코드가 바뀌었으면 homepage/build.py 의 PATCHES · TITLES 를 맞춰요)")
        path.write_text(text.replace(old, new), encoding="utf-8")
    return app


def _strings(lang: str) -> dict:
    return json.loads((HERE / "strings" / f"{lang}.json").read_text(encoding="utf-8"))


def _where(lang: str, page: str) -> Path:
    """그 말 · 그 쪽이 놓이는 자리 (사이트 뿌리에서부터)."""
    return _site(lang, *(() if page == "index" else (page,)), "index.html")


def _png_size(path: Path) -> tuple[int, int]:
    head = path.read_bytes()[:24]
    if head[:8] != b"\x89PNG\r\n\x1a\n":
        raise Stop(f"PNG 그림이 아니에요: {path}")
    return int.from_bytes(head[16:20], "big"), int.from_bytes(head[20:24], "big")


def _shot_file(lang: str, name: str) -> tuple[Path, str]:
    """화면 그림 한 장의 원본과 사이트에서의 자리. 그 판의 화면으로 찍은 것을 써요 (영어는 shots/en/)."""
    folder = _site(lang).as_posix()
    spot = "assets/shots/" + ("" if folder == "." else folder + "/") + name
    for path in (HERE / "static" / "shots" / _site(lang, name), TREE[lang] / SHOTS / name):
        if path.is_file():
            return path, spot
    raise Stop(f"화면 그림이 없어요: {lang} 판의 {name}")


def _shot(up: str, lang: str, name: str, alt: str) -> Markup:
    """화면 그림 한 장. 크기를 같이 적어 두면 그림이 뜨기 전에도 자리가 잡혀요."""
    path, spot = _shot_file(lang, name)
    width, height = _png_size(path)
    # --ratio(너비 ÷ 높이)는 옆 그림을 화면 높이에 맞춰 줄일 때 써요 (site.css의 .feat-media)
    return Markup(f'<img src="{escape(up)}{escape(spot)}" width="{width}" height="{height}" '
                  f'style="--ratio: {width / height:.4f}" alt="{escape(alt)}" loading="lazy">')


def _date(lang: str, iso: str) -> str:
    year, month, day = (int(part) for part in iso.split("-"))
    if lang == "ko":
        return f"{year}.{month}.{day}"
    return f"{day} {('Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec').split()[month - 1]} {year}"


def pages(out: Path) -> list[Path]:
    env = Environment(loader=FileSystemLoader(HERE / "pages"), autoescape=select_autoescape(["html"]),
                      undefined=StrictUndefined, trim_blocks=True, lstrip_blocks=True)
    made = []
    for lang in LANGS:
        text, info = _strings(lang), downloads(lang)
        for page in PAGES:
            where = _where(lang, page)
            up = "../" * (len(where.parts) - 1)            # 이 쪽에서 사이트 뿌리까지
            other = next(l for l in LANGS if l != lang)
            html = env.get_template(f"{page}.html").render(
                t=text, lang=lang, page=page, root=up, dl=info, files=info["files"], other=other,
                link={name: up + _where(lang, name).as_posix() for name in PAGES},
                other_link=up + _where(other, page).as_posix(), guide=up + _site(lang, GUIDE_NAME).as_posix(),
                app=up + _site(lang, "app").as_posix() + "/", usage=f"{info['repo']}/blob/main/{USAGE[lang]}",
                shot=functools.partial(_shot, up, lang), date=_date(lang, info["date"]))
            target = out / where
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(html.strip() + "\n", encoding="utf-8")
            made.append(target)
    return made


def assets(out: Path) -> None:
    shutil.copytree(HERE / "static", out / "assets", ignore=shutil.ignore_patterns(".DS_Store"))
    for lang in LANGS:
        for name in SITE_SHOTS:
            path, spot = _shot_file(lang, name)
            (out / spot).parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, out / spot)
        if not (ROOT / GUIDE[lang]).is_file():
            raise Stop(f"설치 안내 PDF가 없어요: {GUIDE[lang]}")
        (out / _site(lang)).mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / GUIDE[lang], out / _site(lang, GUIDE_NAME))
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
    if edition() != LANGS[0]:
        raise Stop(f"배포 사이트는 한국어판(main)에서 만들어요. 여기는 {edition() or '모르는'} 판이라 한국어 데모를 만들 수 없어요. "
                   f"영어 화면은 main의 {ENGLISH.name}/ 폴더(이 브랜치의 사본)를 다시 가져오면 사이트에 반영돼요 (docs/handoff-english.md).")
    if edition(ENGLISH) != "en":
        raise Stop(f"영어판 폴더가 없거나 영어판이 아니에요: {ENGLISH.name}/ ({ENGLISH_BRANCH} 브랜치의 사본이에요. 가져오는 법은 docs/handoff-english.md)")
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    assets(out)
    for lang in LANGS:
        demo(out, lang)
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
    parser.add_argument("--stamp", action="store_true", help="dist/ 의 설치 파일(한국어판)로 downloads.json 다시 적기")
    parser.add_argument("--stamp-english", type=Path, metavar="폴더", nargs="?", const=ENGLISH,
                        help=f"영어판 설치 파일로 다시 적기 (기본은 {ENGLISH.name}/dist/ · 다른 곳에서 만들었으면 그 {ENGLISH_BRANCH} 폴더)")
    parser.add_argument("--stage", type=Path, help="--stamp · --stamp-english 와 같이: 올릴 이름으로 복사한 파일을 모을 폴더")
    parser.add_argument("--artifact", action="store_true", help="Claude 아티팩트로 올릴 모양으로 (기본 폴더는 dist/site-artifact)")
    args = parser.parse_args(argv)
    try:
        if args.stamp or args.stamp_english:
            if args.stage:
                args.stage.mkdir(parents=True, exist_ok=True)
            info = stamp("en", args.stage, args.stamp_english) if args.stamp_english else stamp(LANGS[0], args.stage)
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
