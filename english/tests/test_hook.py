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


class KoreanFolderTest(unittest.TestCase):
    def test_project_name_is_normalized(self):
        import unicodedata
        payload = dict(load("cursor_payloads.json")[0],
                       workspace_roots=["/Users/demo/" + unicodedata.normalize("NFD", "가닥")])
        self.assertEqual(hook.normalize(payload)["project"], "가닥")


class UnknownPayloadTest(unittest.TestCase):
    def test_ignored(self):
        self.assertIsNone(hook.normalize({"hello": "world"}))
        self.assertIsNone(hook.normalize(["not", "an", "object"]))
        self.assertIsNone(hook.normalize({"conversation_id": "c", "hook_event_name": "beforeReadFile"}))


class MainTest(unittest.TestCase):
    def run_main(self, payload, sent=True, env=None, answer=None, args=()):
        """answer: 가닥이 자동 실행 물음(/auto/…)에 주는 답. None이면 가닥이 꺼져 있는 것."""
        stdout = io.StringIO()
        with mock.patch.object(hook.sys, "stdin", io.StringIO(json.dumps(payload))), \
                mock.patch.object(hook.sys, "stdout", stdout), \
                mock.patch.object(hook.sys, "argv", ["gadak-hook.py", *args]), \
                mock.patch.object(hook, "send", return_value=sent) as send, \
                mock.patch.object(hook, "ask", return_value=answer) as self.asked, \
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

    def test_cursor_stop_hands_back_what_gadak_wants_to_send(self):
        stop = load("cursor_payloads.json")[4]
        code, out, send = self.run_main(stop, answer={"send": "notify.py는 원래대로 되돌려 줘."})
        self.assertEqual((code, json.loads(out)), (0, {"followup_message": "notify.py는 원래대로 되돌려 줘."}))
        send.assert_called_once()                       # 턴이 끝났다는 것도 그대로 알려요
        path, body, timeout = self.asked.call_args[0]
        self.assertEqual((path, body["site"], body["chat_id"], body["message_ref"], body["again"]),
                         ("/auto/stop", "cursor", "conv-demo-1", "gen-1", False))
        self.assertGreater(timeout, body["wait"])       # 가닥이 기다리는 동안 hook도 기다려 줘요
        # 가닥이 보낸 글 때문에 이어진 턴에는 다시 보내지 않게 알려요
        self.run_main(dict(stop, loop_count=1), answer={"send": None})
        self.assertTrue(self.asked.call_args[0][1]["again"])

    def test_claude_code_stop_blocks_with_the_request(self):
        stop = next(p for p in load("claude_code_payloads.json") if p["hook_event_name"] == "Stop")
        code, out, send = self.run_main(stop, answer={"send": "되돌려 줘."}, args=["--auto"])
        self.assertEqual(json.loads(out), {"decision": "block", "reason": "되돌려 줘."})
        send.assert_not_called()                        # --auto: 대화는 기록 파일로 읽으니 이벤트는 안 보내요
        self.assertEqual(self.asked.call_args[0][1]["message_ref"], stop["prompt_id"])
        self.run_main(dict(stop, stop_hook_active=True), answer={"send": None}, args=["--auto"])
        self.assertTrue(self.asked.call_args[0][1]["again"])

    def test_a_new_chat_gets_the_summary_as_context(self):
        summary = "지난 대화에서 정한 것\n1. 텔레그램 봇"
        cursor = {"hook_event_name": "sessionStart", "conversation_id": "conv-2",
                  "workspace_roots": ["/Users/demo/dev/nba-analysis"]}
        _, out, _ = self.run_main(cursor, answer={"context": summary})
        self.assertEqual(json.loads(out), {"additional_context": summary})
        self.assertEqual(self.asked.call_args[0][:2], ("/auto/start", {
            "site": "cursor", "chat_id": "conv-2", "project": "nba-analysis", "source": None}))
        claude = {"hook_event_name": "SessionStart", "session_id": "sess-2", "cwd": "/x/nba-analysis", "source": "startup"}
        _, out, _ = self.run_main(claude, answer={"context": summary}, args=["--auto"])
        self.assertEqual(json.loads(out), {"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": summary}})

    def test_nothing_to_send_prints_nothing(self):
        stop = next(p for p in load("claude_code_payloads.json") if p["hook_event_name"] == "Stop")
        for answer in (None, {"send": None}, {"send": ""}):        # 가닥이 꺼져 있음 · 보낼 것 없음
            self.assertEqual(self.run_main(stop, answer=answer, args=["--auto"])[1], "")
        self.assertEqual(self.run_main({"hook_event_name": "SessionStart", "session_id": "s", "cwd": "/x/p"},
                                       answer={"context": None})[1], "")

    def test_broken_input_does_not_fail(self):
        with mock.patch.object(hook.sys, "stdin", io.StringIO("not json")):
            self.assertEqual(hook.main(), 0)


if __name__ == "__main__":
    unittest.main()
