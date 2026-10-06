import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from backend import config, store
from backend.agent import classify, investigate, tools, trace
from backend.app import create_app
from backend.engines import EngineError
from backend.runtime import Runtime

PROJECT = "환율 알리미"
CHAT = "chat-1"
NOTIFY_OLD = 'def notify(pair, rate):\n    text = f"{pair} {rate}원"\n    send(text)'
NOTIFY_NEW = 'def notify(pair, rate):\n    text = f"[환율 알림] {pair}이 {rate}원을 넘었어요"\n    send(text)'


def use(tool, arg=None, think="본다"):
    return {"think": think, "tool": tool, "arg": arg, "items": []}


def finish(*items, think="다 봤어요"):
    return {"think": think, "tool": "finish", "arg": None, "items": list(items)}


def item(kind, **fields):
    out = {"kind": kind, "text": "", "why": "", "part": None, "file": None, "asked": None, "what": None, "use": []}
    out.update(fields)
    return out


def labels(payload, **by_id):
    """1단 답: 받은 턴마다 제목만 붙이고, by_id로 준 턴은 그 값을 덮어써요."""
    turns = []
    for turn in payload["turns"]:
        answer = {"id": turn["id"], "title": "제목 " + turn["id"], "depth": 0, "seg": None, "topic": None,
                  "chose": False, "dec": None, "ref": None, "parts": [], "wide": False}
        answer.update(by_id.get("t" + turn["id"], {}))
        turns.append(answer)
    return {"turns": turns}


class Engine:
    """1단 · 2단을 같이 흉내 내요. 2단은 걸음마다 정해 둔 답을 차례로 돌려줘요."""
    name = "fake"

    def __init__(self, classify_answer=labels, steps=()):
        self.classify_answer = classify_answer
        self.steps = list(steps)
        self.calls = []

    def complete_json(self, system, prompt, schema):
        payload = json.loads(prompt)
        if "trigger" in payload:
            self.calls.append(("check", payload, schema))
            step = self.steps.pop(0) if self.steps else finish()
            return step(payload, schema) if callable(step) else step
        self.calls.append(("classify", payload, schema))
        return self.classify_answer(payload)

    def checks(self):
        return [c for c in self.calls if c[0] == "check"]


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = Path(self.tmp.name) / "gadak.db"

    def start(self, engine, max_calls=None):
        self.engine = engine
        self.rt = Runtime(self.db, engine=engine)
        self.clf = classify.Classifier(self.rt, engine, max_calls=max_calls)
        self.conn = self.rt.connect()
        self.addCleanup(self.conn.close)
        return self.clf

    def chat(self, chat_id=CHAT, project=PROJECT, title="알림 봇 구현", created_at=None):
        with self.conn:
            store.upsert_chat(self.conn, project=project, chat_id=chat_id, site="claude-code", title=title,
                              created_at=created_at, cwd="/work/fx")

    def turn(self, ref, user, ai="했어요.", chat_id=CHAT, edits=None, created_at=None):
        with self.conn:
            row = store.upsert_turn(self.conn, chat_id=chat_id, message_ref=ref, user=user, ai=ai, state="done",
                                    created_at=created_at)
            store.add_edits(self.conn, row["id"], edits)
        return row["id"]

    def row(self, turn_id):
        return self.conn.execute("SELECT * FROM turns WHERE id = ?", (turn_id,)).fetchone()

    def parts_open(self, turn_id):
        return [r["open"] for r in self.conn.execute("SELECT open FROM parts WHERE turn_id = ? ORDER BY idx", (turn_id,))]

    def run_worker(self, limit=20):
        steps = 0
        while self.clf.step(self.conn) and steps < limit:
            steps += 1
        return steps


