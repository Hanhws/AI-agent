"""남에게 건네는 앱(백엔드를 앱 안에 묶은 것 · backend/macapp.py --bundle)에서 달라지는 것들.
실제로 묶어 보는 것은 오래 걸려서 GADAK_BUNDLE_TESTS=1일 때만 해요 (PyInstaller · Swift가 있어야 해요)."""
import importlib.util
import io
import json
import os
import shlex
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from backend import config, frozen, macapp, sources

ROOT = Path(__file__).resolve().parent.parent
BACKEND_IN_APP = "/Applications/가닥.app/Contents/Resources/backend/gadak-backend"
QUOTED = shlex.quote(BACKEND_IN_APP)      # 한글이 든 길이라 따옴표로 싸요

_spec = importlib.util.spec_from_file_location("gadak_install", ROOT / "cursor-hooks" / "install.py")
install = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(install)


class BundledTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.settings = Path(self.tmp.name) / "claude" / "settings.json"
        env = mock.patch.dict(os.environ, {"GADAK_CLAUDE_SETTINGS": str(self.settings),
                                           "GADAK_CURSOR_HOME": str(Path(self.tmp.name) / "cursor")})
        env.start()
        self.addCleanup(env.stop)

    def bundled(self, executable=BACKEND_IN_APP):
        return mock.patch.object(config, "FROZEN", True), mock.patch.object(sys, "executable", executable)

    def test_what_goes_into_the_app_exists(self):
        for source, _folder in macapp.BUNDLE_DATA:
            self.assertTrue((ROOT / source).exists(), source)
        self.assertTrue((ROOT / "mac" / macapp.ENTRY).is_file())
        folders = {folder for _source, folder in macapp.BUNDLE_DATA}
        # 묶인 백엔드가 파일로 읽는 자리들 (backend/app.py · agent · sources가 config.ROOT 아래에서 찾아요)
        self.assertLessEqual({"shared/ui", "backend/web", "backend/prompts", "data", "cursor-hooks", "extension"}, folders)
        self.assertNotIn(".env", " ".join(source for source, _ in macapp.BUNDLE_DATA))          # 내 설정 · 서버 주소는 넣지 않아요
        self.assertIn(macapp.BACKEND, sources.HOOK_MARKS)
        self.assertIn(f'"backend/{macapp.BACKEND}"', (ROOT / "mac" / "Gadak.swift").read_text(encoding="utf-8"))

    def test_the_bundled_app_carries_no_paths_from_my_computer(self):
        info = macapp.info_plist(bundled=True)
        self.assertFalse({"GadakRoot", "GadakPython", "GadakPath"} & set(info))
        self.assertNotIn(str(ROOT), json.dumps(info, ensure_ascii=False))
        self.assertEqual((info["CFBundleExecutable"], info["CFBundleShortVersionString"]), ("Gadak", config.VERSION))
        self.assertIn("GadakRoot", macapp.info_plist())                                          # 내 PC에서 쓰는 앱은 그대로

    def test_hooks_run_through_the_bundled_backend_not_python(self):
        """받은 사람의 Mac에는 파이썬이 없을 수 있어요. hook은 앱 안의 실행 파일이 돌려요."""
        self.assertTrue(sources.hook_runner().startswith("python3 "))
        frozen_, executable = self.bundled()
        with frozen_, executable:
            self.assertEqual(sources.hook_runner(), f"{QUOTED} hook")
            self.assertEqual(sources.connect_claude(), {"ok": True})
            written = json.loads(self.settings.read_text(encoding="utf-8"))["hooks"]
            self.assertEqual(written["Stop"][0]["hooks"][0]["command"], f"{QUOTED} hook --auto")
            self.assertTrue(sources.claude_connected())                                          # 실행 파일 이름으로도 알아봐요
            self.assertEqual(sources.connect_cursor(), {"ok": True})
            launcher = (Path(self.tmp.name) / "cursor" / "hooks" / "gadak.sh").read_text(encoding="utf-8")
            self.assertIn(f"exec {QUOTED} hook\n", launcher)
            self.assertNotIn("python3", launcher)
            self.assertEqual(sources.disconnect_claude(), {"ok": True})
        self.assertFalse(sources.claude_connected())
        self.assertIn("exec python3 ", install.launcher_script())                                # 저장소에서 쓸 때는 그대로

    def test_an_app_running_from_a_temporary_place_does_not_write_hooks(self):
        """내려받은 앱을 옮기지 않고 켜면 macOS가 임시 자리에서 돌려요. 그 자리를 다른 프로그램의 설정에 적으면 곧 끊겨요."""
        for place in ("/private/var/folders/ab/T/AppTranslocation/1234/d/가닥.app/Contents/Resources/backend/gadak-backend",
                      "/Volumes/가닥/가닥.app/Contents/Resources/backend/gadak-backend"):
            frozen_, executable = self.bundled(place)
            with frozen_, executable:
                for connect in (sources.connect_claude, sources.connect_cursor):
                    result = connect()
                    self.assertEqual((result["ok"], result["reason"]), (False, sources.MOVED))
        self.assertFalse(self.settings.exists())

    def test_the_bundled_backend_runs_the_hook_script_itself(self):
        said = io.StringIO()
        payload = json.dumps({"hook_event_name": "beforeSubmitPrompt", "conversation_id": "c1", "prompt": "안녕"})
        with mock.patch.object(sys, "argv", ["gadak-backend", "hook"]), mock.patch.object(sys, "stdin", io.StringIO(payload)), \
                mock.patch.dict(os.environ, {"GADAK_URL": "http://127.0.0.1:9", "GADAK_HOME": self.tmp.name}), redirect_stdout(said):
            self.assertEqual(frozen.main(["hook"]), 0)
        self.assertEqual(json.loads(said.getvalue()), {"continue": True})                        # Cursor가 기다리는 답
        self.assertTrue((Path(self.tmp.name) / "spool.jsonl").is_file())                         # 가닥이 꺼져 있으면 쌓아 둬요
        with redirect_stdout(io.StringIO()) as said:
            self.assertEqual(frozen.main(["--version"]), 0)
        self.assertIn(config.VERSION, said.getvalue())

    def test_build_notes_are_read_only_inside_a_bundle(self):
        (Path(self.tmp.name) / "BUILD.json").write_text('{"built": "20261006-120000", "collect": "https://example.invalid"}', encoding="utf-8")
        with mock.patch.object(config, "ROOT", Path(self.tmp.name)):
            self.assertEqual(config._build(), {})                                                # 저장소에서 돌 때는 보지 않아요
            with mock.patch.object(config, "FROZEN", True):
                self.assertEqual(config._build()["built"], "20261006-120000")
                with mock.patch.object(config, "BUILD", config._build()):
                    self.assertEqual(config._code_stamp(), "20261006-120000")                    # 묶인 앱의 ‘코드의 판’은 만든 때
        self.assertEqual(config.BUILD, {})

    def test_without_pyinstaller_it_says_what_to_do(self):
        with mock.patch.object(macapp.subprocess, "run", return_value=subprocess.CompletedProcess([], 1)):
            with self.assertRaises(macapp.BuildError) as caught:
                macapp.freeze(self.tmp.name)
        self.assertIn("pip install pyinstaller", str(caught.exception))


