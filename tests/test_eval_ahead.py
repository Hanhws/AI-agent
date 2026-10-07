"""앞길 살피기의 쓸모 재기(eval/ahead.py): 갈림길 고르기, 그 턴에 서서 살피기, 시트와 견주기. 엔진은 가짜예요."""
import contextlib
import csv
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from backend import config, store
from eval import ahead as cli
from eval import run
from tests.test_eval import DEMO, Oracle


class Scout(Oracle):
    """1단은 정답대로. 앞길은 가닥이 먼저 찾아 둔 결정 중 가장 오래된 것을 출처로, 지금 턴을 근거로 길 둘을 내요."""
    name = "scout"

    def __init__(self, scenario=None, model="정답", timeout=None):
        super().__init__(scenario, model, timeout)
        self.seen = []

    def complete_json(self, system, prompt, schema):
        payload = json.loads(prompt)
        if "ahead" not in payload:
            return super().complete_json(system, prompt, schema)
        self.last = {"input_tokens": 200, "output_tokens": 20, "cost": 0.002}
        self.seen.append(payload)
        blank = {"think": "본다", "arg": None, "goal": None, "paths": []}
        mine = [s for s in payload["steps"] if not s.get("by")]            # 가닥이 먼저 본 것 말고, 엔진이 고른 걸음
        if "look_up" in payload["tools"] and not mine:
            return dict(blank, tool="look_up", arg="무료 환율 API 호출 한도")
        now = payload["now"]["id"]
        old = payload["steps"][0]["saw"]["decisions"][-1]["id"]            # 가닥이 먼저 찾아 둔 것 중 가장 먼저 정한 것
        fact = [{"line": "환율은 무료 API에서 가져오기로 했어요.", "source": old}]
        web = [{"line": "하루 1,000번까지 부를 수 있어요.", "source": "https://api.example/limits"}] if mine else []
        return dict(blank, tool="finish", goal="환율 알림 받기", paths=[
            {"kind": "onward", "title": "확인 시각 정하기", "why": "방금 하루 한 번으로 정했어요.", "basis": [now], "found": fact,
             "ask": "몇 시에 확인할지 후보를 알려 줘."},
            {"kind": "check", "title": "호출 한도 확인하기", "why": "무료 API를 쓰기로 했어요.", "basis": [now], "found": fact + web,
             "ask": "무료 API의 호출 한도를 확인해 줘."},
            {"kind": "other", "title": "근거 없는 길", "why": "", "basis": ["t-없는-턴"], "found": [], "ask": "해 줘."},
        ])

    def research(self, question):
        self.last = {"input_tokens": 500, "output_tokens": 50, "cost": 0.05}
        return {"found": [{"line": "하루 1,000번까지예요.", "source": "https://api.example/limits"}], "searched": [question]}


class NoWeb(Scout):
    research = None


