import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

from backend.app import create_app

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "tests" / "fixtures"

_spec = importlib.util.spec_from_file_location("gadak_hook", ROOT / "cursor-hooks" / "gadak-hook.py")
hook = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(hook)


def events(name):
    payloads = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
    return [e for e in (hook.normalize(p) for p in payloads) if e]


class BackendTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.client = create_app(db_path=Path(self.tmp.name) / "test.db").test_client()

    def send(self, batch):
        for event in batch:
            self.assertEqual(self.client.post("/events", json=event).status_code, 200)

    def view(self, project="nba-analysis"):
        return self.client.get(f"/projects/{project}/view").get_json()

    def test_cursor_events_become_one_turn(self):
        self.send(events("cursor_payloads.json"))
        chats = self.view()["chats"]
        self.assertEqual(len(chats), 1)
        self.assertEqual((chats[0]["site"], chats[0]["id"]), ("cursor", "conv-demo-1"))
        (turn,) = chats[0]["turns"]
        self.assertEqual(turn["user"], "식 이름만 바꿔 줘. score를 rating으로.")
        self.assertIn("선 굵기", turn["ai"])
        self.assertEqual(turn["messageRef"], "gen-1")
        self.assertEqual(turn["files"], [
            "/Users/demo/dev/nba-analysis/model.py", "/Users/demo/dev/nba-analysis/plot.py",
        ])

    def test_claude_code_events_become_one_turn(self):
        self.send(events("claude_code_payloads.json"))
        (turn,) = self.view()["chats"][0]["turns"]
        self.assertEqual((turn["user"], turn["ai"]), ("alpha를 0.5로 낮춰 줘", "alpha를 0.5로 낮췄어요."))
        self.assertEqual(turn["files"], ["/Users/demo/dev/nba-analysis/model.py"])

    def test_resending_the_same_events_does_not_duplicate(self):
        batch = events("cursor_payloads.json")
        self.send(batch)
        self.send(batch)
        (turn,) = self.view()["chats"][0]["turns"]
        self.assertEqual(turn["ai"].count("score를 rating으로 바꿨어요"), 1)
        self.assertEqual(len(turn["files"]), 2)

    def test_two_prompts_make_two_turns_in_order(self):
        first = events("cursor_payloads.json")
        second = [dict(e, message_ref="gen-2") for e in first]
        self.send(first + second)
        turns = self.view()["chats"][0]["turns"]
        self.assertEqual([t["messageRef"] for t in turns], ["gen-1", "gen-2"])

    def test_event_without_ref_joins_the_open_turn(self):
        prompt, edit = events("claude_code_payloads.json")[:2]
        self.send([prompt, dict(edit, message_ref=None)])
        (turn,) = self.view()["chats"][0]["turns"]
        self.assertEqual(turn["files"], ["/Users/demo/dev/nba-analysis/model.py"])

    def test_turns_endpoint_overwrites_the_same_message(self):
        body = {
            "project": "빅데이터핀테크응용ai",
            "chat": {"id": "c2", "title": "가닥 고도화", "site": "claude"},
            "turn": {"user": "질문", "ai": "답", "messageRef": "msg-41", "edited_files": ["index.html"]},
        }
        first = self.client.post("/turns", json=body).get_json()["turn"]
        body["turn"]["ai"] = "고친 답"
        second = self.client.post("/turns", json=body).get_json()["turn"]
        self.assertEqual(first["id"], second["id"])
        (turn,) = self.view("빅데이터핀테크응용ai")["chats"][0]["turns"]
        self.assertEqual((turn["ai"], turn["files"]), ("고친 답", ["index.html"]))

    def test_korean_project_name_matches_in_either_unicode_form(self):
        import unicodedata
        decomposed = unicodedata.normalize("NFD", "가닥")
        prompt = dict(events("cursor_payloads.json")[0], project=decomposed)
        self.send([prompt])
        for name in ("가닥", decomposed):
            response = self.client.get(f"/projects/{name}/view")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.get_json()["project"]["id"], "가닥")

    def test_bad_event_is_rejected(self):
        self.assertEqual(self.client.post("/events", json={"kind": "prompt"}).status_code, 400)

    def test_only_local_hosts_and_json_posts(self):
        self.assertEqual(self.client.get("/health", headers={"Host": "evil.example"}).status_code, 403)
        self.assertEqual(self.client.post("/events", data="kind=prompt").status_code, 415)
        self.assertEqual(self.client.get("/health").status_code, 200)

    def test_unknown_project_is_404(self):
        self.assertEqual(self.client.get("/projects/none/view").status_code, 404)


if __name__ == "__main__":
    unittest.main()
