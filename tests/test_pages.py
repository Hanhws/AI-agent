import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from backend import store
from backend.app import EXTENSION_HEADER, create_app
from backend.sources import pages
from tests.test_sources import CHATGPT_EXPORT, CLAUDE_EXPORT

GPT, CLAUDE = "aaaaaaaa-1111-2222-3333-444444444444", "bbbbbbbb-1111-2222-3333-444444444444"


def turn(user, ai, ref=None, fresh=False, open=False):
    return {"ref": ref, "user": user, "ai": ai, "fresh": fresh, "open": open}


class PagesTest(unittest.TestCase):
    """크롬 확장이 보낸 대화 화면을 저장소의 역과 맞추는 것 (backend/sources/pages.py)."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        base = Path(self.tmp.name)
        env = mock.patch.dict(os.environ, {
            "GADAK_CLAUDE_PROJECTS": str(base / "claude"), "GADAK_CODEX_HOME": str(base / "codex"),
            "GADAK_CLAUDE_SETTINGS": str(base / "claude-settings.json"),
            "GADAK_CURSOR_HOME": str(base / "cursor"),
        })
        env.start()
        self.addCleanup(env.stop)
        app = create_app(db_path=base / "gadak.db", engine=None)
        self.rt = app.config["GADAK"]
        self.client = app.test_client()

    def page(self, turns, chat=GPT, site="chatgpt", title="발표 대본", status=200, **extra):
        body = {"site": site, "chat": {"id": chat, "title": title, "project": extra.pop("project", None)}, "turns": turns}
        body.update(extra)
        # 브라우저의 JSON.stringify처럼 보내요 (짝이 깨진 글자는 \ud83d 꼴로 실려 와요)
        response = self.client.post("/pages", data=json.dumps(body), content_type="application/json")
        self.assertEqual(response.status_code, status, response.get_data(as_text=True))
        return response.get_json()

    def rows(self, chat=GPT):
        conn = self.rt.connect()
        self.addCleanup(conn.close)
        return store.chat_turns(conn, chat)

    def shown(self, chat=GPT):
        return [(r["user"], r["ai"], r["state"]) for r in self.rows(chat)]

    def rev(self):
        return self.client.get("/status").get_json()["rev"]

    def test_a_page_becomes_a_chat_and_reading_it_again_adds_nothing(self):
        seen = [turn("대본을 써 줘", "3분 대본이에요.", "u1"), turn("더 짧게", "1분으로 줄였어요.", "u2")]
        first = self.page(seen)
        self.assertEqual(first, {"chat": GPT, "turns": 2, "new": 2, "changed": 0, "live": False})
        (chat,) = self.client.get(f"/projects/{store.NO_PROJECT}/view").get_json()["chats"]
        self.assertEqual((chat["site"], chat["title"], chat["via"], [t["user"] for t in chat["turns"]]),
                         ("chatgpt", "발표 대본", pages.VIA, ["대본을 써 줘", "더 짧게"]))
        self.assertEqual(list(self.rt.classifier.queue), [])     # 열어 보기만 한 지난 대화는 볼 때 정리해요
        before = self.rev()
        again = self.page([dict(t, ai=None) for t in seen])      # 확장은 이미 보낸 답을 다시 싣지 않아요
        self.assertEqual((again["new"], again["changed"]), (0, 0))
        self.assertEqual(self.rev(), before)
        self.assertEqual(self.shown(), [("대본을 써 줘", "3분 대본이에요.", "done"), ("더 짧게", "1분으로 줄였어요.", "done")])

    def test_a_turn_seen_live_is_queued_when_its_answer_ends(self):
        self.page([turn("대본을 써 줘", "3분 대본이에요.", "u1")])
        coming = self.page([turn("대본을 써 줘", None, "u1"), turn("더 짧게", "1분으", "u2", fresh=True, open=True)])
        self.assertEqual((coming["new"], coming["live"]), (1, False))
        self.assertEqual(self.shown()[1], ("더 짧게", "1분으", "open"))
        self.assertEqual(list(self.rt.classifier.queue), [])
        done = self.page([turn("대본을 써 줘", None, "u1"), turn("더 짧게", "1분으로 줄였어요.", "u2", fresh=True)])
        self.assertEqual((done["new"], done["changed"], done["live"]), (0, 1, True))
        self.assertEqual(self.shown()[1], ("더 짧게", "1분으로 줄였어요.", "done"))
        self.assertEqual(list(self.rt.classifier.queue), [GPT])
        same = self.page([turn("대본을 써 줘", None, "u1"), turn("더 짧게", None, "u2", fresh=True)])
        self.assertEqual((same["changed"], same["live"]), (0, False))

    def test_a_chat_from_an_export_file_is_not_doubled_or_overwritten(self):
        raw = json.dumps(CLAUDE_EXPORT, ensure_ascii=False).encode("utf-8")
        self.assertEqual(self.client.post("/import", data=raw, content_type="application/json").status_code, 200)
        # 화면의 글은 내보내기 파일과 띄어쓰기 · 기호가 조금 달라요. Claude 화면에는 메시지 id가 없어요
        seen = [turn("목차를  잡아 줘!", "세 장으로\n나눌게요"), turn("2장을 더 자세히", "2장을 넷으로 나눴어요.")]
        result = self.page(seen, chat="conv-claude-1", site="claude", title="보고서 목차")
        self.assertEqual((result["new"], result["changed"], result["live"]), (0, 0, False))
        self.assertEqual(self.shown("conv-claude-1"), [("목차를 잡아 줘", "세 장으로 나눌게요.", "done"),
                                                       ("2장을 더 자세히", "2장을 넷으로 나눴어요.", "done")])
        self.assertEqual([r["message_ref"] for r in self.rows("conv-claude-1")], ["m1", "m3"])
        more = self.page(seen + [turn("3장도", "3장을 둘로 나눴어요.", fresh=True)], chat="conv-claude-1", site="claude")
        self.assertEqual((more["new"], more["live"], len(self.rows("conv-claude-1"))), (1, True, 3))

    def test_message_ids_match_the_export_file(self):
        raw = json.dumps(CHATGPT_EXPORT, ensure_ascii=False).encode("utf-8")
        self.client.post("/import", data=raw, content_type="application/json")
        result = self.page([turn("대본을 써 줘", "3분 대본이에요!", "n2"), turn("표로도", "표예요.", "n9")], chat="conv-gpt-1")
        self.assertEqual(result["new"], 1)
        self.assertEqual([(r["message_ref"], r["ai"]) for r in self.rows("conv-gpt-1")],
                         [("n2", "3분 대본이에요."), ("n9", "표예요.")])

    def test_the_same_question_twice_is_two_turns(self):
        seen = [turn("계속", "첫 번째 이어 쓰기"), turn("계속", "두 번째 이어 쓰기")]
        self.assertEqual(self.page(seen, chat=CLAUDE, site="claude")["new"], 2)
        self.assertEqual(self.page(seen + [turn("계속!", "세 번째")], chat=CLAUDE, site="claude")["new"], 1)
        self.assertEqual([r["ai"] for r in self.rows(CLAUDE)], ["첫 번째 이어 쓰기", "두 번째 이어 쓰기", "세 번째"])
        refs = [r["message_ref"] for r in self.rows(CLAUDE)]
        self.assertEqual(len(set(refs)), 3)
        self.assertEqual([ref[-2:] for ref in refs], ["-0", "-1", "-2"])     # 같은 글 중 몇 번째인지

    def test_an_answer_that_changed_while_watching_is_sorted_again(self):
        self.page([turn("대본을 써 줘", "3분 대본이에요.", "u1")])
        (row,) = self.rows()
        conn = self.rt.connect()
        with conn:
            store.set_classification(conn, row["id"], title="대본", depth=0, dec="3분", look=["missing"],
                                     parts=[{"t": "대본", "type": "task"}, {"t": "표", "type": "task", "open": 2}])
            store.set_items(conn, row["id"], [{"kind": "missing", "text": "표가 빠졌어요"}])
        conn.close()
        # 글자는 같고 줄만 바뀐 것은 달라진 것이 아니에요
        self.assertEqual(self.page([turn("대본을 써 줘", "3분  대본이에요", "u1", fresh=True)])["changed"], 0)
        again = self.page([turn("대본을 써 줘", "다시 쓴 5분 대본이에요.", "u1", fresh=True)])   # 다시 생성
        self.assertEqual((again["changed"], again["live"]), (1, True))
        (row,) = self.rows()
        self.assertEqual((row["ai"], row["classified"], row["look"]), ("다시 쓴 5분 대본이에요.", 0, None))
        conn = self.rt.connect()
        self.addCleanup(conn.close)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM parts").fetchone()[0], 0)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM items").fetchone()[0], 0)

    def test_an_answer_cut_off_earlier_is_filled_in_later(self):
        # 답이 오는 중에 탭을 닫았다가, 나중에 그 대화를 다시 열었어요 (지켜본 턴이 아니어도 끝까지 채워요)
        self.page([turn("대본을 써 줘", "3분", "u1", fresh=True, open=True)])
        later = self.page([turn("대본을 써 줘", "3분 대본이에요.", "u1")])
        self.assertEqual((later["changed"], later["live"]), (1, False))
        self.assertEqual(self.shown(), [("대본을 써 줘", "3분 대본이에요.", "done")])

    def test_turns_follow_the_order_on_the_page(self):
        self.page([turn("둘째", "나", "u2"), turn("셋째", "다", "u3")])
        result = self.page([turn("첫째", "가", "u1"), turn("둘째", None, "u2"), turn("셋째", None, "u3")])
        self.assertEqual((result["new"], result["live"]), (1, False))
        self.assertEqual([(r["user"], r["seq"]) for r in self.rows()], [("첫째", 1), ("둘째", 2), ("셋째", 3)])

    def test_a_page_still_showing_another_chat_is_refused(self):
        self.page([turn("대본을 써 줘", "3분 대본이에요.", "u1")])
        other = "cccccccc-1111-2222-3333-444444444444"
        refused = self.page([turn("대본을 써 줘", "3분 대본이에요.", "u1")], chat=other, status=409)
        self.assertIn("다른 대화", refused["error"])
        self.assertEqual(self.rows(other), [])
        self.assertEqual(self.page([turn("대본을 써 줘", "3분 대본이에요.", "u1")], chat=other, sure=True)["new"], 1)

    def test_title_and_project_follow_the_site(self):
        self.page([turn("대본을 써 줘", "3분 대본이에요.", "u1")], title=None)
        self.page([turn("대본을 써 줘", None, "u1")], title="  발표   대본 ", project="발표 준비")
        chats = self.client.get("/projects/발표 준비/view").get_json()["chats"]
        self.assertEqual([(c["id"], c["title"]) for c in chats], [(GPT, "발표 대본")])
        self.assertEqual(self.client.get(f"/projects/{store.NO_PROJECT}/view").get_json()["chats"], [])

    def test_long_and_broken_text(self):
        long = "가" * (store.MAX_AI + 5000)
        self.page([turn("반쪽 이모지 \ud83d", long, "u1")])
        ((user, ai, _),) = self.shown()
        self.assertEqual((user, len(ai)), ("반쪽 이모지 ?", store.MAX_AI))
        self.assertIn(store.CUT, ai)
        self.assertEqual(self.page([turn("반쪽 이모지 \ud83d", long, "u1", fresh=True)])["changed"], 0)

    def test_bad_pages_are_refused(self):
        good = [turn("대본을 써 줘", "3분 대본이에요.", "u1")]
        self.page(good, site="elsewhere", status=400)
        self.page(good, chat="../etc", status=400)
        self.page("턴이 아님", status=400)
        self.page([], status=400)
        self.page([turn("", "", "u1")], status=400)
        self.page([turn("질문", 3, "u1")], status=400)
        self.page([turn("질문", "답", "id with space")], status=400)
        self.assertEqual(self.client.post("/pages", data="site=chatgpt").status_code, 415)
        self.assertEqual(self.client.get(f"/projects/{store.NO_PROJECT}/view").status_code, 404)   # 아무것도 안 들어갔어요

    def test_the_extension_shows_up_in_sources_once_it_calls(self):
        def row():
            return next(r for r in self.client.get("/sources").get_json()["sources"] if r["key"] == "extension")
        before = row()
        self.assertEqual((before["mode"], before["connected"], before["chats"]), ("extension", False, 0))
        self.assertEqual(Path(before["folder"]).name, "extension")
        self.assertTrue((Path(before["folder"]) / "manifest.json").is_file())
        self.client.get("/health")                                        # 다른 것이 물어본 건 세지 않아요
        self.assertFalse(row()["connected"])
        self.client.get("/health", headers={EXTENSION_HEADER: "0.1.0"})
        self.page([turn("대본을 써 줘", "3분 대본이에요.", "u1")])
        after = row()
        self.assertEqual((after["connected"], after["seen"], after["chats"]), (True, "오늘", 1))


if __name__ == "__main__":
    unittest.main()
