"""Windows에 까는 가닥에서 달라지는 것들 (backend/win.py · winapp.py · launch.py --app · 자격 증명 관리자).

대부분은 어느 운영체제에서나 돌아요: Windows인 척(win.WINDOWS)하고 폴더 · 명령을 가짜로 바꿔 끼워요.
‘진짜 Windows에서만’이라고 적힌 것은 Windows(또는 Wine)의 파이썬으로 돌릴 때만 돌아요.
"""
import contextlib
import io
import json
import os
import struct
import sys
import tempfile
import threading
import time
import types
import unittest
import zipfile
import zlib
from pathlib import Path
from unittest import mock

from backend import config, launch, limits, sources, store, win, winapp
from backend.agent import investigate, outside
from backend.engines import claude_cli, codex_cli, keys
from backend.runtime import Runtime
from backend.sources import claude_code

ROOT = Path(__file__).resolve().parent.parent
KEY = "sk-proj-" + "Cd2_" * 30 + "qrst"

# npm이 만드는 껍데기(.cmd)의 두 모양
SHIM_NEW = (
    '@ECHO off\r\nGOTO start\r\n:find_dp0\r\nSET dp0=%~dp0\r\nEXIT /b\r\n:start\r\nSETLOCAL\r\nCALL :find_dp0\r\n\r\n'
    'IF EXIST "%dp0%\\node.exe" (\r\n  SET "_prog=%dp0%\\node.exe"\r\n) ELSE (\r\n  SET "_prog=node"\r\n  SET PATHEXT=%PATHEXT:;.JS;=;%\r\n)\r\n\r\n'
    'endLocal & goto #_undefined_# 2>NUL || title %COMSPEC% & "%_prog%"  "%dp0%\\node_modules\\@anthropic-ai\\claude-code\\cli.js" %*\r\n'
)
SHIM_OLD = (
    '@IF EXIST "%~dp0\\node.exe" (\r\n  "%~dp0\\node.exe"  "%~dp0\\node_modules\\@openai\\codex\\bin\\codex.js" %*\r\n) ELSE (\r\n'
    '  @SETLOCAL\r\n  @SET PATHEXT=%PATHEXT:;.JS;=;%\r\n  node  "%~dp0\\node_modules\\@openai\\codex\\bin\\codex.js" %*\r\n)\r\n'
)
SHIM_EXE = '@ECHO off\r\n"%dp0%\\node_modules\\@anthropic-ai\\claude-code\\bin\\claude.exe"   %*\r\n'


def as_windows():
    return mock.patch.object(win, "WINDOWS", True)


class Tmp(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)

    def file(self, *parts, text=""):
        path = self.tmp.joinpath(*parts)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path


