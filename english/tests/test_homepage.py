"""배포 사이트(homepage/)가 제대로 만들어지는지: 쪽 · 링크 · 받기 주소 · 바로 써 보는 데모, 한국어판과 영어판.

사이트는 정적 파일이라, 임시 폴더에 한 번 만들어 놓고 그 파일들을 읽어 확인해요.
사이트는 한국어판(main)에서 만들어요. 영어 쪽은 main의 english/ 폴더(english 브랜치를 통째로 가져다 둔 사본)를 써요.
영어판(english 브랜치)에서는 만드는 확인을 건너뛰어요.
"""
import hashlib
import json
import re
import shutil
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from homepage import build

ROOT = Path(__file__).resolve().parent.parent
LINK = re.compile(r'(?:href|src|data-src)="([^"]+)"')
OUTSIDE = ("http://", "https://", "data:", "mailto:", "#", "chrome://")
HANGUL = re.compile(r"[가-힣]+")
KOREAN = build.edition() == build.LANGS[0]            # 이 폴더가 한국어판인지 (영어판이면 english 브랜치)
ONLY_MAIN = "사이트는 한국어판(main)에서 만들어요"
# 영어 쪽에 남아도 되는 한글: 로고, 한국어 쪽으로 가는 글
KOREAN_ON_ENGLISH_PAGES = {"가닥", "한국어", "한국어판"}


def shape(value):
    """글 표의 뼈대: 열쇠와 목록의 길이만 남겨요."""
    if isinstance(value, dict):
        return {key: shape(item) for key, item in value.items()}
    if isinstance(value, list):
        return [shape(item) for item in value]
    return None


def keys(value):
    if isinstance(value, dict):
        for key, item in value.items():
            yield key
            yield from keys(item)
    elif isinstance(value, list):
        for item in value:
            yield from keys(item)


class StringsTest(unittest.TestCase):
    def test_both_languages_say_the_same_things(self):
        ko, en = (json.loads((build.HERE / "strings" / f"{lang}.json").read_text(encoding="utf-8")) for lang in build.LANGS)
        self.assertEqual(shape(ko), shape(en))

    def test_no_key_hides_behind_a_dict_method(self):
        # 틀에서 t.faq.items 처럼 쓰면 글이 아니라 dict의 items()가 나와요. 그런 이름은 쓰지 않아요
        for lang in build.LANGS:
            text = json.loads((build.HERE / "strings" / f"{lang}.json").read_text(encoding="utf-8"))
            self.assertEqual([key for key in keys(text) if hasattr(dict, key)], [], lang)