class TriggerTest(Base):
    def test_stage_one_marks_what_stage_two_should_look_at(self):
        clf = self.start(Engine(lambda p: labels(
            p,
            t1={"wide": True},                                    # 파일이 안 바뀐 턴은 넓을 수가 없어요
            t2={"wide": True},
            t3={"parts": [{"t": "임계값 바꾸기", "type": "task", "target": None, "open": False},
                          {"t": "테스트는 어떻게 하냐", "type": "q", "target": None, "open": True}]},
        )))
        self.chat()
        one = self.turn("g1", "환율 가져오는 함수 만들어 줘")
        two = self.turn("g2", "임계값만 1300으로", edits=[{"file": "/work/fx/main.py", "old": "T = 1200", "new": "T = 1300"},
                                                       {"file": "/work/fx/notify.py", "old": NOTIFY_OLD, "new": NOTIFY_NEW}])
        three = self.turn("g3", "임계값 바꾸고, 테스트는 어떻게 해?")
        clf.classify_chat(self.conn, CHAT)
        payload = self.engine.calls[0][1]
        self.assertEqual(payload["turns"][1]["changed_lines"], {"main.py": 2, "notify.py": 2})
        self.assertNotIn("changed_lines", payload["turns"][0])
        self.assertEqual([self.row(t)["look"] for t in (one, two, three)], [None, "unasked", "missing"])
        self.assertEqual(self.parts_open(three), [0, store.MAYBE_MISSING])
        self.assertNotIn("open", store.turn_full(self.conn, three)["parts"][1])   # 후보는 화면에 안 보여요
        self.assertEqual(store.view(self.conn, PROJECT)["chats"][0]["checks"], 2)

    def test_a_new_chat_in_a_project_with_decisions_gets_a_handoff_check(self):
        clf = self.start(Engine())
        self.chat("old", title="환율 알리미 기획", created_at="2026-10-01T02:00:00Z")
        first_old = self.turn("o1", "알림은 텔레그램으로 하자", chat_id="old", created_at="2026-10-01T02:00:00Z")
        with self.conn:
            store.set_classification(self.conn, first_old, title="알림 채널", depth=0, dec="텔레그램 봇")
        self.chat("new", title="알림 봇 구현", created_at="2026-10-03T02:00:00Z")
        first = self.turn("n1", "봇 만들자", chat_id="new")
        second = self.turn("n2", "다음은?", chat_id="new")
        clf.classify_chat(self.conn, "new")
        self.assertEqual((self.row(first)["look"], self.row(second)["look"]), ("handoff", None))
        # 더 새 대화가 있으면 옛 대화의 첫 턴은 이어 가기를 볼 까닭이 없어요
        with self.conn:
            self.conn.execute("UPDATE turns SET classified = 0 WHERE id = ?", (first_old,))
        clf.classify_chat(self.conn, "old")
        self.assertIsNone(self.row(first_old)["look"])


