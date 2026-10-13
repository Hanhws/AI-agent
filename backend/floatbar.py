"""떠 있는 가닥 버튼의 둘레 버튼을 사용자가 고르게 해요 (mac/Float.swift · 편집 화면은 backend/web/float-edit.html).

둘레에는 여섯 자리가 있어요. 자리마다 둘 중 하나를 둬요.
- 기능(action): 노선도 · 할 일 · 정함 · 산출물 · 앞길 · 찾기 · 창 · 도움말
- 프로젝트(project): 누르면 가닥 창을 열지 않고 그 프로젝트의 노선도(가장 최근 대화)를 띄워요. 버튼에 쓸 짧은 이름을 붙일 수 있어요

고른 것은 settings의 float.slots에 적어 둬요. 고른 적이 없으면 처음 모양(DEFAULT)이에요.
"""
import json
import re

from . import store

KEY = "float.slots"
MAX = 6                 # 둘레에 놓을 수 있는 수 (가닥 버튼 둘레의 반원에 겹치지 않고 놓이는 만큼)
LABEL_MAX = 4           # 프로젝트 버튼에 쓰는 이름의 글자 수 (동그라미 안에 들어가는 만큼)
# 기능: (버튼의 글, 마우스를 올리면 뜨는 말). 차례는 편집 화면에 보이는 차례예요
ACTIONS = {
    "map": ("노선도", "지금 대화의 노선도"),
    "todo": ("할 일", "놓친 일과 제안"),
    "dec": ("정함", "지금까지 정한 것"),
    "files": ("산출물", "나온 파일"),
    "ahead": ("앞길", "가닥이 찾아본 길"),
    "find": ("찾기", "가닥 창에서 대화 찾기"),
    "window": ("창", "가닥 창 열기"),
    "help": ("도움말", "쓰는 법과 낱말 풀이"),
}
DEFAULT = ("map", "todo", "dec", "files", "find", "window")
LISTS = ("todo", "dec", "files", "ahead")       # 목록 창의 칸을 여는 기능 (backend/web/strip.js가 아는 칸)


def short(name) -> str:
    """프로젝트 이름에서 버튼에 쓸 짧은 이름: 첫 낱말의 앞 세 글자."""
    words = re.split(r"[\s\-_·/()\[\]]+", (name or "").strip())
    first = next((w for w in words if w), "")
    return first[:3] or "프로젝트"


def _projects(conn) -> dict:
    return {p["id"]: p for p in store.projects(conn)}


def clean(conn, slots) -> list:
    """받은 것을 쓸 수 있는 모양으로: 아는 기능 · 있는 프로젝트만, 겹치는 것은 하나만, 여섯 개까지."""
    known, seen, out = _projects(conn), set(), []
    for slot in slots if isinstance(slots, list) else []:
        if not isinstance(slot, dict) or len(out) >= MAX:
            continue
        action, project = slot.get("action"), slot.get("project")
        if isinstance(action, str) and action in ACTIONS and ("a", action) not in seen:
            seen.add(("a", action))
            out.append({"action": action})
        elif isinstance(project, str) and project in known and ("p", project) not in seen:
            seen.add(("p", project))
            label = " ".join(str(slot.get("label") or "").split())[:LABEL_MAX]
            out.append({"project": project, "label": label or short(known[project]["name"])})
    return out


def load(conn) -> list:
    """적어 둔 자리들. 고른 적이 없으면 처음 모양. (없어진 프로젝트의 자리는 빼고 돌려줘요)"""
    raw = store.setting(conn, KEY)
    if raw is None:
        return [{"action": key} for key in DEFAULT]
    try:
        return clean(conn, json.loads(raw))
    except ValueError:
        return [{"action": key} for key in DEFAULT]


def save(conn, slots) -> list:
    kept = clean(conn, slots)
    store.set_setting(conn, KEY, json.dumps(kept, ensure_ascii=False))
    return kept


def reset(conn) -> list:
    conn.execute("DELETE FROM settings WHERE key = ?", (KEY,))
    return load(conn)


def resolved(conn) -> list:
    """버튼을 그리는 쪽(mac/Float.swift)이 받는 모양: [{key, kind, label, tip, project?, color?}]"""
    known, out = _projects(conn), []
    for slot in load(conn):
        if "action" in slot:
            label, tip = ACTIONS[slot["action"]]
            out.append({"key": slot["action"], "kind": "action", "label": label, "tip": tip})
        else:
            project = known[slot["project"]]
            out.append({"key": "p:" + project["id"], "kind": "project", "project": project["id"], "label": slot["label"],
                        "tip": f"{project['name']} · 이 프로젝트의 노선도", "color": project["color"]})
    return out


def editing(conn) -> dict:
    """편집 화면이 받는 것: 지금 자리들과, 더할 수 있는 기능 · 프로젝트."""
    known = _projects(conn)
    slots = []
    for slot in load(conn):
        if "action" in slot:
            slots.append({"action": slot["action"], "name": ACTIONS[slot["action"]][0]})
        else:
            project = known[slot["project"]]
            slots.append({"project": project["id"], "label": slot["label"], "name": project["name"], "color": project["color"]})
    return {
        "slots": slots, "max": MAX, "labelMax": LABEL_MAX,
        "actions": [{"key": key, "name": label, "tip": tip} for key, (label, tip) in ACTIONS.items()],
        "projects": [{"id": p["id"], "name": p["name"], "color": p["color"], "label": short(p["name"])} for p in known.values()],
    }
