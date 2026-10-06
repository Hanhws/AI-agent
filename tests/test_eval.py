"""정확도 평가(eval/)가 숫자를 제대로 세는지. 엔진은 가짜예요: 정답대로 답하는 것과, 아무것도 안 찾는 것."""
import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import eval.__main__ as cli
from backend import replay, store
from backend.engines import BadOutput
from eval import agree, run, score

ROOT = Path(__file__).resolve().parent.parent
DEMO = ROOT / "data" / "demo_conversations.json"


class Oracle:
    """정답 파일을 보고 답하는 엔진. 1단은 정답 칸 그대로, 2단은 근거를 도구로 본 다음에 결론을 내요."""
    name = "oracle"

    def __init__(self, scenario=None, model="정답", timeout=None):
        self.scenario = scenario or run.load(DEMO, "demo")
        self.model = model
        self.last = None

    def _chat(self, title):
        return next(c for c in self.scenario["chats"] if c.get("title") == title)

    def complete_json(self, system, prompt, schema):
        payload = json.loads(prompt)
        self.last = {"input_tokens": 100, "output_tokens": 10, "cost": 0.001}
        return self.check(payload) if "trigger" in payload else self.classify(payload)

    def classify(self, payload):
        chat, out = self._chat(payload["chat"]["title"]), []
        for turn in payload["turns"]:
            gold = chat["turns"][int(turn["id"]) - 1]
            out.append({
                "id": turn["id"], "title": gold["title"], "depth": gold.get("depth") or 0, "seg": gold.get("seg"),
                "topic": None, "chose": bool(gold.get("dec")), "dec": gold.get("dec"), "ref": None,
                "parts": [{"t": p["t"], "type": p["type"], "target": None, "open": bool(p.get("open"))}
                          for p in gold.get("parts") or []],
                "wide": any(i["kind"] == "unasked" for i in gold.get("todo") or []),
            })
        return {"turns": out}

    def check(self, payload):
        need = {"missing": "get_request", "unasked": "get_diff", "handoff": "search_decisions"}
        used = {s["tool"]: s["saw"] for s in payload["steps"]}
        for trigger in payload["trigger"]:
            if need[trigger] not in used:
                return {"think": "근거를 먼저 봐요", "tool": need[trigger], "arg": None, "items": []}
        blank = {"text": "", "why": "정답", "part": None, "file": None, "asked": None, "what": None, "use": []}
        items = []
        for trigger in payload["trigger"]:
            saw = used[need[trigger]]
            if trigger == "missing":
                items += [dict(blank, kind="missing", part=p["no"]) for p in saw["parts"] if p["maybe_missing"]]
            elif trigger == "unasked":
                items.append(dict(blank, kind="unasked", file=saw["files"][0]["file"], asked="임계값", what="알림 문구"))
            else:
                items.append(dict(blank, kind="handoff", use=[d["id"] for d in saw["decisions"]]))
        return {"think": "다 봤어요", "tool": "finish", "arg": None, "items": items}


class Blind(Oracle):
    """모든 턴을 본류로, 아무것도 정하지 않고 나누지도 않았다고 답해요."""
    name = "blind"

    def classify(self, payload):
        return {"turns": [{"id": t["id"], "title": "제목", "depth": 0, "seg": None, "topic": None, "chose": False,
                           "dec": None, "ref": None, "parts": [], "wide": False} for t in payload["turns"]]}


