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

    def test_chats_carried_on_from_one_another_are_not_earlier_chats(self):
        """Claude Code에서 대화를 이어 받으면(fork) 새 대화가 앞 대화의 턴을 처음부터 그대로 담아서 만든 시각이 같아요.
        그런 대화끼리는 ‘지난 대화’가 아니에요. 같은 대화의 옆 턴과 짝지으면 반복 질문이 아닌 것이 반복 질문이 돼요."""
        day, talk = "2026-10-02T09:00:00+00:00", ["알림을 어디로 보낼까", "무료로 돼?", "연결했어"]
        names = {"t1": {"title": "알림 채널 확인"}, "t2": {"title": "텔레그램 봇 연결"}, "t3": {"title": "텔레그램 봇 연결"}}
        self.chat("first", talk, at=day)
        self.chat("carried", talk + ["알림 채널은 어디에 적지"], at=day)        # 이어 받은 대화: 앞의 세 턴은 그대로, 한 턴이 늘었어요
        for chat_id in ("first", "carried", "first"):                            # 어느 쪽을 먼저 정리해도, 다시 정리해도
            items = self.classify(chat_id, **names, t4={"title": "알림 채널 확인하기"})
            self.assertEqual([i["kind"] for turn in items.values() for i in turn], [], chat_id)
        # 정말 다른 대화(먼저 시작했고 이 턴을 담고 있지 않은 대화)의 비슷한 역은 그대로 잡아요
        self.chat("before", ["봇은 어떻게 붙이지"], at="2026-10-01T00:00:00+00:00")
        self.classify("before", t1={"title": "텔레그램 봇 연결"})
        self.chat("later", talk + ["또 물어볼게"], at="2026-10-05T00:00:00+00:00")   # 시각이 달라도 이 턴을 그대로 담은 대화는 빼요
        items = self.classify("later", **names, t4={"title": "다른 이야기"})
        at = {i["at"] for turn in items.values() for i in turn if i["kind"] == "repeat"}
        self.assertEqual(at, {store.chat_turns(self.conn, "before")[0]["id"]})

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

    def test_rule_items_ahead_paths_and_checker_items_share_a_turn(self):
        self.chat("c1", ["시작", "a", "b", "c", "본론"])
        self.classify("c1", t2={"depth": 1}, t3={"depth": 1}, t4={"depth": 1})
        turn = store.chat_turns(self.conn, "c1")[4]["id"]
        kinds = lambda: sorted((i["id"][len(turn):], i["kind"]) for i in store.turn_items(self.conn, turn))
        with self.conn:      # 앞길 살피기가 낸 길(<턴>:a<n>)과 2단이 찾은 할 일이 같은 턴에 붙어요
            store.set_ahead_items(self.conn, turn, [{"kind": "next", "text": "이어 가기 · 문구 정하기"}])
            store.set_items(self.conn, turn, [{"kind": "missing", "text": "표가 빠졌어요"}])
        self.assertEqual(kinds(), [(":0", "open"), (":1", "missing"), (":a0", "next")])
        with self.conn:      # 2단이 다시 써도 규칙 할 일과 길은 남고, 2단의 것만 바뀌어요
            store.set_items(self.conn, turn, [{"kind": "unasked", "text": "하나"}, {"kind": "handoff", "text": "둘"}])
        self.assertEqual(kinds(), [(":0", "open"), (":1", "unasked"), (":2", "handoff"), (":a0", "next")])
        with self.conn:      # 다시 살피면 길만 바뀌어요
            store.set_ahead_items(self.conn, turn, [])
        self.assertEqual(kinds(), [(":0", "open"), (":1", "unasked"), (":2", "handoff")])


if __name__ == "__main__":
    unittest.main()