class CommandTest(Tmp):
    """claude · codex를 부르는 말. npm 껍데기는 cmd.exe를 거쳐서 여러 줄짜리 글(프롬프트)을 넘기지 못해요."""

    def test_an_npm_shim_is_replaced_by_the_program_it_runs(self):
        shim = self.file("npm", "claude.cmd", text=SHIM_NEW)
        script = self.file("npm", "node_modules", "@anthropic-ai", "claude-code", "cli.js")
        with mock.patch.object(win.shutil, "which", return_value="C:/node/node.exe"):
            self.assertEqual(win.unshim(shim), ["C:/node/node.exe", str(script)])
        node = self.file("npm", "node.exe")                       # 껍데기 옆의 node가 먼저예요
        self.assertEqual(win.unshim(shim), [str(node), str(script)])

    def test_the_older_shim_and_a_shim_around_a_real_program(self):
        old = self.file("a", "codex.cmd", text=SHIM_OLD)
        script = self.file("a", "node_modules", "@openai", "codex", "bin", "codex.js")
        with mock.patch.object(win.shutil, "which", return_value="node"):
            self.assertEqual(win.unshim(old), ["node", str(script)])
        direct = self.file("b", "claude.cmd", text=SHIM_EXE)
        real = self.file("b", "node_modules", "@anthropic-ai", "claude-code", "bin", "claude.exe")
        self.assertEqual(win.unshim(direct), [str(real)])

    def test_a_shim_that_cannot_be_read_is_used_as_it_is(self):
        strange = self.file("claude.cmd", text="@echo off\r\necho hi\r\n")
        missing = self.file("x", "claude.cmd", text=SHIM_NEW)        # 가리키는 파일이 없어요
        no_node = self.file("y", "claude.cmd", text=SHIM_NEW)
        self.file("y", "node_modules", "@anthropic-ai", "claude-code", "cli.js")
        with mock.patch.object(win.shutil, "which", return_value=None):
            self.assertEqual([win.unshim(strange), win.unshim(missing), win.unshim(no_node)], [None, None, None])
            with as_windows():
                self.assertEqual(win.command(strange), [str(strange)])

    def test_only_windows_looks_inside_shims(self):
        shim = self.file("npm", "claude.cmd", text=SHIM_EXE)
        real = self.file("npm", "node_modules", "@anthropic-ai", "claude-code", "bin", "claude.exe")
        with mock.patch.object(win, "WINDOWS", False):
            self.assertEqual(win.command(shim), [str(shim)])
            self.assertEqual(win.command("/usr/local/bin/claude"), ["/usr/local/bin/claude"])
        with as_windows():
            self.assertEqual(win.command(shim), [str(real)])
            self.assertEqual(win.command("C:/x/claude.exe"), ["C:/x/claude.exe"])
        self.assertEqual(win.command(None), [])

    def test_the_engines_call_the_real_program(self):
        shim = self.file("npm", "claude.cmd", text=SHIM_EXE)
        real = self.file("npm", "node_modules", "@anthropic-ai", "claude-code", "bin", "claude.exe")
        seen = {}

        def run(command, **kwargs):
            seen.update(command=command, kwargs=kwargs)
            return types.SimpleNamespace(stdout=json.dumps({"loggedIn": True}), stderr="", returncode=0)

        with as_windows(), mock.patch.object(claude_cli, "find_bin", return_value=str(shim)), \
                mock.patch.object(claude_cli.subprocess, "run", run), mock.patch.object(config, "HOME", self.tmp / "home"):
            self.assertTrue(claude_cli.ClaudeCliEngine().check()["ok"])
        self.assertEqual(seen["command"], [str(real), "auth", "status"])

    def test_windows_prefers_a_real_exe_over_a_shim_and_looks_in_more_places(self):
        asked = []

        def which(name, path=None):
            asked.append((name, path))
            return "C:/npm/claude.cmd" if (name, path) == ("claude", None) else None

        with as_windows(), mock.patch.object(win.shutil, "which", which):
            self.assertEqual(win.which("claude", ["C:/a", "C:/b"]), "C:/npm/claude.cmd")
        self.assertEqual(asked[0], ("claude.exe", None))                     # 진짜 실행 파일부터
        self.assertIn(("claude.exe", os.pathsep.join(["C:/a", "C:/b"])), asked)
        with as_windows(), mock.patch.dict(os.environ, {"APPDATA": "C:/Users/me/AppData/Roaming"}):
            spots = claude_cli.windows_path()
        self.assertTrue(spots[0].replace("\\", "/").endswith(".local/bin"))     # 공식 설치가 두는 자리
        self.assertIn(os.path.join("C:/Users/me/AppData/Roaming", "npm"), spots)

    def test_codex_inside_the_editor_extension_is_an_exe_on_windows(self):
        home = self.tmp / "me"
        inside = self.file("me", ".vscode", "extensions", "openai.chatgpt-26.1002.5-win32-x64", "bin", "windows-x86_64", "codex.exe")
        inside.chmod(0o755)                               # Windows에서는 있는 파일이면 돌릴 수 있는 파일이에요
        env = {k: v for k, v in os.environ.items() if k not in (codex_cli.ENV_BIN, "APPDATA")}
        with as_windows(), mock.patch.dict(os.environ, env, clear=True), mock.patch.object(win.shutil, "which", return_value=None), \
                mock.patch.object(codex_cli.Path, "home", return_value=home), mock.patch.object(config, "HOME", self.tmp / "home"):
            self.assertEqual(codex_cli.find_bin(), str(inside))


class BrowserTest(Tmp):
    def roots(self):
        return mock.patch.dict(os.environ, {"ProgramFiles": str(self.tmp / "pf"), "ProgramFiles(x86)": str(self.tmp / "pf86"),
                                            "LocalAppData": str(self.tmp / "local")})

    def test_edge_first_then_chrome_wherever_they_are_installed(self):
        with self.roots():
            self.assertEqual(win.browsers(), [])
            chrome = self.file("local", "Google", "Chrome", "Application", "chrome.exe")       # 내 계정에만 깐 크롬
            self.assertEqual(win.browsers(), [("Google Chrome", str(chrome))])
            edge = self.file("pf86", "Microsoft", "Edge", "Application", "msedge.exe")
            self.assertEqual(win.browsers(), [("Microsoft Edge", str(edge)), ("Google Chrome", str(chrome))])

    def test_the_app_window_runs_in_a_browser_place_of_its_own(self):
        edge = self.file("pf86", "Microsoft", "Edge", "Application", "msedge.exe")
        with self.roots(), as_windows(), mock.patch.dict(os.environ), \
                mock.patch.object(launch.sys, "platform", "win32"), mock.patch.object(config, "HOME", self.tmp / "home"):
            os.environ.pop(launch.BROWSER_ENV, None)
            plain, own = launch.window_command(), launch.window_command(own=True)
        self.assertEqual(plain, [str(edge), f"--app={launch.URL}", f"--window-size={launch.WINDOW}"])
        self.assertEqual(own[:3], plain)
        self.assertIn(f"--user-data-dir={self.tmp / 'home' / launch.PROFILE}", own)      # 쓰던 브라우저와 섞이지 않아요
        for flag in launch.OWN_FLAGS:
            self.assertIn(flag, own)

    def test_without_such_a_browser_it_opens_a_tab_and_does_not_watch(self):
        rt = mock.Mock()
        with mock.patch.object(launch, "window_command", return_value=None), mock.patch.object(launch.webbrowser, "open") as tab:
            launch.own_window(rt)
        tab.assert_called_once_with(launch.URL)
        rt.watch_window.assert_not_called()               # 화면의 ‘끄기’를 누를 때까지 돌아요

    def test_the_browser_it_started_is_watched(self):
        rt, started = mock.Mock(), mock.Mock()
        with mock.patch.dict(os.environ, {launch.BROWSER_ENV: "C:/x/msedge.exe"}), \
                mock.patch.object(launch.subprocess, "Popen", return_value=started) as popen, \
                mock.patch.object(config, "HOME", self.tmp / "home"):
            launch.own_window(rt)
        self.assertEqual(popen.call_args.args[0][:2], ["C:/x/msedge.exe", f"--app={launch.URL}"])
        rt.watch_window.assert_called_once_with(started)