@unittest.skipUnless(KOREAN, ONLY_MAIN)
class BuiltSiteTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp())
        cls.out = build.build(cls.tmp / "site")
        cls.pages = sorted(p for p in cls.out.rglob("*.html") if "app" not in p.relative_to(cls.out).parts)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def page(self, lang, name):
        return (self.out / build._where(lang, name)).read_text(encoding="utf-8")

    def test_every_page_exists_in_every_language(self):
        made = {p.relative_to(self.out).as_posix() for p in self.pages}
        self.assertEqual(made, {"index.html", "download/index.html", "demo/index.html",
                                "en/index.html", "en/download/index.html", "en/demo/index.html"})

    def test_pages_are_fully_filled_in(self):
        for page in self.pages:
            html = page.read_text(encoding="utf-8")
            self.assertTrue(html.startswith("<!doctype html>"), page)
            # {os}는 남아 있어도 돼요: 받기 버튼의 글을 브라우저에서 ‘macOS용 받기’로 바꿀 때 써요
            for left_over in ("{{", "{%", "{version}", "{date}", "{mb}"):
                self.assertNotIn(left_over, html, (page.relative_to(self.out), left_over))

    def test_every_local_link_leads_to_a_file(self):
        apps = [self.out / build._site(lang, "app", name) for lang in build.LANGS for name in ("index.html", "map.html")]
        for page in list(self.pages) + apps:
            for target in LINK.findall(page.read_text(encoding="utf-8")):
                if target.startswith(OUTSIDE):
                    continue
                path = (page.parent / target.split("#")[0].split("?")[0]).resolve()
                self.assertTrue(path.is_file(), f"{page.relative_to(self.out)} → {target}")

    def test_paths_are_relative_so_the_site_works_under_any_address(self):
        for page in self.pages:
            for target in LINK.findall(page.read_text(encoding="utf-8")):
                self.assertFalse(target.startswith("/"), f"{page.relative_to(self.out)} → {target}")

    def test_each_page_links_to_its_other_language(self):
        ko, en = self.page("ko", "download"), self.page("en", "download")
        self.assertIn('href="../en/download/index.html"', ko)
        self.assertIn('href="../../download/index.html"', en)
        self.assertIn('<html lang="ko">', ko)
        self.assertIn('<html lang="en">', en)

    def test_download_buttons_point_at_the_release_files(self):
        for lang in build.LANGS:
            info, html = build.downloads(lang), self.page(lang, "download")
            for key in ("mac-arm64", "mac-x86_64", "win-setup", "win-zip"):
                item = info["files"][key]
                self.assertEqual(item["url"], f"https://github.com/{build.REPO}/releases/download/{info['tag']}/{item['asset']}")
                self.assertIn(f'href="{item["url"]}"', html)
                self.assertIn(item["sha256"], html)
                self.assertTrue(item["asset"].isascii(), "GitHub가 한글 파일 이름을 지워요")
                self.assertRegex(item["sha256"], r"^[0-9a-f]{64}$")
                self.assertGreater(item["bytes"], 1_000_000)

    def test_each_language_hands_out_its_own_edition(self):
        """한국어 쪽은 한국어판을, 영어 쪽은 영어판을 받아요. 릴리스도 파일도 서로 달라요."""
        ko, en = (build.downloads(lang) for lang in build.LANGS)
        self.assertNotEqual(ko["tag"], en["tag"])
        self.assertFalse({item["sha256"] for item in ko["files"].values()} & {item["sha256"] for item in en["files"].values()})
        for lang, mine, theirs in (("ko", ko, en), ("en", en, ko)):
            for name in build.PAGES:
                html = self.page(lang, name)
                self.assertNotIn(f"/releases/download/{theirs['tag']}/", html, (lang, name))
                self.assertNotIn(f"/releases/tag/{theirs['tag']}\"", html, (lang, name))
            self.assertIn(f"/releases/download/{mine['tag']}/", self.page(lang, "download"))

    def test_the_numbers_match_the_installers_that_are_here(self):
        info = build.downloads()
        found = 0
        for key, local, _ in build.INSTALLERS[build.LANGS[0]]:
            path = ROOT / "dist" / local.format(v=info["version"])
            if not path.exists():
                continue
            found += 1
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), info["files"][key]["sha256"], path.name)
            self.assertEqual(path.stat().st_size, info["files"][key]["bytes"], path.name)
        if not found:
            self.skipTest("dist/ 에 설치 파일이 없어요 (만든 PC에서만 견줘 봐요)")

    def test_the_guide_people_download_is_the_one_in_docs(self):
        for lang in build.LANGS:
            self.assertEqual((self.out / build._site(lang, build.GUIDE_NAME)).read_bytes(), (ROOT / build.GUIDE[lang]).read_bytes(), lang)
            self.assertIn(f'href="{"../" * len(build._where(lang, "download").parts[:-1])}{build._site(lang, build.GUIDE_NAME).as_posix()}"',
                          self.page(lang, "download"))
        self.assertNotEqual((ROOT / build.GUIDE["ko"]).read_bytes(), (ROOT / build.GUIDE["en"]).read_bytes())

    def test_the_usage_guide_in_the_footer_exists(self):
        for lang in build.LANGS:
            self.assertTrue((ROOT / build.USAGE[lang]).is_file(), build.USAGE[lang])
            self.assertIn(f'/blob/main/{build.USAGE[lang]}"', self.page(lang, "index"))

    def test_the_demo_shows_only_the_made_up_example(self):
        for lang in build.LANGS:
            app = self.out / build._site(lang, "app")
            self.assertEqual([p.name for p in (app / "data").iterdir()], [build.APP_DATA])
            self.assertIn("var S = { demo: true,", (app / "web" / "app.js").read_text(encoding="utf-8"))
            self.assertNotIn('"/ui/', (app / "map.html").read_text(encoding="utf-8"))
            self.assertIn(f'src="{"../" * (len(build._where(lang, "demo").parts) - 1)}{build._site(lang, "app").as_posix()}/index.html"',
                          self.page(lang, "demo"))
        # 가닥 창의 원본은 그대로예요 (복사본만 고쳐요)
        self.assertIn("demo: params.has('demo')", (ROOT / "backend" / "web" / "app.js").read_text(encoding="utf-8"))
        self.assertIn("demo: params.has('demo')", (build.ENGLISH / "backend" / "web" / "app.js").read_text(encoding="utf-8"))

    def test_the_english_side_shows_the_english_app(self):
        """영어 쪽의 데모 · 화면 그림 · 글은 영어판의 것이에요. 한글은 로고와 한국어 쪽으로 가는 글에만 남아요."""
        app = self.out / "en" / "app"
        self.assertIn('<html lang="en">', (app / "index.html").read_text(encoding="utf-8"))
        self.assertIn("<title>Gadak — live demo</title>", (app / "index.html").read_text(encoding="utf-8"))
        self.assertIn('<html lang="ko">', (self.out / "app" / "index.html").read_text(encoding="utf-8"))
        self.assertFalse(HANGUL.findall((app / "data" / build.APP_DATA).read_text(encoding="utf-8")))
        home = self.page("en", "index")
        shots = re.findall(r'src="\.\./assets/shots/([^"]+)"', home)
        self.assertTrue(shots)
        self.assertEqual([name for name in shots if not name.startswith("en/")], [])
        for name in build.PAGES:
            self.assertEqual(set(HANGUL.findall(self.page("en", name))) - KOREAN_ON_ENGLISH_PAGES, set(), name)
        for name in build.SITE_SHOTS:           # 설치 안내와 같이 쓰는 그림도 영어판에서 가져온 것
            self.assertEqual((self.out / "assets" / "shots" / "en" / name).read_bytes(), (build.ENGLISH / build.SHOTS / name).read_bytes())
            self.assertNotEqual((self.out / "assets" / "shots" / "en" / name).read_bytes(), (self.out / "assets" / "shots" / name).read_bytes())

    def test_pages_carry_no_private_paths(self):
        for page in self.pages:
            html = page.read_text(encoding="utf-8")
            for private in ("/Users/", "pythonanywhere", "서버-정보"):
                self.assertNotIn(private, html, (page, private))