class CheckTest(Base):
    def setUp(self):
        super().setUp()

    def unasked_turn(self, steps):
        """임계값만 바꿔 달랬는데 알림 문구도 바뀐 턴 (README 3-4 업무 A)."""
        self.start(Engine(lambda p: labels(p, t1={"wide": True}), steps))
        self.chat()
        turn_id = self.turn("g1", "임계값만 1300으로 바꿔 줘", "main.py와 notify.py를 고쳤어요.", edits=[
            {"file": "/work/fx/main.py", "old": "THRESHOLD = 1200", "new": "THRESHOLD = 1300"},
            {"file": "/work/fx/notify.py", "old": NOTIFY_OLD, "new": NOTIFY_NEW},
        ])
        self.clf.request(CHAT)
        self.run_worker()
        return turn_id

    def test_unasked_change_found_with_evidence_becomes_an_item(self):
        turn_id = self.unasked_turn([
            use("get_diff", think="파일 두 개가 바뀌었어요. 무엇이 바뀌었는지 봐요"),
            use("get_request"),
            finish(item("unasked", text="임계값만 요청했는데 알림 문구도 바뀌었어요",
                        why="요청은 main.py의 숫자 하나인데 notify.py의 메시지 형식이 같이 바뀌었어요.",
                        file="notify.py", asked="임계값", what="알림 문구")),
        ])
        checks = self.engine.checks()
        self.assertEqual(len(checks), 3)
        self.assertEqual(checks[0][1]["trigger"], ["unasked"])
        self.assertEqual(checks[0][1]["turn"]["changed_lines"], {"main.py": 2, "notify.py": 2})
        self.assertEqual(checks[1][1]["steps"][0]["saw"]["files"][1]["file"], "notify.py")   # 본 것이 다음 걸음에 실려요
        todo = store.turn_full(self.conn, turn_id)["todo"]
        self.assertEqual(len(todo), 1)
        it = todo[0]
        self.assertEqual((it["id"], it["kind"], it["btn"]), (turn_id + ":0", "unasked", "바뀐 곳 보기"))
        self.assertEqual(it["text"], "임계값만 요청했는데 알림 문구도 바뀌었어요")
        self.assertEqual(it["pop"]["title"], "요청 외 변경 · notify.py")
        self.assertIn(["d", '-    text = f"{pair} {rate}원"'], it["pop"]["diff"])
        self.assertIn(["a", '+    text = f"[환율 알림] {pair}이 {rate}원을 넘었어요"'], it["pop"]["diff"])
        self.assertEqual(it["pop"]["prompt"],
                         "notify.py에서 “알림 문구” 부분은 내가 요청하지 않았어. 원래대로 되돌리고, “임계값” 변경만 남겨 줘.")
        self.assertEqual(self.row(turn_id)["checked"], 1)
        runs = trace.runs(self.conn, turn_id=turn_id)
        self.assertEqual(len(runs), 1)
        run = runs[0]
        self.assertEqual([s["tool"] for s in run["steps"]], ["get_diff", "get_request"])
        self.assertEqual(run["steps"][0]["saw"], "파일 2개 · 바뀐 줄 4줄")
        self.assertEqual(run["steps"][0]["think"], "파일 두 개가 바뀌었어요. 무엇이 바뀌었는지 봐요")
        self.assertEqual((run["ended"], run["calls"], run["trigger"]), ("finish", 3, ["unasked"]))
        self.assertEqual(run["items"], [{"id": turn_id + ":0", "kind": "unasked", "text": it["text"]}])
        self.assertEqual((run["turn"]["n"], run["turn"]["project"]), ("01", PROJECT))
        self.assertNotIn("checks", store.view(self.conn, PROJECT)["chats"][0])
        self.assertEqual(self.clf.status["checks"], 1)

    def test_a_conclusion_without_evidence_is_dropped(self):
        turn_id = self.unasked_turn([finish(item("unasked", file="notify.py", asked="임계값", what="알림 문구"))])
        self.assertNotIn("todo", store.turn_full(self.conn, turn_id))
        run = trace.runs(self.conn, turn_id=turn_id)[0]
        self.assertEqual(run["dropped"], [{"kind": "unasked", "why": "바뀐 곳을 보지 않고 낸 결론이라 버렸어요"}])
        self.assertEqual(self.row(turn_id)["checked"], 1)

    def test_a_file_the_turn_did_not_touch_is_dropped_and_wording_falls_back(self):
        turn_id = self.unasked_turn([
            use("get_diff"),
            finish(item("unasked", file="config.py", what="설정"),
                   item("unasked", text="아주 " * 40, file="/work/fx/notify.py", what="알림 문구")),
        ])
        todo = store.turn_full(self.conn, turn_id)["todo"]
        self.assertEqual([t["text"] for t in todo], ["요청하지 않은 “알림 문구”도 바뀌었어요"])   # 너무 긴 글은 틀로
        self.assertEqual(todo[0]["pop"]["prompt"], "notify.py에서 “알림 문구” 부분은 내가 요청하지 않았어. 원래대로 되돌려 줘.")
        dropped = trace.runs(self.conn, turn_id=turn_id)[0]["dropped"]
        self.assertEqual(dropped, [{"kind": "unasked", "why": "이 턴에서 바뀐 파일이 아니라 버렸어요"}])

    def test_the_last_step_can_only_finish(self):
        def stubborn(payload, schema):
            if schema["properties"]["tool"]["enum"] == ["finish"]:
                return finish(think="더 볼 수 없어요")
            return use("get_diff")
        turn_id = self.unasked_turn([stubborn] * 10)
        checks = self.engine.checks()
        self.assertEqual(len(checks), investigate.config.MAX_STEPS)
        self.assertEqual(checks[-1][2]["properties"]["tool"]["enum"], ["finish"])
        self.assertEqual([c[1]["left"] for c in checks], list(range(investigate.config.MAX_STEPS - 1, -1, -1)))
        run = trace.runs(self.conn, turn_id=turn_id)[0]
        self.assertEqual((run["ended"], len(run["steps"]), run["think"]), ("finish", 4, "더 볼 수 없어요"))

    def test_an_engine_that_ignores_the_limit_stops_with_nothing(self):
        self.start(Engine())
        self.chat()
        turn_id = self.turn("g1", "임계값만", edits=[{"file": "/work/fx/main.py", "old": "a", "new": "b"}])
        row = self.row(turn_id)
        result = investigate.check(tools.Context(self.conn, row), ["unasked"],
                                   lambda *_: use("get_diff"), max_steps=3)
        self.assertEqual((result["ended"], len(result["steps"]), result["calls"], result["items"]), ("limit", 3, 3, []))
        odd = investigate.check(tools.Context(self.conn, row), ["unasked"], lambda *_: {"tool": "rm -rf"}, max_steps=3)
        self.assertEqual((odd["ended"], odd["calls"]), ("odd", 1))

    def test_missing_requests_are_confirmed_only_after_reading_the_answer(self):
        engine = Engine(lambda p: labels(p, t1={"parts": [
            {"t": "환율 가져오는 함수", "type": "task", "target": None, "open": False},
            {"t": "텔레그램으로 보내는 함수", "type": "task", "target": None, "open": True},
            {"t": "테스트는 어떻게 하냐", "type": "q", "target": None, "open": True},
        ]}), [use("get_request"), finish(item("missing", part=2, why="답에 테스트 이야기가 없어요."),
                                        item("missing", part=7))])
        self.start(engine)
        self.chat()
        turn_id = self.turn("g1", "환율 함수랑 텔레그램 함수 만들고, 테스트는 어떻게 해?", "두 함수를 만들었어요.")
        self.clf.request(CHAT)
        self.run_worker()
        self.assertEqual(self.parts_open(turn_id), [0, 0, store.MISSING])     # 짐작이 틀린 1번은 답함으로
        parts = store.turn_full(self.conn, turn_id)["parts"]
        self.assertEqual([p.get("open") for p in parts], [None, None, True])
        seen = engine.checks()[1][1]["steps"][0]["saw"]
        self.assertEqual([p["maybe_missing"] for p in seen["parts"]], [False, True, True])
        run = trace.runs(self.conn, turn_id=turn_id)[0]
        self.assertEqual(run["missing"], [{"no": 2, "t": "테스트는 어떻게 하냐", "why": "답에 테스트 이야기가 없어요."}])
        self.assertEqual(run["dropped"], [{"kind": "missing", "why": "이 턴에 없는 요청 번호라 버렸어요"}])
        opened = tools.list_open_items(tools.Context(self.conn, self.row(turn_id)))["items"]
        self.assertEqual([i["id"] for i in opened], [turn_id + ":p2"])

    def test_handoff_summarises_what_earlier_chats_decided(self):
        engine = Engine(steps=[
            use("search_decisions"),
            lambda payload, schema: finish(item("handoff", why="10/1에 알림 채널과 주기를 정했어요.",
                                                use=[d["id"] for d in payload["steps"][0]["saw"]["decisions"]] + ["없는-id"])),
        ])
        self.start(engine)
        self.chat("old", title="환율 알리미 기획", created_at="2026-10-01T02:00:00Z")
        decided = []
        for n, (text, dec) in enumerate([("매일 11시에 확인하자", "오전 11시 확인"), ("텔레그램으로 보내자", "텔레그램 봇")], 1):
            turn_id = self.turn(f"o{n}", text, chat_id="old", created_at=f"2026-10-01T02:0{n}:00Z")
            with self.conn:
                store.set_classification(self.conn, turn_id, title=text[:6], depth=0, dec=dec)
            decided.append(turn_id)
        self.chat("new", title="알림 봇 구현", created_at="2026-10-03T02:00:00Z")
        first = self.turn("n1", "봇 코드 짜자", chat_id="new")
        self.clf.request("new")
        self.run_worker()
        payload = engine.checks()[0][1]
        self.assertEqual(payload["trigger"], ["handoff"])
        self.assertEqual(payload["earlier_chats"][0]["decisions"], 2)
        todo = store.turn_full(self.conn, first)["todo"]
        self.assertEqual(len(todo), 1)
        it = todo[0]
        self.assertEqual((it["kind"], it["btn"], it["text"]), ("handoff", "요약 붙이기", "지난 대화에서 정한 것 2개를 이 대화에 붙일까요?"))
        date = store.display_date("2026-10-01T02:00:00+00:00")
        self.assertEqual(it["pop"]["text"], f"지난 대화({date} 환율 알리미 기획)에서 정한 것\n1. 오전 11시 확인\n2. 텔레그램 봇\n"
                                            "이 결정을 그대로 두고 이어서 진행해 줘.")
        self.assertEqual(it["pop"]["prompt"], it["pop"]["text"])