class Closed:
    """창을 띄운 브라우저 흉내. close()를 부르면 끝나요."""

    def __init__(self):
        self.done = threading.Event()

    def wait(self):
        self.done.wait(10)

    def close(self):
        self.done.set()


class WindowTest(Tmp):
    """창 하나로 도는 가닥은 그 창이 닫히면 꺼져요."""

    def runtime(self):
        rt = Runtime(self.tmp / "gadak.db", engine=None)
        quit = threading.Event()
        rt.on_quit = quit.set
        return rt, quit

    def test_closing_the_window_stops_gadak(self):
        rt, quit = self.runtime()
        browser = Closed()
        rt.watch_window(browser, grace=0.3, quiet=0.2, step=0.05)
        self.assertFalse(quit.wait(0.3))                  # 창이 떠 있는 동안에는 돌아요
        browser.close()
        self.assertTrue(quit.wait(3))

    def test_a_browser_that_handed_the_window_over_does_not_stop_gadak(self):
        """브라우저가 먼저 떠 있던 자기 창에 일을 넘기고 바로 끝난 경우: 화면이 계속 물으면 창은 살아 있어요."""
        rt, quit = self.runtime()
        asking = threading.Event()

        def page():
            while not asking.wait(0.03):
                rt.status()

        threading.Thread(target=page, daemon=True).start()
        browser = Closed()
        browser.close()
        rt.watch_window(browser, grace=0.3, quiet=0.3, step=0.05)
        self.assertFalse(quit.wait(1.0))                  # 화면이 묻는 동안에는 끄지 않아요
        asking.set()                                      # 그 창도 닫혔어요
        self.assertTrue(quit.wait(3))

    def test_quitting_from_the_screen_ends_the_watch(self):
        rt, quit = self.runtime()
        browser = Closed()
        rt.watch_window(browser, grace=5, quiet=5, step=5)
        browser.close()
        rt.quit()                                         # 화면의 ‘끄기’
        self.assertTrue(quit.wait(3))


class LaunchTest(Tmp):
    def launch(self, argv, health=None, env=None):
        with mock.patch.object(launch, "health", return_value=health), mock.patch.object(launch, "serve", return_value=0) as serve, \
                mock.patch.object(launch, "open_window") as window, mock.patch.object(launch.win, "log_streams") as log, \
                mock.patch.object(launch.win, "hold") as hold, mock.patch.dict(os.environ, env or {}), \
                contextlib.redirect_stdout(io.StringIO()):
            os.environ.pop("GADAK_NO_WINDOW", None) if not env else None
            code = launch.main(argv)
        return code, serve, window, log, hold

    def test_the_installed_app_starts_with_one_window_of_its_own(self):
        code, serve, window, log, hold = self.launch(["--app"])
        self.assertEqual(code, 0)
        serve.assert_called_once_with(window=False, shell=False, parent=None, own=True)
        log.assert_called_once_with(config.HOME)          # 창 없이 켜져서 하는 말은 기록 파일로
        hold.assert_called_once_with()                    # 설치 프로그램이 ‘켜져 있음’을 알아보게
        window.assert_not_called()

    def test_started_twice_it_only_opens_the_window_again(self):
        same = {"app": "gadak", "code": config.CODE}
        code, serve, window, _, _ = self.launch(["--app"], health=same)
        self.assertEqual(code, 0)
        serve.assert_not_called()
        window.assert_called_once_with(own=True)

    def test_without_a_window_it_runs_until_told_to_quit(self):
        code, serve, window, _, _ = self.launch(["--app"], env={"GADAK_NO_WINDOW": "1"})
        serve.assert_called_once_with(window=False, shell=False, parent=None)
        window.assert_not_called()

    def test_a_failed_start_is_written_down_and_shown(self):
        with mock.patch.object(launch, "run", side_effect=RuntimeError("안 켜짐")), mock.patch.object(launch.win, "log_streams"), \
                mock.patch.object(launch.win, "hold"), mock.patch.object(launch.win, "alert") as alert, \
                contextlib.redirect_stderr(io.StringIO()) as said:
            self.assertEqual(launch.main(["--app"]), 1)
        self.assertIn("안 켜짐", said.getvalue())
        self.assertIn("gadak.log", alert.call_args.args[0])

    def test_what_gadak_says_goes_to_a_file_when_there_is_no_console(self):
        with mock.patch.object(sys, "stdout", None), mock.patch.object(sys, "stderr", None):
            win.log_streams(self.tmp / "home")
            print("가닥을 켰어요")
            sys.stdout.close()
        self.assertEqual((self.tmp / "home" / "gadak.log").read_text(encoding="utf-8"), "가닥을 켰어요\n")
        before = sys.stdout
        win.log_streams(self.tmp / "other")               # 말할 곳이 있으면 그대로 둬요
        self.assertIs(sys.stdout, before)
        self.assertFalse((self.tmp / "other").exists())