@unittest.skipUnless(KOREAN, ONLY_MAIN)
class DemoPatchTest(unittest.TestCase):
    def test_a_changed_app_stops_the_build_instead_of_shipping_a_broken_demo(self):
        gone = build.PATCHES + (("web/app.js", "이런 줄은 가닥 창에 없어요", "x"),)
        for lang in build.LANGS:
            with tempfile.TemporaryDirectory() as tmp, mock.patch.object(build, "PATCHES", gone):
                with self.assertRaises(build.Stop) as stop:
                    build.demo(Path(tmp), lang)
            self.assertIn("PATCHES", str(stop.exception))


@unittest.skipUnless(KOREAN, ONLY_MAIN)
class EnglishFolderTest(unittest.TestCase):
    """english/ 폴더는 english 브랜치를 통째로 가져다 둔 사본이에요. 사이트의 영어 쪽이 이 폴더의 가닥 창 · 그림을 써요."""

    def test_the_folder_holds_the_english_edition(self):
        self.assertEqual((build.edition(), build.edition(build.ENGLISH)), ("ko", "en"))
        for name in build.APP_WEB:
            self.assertTrue((build.ENGLISH / "backend" / "web" / name).is_file(), name)
        for name in build.SITE_SHOTS:
            self.assertTrue((build.ENGLISH / build.SHOTS / name).is_file(), name)
        self.assertFalse(HANGUL.findall((build.ENGLISH / "data" / build.APP_DATA).read_text(encoding="utf-8")))

    def test_the_english_guide_out_here_is_the_one_in_the_folder(self):
        """뿌리의 영어 설치 안내(README.en.md · 사이트가 가리키는 것)는 영어판의 것과 같은 파일이에요. 폴더를 다시 가져와 달라졌으면 이것도 같이 바꿔요."""
        self.assertEqual((ROOT / build.GUIDE["en"]).read_bytes(), (build.ENGLISH / build.GUIDE["en"]).read_bytes())