class ToolsTest(Base):
    # ----- 지난 결정 다시 꺼내기 (‘생각 못 한 방법 추천’ · 기본은 꺼 둠) -----

    def past_and_now(self, engine, question="알림은 어떻게 보내는 게 좋을까?"):
        """지난 대화에서 ‘텔레그램 봇’으로 정했고, 새 대화에서 방법을 물어요."""
        self.start(engine)
        self.chat("old", title="알림 봇 구상", created_at="2026-10-01T09:00:00+00:00")
        old = self.turn("a1", "알림은 텔레그램으로 하자", "텔레그램 봇으로 정할게요.", chat_id="old")
        with self.conn:
            store.set_classification(self.conn, old, title="알림 채널", depth=0, dec="텔레그램 봇")
        self.chat(created_at="2026-10-05T09:00:00+00:00")
        self.turn("g1", "뼈대부터 만들어 줘")
        now = self.turn("g2", question, "문자 · 메신저 · 메일이 있어요.")
        return old, now

    def test_suggestions_are_off_unless_turned_on(self):
        old, now = self.past_and_now(Engine())
        self.clf.request(CHAT)
        self.run_worker()
        self.assertIsNone(self.row(now)["look"])                           # 꺼 둔 동안에는 걸리지 않아요
        self.assertEqual(self.engine.checks()[0][1]["trigger"], ["handoff"])   # 원래 하던 확인만

    def test_a_past_decision_is_brought_back_when_the_user_asks_how(self):
        def find(payload, schema):
            self.assertIn("next", schema["properties"]["items"]["items"]["properties"]["kind"]["enum"])
            return use("search_decisions", "알림")
        # 지금에 가까운 턴(방법을 묻는 g2)부터 확인하고, 그다음 새 대화의 첫 턴(이어 가기)을 봐요
        engine = Engine(steps=[find, lambda p, s: finish(item(
            "next", text="아무 말", why="같은 알림 채널 이야기예요.", use=[p["steps"][0]["saw"]["decisions"][0]["id"], "t-없는-턴"])),
            finish()])
        with mock.patch.object(config, "SUGGEST", True):
            old, now = self.past_and_now(engine)
            self.clf.request(CHAT)
            self.run_worker()
        self.assertEqual(self.row(now)["look"], "suggest")
        system = [c for c in engine.calls if c[0] == "check"]
        made = store.turn_items(self.conn, now)
        self.assertEqual(len(made), 1)
        one = made[0]
        self.assertEqual((one["kind"], one["at"], one["btn"]), ("next", old, "이 방법으로"))
        self.assertEqual(one["text"], "전에 정한 것이 있어요: “텔레그램 봇”")            # 엔진의 말이 아니라 기록으로 만든 글
        self.assertIn("- 텔레그램 봇 (10/1 알림 봇 구상)", one["pop"]["prompt"])
        self.assertEqual(one["why"], "같은 알림 채널 이야기예요.")
        run = trace.runs(self.conn, turn_id=now)[0]
        self.assertEqual((run["trigger"], [s["tool"] for s in run["steps"]]), (["suggest"], ["search_decisions"]))
        records = [(r["name"], json.loads(r["fields_json"])) for r in self.conn.execute("SELECT * FROM usage")]
        self.assertIn(("item", {"kind": "next", "did": "made", "at": "auto"}), records)
        self.assertEqual(len(system), 3)                                   # 이어 가기 1 + 다시 꺼내기 2

    def test_a_suggestion_without_looking_or_about_a_fresh_decision_is_dropped(self):
        with mock.patch.object(config, "SUGGEST", True):
            # 찾아보지 않고 낸 결론
            old, now = self.past_and_now(Engine())
            ctx = tools.Context(self.conn, self.row(now))
            blind = investigate.check(ctx, ["suggest"], lambda *_: finish(item("next", use=[old])))
            self.assertEqual((blind["items"], blind["dropped"]), ([], [{"kind": "next", "why": "지난 결정을 찾아보지 않고 낸 결론이라 버렸어요"}]))
            # 찾아봤지만 거기 없던 턴을 근거로 댐
            answers = iter([use("search_decisions", "알림"), finish(item("next", use=[now]))])
            other = investigate.check(ctx, ["suggest"], lambda *_: next(answers))
            self.assertEqual(other["dropped"], [{"kind": "next", "why": "찾아본 결정이 아니거나 방금 정한 것이라 버렸어요"}])
            # 길을 묻는 턴이 아닌데 낸 결론
            answers = iter([use("search_decisions", "알림"), finish(item("next", use=[old]))])
            wrong = investigate.check(ctx, ["handoff"], lambda *_: next(answers))
            self.assertEqual(wrong["dropped"], [{"kind": "next", "why": "방법을 묻는 턴이 아니라 버렸어요"}])
            # 같은 대화에서 방금(가까이) 정한 것은 다시 꺼내지 않아요
            with self.conn:
                first = store.chat_turns(self.conn, CHAT)[0]
                store.set_classification(self.conn, first["id"], title="뼈대", depth=0, dec="함수 둘로 나눔")
            answers = iter([use("search_decisions", "함수"), finish(item("next", use=[first["id"]]))])
            near = investigate.check(ctx, ["suggest"], lambda *_: next(answers))
            self.assertEqual((near["items"], len(near["dropped"])), ([], 1))

    def test_only_turns_that_ask_how_with_something_decided_before_are_looked_at(self):
        with mock.patch.object(config, "SUGGEST", True):
            self.past_and_now(Engine(), question="임계값을 1,380원으로 바꿔 줘")      # 길을 묻지 않는 턴
            self.clf.request(CHAT)
            self.run_worker()
            self.assertEqual([r["look"] for r in store.chat_turns(self.conn, CHAT)], ["handoff", None])
        self.assertTrue(investigate.WONDERING.search("이건 어떻게 하지?"))
        self.assertTrue(investigate.WONDERING.search("Which one should I pick?"))
        self.assertFalse(investigate.WONDERING.search("임계값만 바꿔 줘"))

    def test_tools_read_within_the_project_only(self):
        self.start(Engine())
        self.chat("a", created_at="2026-10-01T00:00:00Z")
        a1 = self.turn("a1", "API는 공공 API로 하자", chat_id="a")
        self.chat("b")
        b1 = self.turn("b1", "임계값을 정하자", chat_id="b", edits=[{"file": "/work/fx/main.py", "old": None, "new": "T = 1\nU = 2"}])
        b2 = self.turn("b2", "공공 API 호출 코드", chat_id="b")
        self.chat("elsewhere", project="다른 프로젝트")
        far = self.turn("x1", "남의 프로젝트", chat_id="elsewhere")
        with self.conn:
            store.set_classification(self.conn, a1, title="API 고르기", depth=0, dec="공공 환율 API")
        ctx = tools.Context(self.conn, self.row(b2))
        self.assertEqual(tools.get_request(ctx)["id"], b2)
        self.assertEqual(tools.get_request(ctx, "1")["id"], b1)                    # 숫자는 이 대화의 차례
        self.assertEqual(tools.get_request(ctx, a1)["this_chat"], False)           # 지난 대화도 id로
        self.assertIn("error", tools.get_request(ctx, far))                        # 다른 프로젝트는 못 봐요
        diff = tools.get_diff(ctx, b1)
        self.assertEqual(diff["files"], [{"file": "main.py", "edits": 1, "changed": 2, "diff": "+T = 1\n+U = 2"}])
        self.assertIn("note", tools.get_diff(ctx))
        found = tools.search_decisions(ctx, "공공 API")
        self.assertEqual([d["id"] for d in found["decisions"]], [a1])
        self.assertNotIn("related", found)                                         # 지금 턴(b2)은 빼요
        related = tools.search_decisions(ctx, "임계값")
        self.assertEqual((related["decisions"], [r["id"] for r in related["related"]]), ([], [b1]))
        self.assertIn("note", related)
        self.assertEqual(tools.search_decisions(ctx, "없는말")["decisions"], [])
        self.assertEqual(tools.summary("search_decisions", found), "정한 것 1개")
        with self.conn:
            store.set_items(self.conn, b1, [{"kind": "unasked", "text": "하나", "why": "", "btn": "바뀐 곳 보기"},
                                            {"kind": "unasked", "text": "둘", "why": "", "btn": "바뀐 곳 보기"}])
            store.set_item_state(self.conn, b1 + ":1", "done")
        self.assertEqual([i["text"] for i in tools.list_open_items(ctx)["items"]], ["하나"])

    def test_a_chat_without_a_project_only_sees_itself(self):
        self.start(Engine())
        self.chat("solo", project=None)
        mine = self.turn("s1", "혼자", chat_id="solo")
        self.chat("other", project=None)
        other = self.turn("o1", "남", chat_id="other")
        with self.conn:
            store.set_classification(self.conn, other, title="남", depth=0, dec="남의 결정")
        ctx = tools.Context(self.conn, self.row(mine))
        self.assertIn("error", tools.get_request(ctx, other))
        self.assertEqual(tools.search_decisions(ctx)["decisions"], [])
        self.assertFalse(investigate.handoff_due(self.conn, store.chat_row(self.conn, "solo")))


