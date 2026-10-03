"""가닥이 모으는 사용 기록의 전부 (README 5장 · docs/usage-guide.md 6번).

PC에서 적을 때(backend/usage.py)와 서버가 받을 때(server/app.py) 둘 다 이 표로 걸러요.
여기 없는 이름과 칸은 버리고, 값은 숫자 · 참거짓 · 아래에 정해 둔 낱말뿐이에요. 글이 들어갈 칸이 없어서
대화 내용 · 역 제목 · 파일 이름 · 경로는 실수로도 실리지 않아요. 무엇을 모을지 바꾸려면 이 파일을 고쳐야 해요.

이 파일은 다른 것을 불러오지 않아요. 서버(server/)가 가닥 본체 없이 이 표만 가져다 쓸 수 있게요.
"""
import re

VERSION = 1

SITES = ("claude", "chatgpt", "gemini", "claude-code", "codex", "cursor")
KINDS = ("missing", "unasked", "yours", "branch", "open", "check", "topic", "repeat", "handoff", "next")


def number(top):
    """0부터 top까지의 정수. 넘으면 top으로 적어요."""
    return ("number", top)


def one_of(*words):
    return ("word", frozenset(words))


FLAG = ("flag",)
TAG = ("tag",)   # 같은 대화를 다시 셀 때 알아보는 표시. 대화 id를 섞어 만든 16진수 12자라 글을 담을 수 없어요

_TAG = re.compile(r"[0-9a-f]{12}")
_DAY = re.compile(r"\d{4}-\d{2}-\d{2}")
_INSTALL = re.compile(r"[0-9a-f]{32}")

EVENTS = {
    # 켰을 때: 어디로 켰는지, 어떤 입구의 대화가 얼마나 있는지
    "open": {
        "via": one_of("app", "browser"), "os": one_of("mac", "windows", "linux", "other"),
        "engine": one_of("claude_cli", "api", "none"),
        "projects": number(500), "chats": number(5000), "turns": number(100000),
        **{"chats_" + site.replace("-", "_"): number(5000) for site in SITES},
    },
    # 정리가 끝난 대화 하나의 모양: 사용 유형(한 창 몰아쓰기 · 매번 새 창 · 프로젝트 분리 …)을 보려고
    "chat": {
        "chat": TAG, "site": one_of(*SITES), "turns": number(2000), "side": number(2000), "deep": number(2000),
        "decided": number(2000), "multi": number(2000), "segments": number(200), "files": number(2000),
        "in_project": number(5000),
    },
    # 1단 분류 호출 한 번: 몇 턴을 물어 몇 턴을 받았고 몇 초 걸렸는지
    "classify": {"turns": number(50), "done": number(50), "seconds": number(900)},
    # 2단 확인 한 번: 왜 봤고, 몇 걸음에 어떤 도구를 썼고, 한마디를 만들었는지
    "check": {
        "missing": FLAG, "unasked": FLAG, "handoff": FLAG,
        "steps": number(20), "calls": number(20), "made": number(10), "dropped": number(20),
        "ended": one_of("finish", "limit", "odd"), "seconds": number(900),
        "get_request": number(20), "get_diff": number(20), "search_decisions": number(20), "list_open_items": number(20),
    },
    # 한마디 · 할 일: 어떤 종류가 만들어지고, 보이고, 실행되고, 미뤄지는지
    "item": {"kind": one_of(*KINDS), "did": one_of("made", "shown", "run", "later", "close"),
             "at": one_of("auto", "nudge", "list")},
    # 화면에서 누른 것
    "ui": {"what": one_of(
        "scope_chat", "scope_all", "tab_todo", "tab_dec", "tab_files", "search", "seg_open", "seg_close",
        "open_all", "fold_all", "list_open", "list_close", "map_open", "map_close", "go_map", "go_rail", "go_list",
        "open_chat", "open_project", "full_text", "trace", "sources", "copy",
    )},
    # 내보내기 파일 불러오기 · Cursor 연결
    "import": {"claude": number(5000), "chatgpt": number(5000), "turns": number(100000), "ok": FLAG},
    "connect": {"cursor": FLAG},
    # 정리가 멈춤: 호출 한도 · 엔진 문제(로그인, 구독 한도) · 그 밖
    "stop": {"where": one_of("classify", "check"), "why": one_of("limit", "engine", "other")},
}


def _value(kind, value):
    """칸의 종류에 맞는 값이면 그 값을, 아니면 None."""
    if kind[0] == "number":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        return max(0, min(int(value), kind[1]))
    if kind[0] == "flag":
        return value if isinstance(value, bool) else None
    if kind[0] == "word":
        return value if isinstance(value, str) and value in kind[1] else None
    if kind[0] == "tag":
        return value if isinstance(value, str) and _TAG.fullmatch(value) else None
    return None


def clean(name, fields):
    """표에 있는 이름이면 표에 있는 칸만 남긴 dict를, 모르는 이름이면 None을 돌려줘요."""
    spec = EVENTS.get(name) if isinstance(name, str) else None
    if spec is None or not isinstance(fields, dict):
        return None
    out = {}
    for key, kind in spec.items():
        value = _value(kind, fields.get(key))
        if value is not None:
            out[key] = value
    return out


def valid_day(value) -> bool:
    return isinstance(value, str) and bool(_DAY.fullmatch(value))


def valid_install(value) -> bool:
    return isinstance(value, str) and bool(_INSTALL.fullmatch(value))