class FeedTest(unittest.TestCase):
    def test_an_example_is_fed_in_order_with_what_a_hook_would_give(self):
        scenario = run.load(DEMO, "demo")
        with tempfile.TemporaryDirectory() as tmp:
            conn = store.connect(Path(tmp) / "gadak.db")
            self.addCleanup(conn.close)
            fed = replay.feed(conn, scenario)
            self.assertEqual(fed["chats"], ["demo:c1", "demo:c2"])
            self.assertEqual(list(fed["turns"]), [t["id"] for c in scenario["chats"] for t in c["turns"]])
            first, second = (store.chat_row(conn, c) for c in fed["chats"])
            self.assertLess(first["created_at"], second["created_at"])            # 뒤 대화가 더 새 대화여야 이어 가기가 걸려요
            self.assertEqual((first["site"], first["project_id"]), ("cursor", "환율 알리미"))
            rows = store.chat_turns(conn, "demo:c2")
            self.assertEqual([r["message_ref"] for r in rows], ["b1", "b2", "b3", "b4", "b5", "b6"])
            self.assertTrue(all(r["state"] == "done" and r["classified"] == 0 and r["dec"] is None for r in rows))  # 정답 칸은 안 넣어요
            edits = conn.execute("SELECT file, old, new FROM edits WHERE turn_id = ?", (fed["turns"]["b5"],)).fetchall()
            self.assertEqual([e["file"] for e in edits], ["notify.py"])
            self.assertIn("[환율 알림]", edits[0]["new"])
            self.assertNotIn("[환율 알림]", edits[0]["old"])
            files = [r["name"] for r in conn.execute("SELECT name FROM files WHERE turn_id = ? ORDER BY name", (fed["turns"]["b5"],))]
            self.assertEqual(files, ["main.py", "notify.py"])


