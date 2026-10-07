"""앞길 살피기 (backend/agent/ahead.py · outside.py): 갈림길 잡기, 길과 근거 검사, 기록 밖 도구의 안전장치, 일꾼."""
import json
import subprocess
import tempfile
import unicodedata
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from backend import config, store
from backend.agent import ahead, outside, tools, trace
from backend.app import create_app
from backend.engines import BadOutput, EngineError, claude_cli
from tests.test_investigate import CHAT, PROJECT, Base, Engine, finish, labels

OLD = "2026-10-01T09:00:00+00:00"


def step(tool, arg=None, think="본다"):
    return {"think": think, "tool": tool, "arg": arg, "goal": None, "paths": []}


def done(*paths, goal="환율 알림 봇 내보내기", think="다 봤어요"):
    return {"think": think, "tool": "finish", "arg": None, "goal": goal, "paths": list(paths)}


def path(kind, title="알림 문구부터 정하기", **fields):
    out = {"kind": kind, "title": title, "why": "방금 임계값을 정했어요.", "basis": [], "found": [],
           "ask": "알림 문구 후보를 세 개 만들어 줘."}
    out.update(fields)
    return out


def on(**more):
    """앞길 살피기를 켜고, 갈림길에서 저절로도 살피게 한 설정. (기본은 사용자가 누를 때만: AHEAD_AUTO=False)"""
    values = {"AHEAD": True, "AHEAD_AUTO": True, "AHEAD_WEB": False, "AHEAD_FILES": True, "AHEAD_MODEL": None}
    values.update(more)
    return mock.patch.multiple(config, **values)


class Story(Base):
    """지난 대화에서 알림 채널을 정했고, 지금 대화에서 임계값을 방금 정했어요."""

    def story(self, engine=None, last="임계값은 1300원으로 하자", cwd=None):
        self.start(engine or Engine())
        self.chat("old", title="알림 봇 구상", created_at=OLD)
        self.old = self.turn("o1", "알림은 텔레그램으로 하자", "텔레그램 봇으로 정할게요.", chat_id="old", created_at=OLD)
        self.asked = self.turn("o2", "디스코드로도 보낼 수 있어?", "웹훅을 쓰면 돼요.", chat_id="old",
                               created_at="2026-10-01T09:05:00+00:00")
        with self.conn:
            store.set_classification(self.conn, self.old, title="알림 채널", depth=0, dec="텔레그램 봇",
                                     dec_note="알림은 텔레그램 봇으로 보내기로 했어요.", gist=["텔레그램 봇으로 정했어요."])
            store.set_classification(self.conn, self.asked, title="디스코드 되냐", depth=1, gist=["웹훅을 쓰면 디스코드로도 돼요."])
            store.upsert_chat(self.conn, project=PROJECT, chat_id=CHAT, site="claude-code", title="알림 봇 구현",
                              created_at="2026-10-05T09:00:00+00:00", cwd=cwd or "/work/fx")
        self.first = self.turn("g1", "뼈대부터 만들어 줘", "함수 둘로 나눴어요.")
        self.second = self.turn("g2", "환율은 어디서 가져와?", "공공 API에서 가져와요.")
        self.now = self.turn("g3", last, "1300원으로 바꿨어요. 다음은 알림 문구예요.")
        with self.conn:
            store.set_classification(self.conn, self.first, title="뼈대 만들기", depth=0, gist=["함수 둘로 나눴어요."])
            store.set_classification(self.conn, self.second, title="환율 출처", depth=0)
            store.set_classification(self.conn, self.now, title="임계값 정하기", depth=0, dec="임계값 1300원",
                                     gist=["1300원으로 바꿨어요."])
        return tools.Context(self.conn, self.row(self.now))


class DueTest(unittest.TestCase):
    NOW = datetime(2026, 10, 7, 12, 0, tzinfo=timezone.utc)

    def rows(self, n, looks=None, age_minutes=1):
        made = (self.NOW - timedelta(minutes=age_minutes)).isoformat()
        return [{"seq": i + 1, "look": (looks or {}).get(i + 1), "created_at": made, "user": "고쳐 줘"} for i in range(n)]

    def due(self, rows, row=None, chat=None, **made):
        return ahead.due(chat or {"hidden": 0}, rows, row or rows[-1], made, now=self.NOW)

    def test_it_looks_by_itself_only_when_that_is_turned_on(self):
        self.assertIsNone(self.due(self.rows(5), dec="정함"))                 # 기본: 사용자가 누를 때만 돌아요
        with on(AHEAD_AUTO=False):
            self.assertIsNone(self.due(self.rows(5), dec="정함"))
        with on(AHEAD=False):
            self.assertIsNone(self.due(self.rows(5), dec="정함"))             # 버튼까지 감췄으면 저절로도 안 돌아요
        with on():
            self.assertEqual(self.due(self.rows(5), dec="정함"), "decided")
            rows = self.rows(5)                                               # 화면에서 켜고 끈 것(auto)이 설정보다 먼저예요
            self.assertIsNone(ahead.due({"hidden": 0}, rows, rows[-1], {"dec": "정함"}, now=self.NOW, auto=False))
        with on(AHEAD_AUTO=False):
            self.assertEqual(ahead.due({"hidden": 0}, rows, rows[-1], {"dec": "정함"}, now=self.NOW, auto=True), "decided")

    def test_only_junctions_on_the_last_fresh_turn_count(self):
        with on():
            rows = self.rows(6)
            self.assertIsNone(self.due(rows))                                  # 갈림길이 아닌 턴
            self.assertEqual(self.due(rows, seg="배포"), "stage")
            self.assertIsNone(self.due(rows, dec="정함", depth=1))             # 곁길에서 정한 것
            self.assertIsNone(self.due(rows, rows[2], dec="정함"))             # 지나간 턴
            self.assertIsNone(self.due(self.rows(2), dec="정함"))              # 읽을 노선이 아직 없어요
            self.assertIsNone(self.due(rows, chat={"hidden": 1}, dec="정함"))  # 목록에서 뺀 대화
            self.assertIsNone(self.due(self.rows(6, age_minutes=config.AHEAD_FRESH + 5), dec="정함"))   # 지난 일
            with mock.patch.object(config, "AHEAD_FRESH", 0):
                self.assertEqual(self.due(self.rows(6, age_minutes=99999), dec="정함"), "decided")
            asking = rows[:-1] + [dict(rows[-1], user="이제 뭐부터 하면 좋을까?")]
            self.assertEqual(self.due(asking), "asked")
            self.assertEqual(self.due(asking, dec="정함", depth=1), "asked")   # 물은 것이 먼저예요

    def test_it_does_not_look_again_too_soon(self):
        with on():
            every = config.AHEAD_EVERY
            near = self.rows(every + 2, looks={every: "ahead"})                # 두 턴 전에 살폈어요
            self.assertIsNone(self.due(near, dec="정함"))
            far = self.rows(every + 2, looks={2: "missing,ahead"})             # every턴 전
            self.assertEqual(self.due(far, dec="정함"), "decided")
            asked = near[:-1] + [dict(near[-1], user="다음에 뭐 해?")]
            self.assertEqual(self.due(asked), "asked")                         # 사용자가 물으면 간격을 덜 따져요
            just = self.rows(6, looks={5: "ahead"})
            self.assertIsNone(self.due(just[:-1] + [dict(just[-1], user="다음에 뭐 해?")]))

    def test_words_that_ask_what_is_next(self):
        for text in ("해야할거 뭐있지?", "이제 뭐하지", "다음에 뭐 해?", "남은 일 정리해 줘", "어떤 방향으로 가면 좋을까",
                     "What should we do next?"):
            self.assertEqual(ahead.reason(text, None, None, 0), "asked", text)
        for text in ("고쳐 줘", "푸시해줘", "디자인 방향을 바꾸자", "임계값만 1300으로"):
            self.assertIsNone(ahead.reason(text, None, None, 0), text)

    def test_stage_one_marks_the_junction(self):
        base = Base("run")
        base.setUp()
        self.addCleanup(base.doCleanups)
        clf = base.start(Engine(lambda p: labels(p, t3={"chose": True, "dec": "임계값 1300원"})))
        base.chat()
        ids = [base.turn("g1", "뼈대부터"), base.turn("g2", "환율은 어디서?"), base.turn("g3", "1300원으로 하자")]
        clf.classify_chat(base.conn, CHAT)
        self.assertEqual([base.row(i)["look"] for i in ids], [None, None, None])       # 꺼 둔 동안
        with on(), base.conn:
            for i in ids:
                store.reset_classification(base.conn, i)
        with on():
            clf.tries.clear()
            clf.classify_chat(base.conn, CHAT)
        self.assertEqual([base.row(i)["look"] for i in ids], [None, None, "ahead"])


