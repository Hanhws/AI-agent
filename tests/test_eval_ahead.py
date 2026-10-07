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
        self.assertEqual(config.AHEAD, True)                                        # 재는 동안 건드린 설정은 되돌려요 (기본은 켬: 누를 때만 도는 버튼)

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

    def test_a_verdict_from_fewer_paths_says_so(self):
        """둘 다 매긴 길이 10개가 안 될 때 있는 것으로 판정하면(need를 낮춰서), 낮춰서 낸 판정이라고 같이 적어요."""
        kinds = ["이어 가기", "다른 길", "미리 챙길 것"]

        def sheet(tmp, name, useful):
            return cli.read_sheet(self.sheet(tmp, name, {(n, kinds[n % 3]): (mark, "0") for n, mark in enumerate(useful, 1)}))

        with tempfile.TemporaryDirectory() as tmp:
            five, four, seven = sheet(tmp, "5.csv", "1111100"), sheet(tmp, "4.csv", "1111000"), sheet(tmp, "7.csv", "1111111")
            twelve = sheet(tmp, "12.csv", "1" * 12)
        usual = cli.compare(five, five)                                        # 정해 둔 대로면 7개로는 정하지 않아요
        self.assertEqual((usual["need"], usual["enough"], usual["passed"]), (10, False, False))
        self.assertIn("매긴 길이 10개가 안 돼요", cli.show(usual))
        self.assertNotIn("정해 둔 최소", cli.show(usual))
        fewer = cli.compare(five, five, need=7)
        self.assertEqual((fewer["need"], fewer["enough"], fewer["passed"], fewer["rate"]), (7, True, True, 0.7143))
        text = cli.show(fewer)
        self.assertIn("켤 기준(70% 이상)을 넘었어요", text)
        self.assertIn("! 정해 둔 최소(10개)보다 적은 7개로 낸 판정이에요. 둘 다 쓸모 있다고 한 길이 하나만 적었어도 57% (4/7)로 못 미쳐요.", text)
        text = cli.show(cli.compare(four, four, need=7))                       # 못 미친 쪽도 한 줄 차이면 그렇다고
        self.assertIn("못 미쳐요. 꺼 둔 채로 둬요", text)
        self.assertIn("적은 7개로 낸 판정이에요. 둘 다 쓸모 있다고 한 길이 하나만 많았어도 71% (5/7)로 넘어요.", text)
        text = cli.show(cli.compare(seven, seven, need=7))                     # 한 줄로는 달라지지 않는 판정
        self.assertIn("적은 7개로 낸 판정이에요.", text)
        self.assertNotIn("하나만", text)
        self.assertIn("매긴 길이 8개가 안 돼요", cli.show(cli.compare(five, five, need=8)))
        self.assertNotIn("정해 둔 최소", cli.show(cli.compare(twelve, twelve, need=7)))      # 10개가 넘으면 낮춘 것이 아니에요