class FakeStore:
    """Windows 자격 증명 관리자 흉내 (backend/engines/wincred.py와 같은 세 가지)."""

    def __init__(self):
        self.items, self.labels = {}, {}

    def read(self, target):
        return self.items.get(target)

    def write(self, target, secret, label):
        self.items[target] = secret
        self.labels[target] = label
        return True

    def delete(self, target):
        return self.items.pop(target, None) is not None


class KeysTest(unittest.TestCase):
    def setUp(self):
        self.store = FakeStore()
        keys._seen.update(at=0.0, service=None, key=None)
        for patch in (as_windows(), mock.patch.dict(sys.modules, {"backend.engines.wincred": self.store}),
                      mock.patch.object(keys.subprocess, "run", side_effect=AssertionError("Windows에서는 명령을 띄우지 않아요")),
                      mock.patch.dict(os.environ, {"GADAK_KEYCHAIN_SERVICE": "local.gadak.test"})):
            patch.start()
            self.addCleanup(patch.stop)
        import backend.engines as package
        had = getattr(package, "wincred", None)
        package.wincred = self.store                      # from . import wincred 가 이것을 받아요
        self.addCleanup(lambda: setattr(package, "wincred", had) if had else delattr(package, "wincred"))
        for name in keys.ENVS:
            os.environ.pop(name, None)
        self.addCleanup(keys._seen.update, at=0.0, service=None, key=None)

    def test_a_key_is_kept_in_the_credential_manager(self):
        self.assertTrue(keys.can_store())
        self.assertEqual(keys.place(), "자격 증명 관리자")
        self.assertEqual(keys.find(), (None, None))
        keys.save(KEY)
        self.assertEqual(self.store.items, {"local.gadak.test/api-key": KEY})
        self.assertEqual(self.store.labels["local.gadak.test/api-key"], keys.LABEL)
        self.assertEqual(keys.find(), (KEY, "keychain"))
        self.assertEqual(keys.describe()["company"], "OpenAI")
        self.assertTrue(keys.delete())
        self.assertEqual((keys.find(), self.store.items), ((None, None), {}))
        self.assertFalse(keys.delete())

    def test_a_key_that_was_not_kept_is_reported(self):
        self.store.write = lambda *args: False
        with self.assertRaises(keys.KeyStoreError) as caught:
            keys.save(KEY)
        self.assertIn("자격 증명 관리자", str(caught.exception))
        with self.assertRaises(keys.KeyStoreError):
            keys.save("hello")                            # 키 모양이 아닌 것은 넣기 전에 걸러요


@unittest.skipUnless(sys.platform == "win32", "진짜 Windows에서만: 자격 증명 관리자에 실제로 넣었다 지워요")
class RealCredentialTest(unittest.TestCase):
    TARGET = "local.gadak.unittest/api-key"

    def test_round_trip(self):
        from backend.engines import wincred
        wincred.delete(self.TARGET)
        self.addCleanup(wincred.delete, self.TARGET)
        self.assertIsNone(wincred.read(self.TARGET))
        self.assertTrue(wincred.write(self.TARGET, KEY, "가닥 · 테스트"))
        self.assertEqual(wincred.read(self.TARGET), KEY)
        self.assertTrue(wincred.write(self.TARGET, KEY[:-1] + "z", "가닥 · 테스트"))          # 있으면 바꿔요
        self.assertEqual(wincred.read(self.TARGET), KEY[:-1] + "z")
        self.assertTrue(wincred.delete(self.TARGET))
        self.assertFalse(wincred.delete(self.TARGET))
        self.assertIsNone(wincred.read(self.TARGET))

    def test_the_key_module_uses_it(self):
        with mock.patch.dict(os.environ, {"GADAK_KEYCHAIN_SERVICE": "local.gadak.unittest"}):
            for name in keys.ENVS:
                os.environ.pop(name, None)
            keys._seen.update(at=0.0, service=None, key=None)
            keys.delete()
            self.addCleanup(keys.delete)
            keys.save(KEY)
            self.assertEqual(keys.find(), (KEY, "keychain"))
            self.assertTrue(keys.delete())
            self.assertEqual(keys.find(), (None, None))