@unittest.skipUnless(os.environ.get("GADAK_BUNDLE_TESTS") == "1" and sys.platform == "darwin", "GADAK_BUNDLE_TESTS=1일 때만 실제로 묶어 봐요")
class RealBundleTest(unittest.TestCase):
    def test_the_frozen_backend_starts_without_this_folder_or_python(self):
        with tempfile.TemporaryDirectory() as tmp:
            backend = macapp.freeze(tmp) / macapp.BACKEND
            bare = {"HOME": tmp, "PATH": "/usr/bin:/bin"}
            said = subprocess.run([str(backend), "--version"], capture_output=True, text=True, env=bare, cwd=tmp, timeout=60)
            self.assertEqual(said.returncode, 0, said.stderr)
            self.assertIn(config.VERSION, said.stdout)
            hook = subprocess.run([str(backend), "hook", "--auto"], input="{}", capture_output=True, text=True,
                                  env=dict(bare, GADAK_INTERNAL="1"), cwd=tmp, timeout=60)
            self.assertEqual((hook.returncode, hook.stdout), (0, ""))
            inside = backend.parent / "_internal"
            for path in ("shared/ui/view.js", "backend/web/index.html", "backend/prompts/classify.txt", "data/demo_conversations.json",
                         "cursor-hooks/gadak-hook.py", "extension/manifest.json", "BUILD.json"):
                self.assertTrue((inside / path).is_file(), path)
            self.assertFalse(list(inside.rglob(".env")))
            self.assertFalse(list(inside.rglob("example_conversations.json")))                   # 실제 대화는 들어가면 안 돼요


if __name__ == "__main__":
    unittest.main()
