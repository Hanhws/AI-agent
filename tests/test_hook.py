import importlib.util
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "tests" / "fixtures"

_spec = importlib.util.spec_from_file_location("gadak_hook", ROOT / "cursor-hooks" / "gadak-hook.py")
hook = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(hook)


def load(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


class CursorNormalizeTest(unittest.TestCase):
    def setUp(self):
        self.events = [hook.normalize(p) for p in load("cursor_payloads.json")]

    def test_kinds_follow_the_turn(self):
        self.assertEqual([e["kind"] for e in self.events], ["prompt", "edit", "edit", "answer", "stop"])

    def test_same_turn_shares_ids(self):
        self.assertEqual({(e["site"], e["chat_id"], e["message_ref"]) for e in self.events},
                         {("cursor", "conv-demo-1", "gen-1")})
        self.assertEqual(self.events[0]["project"], "nba-analysis")

    def test_prompt_and_answer_text(self):
        self.assertEqual(self.events[0]["text"], "식 이름만 바꿔 줘. score를 rating으로.")
        self.assertIn("선 굵기", self.events[3]["text"])

    def test_edit_keeps_before_and_after(self):
        self.assertEqual(self.events[1]["edits"], [
            {"file": "/Users/demo/dev/nba-analysis/model.py", "old": "def score(", "new": "def rating("}
        ])

    def test_user_email_is_not_forwarded(self):
        self.assertNotIn("demo@example.com", json.dumps(self.events, ensure_ascii=False))


class ClaudeCodeNormalizeTest(unittest.TestCase):
    def setUp(self):
        self.events = [hook.normalize(p) for p in load("claude_code_payloads.json")]

    def test_only_edit_tools_become_events(self):
        self.assertIsNone(self.events[1])
        self.assertEqual([e["kind"] for e in self.events if e], ["prompt", "edit", "answer"])

    def test_ids_and_project(self):
        prompt = self.events[0]
        self.assertEqual((prompt["site"], prompt["chat_id"], prompt["message_ref"], prompt["project"]),
                         ("claude-code", "sess-demo-1", "prm-1", "nba-analysis"))

    def test_edit_and_answer(self):
        self.assertEqual(self.events[2]["edits"][0]["new"], "alpha=0.5")
        self.assertEqual(self.events[3]["text"], "alpha를 0.5로 낮췄어요.")

    def test_write_tool_has_no_before(self):
        event = hook.normalize({
            "session_id": "s", "prompt_id": "p", "cwd": "/x/proj", "hook_event_name": "PostToolUse",
            "tool_name": "Write", "tool_input": {"file_path": "/x/proj/a.py", "content": "print(1)"},
        })
        self.assertEqual(event["edits"], [{"file": "/x/proj/a.py", "old": None, "new": "print(1)"}])


class UnknownPayloadTest(unittest.TestCase):
    def test_ignored(self):
        self.assertIsNone(hook.normalize({"hello": "world"}))
        self.assertIsNone(hook.normalize(["not", "an", "object"]))
        self.assertIsNone(hook.normalize({"conversation_id": "c", "hook_event_name": "beforeReadFile"}))


class MainTest(unittest.TestCase):
    def run_main(self, payload, sent=True, env=None):
        stdout = io.StringIO()
        with mock.patch.object(hook.sys, "stdin", io.StringIO(json.dumps(payload))), \
                mock.patch.object(hook.sys, "stdout", stdout), \
                mock.patch.object(hook, "send", return_value=sent) as send, \
                mock.patch.dict(hook.os.environ, env or {}, clear=False):
            code = hook.main()
        return code, stdout.getvalue(), send

    def test_cursor_prompt_hook_answers_continue(self):
        code, out, send = self.run_main(load("cursor_payloads.json")[0])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out), {"continue": True})
        send.assert_called_once()

    def test_claude_code_hook_prints_nothing(self):
        for payload in load("claude_code_payloads.json"):
            code, out, _ = self.run_main(payload)
            self.assertEqual((code, out), (0, ""))

    def test_engine_internal_calls_are_skipped(self):
        code, out, send = self.run_main(load("claude_code_payloads.json")[0], env={"GADAK_INTERNAL": "1"})
        self.assertEqual((code, out), (0, ""))
        send.assert_not_called()

    def test_spools_when_backend_is_down(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(hook, "HOME", Path(tmp)):
            code, _, _ = self.run_main(load("cursor_payloads.json")[3], sent=False)
            lines = (Path(tmp) / "spool.jsonl").read_text(encoding="utf-8").splitlines()
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(lines[0])["kind"], "answer")

    def test_broken_input_does_not_fail(self):
        with mock.patch.object(hook.sys, "stdin", io.StringIO("not json")):
            self.assertEqual(hook.main(), 0)


if __name__ == "__main__":
    unittest.main()
