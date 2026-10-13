"""배포 사이트(homepage/)가 제대로 만들어지는지: 쪽 · 링크 · 받기 주소 · 바로 써 보는 데모.

사이트는 정적 파일이라, 임시 폴더에 한 번 만들어 놓고 그 파일들을 읽어 확인해요.
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


class BuiltSiteTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp())
        cls.out = build.build(cls.tmp / "site")
        cls.pages = sorted(p for p in cls.out.rglob("*.html") if "app" not in p.relative_to(cls.out).parts)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

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
        for page in list(self.pages) + [self.out / "app" / "index.html", self.out / "app" / "map.html"]:
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
        ko = (self.out / "download" / "index.html").read_text(encoding="utf-8")
        en = (self.out / "en" / "download" / "index.html").read_text(encoding="utf-8")
        self.assertIn('href="../en/download/index.html"', ko)
        self.assertIn('href="../../download/index.html"', en)
        self.assertIn('<html lang="ko">', ko)
        self.assertIn('<html lang="en">', en)

    def test_download_buttons_point_at_the_release_files(self):
        info = build.downloads()
        for lang in ("", "en/"):
            html = (self.out / lang / "download" / "index.html").read_text(encoding="utf-8")
            for key in ("mac-arm64", "mac-x86_64", "win-setup", "win-zip"):
                item = info["files"][key]
                self.assertEqual(item["url"], f"https://github.com/{build.REPO}/releases/download/v{info['version']}/{item['asset']}")
                self.assertIn(f'href="{item["url"]}"', html)
                self.assertIn(item["sha256"], html)
                self.assertTrue(item["asset"].isascii(), "GitHub가 한글 파일 이름을 지워요")
                self.assertRegex(item["sha256"], r"^[0-9a-f]{64}$")
                self.assertGreater(item["bytes"], 1_000_000)

    def test_the_numbers_match_the_installers_that_are_here(self):
        info = build.downloads()
        found = 0
        for key, local, _ in build.INSTALLERS:
            path = ROOT / "dist" / local.format(v=info["version"])
            if not path.exists():
                continue
            found += 1
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), info["files"][key]["sha256"], path.name)
            self.assertEqual(path.stat().st_size, info["files"][key]["bytes"], path.name)
        if not found:
            self.skipTest("dist/ 에 설치 파일이 없어요 (만든 PC에서만 견줘 봐요)")

    def test_the_guide_people_download_is_the_one_in_docs(self):
        self.assertEqual((self.out / build.GUIDE_NAME).read_bytes(), build.GUIDE.read_bytes())

    def test_the_demo_shows_only_the_made_up_example(self):
        app = self.out / "app"
        self.assertEqual([p.name for p in (app / "data").iterdir()], [build.APP_DATA])
        self.assertIn("var S = { demo: true,", (app / "web" / "app.js").read_text(encoding="utf-8"))
        self.assertNotIn('"/ui/', (app / "map.html").read_text(encoding="utf-8"))
        # 가닥 창의 원본은 그대로예요 (복사본만 고쳐요)
        self.assertIn("demo: params.has('demo')", (ROOT / "backend" / "web" / "app.js").read_text(encoding="utf-8"))

    def test_pages_carry_no_private_paths(self):
        for page in self.pages:
            html = page.read_text(encoding="utf-8")
            for private in ("/Users/", "pythonanywhere", "서버-정보"):
                self.assertNotIn(private, html, (page, private))


class DemoPatchTest(unittest.TestCase):
    def test_a_changed_app_stops_the_build_instead_of_shipping_a_broken_demo(self):
        gone = build.PATCHES + (("web/app.js", "이런 줄은 가닥 창에 없어요", "x"),)
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(build, "PATCHES", gone):
            with self.assertRaises(build.Stop) as stop:
                build.demo(Path(tmp))
        self.assertIn("PATCHES", str(stop.exception))


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
