import contextlib
import io
import plistlib
import re
import subprocess
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from backend import launch, macapp, runtime
from backend.runtime import Runtime


class LaunchTest(unittest.TestCase):
    def test_nothing_running_on_an_unused_port(self):
        with mock.patch.object(launch, "URL", "http://127.0.0.1:9"):
            self.assertFalse(launch.running())

    def test_falls_back_to_the_default_browser(self):
        with mock.patch.object(launch, "window_command", return_value=None), \
                mock.patch.object(launch.webbrowser, "open") as tab:
            launch.open_window()
        tab.assert_called_once_with(launch.URL)

    def test_failed_app_window_falls_back_too(self):
        failed = subprocess.CompletedProcess([], 1)
        with mock.patch.object(launch, "window_command", return_value=["open", "-na", "Google Chrome"]), \
                mock.patch.object(launch.subprocess, "run", return_value=failed), \
                mock.patch.object(launch.webbrowser, "open") as tab:
            launch.open_window()
        tab.assert_called_once_with(launch.URL)

    def test_app_window_command_opens_the_local_page_without_an_address_bar(self):
        command = launch.window_command()
        if command is None:
            self.skipTest("주소창 없는 창을 띄울 브라우저가 없어요")
        self.assertIn(f"--app={launch.URL}", command)

    def test_the_app_is_told_where_the_window_is(self):
        """가닥 앱은 백엔드가 말해 주는 주소를 듣고 화면을 띄워요. 이미 켜진 가닥이 있으면 거기에 붙어요."""
        out = io.StringIO()
        same = {"app": "gadak", "code": launch.config.CODE}
        with mock.patch.object(launch, "health", return_value=same), mock.patch.object(launch, "stop_old") as stop, \
                mock.patch.object(launch, "open_window") as window, contextlib.redirect_stdout(out):
            self.assertEqual(launch.main(["--shell", "--parent", "123"]), 0)
        self.assertEqual(out.getvalue().strip(), f"GADAK_READY {launch.URL} attached")
        window.assert_not_called()          # 창은 앱이 띄워요
        stop.assert_not_called()            # 같은 코드면 그대로 둬요

    def test_a_running_copy_with_old_code_is_replaced(self):
        """코드를 고친 뒤에도 뒤에서 돌던 예전 가닥에 붙으면 새 기능이 없어요. 끄고 지금 코드로 다시 켜요."""
        for old in ({"app": "gadak"}, {"app": "gadak", "code": "1"}):       # 표시가 없던 때의 가닥 · 다른 때의 코드
            with mock.patch.object(launch, "health", return_value=old), \
                    mock.patch.object(launch, "stop_old", return_value=True) as stop, \
                    mock.patch.object(launch, "serve", return_value=0) as serve, contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(launch.main(["--shell", "--parent", "123"]), 0)
            stop.assert_called_once_with()
            serve.assert_called_once_with(window=False, shell=True, parent=123)

    def test_an_old_copy_that_will_not_stop_is_kept(self):
        out = io.StringIO()
        with mock.patch.object(launch, "health", return_value={"app": "gadak"}), \
                mock.patch.object(launch, "stop_old", return_value=False), \
                mock.patch.object(launch, "serve") as serve, contextlib.redirect_stdout(out):
            self.assertEqual(launch.main(["--shell"]), 0)
        self.assertEqual(out.getvalue().strip(), f"GADAK_READY {launch.URL} attached")
        serve.assert_not_called()

    def test_stopping_an_old_copy_asks_it_to_quit_and_waits(self):
        answers = iter([True, True, False])
        with mock.patch.object(launch.urllib.request, "urlopen") as asked, \
                mock.patch.object(launch, "running", side_effect=lambda: next(answers)), \
                mock.patch.object(launch.time, "sleep"):
            self.assertTrue(launch.stop_old())
        request = asked.call_args[0][0]
        self.assertEqual((request.full_url, request.get_method()), (launch.URL + "/quit", "POST"))
        with mock.patch.object(launch.urllib.request, "urlopen", side_effect=OSError), \
                mock.patch.object(launch, "running", return_value=True), mock.patch.object(launch.time, "sleep"):
            self.assertFalse(launch.stop_old(wait=0.01))

    def test_parent_number(self):
        self.assertEqual(launch._number_after(["--shell", "--parent", "4321"], "--parent"), 4321)
        self.assertIsNone(launch._number_after(["--shell", "--parent"], "--parent"))
        self.assertIsNone(launch._number_after(["--shell"], "--parent"))

    def test_backend_started_by_the_app_stops_when_the_app_is_gone(self):
        with tempfile.TemporaryDirectory() as tmp:
            rt = Runtime(Path(tmp) / "gadak.db", engine=None)
            stopped = threading.Event()
            rt.on_quit = stopped.set
            with mock.patch.object(runtime, "PARENT_CHECK", 0.02), \
                    mock.patch.object(runtime.os, "getppid", return_value=1):   # 앱이 사라져 launchd가 부모가 됨
                rt.watch_parent(4321)
                self.assertTrue(stopped.wait(3))