class PathsTest(Tmp):
    """Windows에서 온 경로(C:\\…)도 같은 규칙으로 봐요."""

    def test_artifact_names_are_short_for_windows_paths_too(self):
        cwd = "C:\\Users\\me\\proj"
        self.assertEqual(store.shown_name("C:\\Users\\me\\proj\\src\\app.py", cwd), "src/app.py")
        self.assertEqual(store.shown_name("c:\\users\\me\\proj\\README.md", cwd), "README.md")        # 드라이브 글자의 대소문자
        self.assertEqual(store.shown_name("D:\\other\\notes.md", cwd), "notes.md")
        self.assertEqual(store.shown_name("C:/Users/me/proj/a/b.txt", "C:/Users/me/proj/"), "a/b.txt")
        self.assertEqual(store.shown_name("/Users/me/proj/src/app.py", "/Users/me/proj"), "src/app.py")    # 예전 그대로
        self.assertEqual(store.shown_name("/tmp/x.md", "/Users/me/proj"), "x.md")
        self.assertEqual(store.shown_name("rel/x.md", "/Users/me/proj"), "rel/x.md")

    def test_a_file_the_engine_names_is_matched_to_a_windows_path(self):
        path = "C:\\Users\\me\\proj\\src\\app.py"
        ctx = types.SimpleNamespace(turn_id="t1", edits=lambda _turn: {path: ["pair"]}, shown=lambda p: store.shown_name(p, "C:\\Users\\me\\proj"))
        for given in ("src/app.py", "app.py", "src\\app.py", path):
            self.assertEqual(investigate.match_file(ctx, given), (path, ["pair"]), given)
        self.assertEqual(investigate.match_file(ctx, "other.py"), (None, None))

    def test_onedrive_keeps_the_desktop_and_documents_and_those_are_broad_too(self):
        home = self.tmp / "me"
        for folder in ("OneDrive/Desktop", "OneDrive/문서/proj", "OneDrive - 학교/바탕 화면", "Videos", "code/proj", "OneDrive/proj"):
            (home / folder).mkdir(parents=True)
        with mock.patch.object(outside.Path, "home", return_value=home):
            broad = {name: outside.too_broad(home / name) for name in
                     ("OneDrive", "OneDrive/Desktop", "OneDrive/문서", "OneDrive - 학교", "OneDrive - 학교/바탕 화면", "Videos",
                      "OneDrive/문서/proj", "OneDrive/proj", "code/proj")}
        self.assertEqual(broad, {"OneDrive": True, "OneDrive/Desktop": True, "OneDrive/문서": True, "OneDrive - 학교": True,
                                 "OneDrive - 학교/바탕 화면": True, "Videos": True,
                                 "OneDrive/문서/proj": False, "OneDrive/proj": False, "code/proj": False})

    def test_file_names_are_joined_with_slashes_so_the_secret_rule_sees_them(self):
        base = self.tmp / "proj"
        for name in ("README.md", "sub/notes.md", "sub/.env.json", "sub/deep/token-list.md"):
            self.file("proj", *name.split("/"), text="x")
        with mock.patch.object(outside, "_tracked", return_value=None), mock.patch.object(outside, "git_ready", return_value=True), \
                mock.patch.object(outside, "_repo_above", return_value=False):
            walked, readable = outside._walk(base), outside._readable(base)
        self.assertIn("sub/.env.json", walked)            # 어느 운영체제에서나 /로 이어요
        self.assertEqual(readable, ["README.md", "sub/notes.md"])      # 비밀처럼 보이는 이름은 안쪽 폴더에 있어도 읽지 않아요

    def test_the_desktop_app_settings_are_under_appdata(self):
        env = {k: v for k, v in os.environ.items() if k != "GADAK_CLAUDE_DESKTOP_CONFIG"}
        with mock.patch.dict(os.environ, dict(env, APPDATA=str(self.tmp / "Roaming")), clear=True), \
                mock.patch.object(claude_code.sys, "platform", "win32"):
            self.assertEqual(claude_code.desktop_config(), self.tmp / "Roaming" / "Claude" / "claude_desktop_config.json")


