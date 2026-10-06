import json
import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from backend import auto, sources, store
from backend.app import create_app
from tests.test_investigate import CHAT, NOTIFY_NEW, NOTIFY_OLD, PROJECT, Base, Engine, finish, item, labels, use

REVERT = "notify.py에서 “알림 문구” 부분은 내가 요청하지 않았어. 원래대로 되돌리고, “임계값” 변경만 남겨 줘."
EDITS = [{"file": "/work/fx/main.py", "old": "THRESHOLD = 1200", "new": "THRESHOLD = 1300"},
         {"file": "/work/fx/notify.py", "old": NOTIFY_OLD, "new": NOTIFY_NEW}]
FOUND = [use("get_diff"), finish(item("unasked", text="임계값만 요청했는데 알림 문구도 바뀌었어요",
                                      file="notify.py", asked="임계값", what="알림 문구"))]


class StopTest(Base):
    """턴이 끝날 때: 승인한 ‘요청 외 변경 되돌리기’만, 2단이 확인한 것만 가닥이 이어서 보내요."""

    def begin(self, steps=FOUND, wide=True, on=True):
        self.start(Engine(lambda p: labels(p, t1={"wide": wide}), steps))
        self.rt.classifier = self.clf           # auto가 정리를 재촉할 때 쓰는 일꾼
        self.chat()
        self.turn_id = self.turn("g1", "임계값만 1300으로 바꿔 줘", "main.py와 notify.py를 고쳤어요.", edits=EDITS)
        if on:
            auto.set_enabled(self.conn, "unasked", True)

    def stop(self, **body):
        return auto.on_stop(self.rt, self.conn, dict({"site": "cursor", "chat_id": CHAT}, **body))

    def test_nothing_is_sent_unless_the_kind_was_approved(self):
        self.begin(on=False)
        self.run_worker_after_request()
        self.assertEqual(self.stop(wait=5), {"send": None})
        self.assertEqual(store.view(self.conn, PROJECT)["auto"], {"unasked": False, "handoff": False})
        self.assertEqual(store.view(self.conn, PROJECT)["itemStates"], {})      # 한마디는 그대로 열려 있어요

    def run_worker_after_request(self):
        self.clf.request(CHAT)
        self.run_worker()

    def test_a_checked_unasked_change_is_sent_once_and_logged(self):
        self.begin()
        self.run_worker_after_request()
        sent = self.stop()
        self.assertEqual(sent, {"send": auto.SENT_BY + REVERT, "items": [self.turn_id + ":0"]})
        view = store.view(self.conn, PROJECT)
        self.assertEqual(view["itemStates"], {self.turn_id + ":0": "done"})
        self.assertEqual(view["chats"][0]["turns"][0]["todo"][0]["sent"], "auto")      # 장부에 ‘가닥이 보냄’
        self.assertEqual(view["auto"], {"unasked": True, "handoff": False})
        self.assertEqual(self.stop(), {"send": None})                                  # 같은 것을 두 번 보내지 않아요
        records = [(r["name"], json.loads(r["fields_json"])) for r in self.conn.execute("SELECT * FROM usage")]
        self.assertIn(("item", {"kind": "unasked", "did": "run", "at": "auto"}), records)

    def test_it_waits_for_the_check_to_finish(self):
        self.begin()
        self.assertEqual(self.stop(wait=0), {"send": None})                    # 아직 정리 전이고, 기다리지 말라고 했어요
        self.assertEqual(list(self.clf.queue), [CHAT])                         # 대신 그 대화의 정리를 앞에 세워요
        worker = threading.Thread(target=lambda: (time.sleep(0.3), self.work()))
        worker.start()
        began = time.time()
        sent = self.stop(wait=10)
        worker.join()
        self.assertEqual(sent["send"], auto.SENT_BY + REVERT)
        self.assertLess(time.time() - began, 5)

    def work(self):
        conn = self.rt.connect()
        try:
            for _ in range(20):
                if not self.clf.step(conn):
                    break
        finally:
            conn.close()

    def test_no_file_change_or_no_finding_means_nothing_to_send(self):
        self.begin(steps=[use("get_diff"), finish()])                          # 봤지만 요청 외 변경이 아니었어요
        self.run_worker_after_request()
        self.assertEqual(self.stop(wait=3), {"send": None})
        plain = self.turn("g2", "설명만 해 줘", "설명이에요.")                     # 파일이 안 바뀐 턴은 기다리지도 않아요
        began = time.time()
        self.assertEqual(self.stop(wait=10, message_ref="g2"), {"send": None})
        self.assertLess(time.time() - began, 1)
        self.assertEqual(self.row(plain)["classified"], 0)

    def test_it_never_answers_its_own_message(self):
        self.begin()
        self.run_worker_after_request()
        sent = self.stop()["send"]
        # Cursor는 가닥이 보낸 글을 새 질문으로 이어 가요. 그 턴에서 또 넓게 바뀌어도 다시 보내지 않아요
        self.turn("g2", sent, "되돌렸어요.", edits=[{"file": "/work/fx/notify.py", "old": NOTIFY_NEW, "new": NOTIFY_OLD}])
        began = time.time()
        self.assertEqual(self.stop(wait=10), {"send": None})
        self.assertLess(time.time() - began, 1)
        self.assertEqual(self.stop(again=True, wait=10), {"send": None})       # 도구가 ‘이어진 턴’이라고 알려 줄 때도

    def test_a_chat_taken_off_the_list_is_left_alone(self):
        self.begin()
        with self.conn:
            store.set_hidden(self.conn, [CHAT])
        self.clf.request(CHAT)
        self.run_worker()
        self.assertEqual(self.engine.calls, [])                                # 정리 호출도 쓰지 않아요
        self.assertEqual(self.stop(wait=5), {"send": None})
        with self.conn:
            store.set_hidden(self.conn, [CHAT], False)
        self.run_worker_after_request()
        self.assertEqual(self.stop()["send"], auto.SENT_BY + REVERT)           # 되돌리면 전처럼 돌아요

    def test_without_an_engine_it_does_not_wait(self):
        self.begin()
        self.rt.classifier = type(self.clf)(self.rt, None)
        began = time.time()
        self.assertEqual(self.stop(wait=10), {"send": None})
        self.assertLess(time.time() - began, 1)

    def test_a_turn_that_never_arrives_is_not_waited_for_long(self):
        self.begin()
        with mock.patch.object(auto, "ARRIVE", 0.5):
            began = time.time()
            self.assertEqual(self.stop(chat_id="no-such-chat", wait=10), {"send": None})
        self.assertLess(time.time() - began, 3)


