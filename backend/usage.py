"""사용 기록 (README 5장 · docs/usage-guide.md 6번).

가닥을 어떻게 쓰는지를 숫자와 정해 둔 낱말로만 PC에 적어 두고, 사용자가 동의했을 때만 가닥 팀 서버로 보내요.
무엇을 적을 수 있는지는 usage_schema.py에 다 있어요. 대화 글 · 역 제목 · 파일 이름은 적을 칸이 없어요.

- 적기: record(). 표에 없는 이름 · 칸은 버려요. 적다가 생긴 문제로 가닥이 멈추지는 않아요.
- 동의: 묻기 전과 ‘안 보내기’일 때 적힌 기록은 PC에만 남고, 나중에 동의해도 보내지 않아요.
- 보내기: send(). 서버 주소(GADAK_COLLECT_URL)가 있고 동의했을 때만. 실패하면 다음 차례에 다시 보내요.
- 지우기: forget(). 서버에 있는 내 기록을 지워 달라고 하고, 보내기를 꺼요.
"""
import hashlib
import json
import ssl
import subprocess
import sys
import threading
import urllib.request
import uuid
from datetime import datetime

from . import config, store, usage_schema

BATCH = 200          # 한 번에 보내는 기록 수
TIMEOUT = 8
YES, NO = "yes", "no"


def state(conn) -> dict:
    """화면이 묻는 것: 서버가 정해져 있는지, 동의했는지, 얼마나 쌓이고 보냈는지."""
    share = store.setting(conn, "usage.share", "")
    counts = conn.execute(
        "SELECT COUNT(*) AS kept, COALESCE(SUM(share = 1 AND sent = 0), 0) AS waiting, COALESCE(SUM(sent), 0) AS sent FROM usage"
    ).fetchone()
    return {"configured": bool(config.COLLECT_URL), "share": share, "kept": counts["kept"],
            "waiting": counts["waiting"], "sent": counts["sent"]}


def sharing(conn) -> bool:
    return store.setting(conn, "usage.share", "") == YES


def install_id(conn) -> str:
    """이 PC의 가닥을 가리키는 무작위 번호. 계정 · 이메일 · PC 이름과 이어지지 않아요."""
    value = store.setting(conn, "usage.install")
    if not value:
        value = uuid.uuid4().hex
        store.set_setting(conn, "usage.install", value)
    return value


def consent(conn, share: bool) -> dict:
    with conn:
        store.set_setting(conn, "usage.share", YES if share else NO)
        if share:
            install_id(conn)
    return state(conn)


def chat_tag(conn, chat_id) -> str:
    """같은 대화의 기록을 서버가 한 번만 세게 하는 표시. 대화 id를 설치 번호와 섞어 되돌릴 수 없게 만들어요."""
    return hashlib.sha256(f"{install_id(conn)}:{chat_id}".encode("utf-8")).hexdigest()[:12]


def record(conn, name, fields=None, **more) -> bool:
    """사용 기록 한 줄을 적어요. 표(usage_schema)에 없는 것은 적지 않아요."""
    try:
        cleaned = usage_schema.clean(name, dict(fields or {}, **more))
        if not cleaned:
            return False
        with conn:
            conn.execute(
                "INSERT INTO usage(day, name, fields_json, share) VALUES(?, ?, ?, ?)",
                (datetime.now().strftime("%Y-%m-%d"), name, json.dumps(cleaned), 1 if sharing(conn) else 0),
            )
        return True
    except Exception:
        return False   # 사용 기록 때문에 가닥이 멈추면 안 돼요


def _event(row) -> dict:
    return {"seq": row["seq"], "day": row["day"], "name": row["name"], "fields": json.loads(row["fields_json"])}


def recent(conn, limit=30) -> list:
    """‘보내는 것 보기’: 서버로 가는 모양 그대로, 최근 것부터."""
    rows = conn.execute("SELECT * FROM usage ORDER BY seq DESC LIMIT ?", (limit,)).fetchall()
    return [dict(_event(r), share=bool(r["share"]), sent=bool(r["sent"])) for r in rows]


MAC_ROOTS = ("/usr/bin/security", "find-certificate", "-a", "-p", "/System/Library/Keychains/SystemRootCertificates.keychain")
_tls = None


def tls() -> ssl.SSLContext:
    """https 서버의 인증서를 확인하는 설정.

    python.org에서 받은 macOS용 파이썬은 인증서 묶음 없이 깔려서, 그대로 두면 어떤 https 서버에도 못 보내요.
    그럴 때만 macOS가 믿는 인증서를 읽어 더해요. 확인을 끄는 것이 아니에요: 만료됐거나 주소가 다른 인증서는 그대로 막혀요.
    """
    global _tls
    if _tls is None:
        context = ssl.create_default_context()
        if sys.platform == "darwin" and not context.get_ca_certs():
            try:
                roots = subprocess.run(MAC_ROOTS, capture_output=True, text=True, timeout=10).stdout
                if roots:
                    context.load_verify_locations(cadata=roots)
            except (OSError, subprocess.SubprocessError, ssl.SSLError):
                pass   # 못 읽었으면 보내기가 실패하고, 화면의 찾은 곳에 ‘보내지 못하고 있어요’로 보여요
        _tls = context
    return _tls