class NotYetTest(Tmp):
    """Windows에서는 다른 프로그램의 설정을 고치지 않아요 (돌려 보지 못한 hook을 남의 Cursor · Claude Code에 적지 않아요)."""

    def test_hooks_are_not_written_on_windows(self):
        settings, cursor = self.tmp / "claude" / "settings.json", self.tmp / "cursor"
        with as_windows(), mock.patch.dict(os.environ, {"GADAK_CLAUDE_SETTINGS": str(settings), "GADAK_CURSOR_HOME": str(cursor)}):
            claude, editor = sources.connect_claude(), sources.connect_cursor()
        self.assertEqual((claude["ok"], editor["ok"]), (False, False))
        self.assertIn("Windows", claude["reason"])
        self.assertIn("Windows", editor["reason"])
        self.assertFalse(settings.exists())
        self.assertFalse(cursor.exists())

    def test_the_claude_gauge_does_not_reach_for_the_mac_keychain(self):
        with mock.patch.object(limits.sys, "platform", "win32"), mock.patch.dict(limits._claude, {"token": None, "until": 0.0}), \
                mock.patch("subprocess.run", side_effect=AssertionError("부르면 안 돼요")):
            self.assertIsNone(limits._claude_token())


class BundledTest(Tmp):
    def test_a_folder_install_counts_as_bundled_only_with_its_mark(self):
        with mock.patch.object(config, "ROOT", self.tmp), mock.patch.object(config, "FROZEN", False):
            self.assertFalse(config.bundled())
            (self.tmp / "BUILD.json").write_text('{"built": "20261012-120000"}', encoding="utf-8")
            self.assertFalse(config.bundled())            # 표시가 없으면 저장소로 봐요
            (self.tmp / "BUILD.json").write_text('{"built": "20261012-120000", "folder": true}', encoding="utf-8")
            self.assertTrue(config.bundled())
            with mock.patch.object(config, "BUILD", config._build()):
                self.assertEqual(config._code_stamp(), "20261012-120000")


def png(size, color=(200, 64, 26, 255)) -> bytes:
    rows = b"".join(b"\0" + bytes(color) * size for _ in range(size))

    def chunk(kind, body):
        return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body))

    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b""))


