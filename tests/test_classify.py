import json
import tempfile
import unittest
from pathlib import Path

from backend import store
from backend.agent import classify
from backend.engines import BadOutput, EngineError
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

    def test_an_answer_in_the_wrong_shape_fails_only_that_batch(self):
        """모델이 형식을 따르지 않고 글로 답한 한 번 때문에 정리 전체가 멈추면 안 돼요 (10/6 평가에서 나온 일)."""
        answers = iter([BadOutput("글로 답했어요"), None])

        def flaky(payload):
            answer = next(answers)
            if answer is not None:
                raise answer
            return titled(payload)
        clf = self.start(flaky)
        clf.request(CHAT)
        self.assertTrue(clf.step(self.conn))
        self.assertEqual((clf.status["paused"], clf.status["error"]), (False, None))     # 로그인 · 한도 문제처럼 멈추지 않아요
        self.assertEqual([r["classified"] for r in self.rows()], [1, 1, 1])              # 같은 묶음을 다시 물어 붙였어요
        self.assertEqual((len(self.engine.calls), clf.status["calls"]), (2, 2))

    def test_wrong_shapes_again_and_again_are_given_up(self):
        def never(_payload):
            raise BadOutput("글로 답했어요")
        clf = self.start(never)
        self.assertEqual(clf.classify_chat(self.conn, CHAT), 0)
        self.assertEqual([r["classified"] for r in self.rows()], [-1, -1, -1])           # 임시 제목 그대로 두고 더 묻지 않아요
        self.assertEqual((len(self.engine.calls), clf.status["paused"]), (classify.MAX_TRIES, False))

    def test_the_answer_summary_comes_with_the_same_call(self):
        """답 간추림(gist)은 분류와 같은 호출에서 받아요. 호출 수는 그대로예요."""
        clf = self.start(lambda p: titled(
            p,
            t1={"gist": ["  임계값을 1,380원으로 바꿨어요  ", "", "테스트도 고쳤어요"]},
            t2={"gist": ["가"] * 9 + ["나" * 200]},                    # 너무 많고 너무 길면 줄여요
            t3={"gist": "글 한 덩어리"},                               # 줄 목록이 아니면 버려요
        ), turns=4)
        with self.conn:
            store.upsert_turn(self.conn, chat_id=CHAT, message_ref="g4", user="질문 4", ai="  ", state="done")   # 답이 빈 턴
        self.assertEqual(clf.classify_chat(self.conn, CHAT), 4)
        self.assertEqual(len(self.engine.calls), 1)
        turns = store.view(self.conn, "환율 알리미")["chats"][0]["turns"]
        self.assertEqual(turns[0]["gist"], ["임계값을 1,380원으로 바꿨어요", "테스트도 고쳤어요"])
        self.assertEqual((len(turns[1]["gist"]), len(turns[1]["gist"][0])), (classify.GIST_LINES, 1))
        self.assertNotIn("gist", turns[2])
        self.assertNotIn("gist", turns[3])
        self.assertEqual([r["gist"] for r in self.rows()][2:], ["[]", "[]"])      # 없다고 적어 둬요 (다시 묻지 않게)
        self.assertEqual(classify.SCHEMA["properties"]["turns"]["items"]["required"][-1], "gist")
        with self.conn:
            store.reset_classification(self.conn, self.rows()[0]["id"])           # 답이 달라져 다시 분류할 턴은 간추림도 비워요
        self.assertIsNone(self.rows()[0]["gist"])

    def test_the_decision_note_and_the_answer_summary_arrive_together(self):
        """10/6에 따로 더한 두 칸(조원의 dec_note · 이쪽의 gist)이 한 호출에서 같이 와서 같이 적혀요."""
        clf = self.start(lambda p: titled(p, t1={
            "chose": True, "dec": "임계값 1,380원", "dec_note": "알림 임계값을 1,380원으로 정함", "gist": ["1,380원이 무난하다고 했어요"]}))
        self.assertEqual(clf.classify_chat(self.conn, CHAT), 3)
        first = self.rows()[0]
        self.assertEqual((first["dec"], first["dec_note"], json.loads(first["gist"])),
                         ("임계값 1,380원", "알림 임계값을 1,380원으로 정함", ["1,380원이 무난하다고 했어요"]))
        required = classify.SCHEMA["properties"]["turns"]["items"]["required"]
        self.assertTrue({"dec_note", "gist"} <= set(required))
        for key in ('"dec_note":null', '"gist":[""]'):                     # 프롬프트의 출력 형식에도 둘 다
            self.assertIn(key, classify.SYSTEM)
        self.assertIsNone(self.rows()[1]["dec_note"])                      # 정함이 없으면 풀어 쓴 문장도 없어요
        self.assertEqual(store.SCHEMA_VERSION, 9)

    def test_turns_classified_before_can_get_their_summary_later(self):
        """gist 칸이 생기기 전에 정리한 턴: 화면이 부탁하면 간추림만 채워요. 제목 · 정함 · 할 일은 그대로예요."""
        clf = self.start(lambda p: titled(p, t2={"chose": True, "dec": "임계값 1,380원"}))
        clf.classify_chat(self.conn, CHAT)
        with self.conn:
            self.conn.execute("UPDATE turns SET gist = NULL")                     # 예전에 정리한 턴처럼
            ids = store.set_items(self.conn, self.rows()[1]["id"], [{"kind": "unasked", "text": "요청하지 않은 곳도 바뀌었어요"}])
        before = [(r["title"], r["dec"], r["classified"], r["checked"]) for r in self.rows()]
        self.engine.answer = lambda p: titled(p, t1={"title": "다른 제목", "gist": ["첫 답을 간추렸어요"]},
                                              t2={"dec": "다른 정함", "gist": ["둘째 답을 간추렸어요"]})
        clf.want_gist(CHAT)
        self.assertTrue(clf.step(self.conn))
        self.assertEqual(len(self.engine.calls), 2)                               # 묶음 하나에 한 번만 물어요
        self.assertEqual([json.loads(r["gist"]) for r in self.rows()], [["첫 답을 간추렸어요"], ["둘째 답을 간추렸어요"], []])
        self.assertEqual([(r["title"], r["dec"], r["classified"], r["checked"]) for r in self.rows()], before)
        self.assertEqual([i["id"] for i in store.turn_items(self.conn, self.rows()[1]["id"])], ids)
        clf.want_gist(CHAT)
        clf.step(self.conn)
        self.assertEqual(len(self.engine.calls), 2)                               # 다 채운 대화는 다시 묻지 않아요

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

    def test_a_badly_shaped_segment_answer_keeps_the_segments_and_the_work_goes_on(self):
        def answer(p):
            if "state" in p:
                return titled(p, t1={"seg": "환율"})
            raise BadOutput("글로 답했어요")
        clf = self.start(answer, turns=6)
        clf.request(CHAT)
        self.assertTrue(clf.step(self.conn))
        self.assertEqual((clf.status["paused"], clf.status["error"]), (False, None))     # 정리를 멈추지 않아요
        self.assertEqual([r["seg"] for r in self.rows()], ["환율", None, None, None, None, None])   # 1단이 붙인 구간 그대로
        self.assertEqual(list(clf.checker.queue), [CHAT])                                # 2단은 하던 대로 이어서 봐요
        with self.conn:
            store.upsert_turn(self.conn, chat_id=CHAT, message_ref="g7", user="질문 7", ai="답 7", state="done")
        clf.classify_chat(self.conn, CHAT)
        self.assertEqual(len(self.engine.calls), 3)          # 역이 더 쌓일 때까지는 다시 묻지 않아요

    def test_imported_chats_are_grouped_into_projects_in_one_call(self):
        def answer(p):
            return {"chats": [{"id": "a", "project": "환율 알리미"}, {"id": "b", "project": "DB 수업"},
                              {"id": "c", "project": "DB 수업"}, {"id": "d", "project": "한 번뿐"},
                              {"id": "e", "project": ""}, {"id": "zz", "project": "DB 수업"}]}
        clf = self.start(answer)
        with self.conn:
            for i in "abcde":
                store.upsert_chat(self.conn, project=None, chat_id=i, site="claude", title="대화 " + i)
                store.upsert_turn(self.conn, chat_id=i, message_ref=i + "1", user="질문 " + i, ai="답", state="done")
        clf.want_group(list("abcde") + [CHAT])
        self.assertTrue(clf.step(self.conn))
        where = {i: store.chat_row(self.conn, i)["project_id"] for i in "abcde"}
        self.assertEqual(where, {"a": "환율 알리미", "b": "DB 수업", "c": "DB 수업",
                                 "d": store.NO_PROJECT, "e": store.NO_PROJECT})   # 혼자뿐인 새 이름 · 빈 이름은 그대로
        self.assertEqual(len(self.engine.calls), 1)
        self.assertEqual([c["id"] for c in self.engine.calls[0]["chats"]], list("abcde"))   # 프로젝트가 있는 대화는 묻지 않아요
        self.assertIn("환율 알리미", self.engine.calls[0]["projects"])

    def test_no_engine_means_no_classification(self):
        self.start(titled)
        clf = classify.Classifier(self.rt, None)
        self.assertEqual(clf.classify_chat(self.conn, CHAT), 0)
        self.assertEqual(clf.status["engine"], "none")


if __name__ == "__main__":
    unittest.main()
