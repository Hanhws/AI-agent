import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

from backend import store
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
        self.assertEqual(turn["files"], ["model.py", "plot.py"])  # 작업 폴더 기준 경로로 보여요

    def test_claude_code_events_become_one_turn(self):
        self.send(events("claude_code_payloads.json"))
        (turn,) = self.view()["chats"][0]["turns"]
        self.assertEqual((turn["user"], turn["ai"]), ("alpha를 0.5로 낮춰 줘", "alpha를 0.5로 낮췄어요."))
        self.assertEqual(turn["files"], ["model.py"])

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
        self.assertEqual(turn["files"], ["model.py"])

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



class ScratchFolderTest(unittest.TestCase):
    SCRATCH = "/Users/demo/Library/Application Support/Claude/scratch-workspaces/a/b/scratch-2026-10-06-a1a600"

    def test_scratch_folders_become_one_project_even_in_an_old_db(self):
        self.assertEqual(store.folder_project(self.SCRATCH), store.LOOSE_PROJECT)
        self.assertEqual(store.folder_project("/Users/demo/dev/가닥"), "가닥")
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "gadak.db"
            conn = store.connect(db)
            store.upsert_chat(conn, project="scratch-2026-10-06-a1a600", chat_id="c1", site="claude-code", cwd=self.SCRATCH)
            conn.execute("PRAGMA user_version = 6")
            conn.commit()
            conn.close()
            conn = store.connect(db)   # 예전 DB를 다시 열면 옮겨져요
            self.assertEqual(store.chat_row(conn, "c1")["project_id"], store.LOOSE_PROJECT)
            conn.close()


class ProjectColorTest(unittest.TestCase):
    def test_first_projects_never_share_a_color(self):
        with tempfile.TemporaryDirectory() as tmp:
            conn = store.connect(Path(tmp) / "gadak.db")
            names = ["etc", "폴더 없는 대화", "가닥", "SNU KDT 데이터베이스", "SNU KDT AI응용", "토익"]
            for i, name in enumerate(names):
                store.upsert_chat(conn, project=name, chat_id=f"c{i}", site="claude")
            colors = [store.project_color(conn, r["id"]) for r in conn.execute("SELECT id FROM projects")]
            self.assertEqual(len(set(colors)), len(names))
            self.assertNotIn("#8C8C8C", colors)   # 회색은 곁길 몫
            conn.close()


class ProvisionalTitleTest(unittest.TestCase):
    def test_first_clause_without_list_number(self):
        self.assertEqual(store.provisional_title("1. 포스터가 뭔가 덜 역동적이네. 데이터가 적어서"), "포스터가 뭔가 덜 역동적이네.")
        self.assertEqual(store.provisional_title("색 겹치는 거 project_color 고쳐주고, 지금 역도"), "색 겹치는 거…")
        self.assertEqual(store.provisional_title("짧은 질문"), "짧은 질문")
        self.assertEqual(store.provisional_title("  \n"), "(질문 없음)")


if __name__ == "__main__":
    unittest.main()
