import tempfile
import unittest
from pathlib import Path

from backend import store
from backend.agent import classify, rules
from backend.runtime import Runtime
from tests.test_classify import FakeEngine, titled


class RulesTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.rt = Runtime(Path(tmp.name) / "gadak.db", engine=None)
        self.conn = self.rt.connect()
        self.addCleanup(self.conn.close)

    def chat(self, chat_id, users, at="2026-10-01T00:00:00+00:00"):
        with self.conn:
            store.upsert_chat(self.conn, project="DB 수업", chat_id=chat_id, site="claude-code", title=chat_id, created_at=at)
            for n, user in enumerate(users, 1):
                store.upsert_turn(self.conn, chat_id=chat_id, message_ref=f"{chat_id}-{n}", user=user, ai=f"답 {n}", state="done")

    def classify(self, chat_id, **by_id):
        engine = FakeEngine(lambda p: titled(p, **by_id))
        classify.Classifier(self.rt, engine).classify_chat(self.conn, chat_id)
        return {r["seq"]: store.turn_items(self.conn, r["id"]) for r in store.chat_turns(self.conn, chat_id)}

    def test_a_long_side_path_without_a_decision_is_left_open(self):
        self.chat("c1", ["시작", "operand 뜻", "axiom 뜻", "semantic 뜻", "본론으로", "곁길", "돌아옴"])
        items = self.classify("c1", t2={"depth": 1}, t3={"depth": 1}, t4={"depth": 1}, t6={"depth": 1})
        (item,) = items[5]
        rows = store.chat_turns(self.conn, "c1")
        self.assertEqual((item["kind"], item["at"], item["btn"]), ("open", rows[1]["id"], "정리 받기"))
        self.assertEqual(item["text"], "‘제목 2’ 외 2개 곁길이 결론 없이 끝났어요")
        self.assertEqual(items[7], [])                                   # 곁길 하나로 뜻만 물은 것은 두어요

    def test_a_side_path_that_decided_or_postponed(self):
        self.chat("c1", ["시작", "A안 B안", "B안으로 하자", "본론", "곁길", "그건 나중에 하고 돌아가자"])
        items = self.classify("c1", t2={"depth": 1}, t3={"depth": 1, "dec": "B안"}, t4={"depth": 0}, t5={"depth": 1})
        self.assertEqual(items[4], [])                                   # 곁길에서 정했어요
        self.assertEqual([i["kind"] for i in items[6]], ["open"])        # 미루고 돌아왔어요

    def test_the_same_question_in_an_earlier_chat(self):
        self.chat("old", ["조인 개념 질문"], at="2026-10-01T00:00:00+00:00")
        self.classify("old", t1={"title": "JOIN 종류 설명"})
        self.chat("new", ["다시 조인", "다른 것"], at="2026-10-02T00:00:00+00:00")
        items = self.classify("new", t1={"title": "JOIN 종류 설명해"}, t2={"title": "GROUP BY"})
        (item,) = items[1]
        self.assertEqual((item["kind"], item["at"]), ("repeat", store.chat_turns(self.conn, "old")[0]["id"]))
        self.assertEqual(item["pop"]["text"], "답 1")
        self.assertEqual(items[2], [])

    def test_a_forked_copy_is_not_a_repeat(self):
        self.chat("old", ["조인 개념 질문"], at="2026-10-01T00:00:00+00:00")
        self.classify("old", t1={"title": "JOIN 종류 설명"})
        self.chat("fork", ["조인 개념 질문"], at="2026-10-02T00:00:00+00:00")
        self.assertEqual(self.classify("fork", t1={"title": "JOIN 종류 설명"})[1], [])

    def test_many_topics_suggest_a_transfer_once(self):
        self.chat("c1", [f"질문 {n}" for n in range(1, 7)])
        segs = {"segs": [{"from": "1", "name": "JOIN"}, {"from": "3", "name": "뷰"}, {"from": "5", "name": "집계"}]}
        engine = FakeEngine(lambda p: titled(p) if "state" in p else segs)
        clf = classify.Classifier(self.rt, engine)
        clf.classify_chat(self.conn, "c1")
        rows = store.chat_turns(self.conn, "c1")
        (item,) = store.turn_items(self.conn, rows[4]["id"])
        self.assertEqual((item["kind"], item["effect"], item["btn"]), ("topic", "transfer", "환승하기"))
        self.assertEqual(item["text"], "이 대화에 주제가 3개 쌓였어요 · 새 대화로 갈아탈까요?")
        with self.conn:
            self.assertFalse(rules.transfer(self.conn, "c1"))             # 대화마다 한 번

    def test_the_checker_keeps_rule_items(self):
        self.chat("c1", ["시작", "a", "b", "c", "본론"])
        self.classify("c1", t2={"depth": 1}, t3={"depth": 1}, t4={"depth": 1})
        turn = store.chat_turns(self.conn, "c1")[4]["id"]
        with self.conn:
            store.set_items(self.conn, turn, [{"kind": "missing", "text": "표가 빠졌어요"}])
        self.assertEqual([(i["id"][-2:], i["kind"]) for i in store.turn_items(self.conn, turn)], [(":0", "open"), (":1", "missing")])


if __name__ == "__main__":
    unittest.main()
