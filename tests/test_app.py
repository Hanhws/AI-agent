import io
import json
import os
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from backend import store
from backend.app import create_app
from tests.test_sources import CHATGPT_EXPORT, CLAUDE_EXPORT

ROOT = Path(__file__).resolve().parent.parent
KINDS = {"missing", "unasked", "yours", "branch", "open", "check", "topic", "repeat", "handoff", "next"}


class AppTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        base = Path(self.tmp.name)
        self.cursor_home = base / "cursor"
        env = mock.patch.dict(os.environ, {
            "GADAK_CLAUDE_PROJECTS": str(base / "claude"), "GADAK_CODEX_HOME": str(base / "codex"),
            "GADAK_CURSOR_HOME": str(self.cursor_home),
        })
        env.start()
        self.addCleanup(env.stop)
        app = create_app(db_path=base / "gadak.db", engine=None)
        self.rt = app.config["GADAK"]
        self.client = app.test_client()

    def event(self, kind, ref="g1", **extra):
        body = {"site": "cursor", "project": "환율 알리미", "chat_id": "conv-1", "message_ref": ref, "kind": kind}
        body.update(extra)
        self.assertEqual(self.client.post("/events", json=body).status_code, 200)

    def turn(self, ref="g1", user="임계값만 바꿔 줘", ai="바꿨어요."):
        self.event("prompt", ref, text=user)
        self.event("answer", ref, text=ai)

    def view(self, project="환율 알리미"):
        return self.client.get(f"/projects/{project}/view").get_json()

    def test_the_window_page_and_its_files(self):
        page = self.client.get("/")
        self.assertEqual(page.status_code, 200)
        html = page.get_data(as_text=True)
        for path in ("ui/tokens.css", "ui/gadak.css", "ui/view.js", "ui/map.js", "ui/side.js", "ui/nudge.js",
                     "ui/rail.js", "ui/mark.js", "web/app.css", "web/app.js"):
            self.assertIn(path, html)
            with self.client.get("/" + path) as response:
                self.assertEqual(response.status_code, 200, path)
        self.assertNotIn("<textarea", html)   # 가닥은 대답하지 않아요: 입력창이 없어요
        self.assertEqual(self.client.get("/data/other.json").status_code, 404)

    def test_demo_data_is_made_up_and_consistent(self):
        with self.client.get("/data/demo_conversations.json") as response:
            data = response.get_json()
        for scenario in data["scenarios"].values():
            turns = [t for chat in scenario["chats"] for t in chat["turns"]]
            ids = {t["id"] for t in turns}
            self.assertEqual(len(ids), len(turns))
            self.assertEqual(sum(1 for chat in scenario["chats"] if chat.get("active")), 1)
            for t in turns:
                self.assertIn(t["depth"], (0, 1, 2))
                self.assertTrue(t["title"] and t["user"] and t["ai"])
                self.assertTrue(t.get("ref") is None or t["ref"] in ids)
                for part in t.get("parts", []):
                    self.assertIn(part["type"], ("q", "task", "rev"))
                for item in t.get("todo", []):
                    self.assertIn(item["kind"], KINDS)
                    self.assertTrue(item["text"] and item["why"] and item["btn"])
                    self.assertTrue(item.get("prompt") or item.get("pop") or item.get("effect"))

    def test_status_changes_when_something_arrives(self):
        before = self.client.get("/status").get_json()
        self.assertEqual((before["classify"]["engine"], before["sync"]["phase"]), ("none", "idle"))
        self.turn()
        after = self.client.get("/status").get_json()
        self.assertGreater(after["rev"], before["rev"])
        self.assertEqual(list(self.rt.classifier.queue), ["conv-1"])   # 답이 끝난 턴은 정리 줄에 서요

    def test_view_carries_the_start_and_the_full_text_is_fetched(self):
        self.turn(ai="가" * 3000)
        (turn,) = self.view()["chats"][0]["turns"]
        self.assertTrue(turn["long"])
        self.assertEqual(len(turn["ai"]), store.CLIP_AI + 1)
        full = self.client.get(f"/turns/{turn['id']}").get_json()["turn"]
        self.assertEqual(len(full["ai"]), 3000)
        self.assertNotIn("long", full)
        self.assertEqual(self.client.get("/turns/none").status_code, 404)

    def test_projects_list_recent_first(self):
        self.turn()
        self.event("prompt", project="nba-analysis", chat_id="conv-2", text="나중 질문")
        rows = self.client.get("/projects").get_json()["projects"]
        self.assertEqual({r["id"]: (r["chats"], r["turns"]) for r in rows}, {"환율 알리미": (1, 1), "nba-analysis": (1, 1)})

    def test_search_puts_decisions_first(self):
        self.turn("g1", "임계값은 얼마가 좋아?", "1,380원이 무난해요.")
        self.turn("g2", "그럼 임계값 1,380원으로 하자", "정했어요.")
        self.turn("g3", "알림 문구도 봐 줘", "봤어요.")
        conn = self.rt.connect()
        rows = store.chat_turns(conn, "conv-1")
        with conn:
            store.set_classification(conn, rows[1]["id"], title="임계값 정함", depth=0, dec="임계값 1,380원")
        conn.close()
        hits = self.client.get("/projects/환율 알리미/search?q=임계값").get_json()["hits"]
        self.assertEqual([h["id"] for h in hits], [rows[1]["id"], rows[0]["id"]])
        self.assertIn("임계값", hits[0]["snip"])
        self.assertEqual(self.client.get("/projects/환율 알리미/search?q=").get_json()["hits"], [])
        self.assertEqual(self.client.get("/projects/환율 알리미/search?q=100%25").get_json()["hits"], [])

    def test_item_state_is_kept(self):
        self.turn()
        turn_id = self.view()["chats"][0]["turns"][0]["id"]
        item = f"{turn_id}:p0"
        self.assertEqual(self.client.patch(f"/items/{item}", json={"state": "later"}).status_code, 200)
        self.assertEqual(self.view()["itemStates"], {item: "later"})
        self.assertEqual(self.client.patch(f"/items/{item}", json={"state": "gone"}).status_code, 400)
        self.assertEqual(self.client.patch(f"/items/{item}", data="state=done").status_code, 415)

    def test_import_export_files(self):
        both = json.dumps(CLAUDE_EXPORT + CHATGPT_EXPORT, ensure_ascii=False).encode("utf-8")
        packed = io.BytesIO()
        with zipfile.ZipFile(packed, "w") as archive:
            archive.writestr("conversations.json", both)
        first = self.client.post("/import", data=packed.getvalue(), content_type="application/zip")
        self.assertEqual((first.status_code, first.get_json()), (200, {"chats": 2, "turns": 3}))
        again = self.client.post("/import", data=both, content_type="application/json")
        self.assertEqual(again.get_json(), {"chats": 2, "turns": 3})
        chats = self.view(store.NO_PROJECT)["chats"]
        self.assertEqual(sorted((c["site"], c["title"], len(c["turns"])) for c in chats),
                         [("chatgpt", "발표 대본", 1), ("claude", "보고서 목차", 2)])
        self.assertEqual(self.client.post("/import", data=b"[]", content_type="application/json").status_code, 400)
        self.assertEqual(self.client.post("/import", data=both, content_type="text/plain").status_code, 415)

    def test_sources_and_connecting_cursor(self):
        rows = self.client.get("/sources").get_json()["sources"]
        self.assertEqual([(r["key"], r["mode"]) for r in rows],
                         [("claude-code", "auto"), ("codex", "auto"), ("cursor", "connect"), ("export", "file")])
        self.assertFalse(rows[2]["connected"])
        done = self.client.post("/sources/cursor/connect", json={})
        self.assertEqual((done.status_code, done.get_json()), (200, {"ok": True}))
        hooks = json.loads((self.cursor_home / "hooks.json").read_text(encoding="utf-8"))
        self.assertEqual(hooks["hooks"]["beforeSubmitPrompt"], [{"command": "sh hooks/gadak.sh"}])
        self.assertTrue((self.cursor_home / "hooks" / "gadak.sh").exists())
        self.assertTrue(self.client.get("/sources").get_json()["sources"][2]["connected"])
        self.assertEqual(self.client.post("/sources/cursor/connect", json={}).get_json(), {"ok": True, "already": True})

    def test_an_existing_cursor_config_is_not_overwritten(self):
        self.cursor_home.mkdir(parents=True)
        mine = '{"version": 1, "hooks": {"stop": [{"command": "./my-own.sh"}]}}'
        (self.cursor_home / "hooks.json").write_text(mine, encoding="utf-8")
        refused = self.client.post("/sources/cursor/connect", json={})
        self.assertEqual(refused.status_code, 409)
        self.assertFalse(refused.get_json()["ok"])
        self.assertEqual((self.cursor_home / "hooks.json").read_text(encoding="utf-8"), mine)

    def test_classify_requests_and_pause(self):
        self.turn()
        self.rt.classifier.queue.clear()
        status = self.client.post("/classify", json={"chats": ["conv-1", "conv-1"]}).get_json()
        self.assertEqual((status["queued"], status["paused"]), (1, False))
        self.assertTrue(self.client.post("/classify", json={"pause": True}).get_json()["paused"])
        self.assertFalse(self.client.post("/classify", json={"pause": False}).get_json()["paused"])


if __name__ == "__main__":
    unittest.main()