class ScoreTest(unittest.TestCase):
    def setUp(self):
        self.scenario = run.load(DEMO, "demo")

    def test_answering_from_the_key_scores_full_marks(self):
        out = run.run(self.scenario, Oracle())
        result = score.score(self.scenario, out["view"])
        self.assertEqual((result["turns"], result["excluded"], result["unread"]), (12, 0, 0))
        self.assertEqual((result["depth"]["acc"], result["dec"]["recall"], result["dec"]["precision"], result["parts"]["rate"]),
                         (1.0, 1.0, 1.0, 1.0))
        self.assertEqual(result["depth"]["side"], {"gold": 3, "said": 3, "hit": 3, "recall": 1.0, "precision": 1.0})
        # 정답의 한마디 여섯(빠진 요청 · 내가 할 일 · 이해 확인 · 요청 외 변경 · 다음 할 일 · 이어 가기) 중 가닥이 만드는 종류는 셋
        items = result["items"]
        self.assertEqual((items["made"], items["right"], items["precision"], items["gold"], items["gold_made_kinds"]), (3, 3, 1.0, 6, 3))
        self.assertEqual(items["by_kind"]["yours"], {"gold": 1, "made": 0, "right": 0})
        self.assertEqual(out["stats"]["calls"]["classify"], 2)                    # 대화마다 6턴 → 한 번씩
        self.assertEqual([(t["turn"], t["trigger"], t["tools"], [i["kind"] for i in t["items"]], len(t["missing"])) for t in out["traces"]],
                         [("b5", ["unasked"], ["get_diff"], ["unasked"], 0),
                          ("b1", ["missing", "handoff"], ["get_request", "search_decisions"], ["handoff"], 1)])
        self.assertEqual(out["checks"]["ran"], 2)                                 # b1(빠진 요청 · 이어 가기) · b5(요청 외 변경)
        self.assertEqual((out["stats"]["tokens"], out["stats"]["cost_usd"]),
                         ({"in": 100 * sum(out["stats"]["calls"].values()), "out": 10 * sum(out["stats"]["calls"].values())},
                          round(0.001 * sum(out["stats"]["calls"].values()), 4)))
        self.assertIsNone(out["error"])

    def test_calling_everything_main_line_gives_the_baseline(self):
        out = run.run(self.scenario, Blind())
        result = score.score(self.scenario, out["view"])
        self.assertEqual(result["depth"]["acc"], result["depth"]["baseline"])     # 전부 본류라고 답한 값
        self.assertEqual((result["depth"]["right"], result["depth"]["side"]["recall"]), (9, 0.0))
        self.assertEqual((result["dec"]["recall"], result["dec"]["precision"]), (0.0, None))
        self.assertEqual((result["parts"]["right"], result["parts"]["split"]), (11, {"gold": 1, "said": 0, "hit": 0, "same": 0}))
        # 걸린 턴은 새 대화의 첫 턴뿐인데, 앞 대화에 정함이 없다고 답했으니 이어 가기도 안 걸려요
        self.assertEqual((result["items"]["made"], result["items"]["precision"], out["checks"]["ran"]), (0, None, 0))

    def test_turns_used_as_prompt_examples_are_left_out(self):
        out = run.run(self.scenario, Blind(), check=False)
        result = score.score(self.scenario, out["view"], exclude=["b2", "b3", "no-such-turn"])
        self.assertEqual((result["turns"], result["excluded"]), (10, 2))
        self.assertEqual(result["depth"]["side"]["gold"], 1)                      # 곁길 셋 중 둘을 뺐어요
        self.assertNotIn("check", result["items"]["by_kind"])                     # b3의 한마디도 같이 빠져요
        rows = score.details(self.scenario, out["view"], ["b2"])
        self.assertEqual(rows[7], {"id": "b2", "chat": "c2", "excluded": True, "read": True, "labeled": True, "depth": [1, 0],
                                   "dec": [False, False], "parts": [0, 0], "items": [[], []]})

    def test_turns_the_engine_failed_on_are_counted_as_shown(self):
        class Flaky(Oracle):
            """둘째 대화에서는 형식을 따르지 않고 글로만 답해요."""
            def classify(self, payload):
                if payload["chat"]["title"] == self.scenario["chats"][1]["title"]:
                    raise BadOutput("글로 답했어요")
                return super().classify(payload)

        out = run.run(self.scenario, Flaky())
        self.assertEqual(out["unlabeled"], ["b1", "b2", "b3", "b4", "b5", "b6"])
        self.assertIsNone(out["error"])                                           # 정리가 멈춘 것은 아니에요
        result = score.score(self.scenario, out["view"], unlabeled=out["unlabeled"])
        self.assertEqual((result["turns"], result["unlabeled"]), (12, 6))
        self.assertEqual(result["depth"]["side"], {"gold": 3, "said": 1, "hit": 1, "recall": 0.3333, "precision": 1.0})

    def test_a_wrong_nudge_lowers_precision(self):
        view = {"chats": [{"turns": [
            {"messageRef": "a1", "depth": 0, "todo": [{"kind": "handoff"}]},
            {"messageRef": "a2", "depth": 0, "parts": [{"t": "가", "type": "q", "open": True}, {"t": "나", "type": "q"}]},
        ]}]}
        scenario = {"chats": [{"id": "c1", "turns": [{"id": "a1"}, {"id": "a2", "parts": [{"t": "가", "type": "q"}, {"t": "나", "type": "q"}]}]}],
                    "startTodo": {"kind": "handoff"}}
        items = score.score(scenario, view)["items"]
        self.assertEqual((items["made"], items["right"], items["precision"]), (2, 1, 0.5))   # 빠진 요청은 정답에 없어요


