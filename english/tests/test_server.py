import contextlib
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from server.app import MAX_EVENTS, create_app

A, B = "a" * 32, "b" * 32
DAY = "2026-10-04"
SECRET = "환율 알리미 비밀 계획"


def event(seq, name, **fields):
    return {"seq": seq, "day": DAY, "name": name, "fields": fields}


class ServerTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = Path(self.tmp.name) / "usage.db"
        self.client = create_app(db_path=self.db, token="key").test_client()

    def send(self, install, *events, **more):
        return self.client.post("/v1/events", json=dict({"v": 1, "install": install, "app": "0.1.0", "events": list(events)}, **more))

    def stats(self, query=""):
        return self.client.get("/v1/stats" + query, headers={"Authorization": "Bearer key"}).get_json()

    def stored(self):
        with contextlib.closing(sqlite3.connect(self.db)) as conn:
            return conn.execute("SELECT install, seq, name, fields_json, app FROM events ORDER BY install, seq").fetchall()

    def test_only_listed_values_are_stored(self):
        got = self.send(A, event(1, "ui", what="search", query=SECRET), event(2, "ui", what=SECRET),
                        event(3, "made_up", x=1), {"seq": 4, "day": SECRET, "name": "ui", "fields": {"what": "search"}},
                        {"seq": "5", "day": DAY, "name": "ui", "fields": {"what": "search"}}, SECRET).get_json()
        self.assertEqual(got, {"stored": 1, "dropped": 5})
        self.assertEqual(self.stored(), [(A, 1, "ui", '{"what": "search"}', "0.1.0")])
        self.assertNotIn(SECRET, json.dumps(self.stored(), ensure_ascii=False))

    def test_sending_the_same_batch_again_does_not_double_count(self):
        for _ in range(2):
            self.send(A, event(1, "ui", what="search"), event(2, "ui", what="search"))
        self.assertEqual(self.stats()["ui"], [{"what": "search", "count": 2}])

    def test_bad_requests(self):
        self.assertEqual(self.send("not-an-id", event(1, "ui", what="search")).status_code, 400)
        self.assertEqual(self.send(A.upper(), event(1, "ui", what="search")).status_code, 400)
        self.assertEqual(self.client.post("/v1/events", json={"install": A, "events": "x"}).status_code, 400)
        self.assertEqual(self.client.post("/v1/events", data="install=" + A).status_code, 400)
        many = [event(n, "ui", what="search") for n in range(MAX_EVENTS + 1)]
        self.assertEqual(self.send(A, *many).status_code, 400)
        self.assertEqual(self.send(A, event(1, "ui", what="search"), app=SECRET).status_code, 200)
        self.assertEqual(self.stored()[0][4], None)        # 판 번호처럼 생기지 않은 글은 버려요

    def test_stats_need_the_key(self):
        self.assertEqual(self.client.get("/v1/stats").status_code, 403)
        self.assertEqual(self.client.get("/v1/stats", headers={"Authorization": "Bearer wrong"}).status_code, 403)
        open_server = create_app(db_path=self.db, token="").test_client()   # 암호를 정하지 않으면 아무도 못 봐요
        self.assertEqual(open_server.get("/v1/stats", headers={"Authorization": "Bearer "}).status_code, 403)

    def test_forget_removes_only_that_install(self):
        self.send(A, event(1, "ui", what="search"), event(2, "ui", what="copy"))
        self.send(B, event(1, "ui", what="search"))
        self.assertEqual(self.client.post("/v1/forget", json={"install": A}).get_json(), {"deleted": 2})
        self.assertEqual([row[0] for row in self.stored()], [B])

    def test_summary(self):
        self.send(A,
                  event(1, "open", via="app", os="mac", engine="claude_cli", projects=3, chats=12, turns=90, chats_claude_code=10, chats_cursor=2),
                  event(2, "chat", chat="0" * 12, site="claude-code", turns=4, side=0, decided=0, in_project=1),
                  event(3, "chat", chat="0" * 12, site="claude-code", turns=20, side=5, decided=2, multi=1, files=3, in_project=1),   # 같은 대화가 자람
                  event(4, "chat", chat="1" * 12, site="cursor", turns=3, in_project=7),
                  event(5, "item", kind="missing", did="made", at="auto"), event(6, "item", kind="missing", did="shown", at="nudge"),
                  event(7, "item", kind="missing", did="run", at="nudge"), event(8, "item", kind="unasked", did="made", at="auto"),
                  event(9, "classify", turns=8, done=7, seconds=10), event(10, "classify", turns=8, done=8, seconds=6),
                  event(11, "check", missing=True, steps=3, calls=4, made=1, dropped=0, ended="finish", seconds=20, get_request=2, get_diff=1),
                  event(12, "check", unasked=True, steps=1, calls=2, made=0, dropped=1, ended="limit", seconds=10, get_diff=1),
                  event(13, "stop", where="classify", why="limit"), event(14, "ui", what="scope_all"), event(15, "ui", what="scope_all"))
        self.send(B, event(1, "open", via="browser", os="mac", engine="none", chats=1, chats_chatgpt=1))
        s = self.stats()
        self.assertEqual((s["installs"], s["events"]), (2, 16))
        self.assertEqual(s["days"], [{"day": DAY, "installs": 2, "events": 16}])
        self.assertEqual(s["opened"], {"via": {"app": 1, "browser": 1}, "os": {"mac": 2}, "engine": {"claude_cli": 1, "none": 1}})
        entrances = {e["site"]: (e["installs"], e["chats"]) for e in s["entrances"]}
        self.assertEqual((entrances["claude-code"], entrances["cursor"], entrances["chatgpt"], entrances["gemini"]),
                         ((1, 10), (1, 2), (1, 1), (0, 0)))
        chats = s["chats"]
        self.assertEqual(chats["count"], 2)                                  # 자란 대화는 마지막 모양만 세요
        self.assertEqual([b["count"] for b in chats["turns"]], [1, 0, 1, 0])
        self.assertEqual([b["count"] for b in chats["in_project"]], [1, 0, 1])
        self.assertEqual((chats["with_side"], chats["with_decision"], chats["side_turns"]), (0.5, 0.5, round(5 / 23, 3)))
        self.assertEqual(s["items"], [{"kind": "missing", "made": 1, "shown": 1, "run": 1, "later": 0, "close": 0},
                                      {"kind": "unasked", "made": 1, "shown": 0, "run": 0, "later": 0, "close": 0}])
        self.assertEqual(s["classify"], {"calls": 2, "turns": 16, "done": 15, "kept": 0.938, "seconds": 8.0})
        self.assertEqual((s["check"]["runs"], s["check"]["made"], s["check"]["made_share"], s["check"]["steps"]), (2, 1, 0.5, 2.0))
        self.assertEqual(s["check"]["tools"][:2], [{"tool": "get_request", "count": 2}, {"tool": "get_diff", "count": 2}])
        self.assertEqual((s["check"]["ended"], s["stops"]), ({"finish": 1, "limit": 1}, {"limit": 1}))
        self.assertEqual(s["ui"], [{"what": "scope_all", "count": 2}])

    def test_range_filter(self):
        self.send(A, {"seq": 1, "day": "2020-01-01", "name": "ui", "fields": {"what": "search"}})
        self.assertEqual((self.stats()["events"], self.stats("?days=7")["events"]), (1, 0))

    def test_page_and_tokens(self):
        with self.client.get("/") as page:
            self.assertIn("가닥 사용 기록", page.get_data(as_text=True))
        with self.client.get("/tokens.css") as css:
            self.assertEqual(css.status_code, 200)


if __name__ == "__main__":
    unittest.main()
