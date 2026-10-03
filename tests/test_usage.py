import json
import logging
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from werkzeug.serving import make_server

from backend import config, store, usage, usage_schema
from backend.agent import classify
from backend.app import create_app
from backend.runtime import Runtime
from server.app import create_app as create_server

SECRET = "환율 알리미 비밀 계획"   # 대화에서 나올 법한 글. 어디에도 실리면 안 돼요


class SchemaTest(unittest.TestCase):
    def test_only_listed_names_and_fields_survive(self):
        self.assertEqual(usage_schema.clean("ui", {"what": "scope_all", "title": SECRET}), {"what": "scope_all"})
        self.assertIsNone(usage_schema.clean("made_up", {"what": "scope_all"}))
        self.assertIsNone(usage_schema.clean(SECRET, {}))
        self.assertIsNone(usage_schema.clean("ui", "not a dict"))

    def test_numbers_are_capped_and_flags_are_flags(self):
        self.assertEqual(usage_schema.clean("classify", {"turns": 8, "done": 10 ** 9, "seconds": 3.9}),
                         {"turns": 8, "done": 50, "seconds": 3})
        self.assertEqual(usage_schema.clean("classify", {"turns": True, "done": "8", "seconds": -4}), {"seconds": 0})
        self.assertEqual(usage_schema.clean("connect", {"cursor": 1}), {})
        self.assertEqual(usage_schema.clean("connect", {"cursor": True}), {"cursor": True})

    def test_no_field_of_any_event_can_carry_text(self):
        """모든 이름의 모든 칸에 글을 넣어 봐요. 하나도 남으면 안 돼요."""
        for name, spec in usage_schema.EVENTS.items():
            for value in (SECRET, [SECRET], {"x": SECRET}, SECRET.encode()):
                cleaned = usage_schema.clean(name, dict({key: value for key in spec}, extra=value))
                self.assertEqual(cleaned, {}, name)

    def test_chat_tag_is_hex_only(self):
        for bad in ("가닥", "0123456789ab ", "0123456789AB", "0123456789abc", "<script>"):
            self.assertNotIn("chat", usage_schema.clean("chat", {"chat": bad, "turns": 3}))
        self.assertEqual(usage_schema.clean("chat", {"chat": "0123456789ab"})["chat"], "0123456789ab")


class UsageTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.conn = store.connect(self.base / "gadak.db")
        self.addCleanup(self.conn.close)
        none = mock.patch.object(config, "COLLECT_URL", "")   # 이 PC의 backend/.env에 서버 주소가 있어도 시험은 따로 돌아요
        none.start()
        self.addCleanup(none.stop)

    def serve(self):
        """받는 서버를 빈 포트에 잠깐 띄워요."""
        logging.getLogger("werkzeug").setLevel(logging.ERROR)
        app = create_server(db_path=self.base / "server.db", token="key")
        server = make_server("127.0.0.1", 0, app)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.shutdown)
        url = mock.patch.object(config, "COLLECT_URL", f"http://127.0.0.1:{server.server_port}")
        url.start()
        self.addCleanup(url.stop)
        return app.test_client()

    def stats(self, client):
        return client.get("/v1/stats", headers={"Authorization": "Bearer key"}).get_json()

    def test_nothing_is_asked_or_sent_without_a_server(self):
        self.assertEqual(usage.state(self.conn), {"configured": False, "share": "", "kept": 0, "waiting": 0, "sent": 0})
        usage.consent(self.conn, True)
        usage.record(self.conn, "ui", what="search")
        self.assertEqual(usage.send(self.conn), 0)

    def test_records_before_consent_stay_on_this_pc(self):
        client = self.serve()
        self.assertTrue(usage.record(self.conn, "ui", what="tab_dec"))          # 묻기 전
        self.assertFalse(usage.record(self.conn, "ui", what=SECRET))            # 표에 없는 값은 적지 않아요
        self.assertEqual(usage.send(self.conn), 0)
        usage.consent(self.conn, True)
        usage.record(self.conn, "ui", what="search")
        usage.record(self.conn, "item", kind="missing", did="run", at="nudge")
        self.assertEqual(usage.state(self.conn)["waiting"], 2)
        self.assertEqual(usage.send(self.conn), 2)
        self.assertEqual(usage.send(self.conn), 0)                               # 보낸 것은 다시 보내지 않아요
        got = self.stats(client)
        self.assertEqual((got["installs"], got["events"]), (1, 2))
        self.assertEqual(got["ui"], [{"what": "search", "count": 1}])           # 묻기 전의 tab_dec은 가지 않았어요
        self.assertEqual(usage.state(self.conn), {"configured": True, "share": "yes", "kept": 3, "waiting": 0, "sent": 2})

    def test_turning_it_off_stops_sending(self):
        self.serve()
        usage.consent(self.conn, True)
        usage.consent(self.conn, False)
        usage.record(self.conn, "ui", what="search")
        self.assertEqual(usage.send(self.conn), 0)

    def test_forget_deletes_what_the_server_has(self):
        client = self.serve()
        usage.consent(self.conn, True)
        usage.record(self.conn, "ui", what="search")
        usage.send(self.conn)
        gone = usage.forget(self.conn)
        self.assertEqual((gone["deleted"], gone["share"], gone["waiting"]), (1, "no", 0))
        self.assertEqual(self.stats(client)["events"], 0)
        self.assertIsNone(store.setting(self.conn, "usage.install"))            # 다시 켜면 새 번호로 시작해요

    def test_forget_when_the_server_is_unreachable(self):
        with mock.patch.object(config, "COLLECT_URL", "http://127.0.0.1:9"):
            usage.consent(self.conn, True)
            gone = usage.forget(self.conn)
        self.assertEqual((gone["deleted"], gone["share"]), (None, "no"))
        self.assertIsNotNone(store.setting(self.conn, "usage.install"))         # 나중에 다시 지워 달라고 할 수 있게 남겨요

    def test_https_checks_stay_on(self):
        """인증서를 더 읽을 뿐, 확인을 끄지 않아요."""
        import ssl
        context = usage.tls()
        self.assertEqual((context.verify_mode, context.check_hostname), (ssl.CERT_REQUIRED, True))
        self.assertIs(usage.tls(), context)

    def test_what_is_sent_has_no_names_titles_or_paths(self):
        with self.conn:
            store.upsert_chat(self.conn, project=SECRET, chat_id="chat-secret-id", site="cursor", title=SECRET,
                              cwd="/Users/someone/" + SECRET)
            row = store.upsert_turn(self.conn, chat_id="chat-secret-id", message_ref="g1", user=SECRET, ai=SECRET, state="done")
            store.set_classification(self.conn, row["id"], title=SECRET, depth=0, dec=SECRET, seg=SECRET)
            store.add_file(self.conn, row["id"], "/Users/someone/" + SECRET + ".py")
        usage.consent(self.conn, True)
        usage.note_open(self.conn, "app", "claude_cli")
        usage.note_chat(self.conn, "chat-secret-id")
        sent = json.dumps(usage.recent(self.conn), ensure_ascii=False)
        for leak in (SECRET, "someone", "chat-secret-id", "g1"):
            self.assertNotIn(leak, sent)
        shape = next(e for e in usage.recent(self.conn) if e["name"] == "chat")["fields"]
        self.assertEqual({k: shape[k] for k in ("site", "turns", "decided", "segments", "files", "in_project")},
                         {"site": "cursor", "turns": 1, "decided": 1, "segments": 1, "files": 1, "in_project": 1})
        self.assertEqual(shape["chat"], usage.chat_tag(self.conn, "chat-secret-id"))

    def test_classifying_leaves_counts_only(self):
        class Engine:
            name = "fake"

            def complete_json(self, system, prompt, schema):
                turns = json.loads(prompt)["turns"]
                return {"turns": [{"id": t["id"], "title": SECRET, "depth": 0, "seg": None, "topic": None, "chose": False,
                                   "dec": None, "ref": None, "parts": [], "wide": False} for t in turns]}

        rt = Runtime(self.base / "gadak.db", engine=Engine())
        with self.conn:
            store.upsert_chat(self.conn, project="p", chat_id="c1", site="claude-code")
            for n in range(3):
                store.upsert_turn(self.conn, chat_id="c1", message_ref=f"g{n}", user=SECRET, ai=SECRET, state="done")
        self.assertEqual(rt.classifier.classify_chat(self.conn, "c1"), 3)
        events = usage.recent(self.conn)
        self.assertEqual([e["name"] for e in events], ["chat", "classify"])
        self.assertEqual({k: events[1]["fields"][k] for k in ("turns", "done")}, {"turns": 3, "done": 3})
        self.assertNotIn(SECRET, json.dumps(events, ensure_ascii=False))


class UsageRoutesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.client = create_app(db_path=Path(self.tmp.name) / "gadak.db", engine=None).test_client()

    def test_screen_can_only_record_clicks_and_item_actions(self):
        self.assertEqual(self.client.post("/usage", json={"name": "ui", "fields": {"what": "scope_all"}}).get_json(), {"ok": True})
        self.assertEqual(self.client.post("/usage", json={"name": "ui", "fields": {"what": SECRET}}).get_json(), {"ok": False})
        self.assertEqual(self.client.post("/usage", json={"name": "classify", "fields": {"turns": 3}}).status_code, 400)
        self.assertEqual(self.client.post("/usage", json={"name": "item", "fields": {"kind": "missing", "did": "run", "at": "list", "text": SECRET}}).get_json(), {"ok": True})
        events = self.client.get("/usage/recent").get_json()["events"]
        self.assertEqual([(e["name"], e["fields"]) for e in events],
                         [("item", {"kind": "missing", "did": "run", "at": "list"}), ("ui", {"what": "scope_all"})])

    def test_consent_route(self):
        self.assertEqual(self.client.get("/usage/state").get_json()["share"], "")
        self.assertEqual(self.client.post("/usage/consent", json={"share": True}).get_json()["share"], "yes")
        self.assertEqual(self.client.post("/usage/consent", json={"share": False}).get_json()["share"], "no")
        self.assertEqual(self.client.post("/usage/consent", json={"share": "yes"}).status_code, 400)


if __name__ == "__main__":
    unittest.main()
