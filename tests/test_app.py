import io
import json
import os
import re
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from backend import store
from backend.app import create_app
from tests.test_sources import CHATGPT_EXPORT, CLAUDE_EXPORT

ROOT = Path(__file__).resolve().parent.parent
KINDS = {"missing", "unasked", "yours", "branch", "open", "check", "topic", "repeat", "handoff", "next"}


class AppTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        base = Path(self.tmp.name)
        self.cursor_home = base / "cursor"
        env = mock.patch.dict(os.environ, {
            "GADAK_CLAUDE_PROJECTS": str(base / "claude"), "GADAK_CODEX_HOME": str(base / "codex"),
            "GADAK_CLAUDE_SETTINGS": str(base / "claude-settings.json"),
            "GADAK_CURSOR_HOME": str(self.cursor_home),
        })
        env.start()
        self.addCleanup(env.stop)
        app = create_app(db_path=base / "gadak.db", engine=None)
        self.rt = app.config["GADAK"]
        self.client = app.test_client()

    def event(self, kind, ref="g1", **extra):
        body = {"site": "cursor", "project": "환율 알리미", "chat_id": "conv-1", "message_ref": ref, "kind": kind}
        body.update(extra)
        self.assertEqual(self.client.post("/events", json=body).status_code, 200)

    def turn(self, ref="g1", user="임계값만 바꿔 줘", ai="바꿨어요."):
        self.event("prompt", ref, text=user)
        self.event("answer", ref, text=ai)

    def view(self, project="환율 알리미"):
        return self.client.get(f"/projects/{project}/view").get_json()

    def test_the_window_page_and_its_files(self):
        page = self.client.get("/")
        self.assertEqual(page.status_code, 200)
        html = page.get_data(as_text=True)
        for path in ("ui/tokens.css", "ui/gadak.css", "ui/view.js", "ui/map.js", "ui/side.js", "ui/nudge.js",
                     "ui/rail.js", "ui/mark.js", "web/app.css", "web/app.js"):
            self.assertIn(path, html)
            with self.client.get("/" + path) as response:
                self.assertEqual(response.status_code, 200, path)
        self.assertNotIn("<textarea", html)   # 가닥은 대답하지 않아요: 입력창이 없어요
        self.assertEqual(self.client.get("/data/other.json").status_code, 404)

    def test_demo_data_is_made_up_and_consistent(self):
        with self.client.get("/data/demo_conversations.json") as response:
            data = response.get_json()
        for scenario in data["scenarios"].values():
            turns = [t for chat in scenario["chats"] for t in chat["turns"]]
            ids = {t["id"] for t in turns}
            self.assertEqual(len(ids), len(turns))
            self.assertEqual(sum(1 for chat in scenario["chats"] if chat.get("active")), 1)
            for t in turns:
                self.assertIn(t["depth"], (0, 1, 2))
                self.assertTrue(t["title"] and t["user"] and t["ai"])
                self.assertTrue(1 <= len(t["gist"]) <= 4 and all(isinstance(line, str) and 0 < len(line) <= 70 for line in t["gist"]))
                self.assertTrue(t.get("ref") is None or t["ref"] in ids)
                for part in t.get("parts", []):
                    self.assertIn(part["type"], ("q", "task", "rev"))
                for item in t.get("todo", []):
                    self.assertIn(item["kind"], KINDS)
                    self.assertTrue(item["text"] and item["why"] and item["btn"])
                    self.assertTrue(item.get("prompt") or item.get("pop") or item.get("effect"))

    def test_status_changes_when_something_arrives(self):
        before = self.client.get("/status").get_json()
        self.assertEqual((before["classify"]["engine"], before["sync"]["phase"]), ("none", "idle"))
        self.turn()
        after = self.client.get("/status").get_json()
        self.assertGreater(after["rev"], before["rev"])
        self.assertEqual(list(self.rt.classifier.queue), ["conv-1"])   # 답이 끝난 턴은 정리 줄에 서요

    def test_view_carries_the_start_and_the_full_text_is_fetched(self):
        self.turn(ai="가" * 3000)
        (turn,) = self.view()["chats"][0]["turns"]
        self.assertTrue(turn["long"])
        self.assertEqual(len(turn["ai"]), store.CLIP_AI + 1)
        full = self.client.get(f"/turns/{turn['id']}").get_json()["turn"]
        self.assertEqual(len(full["ai"]), 3000)
        self.assertNotIn("long", full)
        self.assertEqual(self.client.get("/turns/none").status_code, 404)

    def test_the_map_page_and_its_data(self):
        """전체 지도: /map이 열리고, /map/data에 오늘 한 대화가 오늘 날짜(마지막 칸)의 노선으로 실려요."""
        self.assertEqual(self.client.get("/map").status_code, 200)
        self.turn()
        data = self.client.get("/map/data").get_json()
        (project,) = data["projects"]
        (chat,) = project["chats"]
        self.assertEqual(project["name"], "환율 알리미")
        # 대화가 오늘뿐이면 지도도 오늘 하루짜리예요 (90일 전부터 비워 두지 않아요)
        self.assertEqual((data["today"], chat["from"], chat["to"], chat["active"]), (0, 0, 0, True))
        self.assertEqual(chat["turns"][0]["day"], 0)

    def test_projects_list_recent_first(self):
        self.turn()
        self.event("prompt", project="nba-analysis", chat_id="conv-2", text="나중 질문")
        rows = self.client.get("/projects").get_json()["projects"]
        self.assertEqual({r["id"]: (r["chats"], r["turns"]) for r in rows}, {"환율 알리미": (1, 1), "nba-analysis": (1, 1)})

    def test_search_puts_decisions_first(self):
        self.turn("g1", "임계값은 얼마가 좋아?", "1,380원이 무난해요.")
        self.turn("g2", "그럼 임계값 1,380원으로 하자", "정했어요.")
        self.turn("g3", "알림 문구도 봐 줘", "봤어요.")
        conn = self.rt.connect()
        rows = store.chat_turns(conn, "conv-1")
        with conn:
            store.set_classification(conn, rows[1]["id"], title="임계값 정함", depth=0, dec="임계값 1,380원")
        conn.close()
        hits = self.client.get("/projects/환율 알리미/search?q=임계값").get_json()["hits"]
        self.assertEqual([h["id"] for h in hits], [rows[1]["id"], rows[0]["id"]])
        self.assertIn("임계값", hits[0]["snip"])
        self.assertEqual(self.client.get("/projects/환율 알리미/search?q=").get_json()["hits"], [])
        self.assertEqual(self.client.get("/projects/환율 알리미/search?q=100%25").get_json()["hits"], [])

    def test_transfer_copies_this_chats_decisions(self):
        self.turn("g1", "임계값은 얼마가 좋아?", "1,380원이 무난해요.")
        self.assertIsNone(self.client.get("/chats/conv-1/handoff").get_json()["text"])
        self.turn("g2", "그럼 임계값 1,380원으로 하자", "정했어요.")
        conn = self.rt.connect()
        turn_id = store.chat_turns(conn, "conv-1")[1]["id"]
        with conn:
            store.set_classification(conn, turn_id, title="임계값 정함", depth=0, dec="임계값 1,380원",
                                     dec_note="알림 임계값을 1,380원으로 정함")
            for kind, text in (("unasked", "launch.json이 새로 생겼어요"), ("next", "알림 문구 다듬기")):
                conn.execute("INSERT INTO items(id, turn_id, kind, text, state, created_at) VALUES(?, ?, ?, ?, 'open', '')",
                             (kind, turn_id, kind, text))
        text = self.client.get("/chats/conv-1/handoff").get_json()["text"]   # 엔진 없이: 풀어 쓴 정함 · 할 일만
        self.assertIn("1. 알림 임계값을 1,380원으로 정함", text)
        self.assertIn("알림 문구 다듬기", text)
        self.assertNotIn("launch.json", text)
        self.assertEqual(self.client.get("/chats/nope/handoff").status_code, 404)

        from backend.agent import handoff
        from backend.engines import EngineError
        seen = {}
        def call(system, payload, schema):
            seen["payload"] = json.loads(payload)
            return {"text": "이전 대화에서 이어서 해요."}
        self.assertEqual(handoff.write(conn, "conv-1", call), "이전 대화에서 이어서 해요.")
        wrapped = lambda *_: {"text": json.dumps({"text": "이어서 해요.\n■ 정한 것"}, ensure_ascii=False)}
        self.assertEqual(handoff.write(conn, "conv-1", wrapped), "이어서 해요.\n■ 정한 것")   # 한 번 더 감싼 JSON은 벗겨요
        self.assertEqual(seen["payload"]["route"][1]["dec"], "알림 임계값을 1,380원으로 정함")
        self.assertEqual([t["n"] for t in seen["payload"]["turns"]], [1])   # 마지막 턴은 last로 따로, 앞 턴은 답 끝부분만
        def broken(*_):
            raise EngineError("x")
        self.assertIn("1. 알림 임계값", handoff.write(conn, "conv-1", broken))   # 엔진이 실패하면 늘어놓은 글로
        conn.close()

    def test_finding_chats_across_projects(self):
        self.turn("g1", "임계값은 얼마가 좋아?", "1,380원이 무난해요.")                # 환율 알리미 · Cursor
        self.event("prompt", "n1", project="nba-analysis", chat_id="conv-2", text="알리미 프로젝트처럼 Ridge로 예측해 줘")
        self.event("answer", "n1", project="nba-analysis", chat_id="conv-2", text="임계값 없이 alpha만 정하면 돼요.")
        raw = json.dumps(CHATGPT_EXPORT, ensure_ascii=False).encode("utf-8")       # (프로젝트 없음) · ChatGPT · 발표 대본
        self.client.post("/import", data=raw, content_type="application/json")

        def find(q):
            return self.client.get("/chats/search", query_string={"q": q}).get_json()["chats"]

        both = find("임계값")                                      # 두 프로젝트의 글에서
        self.assertEqual({h["id"] for h in both}, {"conv-1", "conv-2"})
        for hit in both:
            self.assertIn("임계값", hit["snip"])
            self.assertEqual(self.client.get(f"/turns/{hit['turn']}").status_code, 200)
        # 이름(프로젝트 · 제목 · 쓴 곳)이 맞는 대화가 글만 맞는 대화보다 먼저. 더 최근 대화여도 뒤로 가요
        self.assertEqual([(h["id"], h["project"]["name"], "turn" in h) for h in find("알리미")],
                         [("conv-1", "환율 알리미", False), ("conv-2", "nba-analysis", True)])
        self.assertEqual([(h["id"], h["title"], h["site"]) for h in find("chatgpt")], [("conv-gpt-1", "발표 대본", "chatgpt")])
        self.assertEqual([h["id"] for h in find("대본")], ["conv-gpt-1"])
        self.assertEqual([h["id"] for h in find("RIDGE")], ["conv-2"])           # 영문은 대소문자를 가리지 않아요
        self.assertEqual(find(""), [])
        self.assertEqual(find("100%"), [])
        self.assertEqual(find("프로젝트 없음"), [])                  # 프로젝트가 없는 대화의 자리 이름으로는 찾지 않아요

    def test_taking_chats_off_the_list_and_putting_them_back(self):
        self.turn("g1", "임계값은 얼마가 좋아?", "1,380원이 무난해요.")                # 환율 알리미 · conv-1
        self.event("prompt", "h1", chat_id="conv-1b", text="알림 문구를 다듬어 줘")     # 같은 프로젝트의 다른 대화
        self.event("prompt", "n1", project="nba-analysis", chat_id="conv-2", text="임계값 없이 Ridge로")
        before = self.client.get("/status").get_json()["rev"]

        def projects():
            data = self.client.get("/projects").get_json()
            return {p["id"]: p["chats"] for p in data["projects"]}, data["hidden"]

        def find(q):
            return [h["id"] for h in self.client.get("/chats/search", query_string={"q": q}).get_json()["chats"]]

        off = self.client.post("/chats/hidden", json={"ids": ["conv-1", "no-such-chat"], "hidden": True}).get_json()
        self.assertEqual(off, {"ids": ["conv-1"], "hidden": 1})
        self.assertGreater(self.client.get("/status").get_json()["rev"], before)
        self.assertEqual(projects(), ({"환율 알리미": 1, "nba-analysis": 1}, 1))
        self.assertEqual([c["id"] for c in self.view()["chats"]], ["conv-1b"])
        self.assertEqual(find("임계값"), ["conv-2"])                                  # 찾기에도 안 나와요
        self.assertEqual(self.client.get("/projects/환율 알리미/search?q=임계값").get_json()["hits"], [])
        hidden = self.client.get("/chats/hidden").get_json()["chats"]
        self.assertEqual([(c["id"], c["project"]["name"], c["site"]) for c in hidden], [("conv-1", "환율 알리미", "cursor")])
        # 뺀 대화가 이어져도 다시 나타나지 않고, 읽어 둔 글은 그대로 있어요
        self.turn("g2", "그럼 1,380원으로 하자", "정했어요.")
        self.assertEqual([c["id"] for c in self.view()["chats"]], ["conv-1b"])
        conn = self.rt.connect()
        self.addCleanup(conn.close)
        self.assertEqual(len(store.chat_turns(conn, "conv-1")), 2)

        # 프로젝트째로 빼면 그 프로젝트가 목록에서 사라지고, 돌려받은 id로 그대로 되돌려요
        gone = self.client.post("/projects/환율 알리미/hide", json={}).get_json()
        self.assertEqual(gone, {"ids": ["conv-1b"], "hidden": 2})
        self.assertEqual(projects(), ({"nba-analysis": 1}, 2))
        back = self.client.post("/chats/hidden", json={"ids": gone["ids"] + off["ids"], "hidden": False}).get_json()
        self.assertEqual((sorted(back["ids"]), back["hidden"]), (["conv-1", "conv-1b"], 0))
        self.assertEqual(projects(), ({"환율 알리미": 2, "nba-analysis": 1}, 0))
        self.assertEqual(sorted(find("임계값")), ["conv-1", "conv-2"])
        for bad in ({"ids": "conv-1", "hidden": True}, {"ids": ["conv-1"]}, {"ids": [1], "hidden": True}):
            self.assertEqual(self.client.post("/chats/hidden", json=bad).status_code, 400)

    def test_the_floating_button_asks_about_the_chat_in_use(self):
        empty = self.client.get("/float").get_json()
        self.assertEqual(len(empty.pop("slots")), 6)                                   # 둘레에 놓을 버튼들 (tests/test_floatbar.py)
        self.assertEqual(empty, {"rev": self.rt.rev, "chat": None, "todo": 0})
        self.turn("g1", "임계값은 얼마가 좋아?", "1,380원이 무난해요.")                # 환율 알리미 · conv-1
        self.event("prompt", "n1", project="nba-analysis", chat_id="conv-2", text="Ridge로 해 줘")
        now = self.client.get("/float").get_json()
        self.assertEqual((now["chat"]["id"], now["chat"]["project"], now["todo"]), ("conv-2", "nba-analysis", 0))
        self.assertEqual(now["rev"], self.client.get("/status").get_json()["rev"])

        conn = self.rt.connect()
        self.addCleanup(conn.close)
        with conn:
            ids = store.set_items(conn, store.chat_turns(conn, "conv-2")[0]["id"],
                                  [{"kind": "unasked", "text": "요청하지 않은 파일도 바뀌었어요"}])
        self.assertEqual(self.client.get("/float").get_json()["todo"], 1)
        self.client.patch(f"/items/{ids[0]}", json={"state": "later"})                # 나중에로 미룬 것은 세지 않아요
        self.assertEqual(self.client.get("/float").get_json()["todo"], 0)
        self.client.post("/chats/hidden", json={"ids": ["conv-2"], "hidden": True})   # 목록에서 뺀 대화는 건너뛰어요
        self.assertEqual(self.client.get("/float").get_json()["chat"]["id"], "conv-1")

    def test_the_strip_page_is_the_map_card_alone(self):
        with self.client.get("/strip") as page:
            html = page.get_data(as_text=True)
        for path in ("ui/tokens.css", "ui/gadak.css", "ui/mark.js", "ui/view.js", "ui/map.js", "ui/side.js", "ui/nudge.js",
                     "web/strip.css", "web/strip.js"):
            self.assertIn(path, html)
            with self.client.get("/" + path) as response:
                self.assertEqual(response.status_code, 200, path)
        self.assertNotIn("<textarea", html)       # 가닥은 대답하지 않아요
        self.assertNotIn("ui/rail.js", html)      # 레일은 없고 노선도 카드만
        # 떠 있는 버튼(mac/Float.swift)의 여섯 가지가 이 화면과 가닥 창이 아는 이름인지
        swift = (ROOT / "mac" / "Float.swift").read_text(encoding="utf-8")
        keys = re.findall(r'FloatAction\(key: "(\w+)"', swift)
        self.assertEqual(len(keys), 6)
        script = (ROOT / "backend" / "web" / "strip.js").read_text(encoding="utf-8")
        tabs = set(re.findall(r"(\w+): 1", re.search(r"TABS = \{([^}]*)\}", script).group(1)))
        self.assertEqual(set(keys) - {"map", "find", "window"}, tabs)
        window = (ROOT / "backend" / "web" / "app.js").read_text(encoding="utf-8")
        for name in ("gadakStrip", "gadakFind", "gadakOpen"):
            self.assertIn("window." + name, swift)
            self.assertIn("window." + name + " = ", script if name == "gadakStrip" else window)
        # 목록 창은 노선도 창과 따로 떠요: 앱이 주소에 붙이는 말과 화면이 앱에 부탁하는 말이 서로 맞는지
        for asks, hears in (('URLQueryItem(name: "only", value: "list")', "params.get('only') === 'list'"),
                            ('URLQueryItem(name: "app", value: "2")', "params.get('app') === '2'"),
                            ('what == "list"', "tell({ float: 'list'"), ('what == "close"', "tell({ float: 'close' })"),
                            ('what == "size"', "tell({ float: 'size'")):
            self.assertIn(asks, swift)
            self.assertIn(hears, script)
        self.assertIn("setProperty('--route'", script)      # 노선 색이 없으면 본선과 역이 같은 색이라 역이 안 보여요
        # ‘주제 전환’ 한마디의 환승하기(effect: transfer)는 떠 있는 창에서도 요약을 복사해요. 이 창에는 노선도 끝의 환승 표시(handoff)가 없어요
        nudge = (ROOT / "shared" / "ui" / "nudge.js").read_text(encoding="utf-8")
        self.assertIn("g.hooks.handoff || g.hooks.transfer", nudge)
        self.assertIn("transfer: transfer", script)
        self.assertNotIn("handoff:", script)
        self.assertIn("'/handoff'", script)

    def test_the_window_keeps_the_list_apart_and_has_help(self):
        """가닥 창: 목록(할 일 · 정한 것 · 산출물 · 앞길)은 노선도 카드와 떼어 오른쪽에, 대화 옆 레일은 그리지 않아요. 도움말이 있어요."""
        window = (ROOT / "backend" / "web" / "app.js").read_text(encoding="utf-8")
        self.assertIn("g.mountDrawer(col, null, true)", window)
        self.assertIn("g.mountSide(R.sideCol, true)", window)
        # 가닥 창은 레일을 놓지 않아요. ‘전체 보기’에 남아 있는 레일 다시 그리기(기획 담당의 줄 그대로)는 레일이 없으면 아무 일도 하지 않아요
        self.assertNotIn("R.rail =", window)
        self.assertIn("if (!rail) return;", (ROOT / "shared" / "ui" / "rail.js").read_text(encoding="utf-8"))
        self.assertIn("fillAnswer(para, d.turn.ai); more.remove(); g.renderRail();", window)   # ‘전체 보기’로 받은 답도 구획 · 표 · 코드로
        side = (ROOT / "shared" / "ui" / "side.js").read_text(encoding="utf-8")
        for words in ("['ahead', '앞길'", "앞길 저절로 살피기", "살피지 못했어요", "내밀 만한 길을 찾지 못했어요"):
            self.assertIn(words, side)
        with self.client.get("/help") as page:
            html = page.get_data(as_text=True)
        self.assertEqual(page.status_code, 200)
        for words in ("가닥 도움말", "노선도 읽기", "낱말 풀이", "앞길 보기", "저절로 살피기", "막힐 때"):
            self.assertIn(words, html)
        self.assertNotIn("<textarea", html)
        # 도움말은 주제별로 나뉘어 한 번에 하나만 보이고(왼쪽에서 고르기), 위의 칸에서 낱말로 찾아요
        topics = re.findall(r'<section id="(\w+)" data-name="([^"]+)"', html)
        self.assertEqual([name for _, name in topics],
                         ["처음 3분", "AI 연결", "대화 읽어 오기", "노선도 읽기", "할 일과 목록", "앞길", "떠 있는 버튼", "낱말 풀이", "막힐 때"])
        self.assertIn('id="find"', html)
        for _, name, body in re.findall(r'<section id="(\w+)" data-name="([^"]+)">(.*?)</section>', html, flags=re.S):
            words = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", body)).strip()
            self.assertLess(len(words), 800, name)                  # 한 주제는 한 화면에 (전에는 한 쪽에 4,500자가 이어져 있었어요)
        for words in ("AI 연결", "버튼 편집"):                         # 화면의 이름과 같은 말로 안내해요
            self.assertIn(words, html)
        self.assertIn("window.open('help'", window)
        # AI 연결: 정리에 쓸 AI를 화면에서 고르고 연결해요 (구독은 한 번 누르기 · API 키는 붙여 넣기). 키를 치는 칸은 가려져요
        for words in ("'AI 연결'", "engine/connect", "engine/choose", "engine/key", "input.type = 'password'", "Claude 구독", "ChatGPT 구독"):
            self.assertIn(words, window)
        swift = (ROOT / "mac" / "Gadak.swift").read_text(encoding="utf-8")
        self.assertIn('menu("도움말"', swift)
        self.assertIn('showPage(helpTitle, path: "help"', swift)
        # 전체 지도 닫기: 지도 쪽이 가닥 창의 길을 바로 부르고, 가닥 창에서는 Esc로도 닫혀요
        self.assertIn("window.gadakMapClose = closeMap", window)
        self.assertIn("parent.gadakMapClose", (ROOT / "backend" / "web" / "map.html").read_text(encoding="utf-8"))

    def test_item_state_is_kept(self):
        self.turn()
        turn_id = self.view()["chats"][0]["turns"][0]["id"]
        item = f"{turn_id}:p0"
        self.assertEqual(self.client.patch(f"/items/{item}", json={"state": "later"}).status_code, 200)
        self.assertEqual(self.view()["itemStates"], {item: "later"})
        self.assertEqual(self.client.patch(f"/items/{item}", json={"state": "gone"}).status_code, 400)
        self.assertEqual(self.client.patch(f"/items/{item}", data="state=done").status_code, 415)

    def test_import_export_files(self):
        both = json.dumps(CLAUDE_EXPORT + CHATGPT_EXPORT, ensure_ascii=False).encode("utf-8")
        packed = io.BytesIO()
        with zipfile.ZipFile(packed, "w") as archive:
            archive.writestr("conversations.json", both)
        first = self.client.post("/import", data=packed.getvalue(), content_type="application/zip")
        self.assertEqual((first.status_code, first.get_json()), (200, {"chats": 2, "turns": 3}))
        again = self.client.post("/import", data=both, content_type="application/json")
        self.assertEqual(again.get_json(), {"chats": 2, "turns": 3})
        chats = self.view(store.NO_PROJECT)["chats"]
        self.assertEqual(sorted((c["site"], c["title"], len(c["turns"])) for c in chats),
                         [("chatgpt", "발표 대본", 1), ("claude", "보고서 목차", 2)])
        self.assertEqual(self.client.post("/import", data=b"[]", content_type="application/json").status_code, 400)
        self.assertEqual(self.client.post("/import", data=both, content_type="text/plain").status_code, 415)

    def test_sources_and_connecting_cursor(self):
        rows = self.client.get("/sources").get_json()["sources"]
        self.assertEqual([(r["key"], r["mode"]) for r in rows],
                         [("claude-code", "auto"), ("codex", "auto"), ("cursor", "connect"),
                          ("extension", "extension"), ("export", "file")])
        self.assertFalse(rows[2]["connected"])
        done = self.client.post("/sources/cursor/connect", json={})
        self.assertEqual((done.status_code, done.get_json()), (200, {"ok": True}))
        hooks = json.loads((self.cursor_home / "hooks.json").read_text(encoding="utf-8"))
        self.assertEqual(hooks["hooks"]["beforeSubmitPrompt"], [{"command": "sh hooks/gadak.sh"}])
        self.assertTrue((self.cursor_home / "hooks" / "gadak.sh").exists())
        self.assertTrue(self.client.get("/sources").get_json()["sources"][2]["connected"])
        self.assertEqual(self.client.post("/sources/cursor/connect", json={}).get_json(), {"ok": True, "already": True})

    def test_an_existing_cursor_config_is_not_overwritten(self):
        self.cursor_home.mkdir(parents=True)
        mine = '{"version": 1, "hooks": {"stop": [{"command": "./my-own.sh"}]}}'
        (self.cursor_home / "hooks.json").write_text(mine, encoding="utf-8")
        refused = self.client.post("/sources/cursor/connect", json={})
        self.assertEqual(refused.status_code, 409)
        self.assertFalse(refused.get_json()["ok"])
        self.assertEqual((self.cursor_home / "hooks.json").read_text(encoding="utf-8"), mine)

    def test_classify_requests_and_pause(self):
        self.turn()
        self.rt.classifier.queue.clear()
        status = self.client.post("/classify", json={"chats": ["conv-1", "conv-1"]}).get_json()
        self.assertEqual((status["queued"], status["paused"]), (1, False))
        self.assertTrue(self.client.post("/classify", json={"pause": True}).get_json()["paused"])
        self.assertFalse(self.client.post("/classify", json={"pause": False}).get_json()["paused"])
        # 화면이 턴을 접어 보여 줄 때: 예전에 정리한 턴에도 답 간추림을 채워 달라고 해요
        self.rt.classifier.queue.clear()
        status = self.client.post("/classify", json={"chats": ["conv-1"], "gist": True}).get_json()
        self.assertEqual((status["queued"], self.rt.classifier.gist_wanted), (1, {"conv-1"}))


if __name__ == "__main__":
    unittest.main()