class FilledSheetTest(unittest.TestCase):
    """사람이 엑셀 · Numbers로 채워 저장한 시트: 형식이 달라도 읽고, 잘못 적은 칸은 조용히 넘기지 않아요."""
    KINDS = ["이어 가기", "다른 길", "미리 챙길 것"]

    def sheet(self, tmp, name, marks):
        path = Path(tmp) / name
        cli.write_sheet(path, [[n, "a1", "방금 정함", "대화", "지금", "목적지", self.KINDS[n % 3], "길", "", "", "· 줄 하나\n· 줄 둘", "보낼 글",
                                "1. 그 뒤", useful, went, ""] for n, (useful, went) in enumerate(marks, 1)]
                        + [[99, "a9", "방금 정함", "대화", "지금", "", "—", "(길을 내지 않았어요)", "", "", "", "", "", "", "", ""]])
        return path

    def test_sheets_saved_by_a_spreadsheet_are_still_read(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self.sheet(tmp, "A.csv", [("1", "0"), ("0", ""), ("1", "1"), ("", "")])
            plain = cli.read_sheet(path)
            self.assertEqual((len(plain), plain["1:a1:다른 길"]), (4, {"useful": 1, "went": 0, "kind": "다른 길", "odd": {}}))
            text = path.read_text(encoding="utf-8-sig")
            old = Path(tmp) / "예전 한글 형식.csv"                     # 엑셀의 ‘쉼표로 분리(.csv)’. —는 이 형식에 없어 ?가 돼요
            old.write_bytes(text.encode("cp949", errors="replace"))
            wide = Path(tmp) / "유니코드 텍스트.txt"                    # 엑셀의 ‘유니코드 텍스트’: UTF-16 · 탭
            with open(wide, "w", encoding="utf-16", newline="") as file:
                csv.writer(file, delimiter="\t").writerows(csv.reader(io.StringIO(text, newline="")))
            semi = Path(tmp) / "쌍반점.csv"
            with open(semi, "w", encoding="utf-8", newline="") as file:
                csv.writer(file, delimiter=";").writerows(csv.reader(io.StringIO(text, newline="")))
            for other in (old, wide, semi):
                self.assertEqual(cli.read_sheet(other), plain, other.name)
            xlsx = Path(tmp) / "시트.xlsx"
            xlsx.write_bytes(b"PK\x03\x04" + b"\x00" * 20)
            renamed = Path(tmp) / "열 이름을 고침.csv"
            renamed.write_text(text.replace("쓸모", "유용", 1), encoding="utf-8-sig")
            broken = Path(tmp) / "깨진 글자.csv"
            broken.write_bytes(b"\x81\x00\xff\xfe\x81")
            for bad, said in ((xlsx, "CSV UTF-8"), (renamed, "‘쓸모’ 열이 없어요"), (broken, "글자를 읽지 못했어요"),
                              (Path(tmp) / "없는 파일.csv", "열지 못했어요")):
                with self.assertRaises(cli.SheetError) as caught:
                    cli.read_sheet(bad)
                self.assertIn(said, str(caught.exception), bad.name)

    def test_marks_that_cannot_be_read_are_reported_not_dropped_quietly(self):
        with tempfile.TemporaryDirectory() as tmp:
            a = cli.read_sheet(self.sheet(tmp, "A.csv", [("1", "1")] * 4))
            b = cli.read_sheet(self.sheet(tmp, "B.csv", [("O", "예"), ("１", " 0 "), ("1.0", ""), ("0 (뻔함)", "X")]))
        self.assertEqual([(b[k]["useful"], b[k]["went"]) for k in ("1:a1:다른 길", "2:a1:미리 챙길 것", "3:a1:이어 가기", "4:a1:다른 길")],
                         [(None, None), (1, 0), (1, None), (0, None)])          # 전각 숫자 · 1.0 · 뒤에 붙인 메모는 읽어요
        looked = cli.check(b)
        self.assertEqual((looked["paths"], looked["useful"], looked["went"], len(looked["odd"]), looked["blank"], looked["ok"]),
                         (4, 3, 1, 3, [], False))
        self.assertIn("‘1 · a1 · 다른 길’의 쓸모 “O”", cli.show_check("B.csv", looked))
        fine = cli.check(a)
        self.assertEqual((fine["ok"], fine["odd"]), (True, []))
        self.assertIn("이대로 견줄 수 있어요", cli.show_check("A.csv", fine))
        result = cli.compare(a, b)
        self.assertEqual((result["paths"], result["unrated"], result["odd"]["one"], len(result["odd"]["two"])), (3, 1, [], 3))
        text = cli.show(result)
        self.assertIn("! 둘째 시트에서 읽지 못한 칸 3개: ‘1 · a1 · 다른 길’의 쓸모 “O”", text)
        self.assertNotIn("첫째 시트에서 읽지 못한", text)
        self.assertNotIn("한쪽 시트에만", text)

    def test_one_persons_sheet_can_be_looked_at_alone_but_the_verdict_takes_two(self):
        owner = [("0", "0"), ("1", "0"), ("1", "0"), ("0", "1"), ("1", "0"), ("1", ""), ("1", "")]
        with tempfile.TemporaryDirectory() as tmp:
            a = cli.read_sheet(self.sheet(tmp, "A.csv", owner))
            many = cli.read_sheet(self.sheet(tmp, "많이.csv", [("1", "0")] * 9 + [("0", "1")] * 3 + [("", ""), ("O", "")]))
        result = cli.score(a)
        self.assertEqual((result["paths"], result["unrated"], result["useful"], result["rate"]), (7, 0, 5, 0.7143))
        self.assertEqual(result["went"], {"of": 5, "new": 3, "anyway": 0, "obvious": 1, "neither": 1})
        self.assertEqual(result["by_kind"], {"다른 길": {"of": 3, "useful": 1}, "미리 챙길 것": {"of": 2, "useful": 2}, "이어 가기": {"of": 2, "useful": 2}})
        text = cli.show_score("A.csv", result)
        for line in ("A.csv · 매긴 길 7개", "쓸모 있다고 한 길        71% (5/7)", "갔나를 매긴 5개 중 — 생각 못 한 길 3개(쓸모 있는데 가지 않음) · 어차피 간 길 0개",
                     "뻔한 되풀이 1개(쓸모없는데 감) · 둘 다 아님 1개"):
            self.assertIn(line, text)
        enough = cli.score(many)                                               # 안 매긴 줄과 못 읽은 줄은 빼요
        self.assertEqual((enough["paths"], enough["unrated"], enough["rate"], len(enough["odd"])), (12, 2, 0.75, 1))
        text = cli.show_score("많이.csv", enough)
        for line in ("매긴 길 12개 (안 매긴 길 2개는 뺐어요)", "! 읽지 못한 칸 1개"):
            self.assertIn(line, text)
        for words in ("켤 기준", "정할 수 없어요"):                              # 한 사람의 시트로는 켤지 말하지 않아요
            self.assertNotIn(words, text)
        self.assertNotIn("passed", enough)
        self.assertEqual(cli.score({})["rate"], None)
        both = cli.compare(many, many)                                         # 판정은 두 시트를 견줘서
        self.assertEqual((both["paths"], both["rate"], both["passed"]), (12, 0.75, True))

    def test_sheets_that_do_not_line_up_are_called_out(self):
        with tempfile.TemporaryDirectory() as tmp:
            seven = cli.read_sheet(self.sheet(tmp, "A.csv", [("1", "")] * 7))
            three = cli.read_sheet(self.sheet(tmp, "B.csv", [("1", "")] * 3))          # 다른 시트(길이 셋뿐인 것)를 채운 경우
        result = cli.compare(seven, three)
        self.assertEqual((result["paths"], len(result["only"]["one"]), result["only"]["two"]), (3, 4, []))
        self.assertIn("! 한쪽 시트에만 있는 길이 있어요 (첫째에만 4개 · 둘째에만 0개): ‘4 · a1 · 다른 길’", cli.show(result))
        self.assertNotIn("한쪽 시트에만", cli.show(cli.compare(seven, seven)))

    def test_the_commands_explain_instead_of_crashing(self):
        def run(*argv):
            with contextlib.redirect_stdout(io.StringIO()) as said:
                return cli.main(list(argv)), said.getvalue()

        with tempfile.TemporaryDirectory() as tmp:
            good = self.sheet(tmp, "A.csv", [("1", "0")] * 3)
            odd = self.sheet(tmp, "B.csv", [("O", "0"), ("1", ""), ("", "")])
            old = Path(tmp) / "C.csv"
            old.write_bytes(good.read_text(encoding="utf-8-sig").encode("cp949", errors="replace"))
            xlsx = Path(tmp) / "D.xlsx"
            xlsx.write_bytes(b"PK\x03\x04")
            code, said = run("check", str(good), str(old))
            self.assertEqual((code, said.count("이대로 견줄 수 있어요"), said.count("길 3개")), (0, 2, 2))
            code, said = run("check", str(odd))
            self.assertEqual(code, 1)
            for line in ("쓸모 1/3칸 · 갔나 1/3칸", "읽지 못한 칸 1개", "쓸모를 비운 길 1개: ‘3 · a1 · 이어 가기’"):
                self.assertIn(line, said)
            self.assertEqual(run("check", str(xlsx), str(Path(tmp) / "없음.csv"))[0], 1)
            code, said = run("check", str(self.sheet(tmp, "빈 시트.csv", [("", "")] * 3)))       # 아직 아무것도 안 매긴 시트
            self.assertEqual((code, "아직 쓸모를 매긴 길이 없어요" in said, "견줄 수 있어요" in said), (1, True, False))
            code, said = run("compare", str(good), str(old))                          # 형식이 달라도 같은 시트로 읽혀요
            self.assertEqual(code, 0)
            self.assertIn("둘 다 매긴 길 3개", said)
            self.assertIn("매긴 길이 10개가 안 돼요", said)
            code, said = run("compare", str(good), str(old), "--need", "3")           # 있는 것으로 판정: 낮춰서 냈다고 같이 적어요
            self.assertEqual(code, 0)
            for line in ("켤 기준(70% 이상)을 넘었어요", "! 정해 둔 최소(10개)보다 적은 3개로 낸 판정이에요."):
                self.assertIn(line, said)
            self.assertEqual(run("compare", str(good), str(old), "--need", "0")[0], 2)
            code, said = run("compare", str(good), str(xlsx))
            self.assertEqual((code, "CSV UTF-8" in said), (2, True))
            code, said = run("score", str(good), str(odd))                           # 한 사람씩의 숫자. 켤지는 말하지 않아요
            self.assertEqual(code, 0)
            for line in ("A.csv · 매긴 길 3개", "쓸모 있다고 한 길        100% (3/3)", "생각 못 한 길 3개", "B.csv · 매긴 길 1개 (안 매긴 길 2개는 뺐어요)",
                         "! 읽지 못한 칸 1개", "켤지는 두 사람의 시트를 견줘서 정해요: python -m eval.ahead compare A.csv B.csv"):
                self.assertIn(line, said)
            for words in ("모두 합쳐", "정할 수 없어요", "켤 기준"):
                self.assertNotIn(words, said)
            self.assertEqual(run("score", str(xlsx))[0], 2)
            # 가닥이 만든 시트가 아닌 파일 뒤에는 붙이지 않아요 (덮어쓰지 않아요)
            other = Path(tmp) / "남의 파일.csv"
            other.write_text("이름,값\n가,1\n", encoding="utf-8")
            with mock.patch.object(cli, "get_engine", lambda name: Scout()), mock.patch.object(cli, "resolve_name", lambda name=None: "scout"), \
                    mock.patch.object(cli, "RESULTS", Path(tmp) / "results"), mock.patch.object(cli, "LOCAL", Path(tmp) / "local"):
                code, said = run("run", "--demo", "--model", "정답", "--append", "--out", str(other))
            self.assertEqual((code, other.read_text(encoding="utf-8")), (2, "이름,값\n가,1\n"))
            self.assertIn("뒤에 붙이지 않았어요", said)


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

    def test_a_stopped_run_can_be_picked_up_and_more_junctions_added_to_a_rated_sheet(self):
        with tempfile.TemporaryDirectory() as tmp:
            sheet = Path(tmp) / "시트.csv"
            base = ["run", "--demo", "--model", "정답", "--out", str(sheet)]
            patches = (mock.patch.object(cli, "get_engine", lambda name: Scout()), mock.patch.object(cli, "resolve_name", lambda name=None: "scout"),
                       mock.patch.object(cli, "RESULTS", Path(tmp) / "results"), mock.patch.object(cli, "LOCAL", Path(tmp) / "local"))
            with contextlib.ExitStack() as stack, contextlib.redirect_stdout(io.StringIO()) as said:
                for patch in patches:
                    stack.enter_context(patch)
                self.assertEqual(cli.main(base + ["--max", "1"]), 0)                      # 첫 갈림길만 살피고 멈춘 셈
                first = cli.sheet_so_far(sheet)
                self.assertEqual(cli.main(base + ["--from", "2", "--append"]), 0)         # 둘째부터 이어서
                both = cli.sheet_so_far(sheet)
                rated = [list(r) for r in both]                                           # 사람이 둘째 갈림길의 두 줄을 매겼어요
                rated[1][13:16], rated[2][13:16] = ["1", "0", "좋아요"], ["0", "", ""]
                cli.write_sheet(sheet, rated)
                self.assertEqual(cli.main(base + ["--append"]), 0)                        # 같은 갈림길을 또: 다시 살피지 않아요
                same = cli.sheet_so_far(sheet)
                with mock.patch.object(config, "AHEAD_EVERY", 1):                         # 간격을 줄이면 사이의 갈림길을 더 살펴요
                    self.assertEqual(cli.main(base + ["--append"]), 0)
                more = cli.sheet_so_far(sheet)
                saved = sorted(p.name for p in (Path(tmp) / "results").glob("*.json"))
            self.assertEqual([(r[0], r[1]) for r in first], [("1", "a4")])
            self.assertEqual([(r[0], r[1]) for r in both], [("1", "a4"), ("2", "b4"), ("2", "b4")])
            self.assertEqual(same, rated)
            self.assertIn("새로 붙일 줄이 없어요", said.getvalue())
            self.assertIn("시트에 이미 있는 갈림길 2곳은 다시 보지 않아요 · 새로 살필 곳 3곳", said.getvalue())
            self.assertEqual(more[:3], rated)                                             # 있던 줄과 매긴 값은 그대로
            self.assertEqual([(r[0], r[1]) for r in more[3:]], [("3", "a5"), ("4", "b5"), ("4", "b5"), ("5", "b6"), ("5", "b6")])   # 번호를 이어 매겨요
            self.assertIn("있던 3줄은 그대로 두고 5줄을 붙였어요", said.getvalue())
            self.assertEqual(len(cli.read_sheet(sheet)), 6)                 # 길이 든 줄: 번호 · 턴 · 종류로 가려요
            self.assertEqual(saved, ["앞길-demo-정답.json"])                 # 이어서 · 더해서 돈 것의 숫자는 남기지 않아요

    def test_without_the_example_file_it_says_how_to_try(self):
        with mock.patch.object(cli, "EXAMPLE", Path("없는 파일.json")), contextlib.redirect_stdout(io.StringIO()) as said:
            self.assertEqual(cli.main(["run"]), 2)
        self.assertIn("python -m eval.ahead run --demo", said.getvalue())


if __name__ == "__main__":
    unittest.main()