class BuildTest(Tmp):
    """설치 파일 만들기 (backend/winapp.py). 받는 일은 가짜로 바꿔 끼워요."""

    def fake_python(self):
        path = self.tmp / "python.zip"
        with zipfile.ZipFile(path, "w") as archive:
            for name in ("python.exe", "pythonw.exe", "python314.dll", "python314.zip"):
                archive.writestr(name, "x")
            archive.writestr("python314._pth", "python314.zip\n.\n\n#import site\n")
        return path

    def fake_wheel(self, name="flask-3.1.3-py3-none-any.whl"):
        path = self.tmp / name
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("flask/__init__.py", "")
            archive.writestr("flask-3.1.3.dist-info/METADATA", "Name: flask\n")
            archive.writestr("flask-3.1.3.data/purelib/flask_extra/__init__.py", "")
            archive.writestr("flask-3.1.3.data/scripts/flask", "#!python\n")
        return path

    def stage(self, collect=None):
        with mock.patch.object(winapp, "fetch_python", return_value=self.fake_python()), \
                mock.patch.object(winapp, "fetch_wheels", return_value=[self.fake_wheel()]):
            return winapp.stage(out=self.tmp / "out", collect=collect, cache=self.tmp / "cache")

    def test_everything_gadak_imports_is_downloaded_at_the_version_installed_here(self):
        pinned, extra = winapp.needed()
        for name in ("flask", "werkzeug", "jinja2", "anthropic", "httpx2", "pydantic", "pydantic-core"):
            self.assertIn(name, pinned)
        import flask
        from importlib.metadata import version
        self.assertEqual(pinned["flask"], version("flask"))
        self.assertNotIn("pyinstaller", pinned)           # 만들 때만 쓰는 것은 넣지 않아요
        self.assertEqual(extra, sorted(extra))

    def test_the_folder_that_gets_installed(self):
        folder = self.stage()
        self.assertEqual(folder, self.tmp / "out" / winapp.FOLDER)
        # 이 파이썬은 깔린 폴더만 봐요 (PC의 다른 파이썬 · PYTHONPATH와 섞이지 않아요)
        self.assertEqual((folder / "python" / "python314._pth").read_text(encoding="ascii").split(),
                         ["python314.zip", ".", "..\\app", "..\\site-packages"])
        for path in ("python/pythonw.exe", "site-packages/flask/__init__.py", "site-packages/flask_extra/__init__.py",
                     "app/backend/launch.py", "app/backend/engines/wincred.py", "app/backend/web/index.html",
                     "app/backend/prompts/classify.txt", "app/shared/ui/view.js", "app/data/demo_conversations.json",
                     "app/extension/manifest.json", winapp.ICON, winapp.START, winapp.FIRST, winapp.MANUAL):
            self.assertTrue((folder / path).is_file(), path)
        self.assertEqual((folder / winapp.MANUAL).read_bytes()[:5], b"%PDF-")           # 그림이 든 설명서 (Mac의 디스크 이미지와 같은 파일)
        self.assertFalse((folder / "site-packages" / "flask-3.1.3.data").exists())
        names = [p.name for p in folder.rglob("*")]
        for bad in (".env", "example_conversations.json", "__pycache__", ".DS_Store"):       # 내 설정 · 실제 대화는 넣지 않아요
            self.assertNotIn(bad, names)
        self.assertFalse([n for n in names if n.endswith((".local.md", ".db"))])
        self.assertFalse((folder / "app" / "tests").exists())
        built = json.loads((folder / "app" / "BUILD.json").read_text(encoding="utf-8"))
        self.assertEqual((built["folder"], built["version"], built["collect"], built["python"]),
                         (True, config.VERSION, None, winapp.PYTHON_VERSION))
        self.assertEqual(json.loads((self.stage(collect="https://example.invalid") / "app" / "BUILD.json").read_text(encoding="utf-8"))["collect"],
                         "https://example.invalid")

    def test_the_start_file_and_the_first_steps(self):
        folder = self.stage()
        start = (folder / winapp.START).read_bytes()
        start.decode("ascii")                             # cmd.exe가 PC마다 다른 글자표로 읽어서 로마자만 써요
        self.assertEqual(start, b'@echo off\r\nstart "" "%~dp0python\\pythonw.exe" -X utf8 -m backend.launch --app\r\n')
        first = (folder / winapp.FIRST).read_bytes()
        self.assertTrue(first.startswith(b"\xef\xbb\xbf"))                     # 메모장이 한글을 바로 읽게
        text = first.decode("utf-8-sig")
        self.assertNotIn("\n", text.replace("\r\n", ""))
        for words in ("추가 정보", "AI 연결", "자격 증명 관리자", "가닥 켜기.cmd", ".gadak", "gadak.log", winapp.names()["setup"], winapp.MANUAL):
            self.assertIn(words, text)

    def test_the_guide_people_receive_matches_what_is_built(self):
        """받는 사람이 보는 설치 안내(docs/install-guide/guide.html → PDF)에 적힌 파일 이름 · 누를 것이 만드는 것과 같은지."""
        html = (ROOT / "docs" / "install-guide" / "guide.html").read_text(encoding="utf-8")
        made = winapp.names()
        for words in (made["setup"], made["zip"], f"가닥-{config.VERSION}-arm64.dmg", f"가닥-{config.VERSION}-x86_64.dmg", winapp.START,
                      "Windows의 PC 보호", "추가 정보", "가닥 켜기", "자격 증명 관리자", "gadak.log", "전체 지도", "낮 · 밤", "가닥 토글"):
            self.assertIn(words, html)
        nsi = (ROOT / "win" / winapp.SCRIPT).read_text(encoding="utf-8")
        self.assertIn('MUI_FINISHPAGE_RUN_TEXT "가닥 켜기"', nsi)                       # 안내의 ‘가닥 켜기’는 설치 프로그램의 그 칸이에요
        for image in __import__("re").findall(r'src="(img/[^"]+)"', html):
            self.assertTrue((ROOT / "docs" / "install-guide" / image).is_file(), image)
        self.assertNotIn("SUIT", html)                                                  # 글꼴은 가닥 창과 같게 (Helvetica Neue + Pretendard)

    def test_the_zip_unpacks_into_one_folder(self):
        target = winapp.zipped(self.stage(), self.tmp / "dist")
        self.assertEqual(target.name, f"가닥-{config.VERSION}-windows-x64.zip")
        with zipfile.ZipFile(target) as archive:
            inside = archive.namelist()
        self.assertTrue(all(name.startswith("Gadak/") for name in inside))
        self.assertIn("Gadak/가닥 켜기.cmd", inside)
        self.assertIn("Gadak/python/pythonw.exe", inside)

    def test_a_wheel_cannot_write_outside_the_folder(self):
        bad = self.tmp / "bad-1.0-py3-none-any.whl"
        with zipfile.ZipFile(bad, "w") as archive:
            archive.writestr("../../evil.py", "")
        with self.assertRaises(winapp.BuildError):
            winapp._unpack_wheel(bad, self.tmp / "site")
        self.assertFalse((self.tmp / "evil.py").exists())

    def test_a_python_that_is_not_the_one_written_down_is_refused(self):
        cache = self.tmp / "cache"
        cache.mkdir()
        (cache / f"python-{winapp.PYTHON_VERSION}-embed-amd64.zip").write_bytes(b"not the real one")
        with self.assertRaises(winapp.BuildError) as caught:
            winapp.fetch_python(cache)
        self.assertIn("달라요", str(caught.exception))
        self.assertFalse(list(cache.iterdir()))           # 틀린 것은 지워서 다음에 다시 받아요

    def test_the_icon_file(self):
        data = winapp.ico([png(16), png(32), png(256)])
        self.assertEqual(struct.unpack("<HHH", data[:6]), (0, 1, 3))
        seen = []
        for i in range(3):
            width, height, _, _, planes, bits, size, offset = struct.unpack("<BBBBHHII", data[6 + 16 * i:22 + 16 * i])
            seen.append((width or 256, height or 256, bits, data[offset:offset + 4] == b"\x89PNG"))
            if width:
                self.assertEqual(struct.unpack("<Iii", data[offset:offset + 12]), (40, width, height * 2))
                self.assertEqual(data[offset + 40:offset + 44], bytes((26, 64, 200, 255)))          # 파랑 · 초록 · 빨강 · 비침 차례
        self.assertEqual(seen, [(16, 16, 32, False), (32, 32, 32, False), (256, 256, 32, True)])
        with self.assertRaises(winapp.BuildError):
            winapp.ico([b"not a png"])
        shipped = (ROOT / "win" / winapp.ICON).read_bytes()
        self.assertEqual(struct.unpack("<HHH", shipped[:6]), (0, 1, len(winapp.ICON_SIZES)))

    def test_the_installer_script_agrees_with_the_code(self):
        script = (ROOT / "win" / winapp.SCRIPT).read_text(encoding="utf-8")
        self.assertIn(f'!define RUNNING "{win.RUNNING}"', script)                    # 켜져 있는 가닥을 알아보는 이름
        self.assertIn(f'!define LAUNCH "{winapp.LAUNCH}"', script)
        self.assertIn(f'!define FOLDER "{winapp.FOLDER}"', script)
        for words in ("RequestExecutionLevel user", "Unicode true", 'MUI_LANGUAGE "Korean"', "$LOCALAPPDATA\\Programs\\${FOLDER}",
                      "pythonw.exe", "WriteUninstaller", 'IfFileExists "$INSTDIR\\${MARK}"'):
            self.assertIn(words, script)
        self.assertNotIn(".gadak", script.split('Section "Uninstall"')[1].split("SectionEnd")[0].replace("%USERPROFILE%\\.gadak", ""))
        self.assertIn("--app", winapp.LAUNCH)
        self.assertIn("utf8", winapp.LAUNCH)              # 한국어 Windows의 기본 글자표(cp949)로 파일을 읽지 않게

    def test_how_the_installer_tool_is_called(self):
        exe = self.file("nsis", "makensis.exe")
        with mock.patch.dict(os.environ, {"GADAK_MAKENSIS": str(exe), "GADAK_WINE": "/opt/wine/bin/wine"}):
            with mock.patch.object(win, "WINDOWS", False):
                self.assertEqual(winapp.find_makensis(), ["/opt/wine/bin/wine", str(exe)])       # Windows가 아니면 Wine으로
            with as_windows():
                self.assertEqual(winapp.find_makensis(), [str(exe)])
        with mock.patch.dict(os.environ, {"GADAK_MAKENSIS": str(self.tmp / "none.exe")}):
            self.assertEqual(winapp.find_makensis(), [])
            with self.assertRaises(winapp.BuildError) as caught:
                winapp.installer(self.tmp)
        self.assertIn("GADAK_MAKENSIS", str(caught.exception))

    def test_the_installer_is_built_in_a_plain_folder_and_then_named(self):
        folder, seen = self.stage(), {}

        def run(command, cwd=None, **_kwargs):
            seen.update(command=command, files=sorted(p.name for p in Path(cwd).iterdir()),
                        script=(Path(cwd) / winapp.SCRIPT).read_text(encoding="utf-8")[:40])
            (Path(cwd) / winapp.SETUP).write_bytes(b"MZ")
            return types.SimpleNamespace(returncode=0, stdout="", stderr="")

        with mock.patch.object(winapp, "find_makensis", return_value=["wine", "C:/nsis/makensis.exe"]), \
                mock.patch.object(winapp.subprocess, "run", run):
            target = winapp.installer(folder, self.tmp / "dist")
        self.assertEqual((target.name, target.read_bytes()), (f"가닥-{config.VERSION}-windows-x64-설치.exe", b"MZ"))
        self.assertEqual(seen["files"], [winapp.SCRIPT, "stage"])
        self.assertEqual(seen["command"], ["wine", "C:/nsis/makensis.exe", "/INPUTCHARSET", "UTF8", "/V2", f"/DVERSION={config.VERSION}",
                                           f"/DLAUNCH={winapp.LAUNCH}", f"/DOUTFILE={winapp.SETUP}", winapp.SCRIPT])


if __name__ == "__main__":
    unittest.main()