class RunTest(unittest.TestCase):
    def test_junctions_are_looked_at_from_where_they_stand(self):
        engine = Scout()
        said = []
        out = cli.run(run.load(DEMO, "demo"), engine, limit=10, say=said.append)
        numbers = out["numbers"]
        self.assertIsNone(out["error"])
        self.assertEqual((numbers["turns"], numbers["junctions"], numbers["by_why"], numbers["looked"]), (12, 2, {"decided": 2}, 2))
        # 첫 갈림길(같은 대화의 두 턴 앞 결정뿐)은 대화 밖에서 찾은 것이 없어 조용하고, 둘째(지난 대화의 결정)는 길 둘
        self.assertEqual((numbers["paths"], numbers["by_kind"], numbers["dropped"], numbers["silent"]), (2, {"onward": 1, "check": 1}, 4, 1))
        self.assertEqual((numbers["stats"]["calls"], numbers["web"]), ({"classify": 2, "check": 0, "ahead": 2, "lookup": 0}, False))
        self.assertEqual(numbers["tools"], {"search_decisions": 2, "list_open_items": 2})
        for payload in engine.seen:                                   # 그 턴 뒤의 대화는 보여 주지 않아요
            self.assertEqual(payload["outline"][-1]["id"], payload["now"]["id"])
            self.assertNotIn("look_up", payload["tools"])
        self.assertEqual([p["now"]["seq"] for p in engine.seen], [4, 4])
        rows = [dict(zip(cli.COLUMNS, r)) for r in out["rows"]]
        self.assertEqual(len(rows), 3)
        quiet, first = rows[0], rows[1]
        self.assertEqual((quiet["번호"], quiet["턴"], quiet["종류"], quiet["길"]), (1, "a4", "—", "(길을 내지 않았어요)"))
        self.assertEqual(len(quiet["그 뒤 실제 대화"].splitlines()), 2)             # a5 · a6
        self.assertEqual((first["번호"], first["턴"], first["살핀 까닭"], first["종류"], first["길"], first["가닥이 읽은 목적지"]),
                         (2, "b4", "방금 정함", "이어 가기", "확인 시각 정하기", "환율 알림 받기"))
        self.assertEqual(first["찾아본 것"], "· 환율은 무료 API에서 가져오기로 했어요. (기록)")
        self.assertTrue(first["그 뒤 실제 대화"].startswith("1. "))
        self.assertEqual((first["쓸모"], first["갔나"]), ("", ""))
        self.assertIn("갈림길 2/2", said[-1])
        self.assertEqual(config.AHEAD, False)                                       # 재는 동안 건드린 설정은 되돌려요

    def test_web_lookups_are_counted_and_only_when_asked(self):
        engine = Scout()
        out = cli.run(run.load(DEMO, "demo"), engine, limit=1, web=True)
        numbers = out["numbers"]
        self.assertEqual((numbers["looked"], numbers["web"], numbers["with_found"], numbers["paths"]), (1, True, 1, 1))
        self.assertEqual(numbers["stats"]["calls"], {"classify": 2, "check": 0, "ahead": 2, "lookup": 1})
        # 대화 밖에서 찾은 것이 웹뿐이라, 웹에서 찾은 줄이 붙은 길만 남아요
        self.assertEqual(dict(zip(cli.COLUMNS, out["rows"][0]))["찾아본 것"], "· 하루 1,000번까지 부를 수 있어요. (https://api.example/limits)")
        plain = cli.run(run.load(DEMO, "demo"), NoWeb(), limit=1, web=True)         # 웹을 못 찾는 엔진이면 켜도 안 써요
        self.assertEqual((plain["numbers"]["web"], plain["numbers"]["stats"]["calls"]["lookup"]), (False, 0))

    def test_the_call_limit_stops_it_and_says_so(self):
        out = cli.run(run.load(DEMO, "demo"), Scout(), limit=10, max_calls=3)
        self.assertEqual(out["numbers"]["looked"], 1)
        self.assertIn("1곳까지만", out["error"])

    def test_labels_and_paths_can_come_from_different_engines(self):
        out = cli.run(run.load(DEMO, "demo"), Scout(model="큰 모델"), limit=10, labeler=Scout(model="작은 모델"))
        stats = out["numbers"]["stats"]
        self.assertEqual((stats["model"], stats["label_model"], stats["calls"]),
                         ("큰 모델", "작은 모델", {"classify": 2, "check": 0, "ahead": 2, "lookup": 0}))
        self.assertEqual(stats["cost_usd"], 2 * 0.001 + 2 * 0.002)
        self.assertIn("scout / 큰 모델 (1단은 작은 모델)", cli.report("demo", out["numbers"]))

    def test_labelled_records_can_be_kept_and_used_again(self):
        with tempfile.TemporaryDirectory() as tmp:
            kept = Path(tmp) / "local" / "demo.db"
            first = cli.run(run.load(DEMO, "demo"), Scout(), limit=10, db=kept)
            self.assertTrue(kept.is_file())
            again = cli.run(run.load(DEMO, "demo"), Scout(), limit=10, db=kept)
        self.assertEqual((first["numbers"]["stats"]["calls"]["classify"], again["numbers"]["stats"]["calls"]["classify"]), (2, 0))
        self.assertEqual((again["numbers"]["turns"], again["numbers"]["junctions"], again["numbers"]["paths"]), (12, 2, 2))
        self.assertEqual([r[1] for r in again["rows"]], [r[1] for r in first["rows"]])

    def test_my_own_records_can_be_used_without_touching_them(self):
        with tempfile.TemporaryDirectory() as tmp:
            mine = Path(tmp) / "gadak.db"
            cli.run(run.load(DEMO, "demo"), Scout(), limit=0, db=mine)           # 정리된 기록 하나를 만들어 두고
            conn = store.connect(mine)
            with conn:
                store.set_hidden(conn, ["demo:c1"])                               # 대화 하나는 목록에서 뺐어요
            conn.close()
            before = mine.read_bytes()
            out = cli.run(None, Scout(), limit=10, records=mine)
            self.assertEqual(mine.read_bytes(), before)                           # 원본은 그대로
        self.assertEqual((out["numbers"]["stats"]["calls"]["classify"], out["numbers"]["junctions"]), (0, 1))   # 뺀 대화는 보지 않아요
        # 뺀 대화에서 정한 것은 찾아보지도 않아서, 이 갈림길에서는 대화 밖에서 찾은 것이 없어요 → 조용해요
        self.assertEqual([(r[1], r[6]) for r in out["rows"]], [("b4", "—")])

    def test_many_junctions_are_sampled_evenly(self):
        self.assertEqual(cli.spread(list(range(10)), 4), [0, 3, 6, 9])
        self.assertEqual(cli.spread([1, 2], 5), [1, 2])
        self.assertEqual(cli.spread([1, 2, 3], 1), [1])
        self.assertEqual(cli.spread([1, 2, 3], None), [1, 2, 3])


