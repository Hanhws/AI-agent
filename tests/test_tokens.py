import json
import tempfile
import unittest
from pathlib import Path

from backend import store, tokens
from backend.agent import classify
from backend.runtime import Runtime
from tests.test_classify import FakeEngine, titled


class TokensTest(unittest.TestCase):
    def test_gadak_and_llm_tokens_of_the_same_chat_are_set_side_by_side(self):
        with tempfile.TemporaryDirectory() as tmp:
            home, projects = Path(tmp), Path(tmp) / "projects"
            (projects / "-x").mkdir(parents=True)
            usage = {"input_tokens": 10, "cache_read_input_tokens": 1000, "output_tokens": 5}
            lines = [{"message": {"id": "m1", "usage": usage}}, {"message": {"id": "m1", "usage": usage}},  # 한 답이 두 줄
                     {"message": {"id": "m2", "usage": usage}}, {"type": "user", "message": {"content": "질문"}}]
            (projects / "-x" / "c1.jsonl").write_text("\n".join(map(json.dumps, lines)), encoding="utf-8")
            tokens.record(home, "classify", "c1", {"input_tokens": 300, "output_tokens": 40, "cost": 0.001})
            tokens.record(home, "segment", "c1", {"input_tokens": 100, "output_tokens": 20})
            tokens.record(home, "classify", "c1", None)                      # 엔진이 토큰을 못 알려 줬어요
            (row,) = tokens.report(home, projects)
            self.assertEqual((row["llm"]["replies"], row["llm"]["cache_r"], row["llm"]["out"]), (2, 2000, 10))
            self.assertEqual((row["gadak"]["calls"], row["gadak"]["in"], row["gadak"]["out"]), (2, 400, 60))
            self.assertEqual(row["by_kind"]["classify"]["cost_micro"], 1000)

    def test_each_engine_call_is_written_with_its_kind_and_chat(self):
        class Spending(FakeEngine):
            def complete_json(self, system, prompt, schema):
                self.last_usage = {"input_tokens": 100, "output_tokens": 10, "cost": 0.001, "model": "haiku"}
                return super().complete_json(system, prompt, schema)

            def research(self, question):
                self.last_usage = {"input_tokens": 500, "output_tokens": 50, "cost": 0.05, "model": "haiku"}
                return {"found": [], "searched": [question], "dropped": 0}

        with tempfile.TemporaryDirectory() as tmp:
            rt = Runtime(Path(tmp) / "gadak.db", engine=None)
            conn = rt.connect()
            self.addCleanup(conn.close)
            with conn:
                store.upsert_chat(conn, project="환율 알리미", chat_id="c1", site="claude-code", title="알림 봇")
                for n in range(1, 7):
                    store.upsert_turn(conn, chat_id="c1", message_ref=f"g{n}", user=f"질문 {n}", ai=f"답 {n}", state="done")
            engine = Spending(lambda p: titled(p) if "state" in p else {"segs": []})
            clf = classify.Classifier(rt, engine)
            clf.classify_chat(conn, "c1")                                    # 1단 한 번 + 6역이 쌓여 구간 나누기 한 번
            clf.research("무료 환율 API 한도", engine, chat="c1")             # 앞길 살피기의 웹 찾아보기
            kinds = tokens.gadak_usage(rt.home)["c1"]
            self.assertEqual({k: (c["calls"], c["in"]) for k, c in kinds.items()},
                             {"classify": (1, 100), "segment": (1, 100), "lookup": (1, 500)})


if __name__ == "__main__":
    unittest.main()
