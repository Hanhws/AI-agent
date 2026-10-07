import json
import tempfile
import unittest
from pathlib import Path

from backend import tokens


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


if __name__ == "__main__":
    unittest.main()