class StartTest(Base):
    """새 대화가 시작될 때: 승인한 ‘이어 가기 요약’만, 같은 프로젝트의 지난 결정이 있을 때만 넣어요."""

    def begin(self, on=True):
        self.start(Engine())
        self.chat("old", title="환율 알리미 기획", created_at="2026-10-01T02:00:00Z")
        for n, dec in enumerate(("텔레그램 봇", "임계값 1,380원"), 1):
            turn_id = self.turn(f"o{n}", f"질문 {n}", chat_id="old", created_at=f"2026-10-01T02:0{n}:00Z")
            with self.conn:
                store.set_classification(self.conn, turn_id, title=f"정함 {n}", depth=0, dec=dec)
        if on:
            auto.set_enabled(self.conn, "handoff", True)

    def started(self, **body):
        return auto.on_start(self.conn, dict({"site": "claude-code", "chat_id": "new", "project": PROJECT, "source": "startup"}, **body))

    def test_the_summary_is_given_once_and_shown_as_sent(self):
        self.begin()
        context = self.started()["context"]
        self.assertEqual(context.splitlines()[1:3], ["1. 텔레그램 봇", "2. 임계값 1,380원"])
        self.assertIn("이어서 진행해 줘", context)
        self.assertEqual(self.started(), {"context": None})                    # 같은 대화에 두 번 넣지 않아요
        # 그 대화의 첫 턴이 들어오면 장부에 ‘가닥이 보냄’으로 보이고, 2단은 이어 가기를 다시 권하지 않아요
        self.chat("new", title="알림 봇 구현", created_at="2026-10-03T02:00:00Z")
        first = self.turn("n1", "봇 만들자", chat_id="new")
        self.clf.classify_chat(self.conn, "new")
        self.assertIsNone(self.row(first)["look"])
        chat = next(c for c in store.view(self.conn, PROJECT)["chats"] if c["id"] == "new")
        (note,) = chat["turns"][0]["todo"]
        self.assertEqual((note["kind"], note["sent"], note["state"], note["text"]),
                         ("handoff", "auto", "done", "지난 대화에서 정한 것 2개를 이 대화에 붙였어요"))
        self.assertEqual(note["pop"]["text"], context)

    def test_decisions_from_a_chat_taken_off_the_list_are_not_carried_over(self):
        self.begin()
        with self.conn:
            store.set_hidden(self.conn, ["old"])
        self.assertEqual(self.started(), {"context": None})

    def test_when_it_stays_quiet(self):
        self.begin(on=False)
        self.assertEqual(self.started(), {"context": None})                    # 승인하지 않았어요
        auto.set_enabled(self.conn, "handoff", True)
        self.assertEqual(self.started(source="resume"), {"context": None})     # 하던 대화를 다시 연 것
        self.assertEqual(self.started(chat_id="old"), {"context": None})       # 이미 시작한 대화
        self.assertEqual(self.started(project="다른 프로젝트"), {"context": None})   # 지난 결정이 없는 프로젝트
        self.assertEqual(self.started(project=None), {"context": None})
        self.assertIsNotNone(self.started()["context"])


class RoutesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        base = Path(self.tmp.name)
        self.settings = base / "claude" / "settings.json"
        env = mock.patch.dict(os.environ, {
            "GADAK_CLAUDE_PROJECTS": str(base / "projects"), "GADAK_CODEX_HOME": str(base / "codex"),
            "GADAK_CURSOR_HOME": str(base / "cursor"), "GADAK_CLAUDE_SETTINGS": str(self.settings),
        })
        env.start()
        self.addCleanup(env.stop)
        self.client = create_app(db_path=base / "gadak.db", engine=None).test_client()

    def test_turning_a_kind_on_and_off(self):
        self.assertEqual(self.client.get("/auto").get_json(),
                         {"auto": {"unasked": False, "handoff": False}, "ways": {"claude-code": False, "cursor": False}})
        on = self.client.post("/auto", json={"kind": "unasked", "on": True}).get_json()
        self.assertEqual(on["auto"], {"unasked": True, "handoff": False})
        self.assertEqual(self.client.post("/auto", json={"kind": "unasked", "on": False}).get_json()["auto"]["unasked"], False)
        for bad in ({"kind": "missing", "on": True}, {"kind": "unasked", "on": "yes"}, {}):   # 자동으로 할 수 있는 건 둘뿐
            self.assertEqual(self.client.post("/auto", json=bad).status_code, 400)

    def test_hooks_ask_and_get_a_quick_no(self):
        self.assertEqual(self.client.post("/auto/stop", json={"site": "cursor", "chat_id": "c", "wait": 30}).get_json(), {"send": None})
        self.assertEqual(self.client.post("/auto/start", json={"site": "cursor", "chat_id": "c", "project": "p"}).get_json(), {"context": None})
        self.assertEqual(self.client.post("/auto/stop", json={}).get_json(), {"send": None})

    def test_connecting_claude_code_adds_two_hooks_and_keeps_the_rest(self):
        self.settings.parent.mkdir(parents=True)
        mine = {"theme": "dark", "permissions": {"allow": ["Bash(ls:*)"]},
                "hooks": {"Stop": [{"hooks": [{"type": "command", "command": "./my-own.sh"}]}]}}
        self.settings.write_text(json.dumps(mine), encoding="utf-8")
        self.assertFalse(sources.claude_connected())
        self.assertEqual(self.client.post("/sources/claude-code/connect", json={}).get_json(), {"ok": True})
        now = json.loads(self.settings.read_text(encoding="utf-8"))
        self.assertEqual((now["theme"], now["permissions"]), ("dark", mine["permissions"]))
        self.assertEqual(now["hooks"]["Stop"][0], mine["hooks"]["Stop"][0])                 # 내 hook은 그대로
        ours = now["hooks"]["Stop"][1]["hooks"][0]
        self.assertTrue(ours["command"].endswith("gadak-hook.py' --auto") or ours["command"].endswith("gadak-hook.py --auto"))
        self.assertEqual((ours["type"], ours["timeout"]), ("command", 60))
        self.assertEqual(len(now["hooks"]["SessionStart"]), 1)
        self.assertEqual(json.loads((self.settings.parent / "settings.json.gadak-backup").read_text(encoding="utf-8")), mine)
        self.assertTrue(self.client.get("/auto").get_json()["ways"]["claude-code"])
        rows = self.client.get("/sources").get_json()["sources"]
        self.assertTrue(next(r for r in rows if r["key"] == "claude-code")["hooks"])
        self.assertEqual(self.client.post("/sources/claude-code/connect", json={}).get_json(), {"ok": True, "already": True})
        self.assertEqual(self.client.post("/sources/claude-code/disconnect", json={}).get_json(), {"ok": True})
        self.assertEqual(json.loads(self.settings.read_text(encoding="utf-8")), mine)       # 뗀 뒤에는 처음과 같아요
        self.assertEqual(self.client.post("/sources/claude-code/disconnect", json={}).get_json(), {"ok": True, "already": True})

    def test_a_settings_file_it_cannot_read_is_left_alone(self):
        self.settings.parent.mkdir(parents=True)
        for broken in ("{not json", '["a list"]', '{"hooks": {"Stop": "oops"}}'):
            self.settings.write_text(broken, encoding="utf-8")
            refused = self.client.post("/sources/claude-code/connect", json={})
            self.assertEqual(refused.status_code, 409)
            self.assertEqual(self.settings.read_text(encoding="utf-8"), broken)

    def test_no_settings_file_yet(self):
        self.assertEqual(self.client.post("/sources/claude-code/connect", json={}).get_json(), {"ok": True})
        self.assertEqual(sorted(json.loads(self.settings.read_text(encoding="utf-8"))["hooks"]), ["SessionStart", "Stop"])
        self.client.post("/sources/claude-code/disconnect", json={})
        self.assertEqual(json.loads(self.settings.read_text(encoding="utf-8")), {})


if __name__ == "__main__":
    unittest.main()