def _post(path, body) -> dict:
    request = urllib.request.Request(
        config.COLLECT_URL + path, data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json", "User-Agent": "gadak"}, method="POST",
    )
    with urllib.request.urlopen(request, timeout=TIMEOUT, context=tls()) as response:
        return json.load(response)


def send(conn) -> int:
    """보내도 되는 기록을 한 묶음 보내요. 보낸 수를 돌려줘요."""
    if not config.COLLECT_URL or not sharing(conn):
        return 0
    rows = conn.execute("SELECT * FROM usage WHERE share = 1 AND sent = 0 ORDER BY seq LIMIT ?", (BATCH,)).fetchall()
    if not rows:
        return 0
    _post("/v1/events", {"v": usage_schema.VERSION, "install": install_id(conn), "app": config.VERSION,
                         "events": [_event(r) for r in rows]})
    with conn:
        conn.executemany("UPDATE usage SET sent = 1 WHERE seq = ?", [(r["seq"],) for r in rows])
    return len(rows)


def forget(conn) -> dict:
    """보내기를 끄고, 서버에 있는 이 PC의 기록을 지워 달라고 해요. 다음에 다시 켜면 새 번호로 시작해요."""
    gone = None
    install = store.setting(conn, "usage.install")
    if config.COLLECT_URL and install:
        try:
            gone = _post("/v1/forget", {"install": install}).get("deleted")
        except Exception:
            gone = None    # 서버에 닿지 못했어요. 화면에 그대로 알려요
    with conn:
        store.set_setting(conn, "usage.share", NO)
        if gone is not None:
            conn.execute("DELETE FROM settings WHERE key = 'usage.install'")
            conn.execute("UPDATE usage SET share = 0, sent = 0")   # 서버에 없으니 ‘보낸 기록’도 0으로
    return dict(state(conn), deleted=gone)


def os_name() -> str:
    return {"darwin": "mac", "win32": "windows", "linux": "linux"}.get(sys.platform, "other")


def note_open(conn, via, engine) -> None:
    """켰을 때 한 번: 어디로 켰고, 어떤 입구의 대화가 얼마나 있는지(수만)."""
    sites = store.site_counts(conn)
    totals = conn.execute(
        "SELECT (SELECT COUNT(*) FROM projects) AS projects, (SELECT COUNT(*) FROM turns) AS turns"
    ).fetchone()
    record(conn, "open", via=via, os=os_name(), engine=engine if engine in ("claude_cli", "none") else "api",
           projects=totals["projects"], chats=sum(sites.values()), turns=totals["turns"],
           **{"chats_" + site.replace("-", "_"): count for site, count in sites.items()})


def note_chat(conn, chat_id) -> None:
    """정리가 끝난 대화의 모양(수만). 대화를 가리키는 것은 되돌릴 수 없는 표시뿐이에요."""
    chat = store.chat_row(conn, chat_id)
    if chat is None:
        return
    shape = conn.execute(
        "SELECT COUNT(*) AS turns, COALESCE(SUM(depth >= 1), 0) AS side, COALESCE(SUM(depth >= 2), 0) AS deep,"
        " COALESCE(SUM(dec IS NOT NULL), 0) AS decided, COUNT(DISTINCT seg) AS segments,"
        " (SELECT COUNT(DISTINCT p.turn_id) FROM parts p JOIN turns x ON x.id = p.turn_id WHERE x.chat_id = t.chat_id) AS multi,"
        " (SELECT COUNT(DISTINCT f.turn_id) FROM files f JOIN turns x ON x.id = f.turn_id WHERE x.chat_id = t.chat_id) AS files"
        " FROM turns t WHERE t.chat_id = ?", (chat_id,),
    ).fetchone()
    together = conn.execute("SELECT COUNT(*) FROM chats WHERE project_id = ?", (chat["project_id"],)).fetchone()[0]
    record(conn, "chat", chat=chat_tag(conn, chat_id), site=chat["site"], turns=shape["turns"], side=shape["side"],
           deep=shape["deep"], decided=shape["decided"], multi=shape["multi"], segments=shape["segments"],
           files=shape["files"], in_project=together)


class Sender:
    """켜 둔 동안 가끔 보내요. 서버가 없거나 동의하지 않았으면 아무것도 하지 않아요."""

    def __init__(self, runtime):
        self.rt = runtime
        self.wake = threading.Event()
        self.status = {"last": None, "error": None}

    def poke(self) -> None:
        """기다리지 말고 지금 보내요 (방금 동의했을 때)."""
        self.wake.set()

    def run_forever(self, stop) -> None:
        conn = self.rt.connect()
        wait = 20     # 켜고 조금 있다가 한 번, 그 뒤로는 config.SEND_EVERY마다
        while not stop.is_set():
            self.wake.wait(wait)
            self.wake.clear()
            wait = config.SEND_EVERY
            try:
                while send(conn) == BATCH:
                    pass
                self.status.update(last=store.now(), error=None)
            except Exception as exc:
                self.status["error"] = type(exc).__name__
        conn.close()