class CompareTest(unittest.TestCase):
    def sheet(self, tmp, name, marks):
        """marks: {(번호, 종류): (쓸모, 갔나)}"""
        path = Path(tmp) / name
        rows = [[n, "a1", "방금 정함", "대화", "지금", "목적지", kind, "길", "", "", "", "보낼 글", "그 뒤", useful, went, ""]
                for (n, kind), (useful, went) in marks.items()]
        rows.append([99, "a9", "방금 정함", "대화", "지금", "", "—", "(길을 내지 않았어요)", "", "", "", "", "", "", "", ""])
        cli.write_sheet(path, rows)
        return path

    def test_two_raters(self):
        kinds = ["이어 가기", "다른 길", "미리 챙길 것"]
        keys = [(n, kinds[n % 3]) for n in range(1, 13)]
        with tempfile.TemporaryDirectory() as tmp:
            # 12개 중 둘 다 쓸모 있음 9개, 하나는 한쪽만, 하나는 둘 다 아님, 하나는 한쪽이 안 매김
            one = {k: ("1", "1" if i < 5 else "0") for i, k in enumerate(keys)}
            two = dict(one)
            one[keys[9]], two[keys[9]] = ("1", "0"), ("0", "0")
            one[keys[10]], two[keys[10]] = ("0", ""), ("0", "")
            two[keys[11]] = ("", "")
            a, b = cli.read_sheet(self.sheet(tmp, "A.csv", one)), cli.read_sheet(self.sheet(tmp, "B.csv", two))
            with open(Path(tmp) / "A.csv", encoding="utf-8-sig", newline="") as file:
                self.assertEqual(tuple(next(csv.reader(file))), cli.COLUMNS)
        self.assertEqual(len(a), 12)                                           # 길을 내지 않은 줄은 세지 않아요
        result = cli.compare(a, b)
        self.assertEqual((result["paths"], result["unrated"], result["both"], result["rate"]), (11, 1, 9, 0.8182))
        self.assertEqual((result["one"], result["two"], result["same"]), (10, 9, 10))
        self.assertEqual(result["went"], {"of": 10, "both": 5})
        self.assertEqual(result["useful_but_new"], 4)                          # 가지 않았지만 둘 다 쓸모 있다고 한 길
        self.assertEqual((result["enough"], result["passed"]), (True, True))
        self.assertEqual(sum(v["of"] for v in result["by_kind"].values()), 11)
        text = cli.show(result)
        self.assertIn("둘 다 쓸모 있다고 한 길   82% (9/11)", text)
        self.assertIn("켤 기준(70% 이상)을 넘었어요", text)
        few = cli.compare({k: v for k, v in list(a.items())[:4]}, b)
        self.assertEqual((few["enough"], few["passed"]), (False, False))
        self.assertIn("매긴 길이 10개가 안 돼요", cli.show(few))
        low = cli.compare(a, {k: dict(v, useful=0) for k, v in a.items()})
        self.assertIn("못 미쳐요", cli.show(low))


