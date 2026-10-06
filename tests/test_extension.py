"""크롬 확장(extension/)의 확인.

- 파일 확인은 언제나 돌아요: manifest가 가리키는 파일, 달라는 권한, 보내는 곳이 내 PC뿐인지.
- 크롬에서 돌리는 확인은 GADAK_BROWSER_TESTS=1 일 때만 돌아요 (크롬을 띄워서 몇 초 걸려요):
    GADAK_BROWSER_TESTS=1 python -m unittest tests.test_extension
  tests/extension/의 화면은 내가 아는 대로 흉내 낸 것이라, 실제 사이트 화면과 맞는지는 여기서 알 수 없어요.
"""
import html
import http.server
import json
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
import unittest
from pathlib import Path

from backend import config, store

ROOT = Path(__file__).resolve().parent.parent
EXT = ROOT / "extension"
PAGES = ROOT / "tests" / "extension"
CHROME = os.environ.get("GADAK_CHROME", "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
TEXT_FILES = (".js", ".html", ".json", ".css")


def texts():
    return {p.relative_to(EXT).as_posix(): p.read_text(encoding="utf-8")
            for p in sorted(EXT.rglob("*")) if p.suffix in TEXT_FILES}


class ExtensionFilesTest(unittest.TestCase):
    def setUp(self):
        self.manifest = json.loads((EXT / "manifest.json").read_text(encoding="utf-8"))

    def test_manifest_points_at_real_files(self):
        m = self.manifest
        files = [m["background"]["service_worker"], m["action"]["default_popup"], *m["icons"].values(),
                 *m["action"]["default_icon"].values()]
        for script in m["content_scripts"]:
            files += script["js"]
        for name in files:
            self.assertTrue((EXT / name).is_file(), name)
        self.assertEqual((m["manifest_version"], m["version"]), (3, config.VERSION))
        popup = (EXT / m["action"]["default_popup"]).read_text(encoding="utf-8")
        for name in re.findall(r'(?:src|href)="([^"]+)"', popup):
            self.assertTrue((EXT / "popup" / name).is_file(), name)
        self.assertNotIn("<script>", popup)       # 확장 화면에는 글 안에 넣은 스크립트를 쓸 수 없어요

    def test_it_asks_for_as_little_as_it_can(self):
        m = self.manifest
        self.assertEqual(m["permissions"], ["storage"])
        self.assertEqual(m["host_permissions"], ["http://127.0.0.1:7311/*"])     # 내 PC의 가닥만
        self.assertEqual([s["matches"] for s in m["content_scripts"]], [["https://chatgpt.com/*"], ["https://claude.ai/*"]])
        self.assertEqual(m["incognito"], "not_allowed")                          # 시크릿 창에서는 켤 수 없어요
        self.assertTrue(all("all_frames" not in s for s in m["content_scripts"]))

    def test_the_only_place_it_sends_to_is_this_pc(self):
        """대화는 내 PC 밖으로 나가지 않아요: 코드에 나오는 주소와, 밖으로 보낼 수 있는 길을 다 세어 봐요."""
        files = texts()
        urls = {url.rstrip("/") for text in files.values() for url in re.findall(r"https?://[^\s'\"*<>)]+", text)}
        self.assertEqual(urls, {"http://127.0.0.1:7311", "https://chatgpt.com", "https://claude.ai"})
        for name, text in files.items():
            for way in ("XMLHttpRequest", "WebSocket", "sendBeacon", "EventSource", "importScripts", "eval(", "new Function"):
                self.assertNotIn(way, text, name)
            if name != "background.js":
                self.assertNotIn("fetch(", text, name)
        self.assertEqual(files["background.js"].count("fetch("), 1)
        self.assertIn("fetch(GADAK + path", files["background.js"])

    def test_reading_does_not_touch_the_page(self):
        """화면은 읽기만 해요. 읽는 쪽(content/)에는 화면을 고치는 코드가 없어요."""
        for name, text in texts().items():
            if name.startswith("content/"):
                for way in ("innerHTML", "appendChild", "insertBefore", ".remove(", "setAttribute", ".click(", ".value =",
                            "document.cookie", "localStorage", "sessionStorage"):
                    self.assertNotIn(way, text, f"{name}: {way}")

    def test_long_text_is_cut_the_same_way_as_the_store(self):
        text = (EXT / "content" / "text.js").read_text(encoding="utf-8")
        found = re.search(r"var MAX = (\d+), HEAD = (\d+), CUT = '([^']*)';", text)
        self.assertIsNotNone(found)
        self.assertEqual((int(found[1]), int(found[2]), found[3].replace("\\n", "\n")),
                         (store.MAX_AI, store.AI_HEAD, store.CUT))


class _Pages(http.server.BaseHTTPRequestHandler):
    """시험 화면을 진짜 주소 모양(/c/<id> · /chat/<id>)으로 내줘요."""

    def do_GET(self):
        path = self.path.split("?")[0]
        if path.startswith("/ext/"):
            target = (EXT / path[5:]).resolve()
            if EXT.resolve() not in target.parents or not target.is_file():
                return self.send_error(404)
        elif path == "/harness.js":
            target = PAGES / "harness.js"
        elif path.startswith(("/c/", "/g/")):
            target = PAGES / "chatgpt.html"
        elif path.startswith("/chat/"):
            target = PAGES / "claude.html"
        else:
            return self.send_error(404)
        body = target.read_bytes()
        kind = "text/javascript" if target.suffix == ".js" else "text/html"
        self.send_response(200)
        self.send_header("Content-Type", kind + "; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


@unittest.skipUnless(os.environ.get("GADAK_BROWSER_TESTS") == "1" and Path(CHROME).exists(),
                     "크롬에서 돌리는 확인은 GADAK_BROWSER_TESTS=1 일 때만 돌아요")
class ExtensionInChromeTest(unittest.TestCase):
    """읽는 쪽(content/)을 크롬에서 돌려, 가닥으로 무엇을 언제 보내려 하는지 봐요. 시간은 크롬이 빨리 감아요."""

    @classmethod
    def setUpClass(cls):
        cls.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Pages)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.addClassCleanup(cls.server.server_close)
        cls.addClassCleanup(cls.server.shutdown)

    def run_page(self, path, budget):
        profile = tempfile.mkdtemp(prefix="gadak-chrome-")
        self.addCleanup(shutil.rmtree, profile, True)
        out = Path(profile) / "dom.html"
        url = f"http://127.0.0.1:{self.server.server_address[1]}{path}"
        command = [CHROME, "--headless=new", "--disable-gpu", "--no-first-run", "--no-default-browser-check",
                   "--disable-background-networking", "--disable-component-update", "--disable-extensions",
                   f"--user-data-dir={profile}", f"--virtual-time-budget={budget}", "--dump-dom", url]
        with open(out, "w", encoding="utf-8") as sink:
            chrome = subprocess.Popen(command, stdout=sink, stderr=subprocess.DEVNULL)
            try:
                for _ in range(240):                   # 크롬은 다 쓰고도 스스로 꺼지지 않을 때가 있어요
                    time.sleep(0.25)
                    if chrome.poll() is not None or "</html>" in out.read_text(encoding="utf-8", errors="replace"):
                        break
            finally:
                if chrome.poll() is None:
                    chrome.terminate()
                    try:
                        chrome.wait(5)
                    except subprocess.TimeoutExpired:
                        chrome.kill()
                subprocess.run(["pkill", "-f", f"user-data-dir={profile}"], check=False)
        found = re.search(r'<pre id="result">(.*?)</pre>', out.read_text(encoding="utf-8", errors="replace"), re.S)
        self.assertIsNotNone(found, "시험 화면이 끝까지 돌지 못했어요")
        result = json.loads(html.unescape(found[1]))
        self.assertEqual(result["errors"], [])
        failed = [f"{c['name']}: {c['detail']}" for c in result["checks"] if not c["ok"]]
        self.assertEqual(failed, [], "\n" + "\n".join(failed))
        return result

    def test_chatgpt_page(self):
        result = self.run_page("/c/aaaaaaaa-1111-4111-8111-111111111111", 92000)
        self.assertGreater(len(result["checks"]), 20)

    def test_claude_page(self):
        result = self.run_page("/chat/aaaaaaaa-1111-4111-8111-111111111111", 24000)
        self.assertGreater(len(result["checks"]), 10)


if __name__ == "__main__":
    unittest.main()
