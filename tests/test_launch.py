import plistlib
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from backend import launch


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

    def test_app_bundle_runs_the_launcher_from_this_folder(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = launch.install_app(tmp)
            script = (app / "Contents" / "MacOS" / "gadak").read_text(encoding="utf-8")
            info = plistlib.loads((app / "Contents" / "Info.plist").read_bytes())
            executable = (app / "Contents" / "MacOS" / "gadak").stat().st_mode & 0o111
        self.assertEqual(app.name, "가닥.app")
        self.assertIn(str(launch.config.ROOT), script)
        self.assertIn(f"{sys.executable} -m backend.launch --app" if " " not in sys.executable else "-m backend.launch --app", script)
        self.assertEqual((info["CFBundleExecutable"], info["CFBundleName"], info["LSUIElement"]), ("gadak", "가닥", True))
        self.assertTrue(executable)


if __name__ == "__main__":
    unittest.main()