class MacAppTest(unittest.TestCase):
    def test_info_plist_points_at_this_folder(self):
        info = macapp.info_plist()
        self.assertEqual((info["CFBundleName"], info["CFBundleExecutable"], info["CFBundleIconFile"]), ("가닥", "Gadak", "AppIcon"))
        self.assertEqual(info["GadakRoot"], str(launch.config.ROOT))
        self.assertTrue(info["GadakPython"].endswith("python"))
        self.assertNotIn("LSUIElement", info)       # Dock에 보이는 보통 앱이에요
        plistlib.loads(plistlib.dumps(info))         # plist로 쓸 수 있는 값만

    def test_search_path_keeps_only_real_folders_once(self):
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.dict(macapp.os.environ, {"PATH": f"{tmp}:/no/such/folder:{tmp}"}):
            self.assertEqual(macapp.search_path(), tmp)

    def test_install_folder(self):
        self.assertEqual(macapp.install_folder("~/somewhere"), Path.home() / "somewhere")
        with mock.patch.object(macapp.os, "access", return_value=False):
            self.assertEqual(macapp.install_folder(), Path.home() / "Applications")
        with mock.patch.object(macapp.os, "access", return_value=True):
            self.assertEqual(macapp.install_folder(), Path("/Applications"))

    def test_install_replaces_the_old_copy(self):
        with tempfile.TemporaryDirectory() as tmp:
            built = Path(tmp) / "dist" / "가닥.app"
            (built / "Contents").mkdir(parents=True)
            (built / "Contents" / "Info.plist").write_text("new", encoding="utf-8")
            old = Path(tmp) / "Applications" / "가닥.app"
            old.mkdir(parents=True)
            (old / "stale").write_text("old", encoding="utf-8")
            target = macapp.install(built, Path(tmp) / "Applications")
            self.assertEqual(target, old)
            self.assertEqual(sorted(p.name for p in target.rglob("*") if p.is_file()), ["Info.plist"])

    def test_the_app_is_built_from_all_its_swift_files(self):
        self.assertEqual(macapp.APP_SOURCES, ("Gadak.swift", "Float.swift", "FloatCheck.swift"))   # 창 · 메뉴 / 떠 있는 버튼 / 그 확인
        for name in macapp.APP_SOURCES:
            self.assertTrue((macapp.SOURCES / name).is_file(), name)
        self.assertIn("@main", (macapp.SOURCES / "Gadak.swift").read_text(encoding="utf-8"))   # 파일이 여럿이라 시작하는 곳을 적어 둬요

    def test_the_disk_image_carries_the_guide_for_whoever_receives_it(self):
        """받아서 쓰는 사람에게 가는 것: 가닥 · 응용 프로그램 폴더로 가는 길 · 처음 여는 법 · 그림이 든 설치 안내(PDF)."""
        self.assertTrue(macapp.GUIDE.is_file())
        self.assertEqual(macapp.GUIDE.read_bytes()[:5], b"%PDF-")
        for words in ("그래도 열기", "AI 연결", "터미널을 열 일은 없어요", "가닥 설치 안내.pdf"):
            self.assertIn(words, macapp.FIRST_OPEN)
        made = []
        def fake_run(command, what):
            made.append(sorted(p.name for p in Path(command[command.index("-srcfolder") + 1]).iterdir()))
        with tempfile.TemporaryDirectory() as tmp:
            app = Path(tmp) / "가닥.app"
            (app / "Contents").mkdir(parents=True)
            with mock.patch.object(macapp, "_run", fake_run):
                target = macapp.dmg(app, Path(tmp) / "out")
        self.assertEqual(made, [sorted(["Applications", "가닥 설치 안내.pdf", "가닥.app", "처음 여는 법.txt"])])
        self.assertTrue(target.name.startswith("가닥-") and target.name.endswith(".dmg"))
        # 설명서의 글 · 그림 · 다시 찍는 스크립트가 같이 있어요. 그림에 실제 대화가 들어가지 않게 지어낸 예시로 찍어요 (README에 적어 둠)
        guide = macapp.GUIDE.parent / "install-guide"
        html = (guide / "guide.html").read_text(encoding="utf-8")
        for image in re.findall(r'src="(img/[^"]+)"', html):
            self.assertTrue((guide / image).is_file(), image)
        for words in ("그래도 열기", "AI 연결", "연결하기", "버튼 편집", "chrome://extensions", "~/.gadak"):
            self.assertIn(words, html)
        self.assertTrue((guide / "make-pdf.sh").is_file())

    def test_without_swift_it_says_what_to_do(self):
        with mock.patch.object(macapp.shutil, "which", return_value=None), mock.patch.object(macapp.sys, "platform", "darwin"):
            with self.assertRaises(macapp.BuildError) as caught:
                macapp.build()
        self.assertIn("xcode-select --install", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
