"""떠 있는 가닥 버튼의 둘레 버튼을 사용자가 고르기 (backend/floatbar.py · mac/Float.swift · backend/web/float-edit.html)."""
import re
import tempfile
import unittest
from pathlib import Path

from backend import floatbar
from backend.app import create_app

ROOT = Path(__file__).resolve().parent.parent
STOCK = ["map", "todo", "dec", "files", "find", "window"]


class FloatBarTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        app = create_app(db_path=Path(tmp.name) / "gadak.db", engine=None)
        self.rt, self.client = app.config["GADAK"], app.test_client()
        self.turn("환율 알리미", "c1", "m1", "임계값은 얼마가 좋아?")
        self.turn("DB 수업", "c2", "m2", "JOIN이 뭐야?")
        self.turn("환율 알리미", "c3", "m3", "알림 문구도 바꿔 줘")          # 환율 알리미에서 가장 최근에 쓴 대화

    def turn(self, project, chat, ref, user):
        done = self.client.post("/turns", json={"project": project, "chat": {"id": chat, "site": "claude"},
                                                "turn": {"messageRef": ref, "user": user, "ai": "네."}})
        self.assertEqual(done.status_code, 200)

    def slots(self):
        return self.client.get("/float").get_json()["slots"]

    def put(self, slots):
        return self.client.post("/float/slots", json={"slots": slots})

    def test_the_six_stock_buttons_until_the_user_changes_them(self):
        self.assertEqual([(s["key"], s["kind"]) for s in self.slots()], [(key, "action") for key in STOCK])
        self.assertEqual([s["label"] for s in self.slots()], ["노선도", "할 일", "정함", "산출물", "찾기", "창"])
        editing = self.client.get("/float/slots").get_json()
        self.assertEqual(([s["action"] for s in editing["slots"]], editing["max"], editing["labelMax"]), (STOCK, 6, 4))
        self.assertEqual([a["key"] for a in editing["actions"]], ["map", "todo", "dec", "files", "ahead", "find", "window", "help"])
        self.assertEqual(sorted((p["id"], p["label"]) for p in editing["projects"]), [("DB 수업", "DB"), ("환율 알리미", "환율")])
        self.assertTrue(all(re.fullmatch(r"#[0-9A-Fa-f]{6}", p["color"]) for p in editing["projects"]))    # 가닥 창과 같은 노선 색

    def test_buttons_can_be_removed_added_and_put_in_another_order(self):
        before = self.client.get("/status").get_json()["rev"]
        saved = self.put([{"action": "todo"}, {"action": "ahead"}, {"action": "help"}])
        self.assertEqual((saved.status_code, saved.get_json()["ok"]), (200, True))
        self.assertEqual([s["key"] for s in self.slots()], ["todo", "ahead", "help"])
        self.assertGreater(self.client.get("/status").get_json()["rev"], before)
        # 모르는 것 · 겹치는 것은 빼고, 여섯 개까지만 둬요
        self.put([{"action": "없는-기능"}, {"action": "map"}, {"action": "map"}, "글", {"action": "todo"}, {"action": "dec"},
                  {"action": "files"}, {"action": "ahead"}, {"action": "find"}, {"action": "window"}])
        self.assertEqual([s["key"] for s in self.slots()], ["map", "todo", "dec", "files", "ahead", "find"])
        self.put([])                                                        # 다 빼면 가닥 버튼만 떠요
        self.assertEqual(self.slots(), [])
        self.assertEqual(self.client.post("/float/slots", json={"slots": "todo"}).status_code, 400)
        self.assertEqual(self.client.post("/float/slots", data="slots=todo").status_code, 415)   # 다른 사이트가 폼으로 못 바꾸게
        back = self.client.post("/float/slots", json={"reset": True}).get_json()
        self.assertEqual(([s["action"] for s in back["slots"]], [s["key"] for s in self.slots()]), (STOCK, STOCK))

    def test_a_project_button_shows_that_projects_latest_chat_without_the_window(self):
        self.put([{"action": "map"}, {"project": "DB 수업", "label": " 디비 수업반 "}, {"project": "환율 알리미"}, {"project": "없는 프로젝트"},
                  {"project": "DB 수업"}])
        mine = self.slots()
        self.assertEqual([(s["key"], s["label"]) for s in mine], [("map", "노선도"), ("p:DB 수업", "디비 수"), ("p:환율 알리미", "환율")])
        project = mine[1]
        self.assertEqual((project["kind"], project["project"], project["tip"]), ("project", "DB 수업", "DB 수업 · 이 프로젝트의 노선도"))
        self.assertRegex(project["color"], r"#[0-9A-Fa-f]{6}")
        # 누르면 화면이 그 프로젝트의 가장 최근 대화를 물어요. 그냥 물으면 ‘지금 쓰는 대화’
        self.assertEqual(self.client.get("/float").get_json()["chat"]["id"], "c3")
        self.assertEqual(self.client.get("/float?project=DB 수업").get_json()["chat"], {"id": "c2", "title": None, "project": "DB 수업"})
        self.assertEqual(self.client.get("/float?project=환율 알리미").get_json()["chat"]["id"], "c3")
        self.assertIsNone(self.client.get("/float?project=없는 프로젝트").get_json()["chat"])
        # 그 프로젝트의 대화를 목록에서 다 빼면 버튼도 빠져요
        self.assertEqual(self.client.post("/chats/hidden", json={"ids": ["c2"], "hidden": True}).status_code, 200)
        self.assertEqual([s["key"] for s in self.slots()], ["map", "p:환율 알리미"])

    def test_a_short_name_for_the_button_comes_from_the_project_name(self):
        for name, label in (("환율 알리미", "환율"), ("AI 응용사례특강-공훈의", "AI"), ("데이터베이스", "데이터"), ("(프로젝트 없음)", "프로젝"), ("", "프로젝트")):
            self.assertEqual(floatbar.short(name), label, name)

    def test_the_button_the_screens_and_the_backend_agree(self):
        swift = (ROOT / "mac" / "Float.swift").read_text(encoding="utf-8")
        self.assertEqual(re.findall(r'FloatAction\(key: "(\w+)"', swift), list(floatbar.DEFAULT))          # 처음 모양이 같아요
        handled = set(re.findall(r'case "(\w+)":', swift.split("func choose(")[1].split("func pinnedScript")[0]))
        self.assertEqual(handled | set(floatbar.LISTS), set(floatbar.ACTIONS))                              # 고를 수 있는 기능은 다 눌려요
        for words in ('json["slots"]', "applySlots", '"버튼 편집…"', 'URLQueryItem(name: "project"'):
            self.assertIn(words, swift)
        self.assertIn('path: "float/edit"', (ROOT / "mac" / "Gadak.swift").read_text(encoding="utf-8"))
        strip = (ROOT / "backend" / "web" / "strip.js").read_text(encoding="utf-8")
        tabs = set(re.findall(r"(\w+): 1", re.search(r"TABS = \{([^}]*)\}", strip).group(1))) | {"ahead"}    # 목록 창이 여는 칸
        self.assertEqual(tabs, set(floatbar.LISTS))
        for words in ("'float' + (S.pin ? '?project='", "'project' in o"):
            self.assertIn(words, strip)
        with self.client.get("/float/edit") as page:
            html = page.get_data(as_text=True)
        self.assertEqual(page.status_code, 200)
        for words in ("떠 있는 버튼 편집", "여섯 개까지", "처음 모양으로", "fetch('slots'"):
            self.assertIn(words, html)
        self.assertNotIn("<textarea", html)


if __name__ == "__main__":
    unittest.main()