class AgreeTest(unittest.TestCase):
    def test_kappa(self):
        self.assertEqual(agree.kappa([0, 1, 0, 1], [0, 1, 0, 1]), 1.0)
        self.assertEqual(agree.kappa([0, 0, 1, 1], [0, 1, 0, 1]), 0.0)           # 반만 맞고, 우연히도 반은 맞아요
        self.assertIsNone(agree.kappa([0, 0], [0, 0]))                           # 둘 다 한 가지 값만 썼으면 잴 수 없어요
        self.assertIsNone(agree.kappa([], []))

    def test_two_sheets_are_compared_on_the_turns_both_filled(self):
        scenario = run.load(DEMO, "demo")
        with tempfile.TemporaryDirectory() as tmp:
            blank = Path(tmp) / "빈 시트.csv"
            marked = agree.write_sheet(scenario, blank, n=8, seed=1)
            self.assertEqual(marked, 8)
            self.assertEqual(agree.read_sheet(blank), {})                        # 채우기 전
            text = blank.read_text(encoding="utf-8-sig")
            self.assertEqual(text.count(agree.MARK), 8)
            self.assertEqual(agree.pick(scenario, 8, 1), agree.pick(scenario, 8, 1))          # 같은 씨앗이면 같은 턴
            gold = agree.gold_labels(scenario)

            def fill(name, change):
                rows = []
                for line in text.splitlines()[1:]:
                    cells = next(iter(agree.csv.reader([line])))
                    if cells[0] == agree.MARK:
                        label = dict(gold[cells[1]])
                        change(cells[1], label)
                        cells[5:8] = [str(label["depth"]), str(label["dec"]), str(label["parts"] or 1)]   # 요청 하나는 1로 적어요
                    rows.append(cells)
                path = Path(tmp) / name
                with open(path, "w", encoding="utf-8-sig", newline="") as file:
                    writer = agree.csv.writer(file)
                    writer.writerow(agree.COLUMNS)
                    writer.writerows(rows)
                return path

            first = fill("A.csv", lambda turn, label: None)
            second = fill("B.csv", lambda turn, label: label.update(depth=0) if turn == "b3" else None)
            result = agree.compare(agree.read_sheet(first), agree.read_sheet(second))
            self.assertEqual(result["turns"], 8)
            self.assertEqual((result["dec"]["rate"], result["parts"]["rate"]), (1.0, 1.0))
            self.assertEqual((result["depth"]["same"], result["depth"]["differ"]), (7, ["b3"]))
            self.assertEqual(agree.compare(agree.read_sheet(first), gold)["depth"]["rate"], 1.0)
            with contextlib.redirect_stdout(io.StringIO()) as said:
                self.assertEqual(agree.main(["compare", str(first), str(second), "--demo"]), 0)
            self.assertIn("갈린 턴 b3", said.getvalue())


class CliTest(unittest.TestCase):
    def run_cli(self, *argv):
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(cli, "get_engine", lambda name: Oracle()), \
                mock.patch.object(cli, "resolve_name", lambda name=None: "oracle"), \
                mock.patch.object(cli, "RESULTS", Path(tmp) / "results"), mock.patch.object(cli, "LOCAL", Path(tmp) / "local"), \
                contextlib.redirect_stdout(io.StringIO()) as said:
            code = cli.main(list(argv))
            saved = {p.name: json.loads(p.read_text(encoding="utf-8")) for p in Path(tmp).rglob("*.json")}
        return code, said.getvalue(), saved

    def test_it_prints_the_four_numbers(self):
        code, said, saved = self.run_cli("--demo", "--model", "작은 모델")
        self.assertEqual(code, 0)
        for line in ("demo · 12턴 · oracle / 작은 모델", "depth 정확도       100.0% (12/12)", "dec 재현율         100.0% (5/5)",
                     "parts 개수 일치율  100.0% (12/12)", "items 정밀도       100.0% (3/3)", "호출 1단 2번"):
            self.assertIn(line, said)
        self.assertEqual(saved, {})                                              # --save를 줄 때만 남겨요

    def test_saved_results_hold_numbers_but_no_text(self):
        code, said, saved = self.run_cli("--demo", "--no-check", "--save", "--model", "정답", "--tag", "시험")
        self.assertEqual(code, 0)
        self.assertIn("items 정밀도       재지 않음", said)
        result = saved["demo-정답-시험.json"]
        self.assertEqual((result["scenario"], result["check"], result["result"]["depth"]["acc"]), ("demo", False, 1.0))
        text = json.dumps(saved, ensure_ascii=False)
        for words in ("임계값", "알림 문구", "환율"):                              # 대화 글 · 제목은 어디에도 남기지 않아요
            self.assertNotIn(words, text)

    def test_without_the_answer_file_it_says_where_to_get_it(self):
        with mock.patch.object(cli, "EXAMPLE", ROOT / "data" / "없는 파일.json"), \
                contextlib.redirect_stdout(io.StringIO()) as said:
            self.assertEqual(cli.main([]), 2)
        self.assertIn("python -m eval --demo", said.getvalue())


if __name__ == "__main__":
    unittest.main()