class CliTest(unittest.TestCase):
    def run_cli(self, *argv):
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(cli, "get_engine", lambda name: Scout()), \
                mock.patch.object(cli, "resolve_name", lambda name=None: "scout"), \
                mock.patch.object(cli, "RESULTS", Path(tmp) / "results"), mock.patch.object(cli, "LOCAL", Path(tmp) / "local"), \
                contextlib.redirect_stdout(io.StringIO()) as said:
            code = cli.main(list(argv))
            results = {p.name: json.loads(p.read_text(encoding="utf-8")) for p in (Path(tmp) / "results").glob("*.json")}
            local = sorted(p.name for p in (Path(tmp) / "local").glob("*"))
        return code, said.getvalue(), results, local

    def test_run_writes_a_sheet_to_rate_and_numbers_without_text(self):
        code, said, results, local = self.run_cli("run", "--demo", "--model", "정답", "--tag", "시험")
        self.assertEqual(code, 0)
        for line in ("demo · 12턴 · scout / 정답", "갈림길 2곳 (방금 정함 2) 중 2곳을 살폈어요", "낸 길 2개 (이어 가기 1 · 미리 챙길 것 1)",
                     "길을 내지 않은 곳 1곳", "호출 1단 2번", "앞길 2번"):
            self.assertIn(line, said)
        self.assertIn("앞길-시트-시험.csv", local)
        numbers = results["앞길-demo-정답-시험.json"]
        self.assertEqual((numbers["scenario"], numbers["paths"], numbers["looked"]), ("demo", 2, 2))
        text = json.dumps(results, ensure_ascii=False)
        for words in ("확인 시각", "호출 한도", "환율", "몇 시에"):                # 대화 글 · 길의 글은 숫자 파일에 남기지 않아요
            self.assertNotIn(words, text)

    def test_a_stopped_run_can_be_picked_up_and_more_talks_added_to_the_same_sheet(self):
        with tempfile.TemporaryDirectory() as tmp:
            sheet = Path(tmp) / "시트.csv"
            patches = (mock.patch.object(cli, "get_engine", lambda name: Scout()), mock.patch.object(cli, "resolve_name", lambda name=None: "scout"),
                       mock.patch.object(cli, "RESULTS", Path(tmp) / "results"), mock.patch.object(cli, "LOCAL", Path(tmp) / "local"))
            with contextlib.ExitStack() as stack, contextlib.redirect_stdout(io.StringIO()):
                for patch in patches:
                    stack.enter_context(patch)
                self.assertEqual(cli.main(["run", "--demo", "--model", "정답", "--max", "1", "--out", str(sheet)]), 0)           # 첫 갈림길만
                first = cli.sheet_so_far(sheet)
                self.assertEqual(cli.main(["run", "--demo", "--model", "정답", "--from", "2", "--append", "--out", str(sheet)]), 0)   # 둘째부터 이어서
                both = cli.sheet_so_far(sheet)
                self.assertEqual(cli.main(["run", "--demo", "--model", "정답", "--append", "--out", str(sheet)]), 0)             # 한 번 더: 번호를 이어 매겨요
                more = cli.sheet_so_far(sheet)
                saved = sorted(p.name for p in (Path(tmp) / "results").glob("*.json"))
            self.assertEqual([(r[0], r[1]) for r in first], [("1", "a4")])
            self.assertEqual([(r[0], r[1]) for r in both], [("1", "a4"), ("2", "b4"), ("2", "b4")])
            self.assertEqual([(r[0], r[1]) for r in more[3:]], [("3", "a4"), ("4", "b4"), ("4", "b4")])
            self.assertEqual(len(cli.read_sheet(sheet)), 4)                 # 길이 든 줄: 번호 · 턴 · 종류로 가려요
            self.assertEqual(saved, ["앞길-demo-정답.json"])                 # 이어서 돈 것의 숫자는 남기지 않아요

    def test_without_the_example_file_it_says_how_to_try(self):
        with mock.patch.object(cli, "EXAMPLE", Path("없는 파일.json")), contextlib.redirect_stdout(io.StringIO()) as said:
            self.assertEqual(cli.main(["run"]), 2)
        self.assertIn("python -m eval.ahead run --demo", said.getvalue())


if __name__ == "__main__":
    unittest.main()