@unittest.skipIf(KOREAN, "english 브랜치에서만이에요")
class EnglishBranchTest(unittest.TestCase):
    def test_the_site_is_not_built_from_the_english_branch(self):
        with tempfile.TemporaryDirectory() as tmp, self.assertRaises(build.Stop) as stop:
            build.build(Path(tmp) / "site")
        self.assertIn("main", str(stop.exception))

    def test_the_copy_kept_on_main_did_not_come_along(self):
        """main을 이 브랜치에 합치면 main의 english/ 폴더(이 브랜치의 사본)가 딸려 와요. 영어판 안에 영어판이 또 생기지 않게 빼요: git rm -r english"""
        self.assertFalse(build.ENGLISH.exists())


class FakeEnglish:
    """영어판 폴더를 흉내 낸 임시 폴더: 가닥 창의 첫 쪽 · 크롬 확장 · 만든 설치 파일."""

    def __init__(self, lang="en"):
        self.tmp = Path(tempfile.mkdtemp())
        self.root = self.tmp / "english"
        self.write(Path("backend", "web", "index.html"), f'<!doctype html>\n<html lang="{lang}">\n')
        self.write(Path("extension", "manifest.json"), "{}")
        self.version = json.loads(build.DOWNLOADS.read_text(encoding="utf-8"))["en"]["version"]
        for _, local, _ in build.INSTALLERS["en"]:
            self.write(Path("dist", local.format(v=self.version)), "installer " + local.format(v=self.version))

    def write(self, rel, text):
        (self.root / rel).parent.mkdir(parents=True, exist_ok=True)
        (self.root / rel).write_text(text, encoding="utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        shutil.rmtree(self.tmp, ignore_errors=True)


class StampTest(unittest.TestCase):
    def test_english_installers_fill_only_the_english_half(self):
        with FakeEnglish() as fake:
            sheet, staged = fake.tmp / "downloads.json", fake.tmp / "staged"
            shutil.copyfile(build.DOWNLOADS, sheet)
            staged.mkdir()
            before = json.loads(sheet.read_text(encoding="utf-8"))
            with mock.patch.object(build, "DOWNLOADS", sheet):
                build.stamp("en", staged, fake.root)
            after = json.loads(sheet.read_text(encoding="utf-8"))
            self.assertEqual(after["ko"], before["ko"])
            for key, local, asset in build.INSTALLERS["en"]:
                body, name = ("installer " + local.format(v=fake.version)).encode("utf-8"), asset.format(v=fake.version)
                self.assertEqual(after["en"]["files"][key], {"asset": name, "bytes": len(body), "sha256": hashlib.sha256(body).hexdigest()})
                self.assertEqual((staged / name).read_bytes(), body)
            packed = staged / after["en"]["files"]["extension"]["asset"]
            with zipfile.ZipFile(packed) as z:
                self.assertEqual(z.namelist(), ["gadak-extension/manifest.json"])       # 영어판의 extension/ 폴더를 묶어요
            sums = (staged / build.SUMS).read_text(encoding="utf-8").splitlines()
            self.assertEqual(sums, sorted(sums, key=lambda line: line.split("  ")[1]))
            self.assertEqual({tuple(line.split("  ")) for line in sums},
                             {(item["sha256"], item["asset"]) for item in after["en"]["files"].values()})

    def test_it_refuses_installers_of_the_other_edition(self):
        with FakeEnglish() as fake, mock.patch.object(build, "DOWNLOADS", fake.tmp / "nothing.json"):
            with self.assertRaises(build.Stop):
                build.stamp("ko", None, fake.root)


class ExtensionZipTest(unittest.TestCase):
    def test_the_same_folder_always_makes_the_same_zip(self):
        with tempfile.TemporaryDirectory() as one, tempfile.TemporaryDirectory() as two:
            first, second = build.extension_zip(Path(one)), build.extension_zip(Path(two))
            self.assertEqual(first.read_bytes(), second.read_bytes())
            with zipfile.ZipFile(first) as z:
                names = z.namelist()
        self.assertIn("gadak-extension/manifest.json", names)
        self.assertTrue(all(name.startswith("gadak-extension/") for name in names))
        self.assertFalse([name for name in names if ".DS_Store" in name])


if __name__ == "__main__":
    unittest.main()
