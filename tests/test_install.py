import importlib.util
import io
import json
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "tests" / "fixtures"

_spec = importlib.util.spec_from_file_location("gadak_install", ROOT / "cursor-hooks" / "install.py")
install = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(install)


def run(argv):
    out = io.StringIO()
    with redirect_stdout(out):
        code = install.main(argv)
    return code, out.getvalue()


class InstallTest(unittest.TestCase):
    def test_print_only_points_at_the_hook(self):
        for target in ("cursor", "claude"):
            code, out = run([target])
            self.assertEqual(code, 0)
            self.assertIn(str(install.HOOK), json.dumps(json.loads(out), ensure_ascii=False))

    def test_project_install_writes_config_and_launcher(self):
        with tempfile.TemporaryDirectory() as tmp:
            code, _ = run(["cursor", tmp, "--project"])
            config = json.loads((Path(tmp) / ".cursor" / "hooks.json").read_text(encoding="utf-8"))
            launcher = (Path(tmp) / ".cursor" / "hooks" / "gadak.sh").read_text(encoding="utf-8")
        self.assertEqual(code, 0)
        self.assertEqual(config["version"], 1)
        self.assertEqual(set(config["hooks"]),
                         {"beforeSubmitPrompt", "afterAgentResponse", "afterFileEdit", "stop", "sessionStart"})
        self.assertEqual(config["hooks"]["stop"], [{"command": "sh .cursor/hooks/gadak.sh"}])
        self.assertIn(str(install.HOOK), launcher)
        self.assertNotIn("GADAK_DEBUG", launcher)

    def test_existing_config_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as tmp:
            existing = Path(tmp) / ".cursor" / "hooks.json"
            existing.parent.mkdir()
            existing.write_text('{"version": 1, "hooks": {}}', encoding="utf-8")
            code, out = run(["cursor", tmp, "--project"])
            self.assertEqual(existing.read_text(encoding="utf-8"), '{"version": 1, "hooks": {}}')
        self.assertEqual(code, 2)
        self.assertIn("덮어쓰지 않았어요", out)

    def test_launcher_runs_the_hook_from_the_project_root(self):
        """Cursor가 하듯 프로젝트 루트에서 실행기를 돌려요. 백엔드가 없으니 이벤트는 쌓여요."""
        payload = json.loads((FIXTURES / "cursor_payloads.json").read_text(encoding="utf-8"))[0]
        with tempfile.TemporaryDirectory() as project, tempfile.TemporaryDirectory() as home:
            run(["cursor", project, "--project", "--debug"])
            done = subprocess.run(
                ["sh", ".cursor/hooks/gadak.sh"], cwd=project, input=json.dumps(payload),
                capture_output=True, text=True,
                env={"PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin",
                     "GADAK_HOME": home, "GADAK_URL": "http://127.0.0.1:9"},
            )
            spooled = (Path(home) / "spool.jsonl").read_text(encoding="utf-8")
            raw = (Path(home) / "raw.jsonl").read_text(encoding="utf-8")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(json.loads(done.stdout), {"continue": True})
        self.assertEqual(json.loads(spooled)["kind"], "prompt")
        self.assertEqual(json.loads(raw)["hook_event_name"], "beforeSubmitPrompt")
        self.assertNotIn("demo@example.com", raw)


if __name__ == "__main__":
    unittest.main()