class WorkerTest(Base):
    def test_checks_share_the_call_limit_and_resume_later(self):
        engine = Engine(lambda p: labels(p, t1={"wide": True}),
                        [use("get_diff"), use("get_request"), finish()])
        self.start(engine, max_calls=2)
        self.chat()
        turn_id = self.turn("g1", "임계값만", edits=[{"file": "/work/fx/main.py", "old": "a", "new": "b"}])
        self.clf.request(CHAT)
        self.run_worker()
        self.assertTrue(self.clf.status["paused"])
        self.assertIn("2번", self.clf.status["error"])
        self.assertEqual(self.row(turn_id)["checked"], 0)                 # 끝까지 못 봤으니 다음에 다시
        self.assertEqual(self.clf.checker.tries[turn_id], 0)              # 한도는 턴 탓이 아니라 실패로 안 세요
        self.assertEqual(trace.runs(self.conn), [])
        self.clf.max_calls = 10
        self.clf.resume()
        self.clf.checker.request(CHAT)
        self.run_worker()
        self.assertEqual(self.row(turn_id)["checked"], 1)

    def test_a_turn_that_keeps_failing_is_left_alone(self):
        def broken(payload, schema):
            raise ValueError("엉뚱한 답")
        engine = Engine(lambda p: labels(p, t1={"wide": True}), [broken] * 5)
        self.start(engine)
        self.chat()
        turn_id = self.turn("g1", "임계값만", edits=[{"file": "/work/fx/main.py", "old": "a", "new": "b"}])
        self.clf.request(CHAT)
        self.run_worker()
        self.assertEqual(self.row(turn_id)["checked"], -1)
        self.assertEqual(len(engine.checks()), investigate.MAX_TRIES)
        self.assertFalse(self.clf.step(self.conn))

    def test_engine_trouble_during_a_check_pauses_without_giving_up(self):
        def logged_out(payload, schema):
            raise EngineError("로그인이 필요해요")
        engine = Engine(lambda p: labels(p, t1={"wide": True}), [logged_out, logged_out, logged_out, use("get_diff"), finish()])
        self.start(engine)
        self.chat()
        turn_id = self.turn("g1", "임계값만", edits=[{"file": "/work/fx/main.py", "old": "a", "new": "b"}])
        self.clf.request(CHAT)
        for _ in range(3):
            self.run_worker()
            self.assertEqual((self.clf.status["paused"], self.clf.status["error"]), (True, "로그인이 필요해요"))
            self.clf.resume()
        self.run_worker()
        self.assertEqual(self.row(turn_id)["checked"], 1)                 # 세 번 막혔어도 포기하지 않았어요

    def test_no_engine_no_checks(self):
        self.start(None)
        self.chat()
        turn_id = self.turn("g1", "임계값만")
        with self.conn:
            store.set_classification(self.conn, turn_id, title="임계값", depth=0, look=["unasked"])
        self.clf.checker.request(CHAT)
        self.assertFalse(self.clf.step(self.conn))
        self.assertEqual(self.row(turn_id)["checked"], 0)


