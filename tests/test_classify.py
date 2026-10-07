import json
import tempfile
import unittest
from pathlib import Path

from backend import store
from backend.agent import classify
from backend.engines import EngineError
from backend.runtime import Runtime

CHAT = "chat-1"


class FakeEngine:
    """LLM 대신 정해 둔 답을 돌려줘요. 받은 입력은 calls에 남겨요."""
    name = "fake"

    def __init__(self, answer):
        self.answer = answer
        self.calls = []

    def complete_json(self, system, prompt, schema):
        payload = json.loads(prompt)
        self.calls.append(payload)
        return self.answer(payload)


def titled(payload, **by_id):
    """받은 턴마다 제목만 붙이고, by_id로 준 턴은 그 값을 덮어써요."""
    turns = []
    for turn in payload["turns"]:
        item = {"id": turn["id"], "title": "제목 " + turn["id"], "depth": 0, "seg": None, "topic": None,
                "dec": None, "ref": None, "parts": []}
        item.update(by_id.get("t" + turn["id"], {}))
        turns.append(item)
    return {"turns": turns}


class ClassifyTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = Path(self.tmp.name) / "gadak.db"

    def start(self, answer, turns=3, **kwargs):
        self.engine = FakeEngine(answer)
        self.rt = Runtime(self.db, engine=self.engine)
        self.clf = classify.Classifier(self.rt, self.engine, **kwargs)
        self.conn = self.rt.connect()
        self.addCleanup(self.conn.close)
        with self.conn:
            store.upsert_chat(self.conn, project="환율 알리미", chat_id=CHAT, site="cursor", title="알림 봇 구현")
            for n in range(1, turns + 1):
                row = store.upsert_turn(self.conn, chat_id=CHAT, message_ref=f"g{n}", user=f"질문 {n}", ai=f"답 {n}",
                                        state="done")
                if n == 2:
                    store.add_file(self.conn, row["id"], "/x/main.py")
        return self.clf

    def rows(self):
        return store.chat_turns(self.conn, CHAT)

    def test_results_are_written_to_the_turns(self):
        clf = self.start(lambda p: titled(
            p,
            t1={"seg": "구현", "depth": 1},                      # 첫 턴은 갈라질 본류가 없어요 → 본류
            t2={"depth": 1, "dec": "넘을 때만 알림"},
            t3={"ref": "1", "parts": [{"t": "임계값 바꾸기", "type": "task", "target": None},
                                      {"t": "문구는 그대로냐", "type": "q", "target": "2"}]},
        ))
        self.assertEqual(clf.classify_chat(self.conn, CHAT), 3)
        one, two, three = self.rows()
        self.assertEqual((one["title"], one["depth"], one["seg"], one["classified"]), ("제목 1", 0, "구현", 1))
        self.assertEqual((two["depth"], two["dec"], two["ret"]), (1, "넘을 때만 알림", 0))
        self.assertEqual((three["depth"], three["ret"], three["ref"]), (0, 1, one["id"]))  # 곁길에서 돌아온 첫 턴
        parts = store.turn_public(self.conn, three)["parts"]
        self.assertEqual(parts, [{"t": "임계값 바꾸기", "type": "task"},
                                 {"t": "문구는 그대로냐", "type": "q", "target": two["id"]}])
        self.assertNotIn("pending", store.view(self.conn, "환율 알리미")["chats"][0])

    def test_input_carries_the_line_so_far_not_the_whole_chat(self):
        clf = self.start(lambda p: titled(p, t9={"depth": 1}), turns=12)
        self.assertEqual(clf.classify_chat(self.conn, CHAT), 12)
        first, second, whole = self.engine.calls              # 12턴 = 8개 + 4개, 그다음 구간 나누기
        self.assertEqual([t["id"] for t in first["turns"]], [str(n) for n in range(1, 9)])
        self.assertEqual(first["turns"][1], {"id": "2", "user": "질문 2", "ai": "답 2", "edited_files": ["main.py"]})
        self.assertEqual((first["project"], first["chat"], first["state"]["main"]), ("환율 알리미", {"title": "알림 봇 구현"}, []))
        self.assertEqual([t["id"] for t in second["turns"]], ["9", "10", "11", "12"])
        self.assertEqual(second["state"]["main"][-1], {"id": "8", "title": "제목 8", "dec": None})
        self.assertIsNone(second["state"]["open_side_chain"])
        self.assertEqual(len(whole["turns"]), 12)
        self.assertEqual(clf.status["calls"], 3)

    def test_wrong_values_from_the_model_are_corrected(self):
        clf = self.start(lambda p: titled(
            p,
            t1={"title": "  아주 " + "긴 " * 30, "seg": "  "},
            t2={"depth": 2, "ref": "3", "parts": [{"t": "하나뿐", "type": "task", "target": None}]},   # 미래 턴 참조, 요청 1개
            t3={"depth": 7, "ref": "99", "dec": ""},
        ))
        clf.classify_chat(self.conn, CHAT)
        one, two, three = self.rows()
        self.assertLessEqual(len(one["title"]), classify.TITLE_MAX)
        self.assertTrue(one["title"].startswith("아주 긴") and one["title"].endswith("…"))
        self.assertIsNone(one["seg"])
        self.assertEqual((two["depth"], two["ref"]), (1, None))     # 곁길 없이 2차 곁길이 될 수 없어요
        self.assertNotIn("parts", store.turn_public(self.conn, two))
        self.assertEqual((three["depth"], three["ref"], three["dec"]), (0, None, None))

    def test_a_decision_needs_the_user_to_have_chosen(self):
        clf = self.start(lambda p: titled(
            p,
            t1={"chose": False, "dec": "뼈대 구현 완료"},        # 일을 끝냈다는 것은 정한 것이 아니에요
            t2={"chose": True, "dec": "텔레그램 봇"},
        ))
        clf.classify_chat(self.conn, CHAT)
        self.assertEqual([r["dec"] for r in self.rows()], [None, "텔레그램 봇", None])

    def test_a_turn_the_model_skips_is_retried_then_left_alone(self):
        clf = self.start(lambda p: {"turns": [t for t in titled(p)["turns"] if t["id"] != "2"]})
        self.assertEqual(clf.classify_chat(self.conn, CHAT), 2)
        self.assertEqual([r["classified"] for r in self.rows()], [1, -1, 1])
        self.assertEqual(self.rows()[1]["title"], "질문 2")           # 임시 제목 그대로
        self.assertEqual(len(self.engine.calls), 2)

    def test_the_turn_still_being_answered_waits(self):
        clf = self.start(titled)
        with self.conn:
            store.upsert_turn(self.conn, chat_id=CHAT, message_ref="g4", user="질문 4")   # 답을 기다리는 중
        self.assertEqual(clf.classify_chat(self.conn, CHAT), 3)
        self.assertEqual(self.rows()[3]["classified"], 0)

    def test_engine_trouble_pauses_instead_of_hammering(self):
        def broken(_payload):
            raise EngineError("로그인이 필요해요")
        clf = self.start(broken)
        clf.request(CHAT)
        clf.request(CHAT)                                      # 같은 대화는 한 번만 줄을 서요
        self.assertEqual(len(clf.queue), 1)
        self.assertTrue(clf.step(self.conn))
        self.assertEqual((clf.status["paused"], clf.status["error"]), (True, "로그인이 필요해요"))
        clf.request(CHAT)
        self.assertFalse(clf.step(self.conn))                  # 멈춘 동안에는 부르지 않아요
        self.assertEqual(len(self.engine.calls), 1)
        clf.resume()
        self.assertTrue(clf.step(self.conn))

    def test_call_limit(self):
        clf = self.start(titled, turns=20, max_calls=1)
        self.assertEqual(clf.classify_chat(self.conn, CHAT), 8)
        self.assertTrue(clf.status["paused"])
        self.assertIn("1번", clf.status["error"])

    def test_segments_are_redrawn_from_the_whole_chat(self):
        def answer(p):
            if "state" in p:
                return titled(p, t1={"seg": "시작"})
            return {"segs": [{"from": "3", "name": "JOIN"}, {"from": "7", "name": "뷰와 독립성"}, {"from": "99", "name": "없음"}]}
        clf = self.start(answer, turns=8)
        clf.classify_chat(self.conn, CHAT)
        self.assertEqual([r["seg"] for r in self.rows()], ["JOIN", None, None, None, None, None, "뷰와 독립성", None])
        with self.conn:
            store.upsert_turn(self.conn, chat_id=CHAT, message_ref="g9", user="질문 9", ai="답 9", state="done")
        clf.classify_chat(self.conn, CHAT)
        self.assertEqual(len(self.engine.calls), 3)          # 한 역 늘었다고 다시 나누지 않아요

    def test_no_engine_means_no_classification(self):
        self.start(titled)
        clf = classify.Classifier(self.rt, None)
        self.assertEqual(clf.classify_chat(self.conn, CHAT), 0)
        self.assertEqual(clf.status["engine"], "none")


if __name__ == "__main__":
    unittest.main()