class ScoutTest(Story):
    def test_gadak_looks_first_and_paths_are_built_from_what_was_found(self):
        ctx = self.story()
        seen = []

        def find(payload, schema):
            seen.append((payload, schema["properties"]["tool"]["enum"]))
            return step("search_turns", "디스코드")

        def conclude(payload, schema):
            seen.append((payload, schema["properties"]["tool"]["enum"]))
            hit = payload["steps"][-1]["saw"]["turns"][0]["id"]
            return done(
                path("onward", basis=[payload["now"]["id"]]),                    # 찾아본 것이 없는 길
                path("other", "디스코드로도 보내기", why="전에 한 번 물어봤어요.", basis=[payload["now"]["id"], "t-없는-턴"],
                     found=[{"line": "웹훅을 쓰면 디스코드로도 보낼 수 있어요.", "source": hit},
                            {"line": "지어낸 줄이에요.", "source": "https://example.com/made-up"}],
                     ask="알림을 디스코드 웹훅으로도 보내게 해 줘."),
                path("check", "알림 채널부터 맞추기", basis=["2"], found=[{"line": "알림은 텔레그램 봇으로 보내기로 했어요.", "source": self.old}],
                     ask="알림 문구를 텔레그램 봇에 맞게 써 줘."),
            )

        answers = iter([find, conclude])
        result = ahead.scout(ctx, "asked", lambda system, payload, schema: next(answers)(json.loads(payload), schema))
        first, choices = seen[0]
        self.assertEqual(first["ahead"], {"why": "asked"})
        self.assertEqual(first["tools"], list(ahead.RECORD_TOOLS))                 # 폴더가 없고 웹도 꺼 둠
        self.assertEqual(choices, list(ahead.RECORD_TOOLS) + ["finish"])
        self.assertNotIn("lookups_left", first)
        # 가닥이 늘 먼저 보는 것은 엔진에게 묻지 않고 이미 찾아 둬요
        self.assertEqual([(s["tool"], s.get("by")) for s in first["steps"]], [("search_decisions", "gadak"), ("list_open_items", "gadak")])
        self.assertEqual([d["dec"] for d in first["steps"][0]["saw"]["decisions"]], ["임계값 1300원", "텔레그램 봇"])
        self.assertEqual((first["now"]["title"], first["now"]["llm_answer"]["summary"]), ("임계값 정하기", ["1300원으로 바꿨어요."]))
        self.assertIn("다음은 알림 문구예요", first["now"]["llm_answer"]["ending"])
        self.assertEqual([t["title"] for t in first["recent"]], ["뼈대 만들기", "환율 출처"])
        self.assertEqual(first["decided"], [{"id": self.now, "seq": 3, "what": "임계값 1300원"}])
        self.assertEqual((first["earlier"][0]["title"], first["stages"]), ("알림 봇 구상", []))
        self.assertEqual((result["goal"], result["ended"], result["calls"], len(result["steps"])), ("환율 알림 봇 내보내기", "finish", 2, 3))
        self.assertEqual([i["text"] for i in result["items"]], ["다른 길 · 디스코드로도 보내기", "미리 챙길 것 · 알림 채널부터 맞추기"])
        other = result["items"][0]
        self.assertEqual((other["kind"], other["btn"], other["pop"]["btn"]), ("next", "이 길 보기", "이 길로 묻기"))
        self.assertNotIn("at", other)
        text = other["pop"]["text"]
        for line in ("지금 하려는 일\n환율 알림 봇 내보내기", "다른 길: 디스코드로도 보내기", "· ‘임계값 정하기’ (이 대화)",
                     "· 웹훅을 쓰면 디스코드로도 보낼 수 있어요. (10/1 알림 봇 구상 ‘디스코드 되냐’)",
                     "보낼 글\n알림을 디스코드 웹훅으로도 보내게 해 줘."):
            self.assertIn(line, text)
        self.assertNotIn("지어낸", text)                                           # 출처가 도구 결과에 없는 줄은 빼요
        self.assertTrue(other["pop"]["prompt"].startswith("알림을 디스코드 웹훅으로도 보내게 해 줘."))
        self.assertIn("참고로 미리 찾아본 것이야", other["pop"]["prompt"])
        self.assertEqual((result["cut"], result["dropped"]), (1, [
            {"kind": "onward", "why": "찾아본 것이 없는 길이라 버렸어요"},
            {"kind": "other", "why": "출처로 칠 수 없는 줄 1개를 뺐어요 (길은 남겼어요)"}]))
        self.assertEqual(result["paths"][1]["basis"], [{"id": self.second, "title": "환율 출처"}])   # 차례 번호로 가리켜도 돼요
        self.assertEqual(result["paths"][0]["found"], [{"line": "웹훅을 쓰면 디스코드로도 보낼 수 있어요.", "from": "turn", "source": self.asked}])

    def test_what_was_found_must_come_from_outside_the_talk_at_hand(self):
        ctx = self.story()
        far = {"line": "알림은 텔레그램 봇으로 보내기로 했어요.", "source": self.old}          # 지난 대화의 결정 (가닥이 먼저 찾아 둔 것)
        answers = iter([step("search_turns", "뼈대"), done(
            path("onward", "근거가 없는 턴", basis=["t-없는-턴"], found=[far]),
            path("other", basis=[], found=[far]),
            path("check", "지금 턴을 출처로 댐", basis=[self.now], found=[{"line": "방금 1300원으로 바꿨어요.", "source": self.now}]),
            path("check", "방금 대화를 출처로 댐", basis=[self.now], found=[{"line": "함수 둘로 나눴어요.", "source": self.first}]),
            path("onward", "보낼 글이 빈 길", basis=[self.now], found=[far], ask="  "),
            path("sideways", basis=[self.now], found=[far]),
            path("onward", basis=[self.now], found=[far]),
            path("onward", "두 번째 이어 가기", basis=[self.now], found=[far]),
        )])
        result = ahead.scout(ctx, "asked", lambda *_: next(answers))
        self.assertEqual(result["steps"][-1]["data"]["turns"][0]["id"], self.first)            # 찾아봤지만 방금 대화의 것
        self.assertEqual([i["text"] for i in result["items"]], ["이어 가기 · 알림 문구부터 정하기"])
        self.assertEqual([d["why"] for d in result["dropped"]], [
            "근거가 된 턴이 이번에 본 기록에 없어서 버렸어요", "근거가 된 턴이 이번에 본 기록에 없어서 버렸어요",
            "찾아본 것이 없는 길이라 버렸어요 (출처로 칠 수 없는 줄 1개)", "찾아본 것이 없는 길이라 버렸어요 (출처로 칠 수 없는 줄 1개)",
            "길의 이름이나 보낼 글이 없어서 버렸어요", "모르는 종류라 버렸어요", "같은 종류의 길이 이미 있어서 버렸어요"])
        # 이 대화에서도 한참 앞의 턴은 출처가 돼요
        with mock.patch.object(ahead, "NEAR", 2):
            again = iter([step("search_turns", "뼈대"), done(path("check", basis=[self.now], found=[
                {"line": "함수 둘로 나눴어요.", "source": self.first}]))])
            self.assertEqual(len(ahead.scout(ctx, "decided", lambda *_: next(again))["items"]), 1)
        # 누가 눌렀든 가닥이 먼저 말을 걸든, 찾아본 것이 없으면 아무 말도 하지 않아요
        for why in ahead.WHYS:
            quiet = ahead.scout(ctx, why, lambda *_: done(path("onward", basis=[self.now])))
            self.assertEqual((quiet["items"], quiet["calls"]), ([], 1), why)

    def test_turn_ids_never_show_in_what_people_read(self):
        ctx = self.story()
        leaky = done(path(
            "other", f"{self.asked}에서 본 길 다시 보기", why=f"{self.asked}에서 물었고 {self.old}에서 정했어요. tffffffffff는 없는 턴이에요.",
            basis=[self.now], found=[{"line": f"{self.asked}에서 웹훅이면 된다고 했어요.", "source": self.asked}],
            ask=f"{self.asked}에서 말한 웹훅으로 보내 줘."))
        answers = iter([step("search_turns", "디스코드"), leaky])
        result = ahead.scout(ctx, "asked", lambda *_: next(answers))
        item, shown = result["items"][0], result["paths"][0]
        self.assertEqual(shown["title"], "‘디스코드 되냐’에서 본 길 다시 보기")
        self.assertEqual(shown["why"], "‘디스코드 되냐’에서 물었고 ‘알림 채널’에서 정했어요. 는 없는 턴이에요.")
        self.assertEqual((shown["ask"], shown["found"][0]["line"]), ("‘디스코드 되냐’에서 말한 웹훅으로 보내 줘.", "‘디스코드 되냐’에서 웹훅이면 된다고 했어요."))
        self.assertEqual(shown["found"][0]["source"], self.asked)             # 출처 칸에는 id가 그대로 (화면에는 제목으로 풀어 보여 줘요)
        for text in (item["text"], item["why"], item["pop"]["text"], item["pop"]["prompt"]):
            self.assertIsNone(ahead.TURN_ID.search(text), text)

    def test_it_stands_on_the_turn_and_does_not_see_what_came_after(self):
        ctx = self.story()
        later = self.turn("g4", "알림 문구는 짧게 하자", "짧게 바꿨어요.",
                          created_at=(datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat())
        with self.conn:
            store.set_classification(self.conn, later, title="알림 문구", depth=0, dec="문구는 짧게")
        answers = iter([step("search_turns", "문구"), step("get_request", later),
                        done(path("onward", basis=[later], found=[{"line": "문구는 짧게 하기로 했어요.", "source": later}]))])
        result = ahead.scout(ctx, "decided", lambda *_: next(answers))
        saw = [s["data"] for s in result["steps"]]
        self.assertEqual([d["dec"] for d in saw[0]["decisions"]], ["임계값 1300원", "텔레그램 봇"])   # 가닥이 먼저 본 것도 그 턴까지만
        self.assertEqual(saw[2]["turns"], [])
        self.assertIn("error", saw[3])
        self.assertEqual((result["items"], len(result["dropped"])), ([], 1))
        self.assertEqual(tools.search_decisions(tools.Context(self.conn, self.row(self.now)))["decisions"][0]["dec"], "문구는 짧게")   # 2단의 다른 일은 그대로 다 봐요

    def test_the_last_step_can_only_finish_and_odd_tools_stop_it(self):
        ctx = self.story()
        schemas = []

        def call(system, payload, schema):
            schemas.append(schema["properties"]["tool"]["enum"])
            return step("list_open_items")

        result = ahead.scout(ctx, "asked", call, max_steps=3)
        self.assertEqual((result["ended"], result["calls"], result["items"]), ("limit", 3, []))
        self.assertEqual((schemas[0], schemas[-1]), (list(ahead.RECORD_TOOLS) + ["finish"], ["finish"]))
        self.assertEqual(len(result["steps"]), 2 + 3)                               # 가닥이 먼저 본 둘 + 엔진이 고른 셋
        self.assertEqual(ahead.scout(ctx, "asked", call, max_steps=1)["calls"], 1)   # 한 걸음뿐이면 끝내는 것만
        odd = ahead.scout(ctx, "asked", lambda *_: step("get_diff"))
        self.assertEqual((odd["ended"], odd["items"]), ("odd", []))

    def test_web_lookups_are_offered_only_when_on_and_counted(self):
        ctx = self.story()
        asked = []

        def lookup(question):
            asked.append(question)
            return {"found": [{"line": "텔레그램 봇은 초당 30건까지 보낼 수 있어요.", "source": "https://core.telegram.org/bots/faq#broadcasting"},
                              {"line": "", "source": "https://x.example"}],
                    "searched": ["telegram bot rate limit"]}

        ctx.lookup = lookup
        tools_seen = []

        def first(payload, schema):
            tools_seen.append((payload["tools"], payload["lookups_left"]))
            return step("look_up", "텔레그램 봇 전송 한도")

        answers = iter([first, lambda p, s: step("look_up", "두 번째"), lambda p, s: step("look_up", "세 번째"),
                        lambda p, s: done(path("check", "전송 한도 챙기기", basis=[self.now], found=[
                            {"line": "초당 30건까지예요.", "source": "https://core.telegram.org/bots/faq/"},
                            {"line": "검색에 없던 주소예요.", "source": "https://core.telegram.org/other"}]))])
        result = ahead.scout(ctx, "decided", lambda system, payload, schema: next(answers)(json.loads(payload), schema))
        mine = [s for s in result["steps"] if not s.get("by")]
        self.assertEqual(tools_seen, [(list(ahead.RECORD_TOOLS) + ["look_up"], ahead.LOOKUPS)])
        self.assertEqual((asked, result["lookups"]), (["텔레그램 봇 전송 한도", "두 번째"], 2))       # 한도를 넘으면 부르지 않아요
        self.assertIn("error", mine[2]["data"])
        item = result["items"][0]
        self.assertIn("· 초당 30건까지예요. (core.telegram.org)", item["pop"]["text"])
        figures = iter([step("look_up", "한도"), done(path("check", basis=[self.now], found=[
            {"line": "초당 300건까지 보낼 수 있어요.", "source": "https://core.telegram.org/bots/faq"}]))])   # 웹에서 본 것은 30건
        self.assertEqual(ahead.scout(ctx, "decided", lambda *_: next(figures))["items"], [])
        self.assertIn("(https://core.telegram.org/bots/faq#broadcasting)", item["pop"]["prompt"])   # 보낼 글에는 주소를 그대로
        self.assertNotIn("검색에 없던", item["pop"]["text"])
        self.assertEqual(outside.summary("look_up", mine[0]["data"]), "찾은 것 1줄 · 검색 1번")
        self.assertIn("error", outside.look_up(tools.Context(self.conn, self.row(self.now)), "무엇"))   # 꺼 둔 동안


class OutsideTest(Story):
    def folder(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        base = Path(tmp.name) / "fx"
        (base / "src").mkdir(parents=True)
        (base / "node_modules" / "x").mkdir(parents=True)
        (base / "README.md").write_text("# 환율 알리미\n\n" + "설명 줄\n" * 2000 + "\n## 남은 일과 일정\n- 10/10까지 알림 문구\n",
                                        encoding="utf-8")
        (base / "가닥").mkdir()
        (base / "가닥" / "계획.md").write_text("# 계획\n\n### 아직 안 정한 것\n- 알림 채널\n", encoding="utf-8")
        (base / "src" / "main.py").write_text("T = 1300\n", encoding="utf-8")
        (base / "src" / "logo.png").write_bytes(b"\x89PNG\r\n")
        (base / "node_modules" / "x" / "index.js").write_text("x", encoding="utf-8")
        (base / ".env").write_text("TOKEN=secret", encoding="utf-8")
        (base / "서버-정보.local.md").write_text("암호", encoding="utf-8")
        (base / "notes.md").write_text("깃이 무시하는 메모", encoding="utf-8")
        (base / "big.md").write_text("x" * (outside.READ_BYTES + 1), encoding="utf-8")
        (base / "bad.txt").write_bytes(b"\xff\xfe\x00")
        (Path(tmp.name) / "outside.md").write_text("폴더 밖", encoding="utf-8")
        (base / "link.md").symlink_to(Path(tmp.name) / "outside.md")
        return base

    def git(self, base):
        (base / ".gitignore").write_text("notes.md\n.env\n", encoding="utf-8")
        subprocess.run(["git", "init", "-q", str(base)], check=True, capture_output=True)

    def test_files_are_read_only_inside_the_folder_and_never_secrets(self):
        base = self.folder()
        self.git(base)
        ctx = self.story(cwd=str(base))
        with on():
            self.assertEqual(ahead.tool_names(ctx), ahead.RECORD_TOOLS + outside.FILE_TOOLS)
        with on(AHEAD_FILES=False):
            self.assertEqual(ahead.tool_names(ctx), ahead.RECORD_TOOLS)
        listed = outside.list_files(ctx)
        names = [f["path"] for f in listed["files"]]
        self.assertEqual(listed["folder"], "fx")
        for name in ("README.md", "src/main.py", "big.md", "link.md", "가닥/계획.md"):
            self.assertIn(name, names)
        for name in (".env", "서버-정보.local.md", "notes.md", "src/logo.png", "node_modules/x/index.js", ".gitignore"):
            self.assertNotIn(name, names)
        self.assertEqual([f["path"] for f in outside.list_files(ctx, "src")["files"]], ["src/main.py"])
        self.assertIn("error", outside.list_files(ctx, "../"))
        read = outside.read_file(ctx, "README.md")
        self.assertEqual((read["path"], read["cut"], len(read["text"])), ("README.md", True, outside.READ_CHARS))
        self.assertEqual(outside.read_file(ctx, "src/main.py")["text"], "T = 1300\n")
        refused = {"../outside.md": "안의 경로만", "/etc/hosts": "안의 경로만", "link.md": "밖을 가리키는",
                   ".env": "비밀", "서버-정보.local.md": "비밀", "notes.md": "깃이 무시하는", "src/logo.png": "글 파일만",
                   "big.md": "너무 큰", "bad.txt": "글로 읽을 수 없는", "없는파일.md": "파일이 없어요", "": "경로를"}
        for name, why in refused.items():
            self.assertIn(why, outside.read_file(ctx, name).get("error", ""), name)
        self.assertEqual(outside.summary("read_file", read), f"README.md · {read['lines']}줄 (한 부분만)")
        self.assertEqual(outside.summary("list_files", listed), f"파일 {len(names)}개")
        # 낱말로 찾기: 읽어도 되는 파일에서만
        hits = outside.search_files(ctx, "1300 설명")
        self.assertEqual(hits["files"], 2)
        self.assertEqual(hits["hits"][0], {"path": "README.md", "line": 3, "text": "설명 줄"})      # 많이 든 파일부터
        # 문서의 목차: 계획 · 일정 · 미정이 적힌 제목과 줄 번호 (가닥이 먼저 보는 것)
        heads = outside.headings(ctx, ahead.PLAN_WORDS)
        self.assertEqual(heads["hits"], [{"path": "README.md", "line": 2004, "text": "남은 일과 일정"},
                                         {"path": "가닥/계획.md", "line": 1, "text": "계획"},
                                         {"path": "가닥/계획.md", "line": 3, "text": "아직 안 정한 것"}])
        self.assertEqual(heads["hits"][1]["path"], unicodedata.normalize("NFC", "가닥/계획.md"))     # 한글 이름은 붙여 쓴 표기로
        self.assertEqual(outside.read_file(ctx, unicodedata.normalize("NFD", "가닥/계획.md") + ":4")["from_line"], 2)
        self.assertEqual(len([h for h in hits["hits"] if h["path"] == "README.md"]), outside.HITS_PER_FILE)
        self.assertIn({"path": "src/main.py", "line": 1, "text": "T = 1300"}, hits["hits"])
        self.assertGreater(hits["more"], 1000)
        for word in ("secret", "암호", "무시하는", "폴더 밖"):                       # .env · *.local.* · 깃이 무시하는 파일 · 폴더 밖
            self.assertEqual(outside.search_files(ctx, word)["hits"], [], word)
        self.assertIn("error", outside.search_files(ctx, "x"))
        self.assertEqual(outside.summary("search_files", hits), "파일 2개에서 9줄 (더 있음)")
        spot = outside.read_file(ctx, "README.md:1500")
        self.assertEqual((spot["from_line"], spot["text"].splitlines()[0], spot["path"]), (1498, "설명 줄", "README.md"))
        with on():       # 작업 폴더가 있으면 가닥이 목차도 먼저 봐요. 길의 출처는 풀어 쓴 표기로 적어도 같은 파일이에요
            answers = iter([lambda p, s: done(path("check", basis=[p["now"]["id"]], found=[
                {"line": "알림 채널이 아직 미정이에요.", "source": unicodedata.normalize("NFD", "가닥/계획.md") + ":3"}]))])
            result = ahead.scout(ctx, "decided", lambda system, payload, schema: next(answers)(json.loads(payload), schema))
        self.assertEqual([(s["tool"], s["arg"]) for s in result["steps"]],
                         [("search_decisions", None), ("list_open_items", None), ("search_files", "계획 · 일정 · 미정 · 규칙이 적힌 곳")])
        self.assertEqual(len(result["steps"][2]["data"]["hits"]), 3)
        self.assertEqual(len(result["items"]), 1)

    def test_a_folder_that_is_not_a_repo_is_walked_and_a_chat_without_one_has_no_file_tools(self):
        base = self.folder()
        ctx = self.story(cwd=str(base))
        names = [f["path"] for f in outside.list_files(ctx)["files"]]
        self.assertIn("notes.md", names)                       # 깃이 없으면 이름으로만 가려요
        self.assertNotIn(".env", names)
        self.assertNotIn("node_modules/x/index.js", names)
        with self.conn:
            self.conn.execute("UPDATE chats SET cwd = NULL WHERE id = ?", (CHAT,))
        bare = tools.Context(self.conn, self.row(self.now))
        with on():
            self.assertEqual(ahead.tool_names(bare), ahead.RECORD_TOOLS)
        self.assertIn("error", outside.list_files(bare))
        self.assertIn("error", outside.read_file(bare, "README.md"))

    def test_a_repo_inside_the_folder_keeps_its_ignore_rules_and_broad_folders_are_not_read(self):
        base = self.folder()
        inner = base / "inner"
        inner.mkdir()
        (inner / "kept.md").write_text("# 일정\n- 남길 글", encoding="utf-8")
        (inner / "draft.md").write_text("올리지 않기로 한 초안", encoding="utf-8")
        (inner / ".gitignore").write_text("draft.md\n", encoding="utf-8")
        subprocess.run(["git", "init", "-q", str(inner)], check=True, capture_output=True)
        ctx = self.story(cwd=str(base))                         # 작업 폴더는 저장소가 아니고, 그 안에 저장소가 하나 있어요
        names = [f["path"] for f in outside.list_files(ctx)["files"]]
        self.assertIn("inner/kept.md", names)
        self.assertNotIn("inner/draft.md", names)
        self.assertEqual(outside.search_files(ctx, "초안")["hits"], [])
        self.assertIn("깃이 무시하는", outside.read_file(ctx, "inner/draft.md")["error"])
        self.assertEqual(outside.read_file(ctx, "inner/kept.md")["lines"], 2)
        self.assertIn({"path": "inner/kept.md", "line": 1, "text": "일정"}, outside.headings(ctx, ahead.PLAN_WORDS)["hits"])
        # 홈 · 문서 · 바탕화면처럼 넓은 곳에서 연 대화에서는 파일을 읽지 않아요
        home = base.parent
        (home / "Documents" / "보고서").mkdir(parents=True)
        with mock.patch.object(outside.Path, "home", return_value=home), on():
            for cwd, allowed in ((home, False), (home / "Documents", False), (home.parent, False),
                                 (home / "Documents" / "보고서", True), (base, True)):
                with self.conn:
                    self.conn.execute("UPDATE chats SET cwd = ? WHERE id = ?", (str(cwd), CHAT))
                here = tools.Context(self.conn, self.row(self.now))
                self.assertEqual(outside.root(here) is not None, allowed, cwd)
                self.assertEqual("read_file" in ahead.tool_names(here), allowed, cwd)

    def test_without_git_files_inside_a_repo_are_left_alone(self):
        base = self.folder()
        inner = base / "inner"
        inner.mkdir()
        (inner / "kept.md").write_text("# 일정", encoding="utf-8")
        subprocess.run(["git", "init", "-q", str(inner)], check=True, capture_output=True)
        ctx = self.story(cwd=str(base))
        with mock.patch.object(outside, "git_ready", return_value=False), mock.patch.object(outside.subprocess, "run") as run:
            names = [f["path"] for f in outside.list_files(ctx)["files"]]
            self.assertIn("README.md", names)                      # 저장소가 아닌 곳의 파일은 이름으로만 가려서 봐요
            self.assertNotIn("inner/kept.md", names)               # 저장소 안은 무엇을 무시하기로 했는지 몰라서 안 봐요
            self.assertIn("깃을 쓸 수 없어서", outside.read_file(ctx, "inner/kept.md")["error"])
            self.assertEqual(outside.read_file(ctx, "src/main.py")["text"], "T = 1300\n")
            run.assert_not_called()                                # 깃을 부르지 않아요 (개발자 도구 설치 창이 뜨지 않게)
            with self.conn:
                self.conn.execute("UPDATE chats SET cwd = ? WHERE id = ?", (str(inner), CHAT))
            self.assertEqual(outside.list_files(tools.Context(self.conn, self.row(self.now)))["files"], [])
        self.assertTrue(outside.git_ready())                       # 이 PC에는 깃이 있어요 (위의 저장소도 깃으로 만들었어요)

    def test_a_file_that_was_read_can_be_a_source(self):
        base = self.folder()
        ctx = self.story(cwd=str(base))
        answers = iter([step("search_files", "1300"), done(path("check", basis=[self.now], found=[
            {"line": "임계값이 코드에 1300으로 박혀 있어요.", "source": "src/main.py:1"},
            {"line": "찾아보지 않은 파일이에요.", "source": "src/other.py"}]))])
        with on():
            result = ahead.scout(ctx, "decided", lambda *_: next(answers))
        self.assertIn("· 임계값이 코드에 1300으로 박혀 있어요. (src/main.py:1)", result["items"][0]["pop"]["text"])
        self.assertEqual(result["cut"], 1)
        again = iter([step("read_file", "README.md"), done(path("other", basis=[self.now], found=[
            {"line": "README에 설명이 있어요.", "source": "README.md"}]))])
        with on():
            self.assertEqual(len(ahead.scout(ctx, "decided", lambda *_: next(again))["items"]), 1)
        # 간추리다 수를 틀리게 옮긴 줄은 빼요: 출처의 글에 없는 번호 · 날짜 · 퍼센트
        wrong = iter([step("read_file", "README.md:2004"), done(path("check", basis=[self.now], found=[
            {"line": "10/10까지 알림 문구를 끝내야 해요.", "source": "README.md:2005"},
            {"line": "PR #7까지 합쳐야 한다고 적혀 있어요.", "source": "README.md:2005"},
            {"line": "12/31까지라고 적혀 있어요.", "source": "README.md"},
            {"line": "정확도가 70%라고 적혀 있어요.", "source": "README.md"}]))])
        with on():
            result = ahead.scout(ctx, "decided", lambda *_: next(wrong))
        self.assertEqual([f["line"] for f in result["paths"][0]["found"]], ["10/10까지 알림 문구를 끝내야 해요."])
        self.assertEqual((result["cut"], result["dropped"][0]["why"]), (3, "출처로 칠 수 없는 줄 3개를 뺐어요 (길은 남겼어요)"))
        self.assertEqual(ahead._figures("PR #2 · #4를 10/13에 85.5%로 3번"), {"#2", "#4", "10", "13", "85.5%"})


class WorkerTest(Story):
    @staticmethod
    def grounded(payload, schema):
        """가닥이 먼저 찾아 둔 지난 대화의 결정을 출처로 든 길."""
        old = payload["steps"][0]["saw"]["decisions"][-1]["id"]
        return done(path("onward", basis=[payload["now"]["id"]], found=[{"line": "알림은 텔레그램 봇으로 보내기로 했어요.", "source": old}]))

    def junction(self, engine):
        """지난 대화에서 정한 것이 있고, 방금 정한 턴이 마지막인 대화를 1단부터 돌려요."""
        self.start(engine)
        self.chat("old", title="알림 봇 구상", created_at=OLD)
        old = self.turn("o1", "알림은 텔레그램으로 하자", "텔레그램 봇으로 정할게요.", chat_id="old", created_at=OLD)
        with self.conn:
            store.set_classification(self.conn, old, title="알림 채널", depth=0, dec="텔레그램 봇")
        self.chat()
        ids = [self.turn("g1", "뼈대부터 만들어 줘"), self.turn("g2", "환율은 어디서 가져와?"),
               self.turn("g3", "임계값 바꾸고, 테스트는 어떻게 해? 1300원으로 하자")]
        self.clf.request(CHAT)
        self.run_worker()
        return ids

    def test_by_default_a_junction_waits_for_the_button(self):
        """저절로 살피기를 켜지 않으면(기본) 갈림길이어도 앞길을 살피지 않아요. 다른 확인은 하던 대로 해요."""
        marks = lambda p: labels(p, t3={"chose": True, "dec": "임계값 1300원", "parts": [
            {"t": "임계값 바꾸기", "type": "task", "target": None, "open": False},
            {"t": "테스트는 어떻게 하냐", "type": "q", "target": None, "open": True}]})
        engine = Engine(marks, steps=[{"think": "본다", "tool": "get_request", "arg": None, "items": []},
                                      finish({"kind": "missing", "text": "", "why": "답에 없어요", "part": 1, "file": None,
                                              "asked": None, "what": None, "use": []})],
                        ahead=[step("search_turns", "환율"), self.grounded])
        with on(AHEAD_AUTO=False):
            ids = self.junction(engine)
        now = self.row(ids[2])
        self.assertEqual((now["look"], now["checked"]), ("missing", 1))
        self.assertFalse(any(isinstance(c[1], dict) and "ahead" in c[1] for c in engine.calls))

    def test_a_junction_is_looked_at_once_and_other_items_stay(self):
        marks = lambda p: labels(p, t3={"chose": True, "dec": "임계값 1300원", "parts": [
            {"t": "임계값 바꾸기", "type": "task", "target": None, "open": False},
            {"t": "테스트는 어떻게 하냐", "type": "q", "target": None, "open": True}]})
        engine = Engine(marks, steps=[{"think": "본다", "tool": "get_request", "arg": None, "items": []},
                                      finish({"kind": "missing", "text": "", "why": "답에 없어요", "part": 1, "file": None,
                                              "asked": None, "what": None, "use": []})],
                        ahead=[step("search_turns", "환율"), self.grounded])
        with on():
            ids = self.junction(engine)
        self.assertEqual(self.row(ids[0])["look"], "handoff")                      # 새 대화의 첫 턴은 하던 대로 이어 가기를 봐요
        now = self.row(ids[2])
        self.assertEqual((now["look"], now["checked"]), ("missing,ahead", 1))
        self.assertEqual(self.parts_open(ids[2]), [0, store.MISSING])
        made = store.turn_items(self.conn, ids[2])
        self.assertEqual([(i["id"], i["kind"]) for i in made], [(ids[2] + ":a0", "next")])
        runs = {tuple(r["trigger"]): r for r in trace.runs(self.conn, turn_id=ids[2])}
        self.assertEqual(sorted(runs), [("ahead",), ("missing",)])
        run = runs[("ahead",)]
        self.assertEqual((run["goal"], run["why"], run["paths"][0]["kind"], [s["label"] for s in run["steps"]]),
                         ("환율 알림 봇 내보내기", "decided", "onward", ["정한 것 찾기", "열린 할 일 보기", "지난 물음 찾기"]))
        self.assertEqual(run["items"], [{"id": ids[2] + ":a0", "kind": "next", "text": "이어 가기 · 알림 문구부터 정하기"}])
        self.assertEqual(len([c for c in engine.calls if c[0] == "ahead"]), 2)
        records = [(r["name"], json.loads(r["fields_json"])) for r in self.conn.execute("SELECT * FROM usage")]
        self.assertIn(("item", {"kind": "next", "did": "made", "at": "auto"}), records)
        with self.conn:      # 그 턴의 다른 한마디를 다시 적어도 앞길은 남아요
            store.set_items(self.conn, ids[2], [{"kind": "unasked", "text": "하나", "why": "", "btn": "바뀐 곳 보기"}])
        self.assertEqual([i["id"] for i in store.turn_items(self.conn, ids[2])], [ids[2] + ":a0", ids[2] + ":0"])
        self.assertEqual(self.run_worker(), 0)                                     # 다시 살피지 않아요

    def test_trouble_while_looking_ahead(self):
        marks = lambda p: labels(p, t3={"chose": True, "dec": "임계값 1300원"})

        def bad(payload, schema):
            raise BadOutput("형식이 틀렸어요")

        with on():
            ids = self.junction(Engine(marks, ahead=[bad]))
        self.assertEqual((self.row(ids[2])["checked"], store.turn_items(self.conn, ids[2])), (1, []))   # 못 살펴도 확인은 끝
        seen = self.clf.checker.ahead_state(self.conn, CHAT)                       # 왜 아무것도 안 떴는지는 남겨요
        self.assertEqual((seen["state"], seen["turn"], "형식" in seen["reason"]), ("failed", ids[2], True))

    def test_engine_trouble_pauses_and_the_turn_waits(self):
        marks = lambda p: labels(p, t3={"chose": True, "dec": "임계값 1300원"})

        def limit(payload, schema):
            raise EngineError("한도를 다 썼어요")

        engine = Engine(marks, ahead=[limit, self.grounded])
        with on():
            ids = self.junction(engine)
            self.assertEqual((self.clf.status["paused"], self.row(ids[2])["checked"]), (True, 0))
            seen = self.clf.checker.ahead_state(self.conn, CHAT)
            self.assertEqual((seen["state"], "한도를 다 썼어요" in seen["reason"]), ("failed", True))
            self.clf.resume()
            self.run_worker()
        self.assertEqual((self.row(ids[2])["checked"], len(store.turn_items(self.conn, ids[2]))), (1, 1))
        seen = self.clf.checker.ahead_state(self.conn, CHAT)
        self.assertEqual((seen["state"], seen["paths"], seen["goal"]), ("done", 1, "환율 알림 봇 내보내기"))
        self.clf.checker.seen_ahead.clear()                                        # 가닥을 다시 켠 뒤에는 판단 기록에서 찾아요
        again = self.clf.checker.ahead_state(self.conn, CHAT)
        self.assertEqual((again["state"], again["paths"], again["turn"]), ("done", 1, ids[2]))
        self.assertEqual(self.clf.checker.ahead_state(self.conn, "없는 대화"), {"state": "idle"})

    def test_the_button_looks_from_the_last_turn_and_replaces_earlier_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            calls = []

            def research(question):
                calls.append(question)
                return {"found": [{"line": "찾은 줄이에요.", "source": "https://x.example/a"}], "searched": [question]}

            web = [{"line": "찾은 줄이에요.", "source": "https://x.example/a"}]
            engine = Engine(ahead=[step("look_up", "무엇"),
                                   lambda p, s: done(path("onward", "첫 번째 길", basis=[p["now"]["id"]], found=web)),
                                   lambda p, s: done(path("other", "두 번째 길", basis=[p["now"]["id"]], found=web))])
            engine.research = research
            app = create_app(db_path=Path(tmp) / "gadak.db", engine=engine)
            client, rt = app.test_client(), app.config["GADAK"]
            conn = rt.connect()
            self.addCleanup(conn.close)
            with conn:
                store.upsert_chat(conn, project=PROJECT, chat_id=CHAT, site="claude", title="알림 봇")
                ids = [store.upsert_turn(conn, chat_id=CHAT, message_ref=f"g{n}", user=f"질문 {n}", ai="답", state="done")["id"]
                       for n in range(3)]
            self.assertEqual(client.post("/chats/없는대화/ahead", json={}).status_code, 404)
            with on(AHEAD=False):                                                                   # 버튼을 감춘 동안 (GADAK_AHEAD=0)
                off = client.post(f"/chats/{CHAT}/ahead", json={})
                self.assertEqual((off.status_code, off.get_json()["ok"]), (409, False))
                self.assertEqual(client.get("/status").get_json()["ahead"], {"on": False, "auto": False, "web": False, "files": False})
                self.assertEqual(client.post("/ahead/auto", json={"on": True}).status_code, 409)
            with on(AHEAD_AUTO=False):                      # 화면의 ‘저절로 살피기’: 사용자가 켜고 끈 것을 가닥이 기억하고, 설정보다 먼저예요
                self.assertEqual(client.get("/status").get_json()["ahead"]["auto"], False)
                self.assertEqual(client.post("/ahead/auto", json={"on": "yes"}).status_code, 400)
                self.assertEqual(client.post("/ahead/auto", json={"on": True}).get_json(), {"ok": True, "auto": True})
                self.assertEqual((ahead.auto_on(conn), client.get("/status").get_json()["ahead"]["auto"]), (True, True))
            with on():                                      # 설정으로 켜 둔 가닥에서도 화면에서 끌 수 있어요
                self.assertEqual(client.post("/ahead/auto", json={"on": False}).get_json(), {"ok": True, "auto": False})
                self.assertFalse(ahead.auto_on(conn))

            def work():
                n = 0
                while rt.classifier.step(conn) and n < 20:
                    n += 1

            with on(AHEAD_WEB=True, AHEAD_AUTO=False):                                              # 저절로 살피기는 끈 채로 (기본)
                self.assertEqual(client.get("/status").get_json()["ahead"], {"on": True, "auto": False, "web": True, "files": True})
                self.assertTrue(client.post(f"/chats/{CHAT}/ahead", json={}).get_json()["ok"])
                self.assertEqual(client.get("/status").get_json()["classify"]["aheadQueued"], 1)
                project = conn.execute("SELECT project_id FROM chats WHERE id = ?", (CHAT,)).fetchone()[0]
                seen = lambda: client.get(f"/projects/{project}/view?chat={CHAT}").get_json()["ahead"]     # 화면의 ‘앞길’ 칸이 받는 것
                self.assertEqual(seen()["state"], "queued")
                before = rt.classifier.status["calls"]
                work()                                                                               # 1단이 먼저, 그다음 앞길
                last = ids[2]
                self.assertEqual([i["text"] for i in store.turn_items(conn, last)], ["이어 가기 · 첫 번째 길"])
                self.assertEqual([seen()[k] for k in ("state", "turn", "why", "paths")], ["done", last, "button", 1])
                self.assertEqual(engine.calls[-1][1]["ahead"], {"why": "button"})
                self.assertIn("look_up", engine.calls[-1][1]["tools"])
                self.assertEqual((calls, rt.classifier.status["calls"] - before), (["무엇"], 1 + 3))    # 1단 1번 + 앞길 2번 + 웹 1번
                self.assertTrue(client.patch(f"/items/{last}:a0", json={"state": "done"}).get_json()["ok"])
            with on(AHEAD_AUTO=False):
                client.post(f"/chats/{CHAT}/ahead", json={})
                work()
                self.assertNotIn("look_up", engine.calls[-1][1]["tools"])                            # 웹은 따로 켜야 해요
                # 다시 살피면 앞서 낸 길과 그 상태는 지워요. 이번에는 웹에서 찾은 것이 없으니(꺼 둠) 낼 길이 없어요
                self.assertEqual(store.turn_items(conn, last), [])
                self.assertEqual((seen()["state"], seen()["paths"]), ("none", 0))          # 살폈지만 낼 길이 없었다고 말해 줘요
                self.assertIsNone(conn.execute("SELECT 1 FROM item_states WHERE id = ?", (last + ":a0",)).fetchone())
            self.assertEqual([tuple(r["trigger"]) for r in trace.runs(conn, turn_id=last)], [("ahead",), ("ahead",)])


class ResearchTest(unittest.TestCase):
    """Claude 구독 엔진의 웹에서 찾아보기: 검색 도구가 돌려준 주소만 출처로 남겨요."""

    def run_with(self, lines=None, error=None):
        engine = claude_cli.ClaudeCliEngine(model="haiku")
        engine.bin = "/usr/bin/true"
        out = mock.Mock(stdout="\n".join(json.dumps(l, ensure_ascii=False) for l in lines or []), stderr="")
        with mock.patch.object(claude_cli.subprocess, "run", side_effect=error, return_value=out) as run, \
                tempfile.TemporaryDirectory() as tmp, mock.patch.object(config, "HOME", Path(tmp)):
            result = engine.research("텔레그램 봇 전송 한도")
        return engine, run, result

    def stream(self, found, links='Links: [{"title":"FAQ","url":"https://core.telegram.org/bots/faq"}]'):
        return [
            {"type": "system", "subtype": "init"},
            {"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "WebSearch", "input": {"query": "q"}}]}},
            {"type": "user", "message": {"content": [{"type": "tool_result", "content": 'Web search results for query: "q"\n\n' + links}]}},
            {"type": "result", "is_error": False, "total_cost_usd": 0.05, "usage": {"input_tokens": 10, "output_tokens": 5},
             "structured_output": {"found": found, "searched": ["q"]}},
        ]

    def test_only_pages_the_search_returned_are_kept(self):
        engine, run, result = self.run_with(self.stream([
            {"line": "초당 30건까지예요.", "source": "https://core.telegram.org/bots/faq/"},
            {"line": "지어낸 출처예요.", "source": "https://core.telegram.org/bots/limits"}]))
        self.assertEqual(result, {"found": [{"line": "초당 30건까지예요.", "source": "https://core.telegram.org/bots/faq/"}],
                                  "searched": ["q"], "dropped": 1})
        cmd = run.call_args.args[0]
        self.assertEqual(cmd[cmd.index("--tools") + 1], "WebSearch")                 # 검색만 켜요
        self.assertEqual(cmd[cmd.index("--allowedTools") + 1], "WebSearch")
        self.assertIn("--safe-mode", cmd)
        self.assertEqual(run.call_args.kwargs["input"], "텔레그램 봇 전송 한도")
        self.assertEqual(engine.last["cost"], 0.05)

    def test_slow_or_broken_searches_do_not_stop_the_worker_but_login_trouble_does(self):
        _, _, slow = self.run_with(error=subprocess.TimeoutExpired("claude", 1))
        self.assertEqual((slow["found"], slow["dropped"]), ([], 0))
        with self.assertRaises(EngineError):
            self.run_with([{"type": "system"}])
        with self.assertRaises(EngineError) as caught:
            self.run_with([{"type": "result", "is_error": True, "result": "Not logged in · Please run /login"}])
        self.assertIn("로그인", str(caught.exception))
        _, _, empty = self.run_with([{"type": "result", "is_error": False, "result": "글로 답했어요"}])
        self.assertEqual(empty, {"found": [], "searched": [], "dropped": 0})

    def test_addresses_are_compared_loosely_but_not_too_loosely(self):
        same = claude_cli.same_page
        self.assertEqual(same("HTTPS://Example.com/a/b/#top"), same("https://example.com/a/b"))
        self.assertNotEqual(same("https://example.com/a"), same("https://example.com/b"))
        pages = claude_cli.searched_pages(json.dumps({"type": "user", "message": {"content": [{"type": "tool_result", "content": [
            {"type": "text", "text": 'Links: [{"title":"M","url":"https://en.wikipedia.org/wiki/Mercury_(planet)"}]'}]}]}}))
        self.assertIn("https://en.wikipedia.org/wiki/Mercury_(planet)", pages)


if __name__ == "__main__":
    unittest.main()