class TraceApiTest(unittest.TestCase):
    def test_trace_page_and_its_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = create_app(db_path=Path(tmp) / "gadak.db", engine=None)
            client = app.test_client()
            conn = store.connect(app.config["DB_PATH"])
            with conn:
                store.upsert_chat(conn, project=PROJECT, chat_id=CHAT, site="cursor", title="알림 봇 구현")
                row = store.upsert_turn(conn, chat_id=CHAT, message_ref="g1", user="임계값만", ai="했어요", state="done")
                trace.save(conn, row["id"], ["unasked"], {
                    "steps": [{"tool": "get_diff", "arg": None, "think": "본다", "saw": "파일 1개 · 바뀐 줄 2줄",
                               "data": {"id": row["id"], "files": [], "big": "x" * 9000}}],
                    "think": "요청 안이에요", "ended": "finish", "calls": 2, "missing": [], "dropped": [], "items": []})
            conn.close()
            page = client.get("/trace")
            self.assertEqual(page.status_code, 200)
            html = page.get_data(as_text=True)
            page.close()
            for path in ("ui/tokens.css", "ui/mark.js", "web/trace.css", "web/trace.js"):
                self.assertIn(path, html)
                with client.get("/" + path) as response:
                    self.assertEqual(response.status_code, 200, path)
            self.assertNotIn("<textarea", html)
            runs = client.get("/runs").get_json()["runs"]
            self.assertEqual(len(runs), 1)
            self.assertEqual((runs[0]["steps"][0]["label"], runs[0]["turn"]["chat"]), ("바뀐 곳 보기", "알림 봇 구현"))
            self.assertTrue(runs[0]["steps"][0]["data"]["cut"])                    # 큰 결과는 잘라서 남겨요
            self.assertEqual(client.get(f"/runs?project={PROJECT}").get_json()["runs"][0]["id"], runs[0]["id"])
            self.assertEqual(client.get("/runs?project=없음").get_json()["runs"], [])
            self.assertEqual(client.get(f"/turns/{row['id']}/trace").get_json()["runs"][0]["id"], runs[0]["id"])


if __name__ == "__main__":
    unittest.main()
