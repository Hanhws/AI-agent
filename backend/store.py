"""SQLite 저장소.

테이블과 필드 이름은 docs/schema.md를 따라요. edits · item_states · sync_state 테이블과
turns의 state · classified, chats의 via · cwd는 10/3에 더한 것이에요 (docs/changes-detail.md 4번).
agent_runs 테이블과 turns의 look · checked는 2단(확인)을 붙이며 더했어요 (docs/changes-detail.md 8번).
auto_log는 가닥이 직접 보낸 것의 기록이에요 (승인한 종류의 자동 실행 · backend/auto.py).
chats.hidden은 사용자가 목록에서 뺀 대화예요(1). 읽어 둔 글은 그대로 두고, 화면 · 찾기 · 정리에서만 빠져요.
parts.open은 0 답함 · 1 빠짐(2단이 확인) · 2 빠진 것 같음(1단의 후보, 화면에는 안 보냄)이에요.
turns.gist는 답을 간추린 두세 줄이에요(JSON 배열). 1단이 분류할 때 같이 적어요. NULL은 아직 안 적은 것, []는 적을 것이 없던 것.
"""
import collections
import json
import sqlite3
import threading
import unicodedata
import uuid
import zlib
from datetime import datetime, timedelta, timezone
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS projects(
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS chats(
  id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL REFERENCES projects(id),
  title TEXT,
  site TEXT NOT NULL,
  created_at TEXT NOT NULL,
  via TEXT,
  cwd TEXT,
  hidden INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS turns(
  id TEXT PRIMARY KEY,
  chat_id TEXT NOT NULL REFERENCES chats(id),
  seq INTEGER NOT NULL,
  depth INTEGER NOT NULL DEFAULT 0,
  title TEXT NOT NULL,
  seg TEXT,
  topic TEXT,
  dec TEXT,
  ret INTEGER NOT NULL DEFAULT 0,
  ref TEXT,
  user TEXT NOT NULL DEFAULT '',
  ai TEXT NOT NULL DEFAULT '',
  message_ref TEXT NOT NULL,
  created_at TEXT NOT NULL,
  state TEXT NOT NULL DEFAULT 'open',
  classified INTEGER NOT NULL DEFAULT 0,
  look TEXT,
  checked INTEGER NOT NULL DEFAULT 0,
  gist TEXT,
  UNIQUE(chat_id, message_ref)
);
CREATE TABLE IF NOT EXISTS parts(
  turn_id TEXT NOT NULL REFERENCES turns(id),
  idx INTEGER NOT NULL,
  t TEXT NOT NULL,
  type TEXT NOT NULL,
  open INTEGER NOT NULL DEFAULT 0,
  target TEXT,
  PRIMARY KEY(turn_id, idx)
);
CREATE TABLE IF NOT EXISTS files(
  turn_id TEXT NOT NULL REFERENCES turns(id),
  name TEXT NOT NULL,
  url TEXT,
  base_name TEXT,
  PRIMARY KEY(turn_id, name)
);
CREATE TABLE IF NOT EXISTS edits(
  turn_id TEXT NOT NULL REFERENCES turns(id),
  idx INTEGER NOT NULL,
  file TEXT NOT NULL,
  old TEXT,
  new TEXT,
  PRIMARY KEY(turn_id, idx)
);
CREATE TABLE IF NOT EXISTS items(
  id TEXT PRIMARY KEY,
  turn_id TEXT NOT NULL REFERENCES turns(id),
  kind TEXT NOT NULL,
  text TEXT NOT NULL,
  why TEXT,
  btn TEXT,
  prompt TEXT,
  effect TEXT,
  pop_json TEXT,
  at TEXT,
  state TEXT NOT NULL DEFAULT 'open',
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS item_states(
  id TEXT PRIMARY KEY,
  state TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS agent_runs(
  id TEXT PRIMARY KEY,
  turn_id TEXT NOT NULL REFERENCES turns(id),
  trigger TEXT NOT NULL,
  steps_json TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sync_state(
  path TEXT PRIMARY KEY,
  source TEXT NOT NULL,
  size INTEGER NOT NULL,
  mtime REAL NOT NULL,
  offset INTEGER NOT NULL,
  state_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS usage(
  seq INTEGER PRIMARY KEY AUTOINCREMENT,
  day TEXT NOT NULL,
  name TEXT NOT NULL,
  fields_json TEXT NOT NULL,
  share INTEGER NOT NULL DEFAULT 0,
  sent INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS settings(
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS auto_log(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  chat_id TEXT NOT NULL,
  item_id TEXT,
  kind TEXT NOT NULL,
  text TEXT NOT NULL,
  created_at TEXT NOT NULL
);
"""

# 먼저 만들어진 DB에 없는 열 (CREATE TABLE IF NOT EXISTS는 열을 더해 주지 않아요)
ADDED_COLUMNS = {
    "chats": {"via": "TEXT", "cwd": "TEXT", "hidden": "INTEGER NOT NULL DEFAULT 0"},
    "turns": {"look": "TEXT", "checked": "INTEGER NOT NULL DEFAULT 0", "gist": "TEXT", "dec_note": "TEXT"},
}

NO_PROJECT = "_none"
LOOSE_PROJECT = "폴더 없는 대화"   # Claude 데스크톱이 폴더 없이 연 세션은 앱이 만든 임시 폴더(scratch-workspaces)에서 돌아요
TITLE_LEN = 16
MAX_AI = 20000            # 답이 아주 긴 턴은 앞 조금과 끝을 남겨요 (결론은 끝에 있어요)
AI_HEAD = 4000
CUT = "\n…(가운데 줄임)…\n"
CLIP_USER, CLIP_AI = 600, 700   # 노선도 화면에 보내는 길이. 전체는 turn_full
ITEM_STATES = {"open", "later", "done"}
MISSING, MAYBE_MISSING = 1, 2   # parts.open
# 4: usage · settings (사용 기록) · 5: auto_log (자동 실행) · 6: chats.hidden (목록에서 뺀 대화)
# 7 · 8: 두 가지에서 따로 올린 번호예요 (turns.gist 답 간추림 / scratch 폴더 대화 묶기 · turns.dec_note). 9: 둘을 합침
SCHEMA_VERSION = 9
_setup = threading.Lock()  # 여러 스레드가 동시에 처음 열면 테이블 만들기가 서로 막혀요
_checked = set()           # 이 프로세스에서 열 확인을 마친 저장소


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def norm_ts(value) -> str:
    """입구마다 다른 시각 표기(…Z, 밀리초, 초 단위 숫자)를 한 가지로 맞춰요."""
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, timezone.utc).isoformat(timespec="seconds")
    if isinstance(value, str) and value:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return now()
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc).isoformat(timespec="seconds")
    return now()


def connect(db_path) -> sqlite3.Connection:
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    if conn.execute("PRAGMA user_version").fetchone()[0] < SCHEMA_VERSION:
        with _setup:
            _create(conn)
    elif str(path) not in _checked:
        # 판 번호가 이미 높은 저장소예요(다른 가지의 코드가 먼저 올려 뒀을 수 있어요). 번호만 믿지 않고, 이 코드가 쓰는 열이 있는지 봐요
        with _setup:
            _add_columns(conn)
            conn.commit()
    _checked.add(str(path))
    return conn


def _create(conn) -> None:
    if conn.execute("PRAGMA user_version").fetchone()[0] >= SCHEMA_VERSION:
        return
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(SCHEMA)
    _add_columns(conn)
    # 폴더 없이 연 데스크톱 대화(임시 폴더)는 한 프로젝트로 묶어요
    if conn.execute("SELECT 1 FROM chats WHERE cwd LIKE '%/scratch-workspaces/%' LIMIT 1").fetchone():
        conn.execute("INSERT OR IGNORE INTO projects(id, name) VALUES(?, ?)", (LOOSE_PROJECT, LOOSE_PROJECT))
        conn.execute("UPDATE chats SET project_id = ? WHERE cwd LIKE '%/scratch-workspaces/%'", (LOOSE_PROJECT,))
    conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
    conn.commit()


def _add_columns(conn) -> None:
    for table, columns in ADDED_COLUMNS.items():
        have = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
        for name, kind in columns.items():
            if name not in have:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {kind}")


def provisional_title(text: str) -> str:
    """분류 전까지 쓰는 임시 역 제목. 제목은 원래 에이전트가 만들어요(README 3-1)."""
    first = next((line.strip() for line in (text or "").splitlines() if line.strip()), "")
    if not first:
        return "(질문 없음)"
    return first if len(first) <= TITLE_LEN else first[:TITLE_LEN] + "…"


def folder_project(cwd):
    """대화가 돈 폴더 → 프로젝트 이름. 임시 폴더에서 연 대화는 한 프로젝트로 묶어요."""
    if not cwd:
        return None
    path = Path(cwd)
    return LOOSE_PROJECT if "scratch-workspaces" in path.parts else project_key(path.name)


def project_key(name):
    """한글 이름은 자모가 풀린 형태로 들어오기도 해서 한 가지 형태(NFC)로 맞춰요."""
    return unicodedata.normalize("NFC", name) if name else name


def upsert_chat(conn, *, project, chat_id, site, title=None, created_at=None, via=None, cwd=None) -> None:
    project = project_key(project)
    project_id = project or NO_PROJECT
    conn.execute(
        "INSERT OR IGNORE INTO projects(id, name) VALUES(?, ?)",
        (project_id, project or "(프로젝트 없음)"),
    )
    conn.execute(
        "INSERT OR IGNORE INTO chats(id, project_id, title, site, created_at, via, cwd) VALUES(?, ?, ?, ?, ?, ?, ?)",
        (chat_id, project_id, title, site, norm_ts(created_at) if created_at else now(), via, cwd),
    )
    if title:
        conn.execute("UPDATE chats SET title = ? WHERE id = ? AND title IS NULL", (title, chat_id))
    if cwd:
        conn.execute("UPDATE chats SET cwd = ? WHERE id = ? AND cwd IS NULL", (cwd, chat_id))


def set_chat_title(conn, chat_id, title) -> None:
    conn.execute("UPDATE chats SET title = ? WHERE id = ?", (title, chat_id))


def set_chat_project(conn, chat_id, project) -> bool:
    """대화를 그 프로젝트로 옮겨요 (사람이 나눈 그룹을 따라갈 때). 옮겼으면 True."""
    project = project_key(project)
    conn.execute("INSERT OR IGNORE INTO projects(id, name) VALUES(?, ?)", (project, project))
    return conn.execute("UPDATE chats SET project_id = ? WHERE id = ? AND project_id != ?",
                        (project, chat_id, project)).rowcount > 0


def move_chat(conn, chat_id, project) -> bool:
    """프로젝트 없이 들어온 대화의 프로젝트를 나중에 알게 되면 그쪽으로 옮겨요. 옮겼으면 True."""
    project = project_key(project)
    row = chat_row(conn, chat_id)
    if not project or row is None or row["project_id"] != NO_PROJECT:
        return False
    conn.execute("INSERT OR IGNORE INTO projects(id, name) VALUES(?, ?)", (project, project))
    conn.execute("UPDATE chats SET project_id = ? WHERE id = ?", (project, chat_id))
    return True


def set_hidden(conn, chat_ids, hidden=True) -> list:
    """대화를 목록에서 빼거나 되돌려요. 읽어 둔 글은 지우지 않아요: 화면 · 찾기 · 정리 · 자동 실행에서만 빠져요.
    그 대화가 이어져도 다시 나타나지 않아요. 바뀐 대화의 id를 돌려줘요."""
    value, changed = (1 if hidden else 0), []
    for chat_id in chat_ids:
        if conn.execute("UPDATE chats SET hidden = ? WHERE id = ? AND hidden != ?", (value, chat_id, value)).rowcount:
            changed.append(chat_id)
    return changed


def visible_chat_ids(conn, project_id) -> list:
    return [r["id"] for r in conn.execute(
        "SELECT id FROM chats WHERE project_id = ? AND hidden = 0", (project_key(project_id),))]


def hidden_count(conn) -> int:
    return conn.execute("SELECT COUNT(*) FROM chats WHERE hidden = 1").fetchone()[0]


def hidden_chats(conn) -> list:
    """목록에서 뺀 대화들 (최근에 쓴 것부터). 되돌릴 때 알아볼 수 있게 제목 · 프로젝트 · 쓴 곳만."""
    rows = conn.execute(
        "SELECT c.id, c.title, c.site, c.created_at, c.project_id, p.name AS project,"
        " (SELECT MAX(t.created_at) FROM turns t WHERE t.chat_id = c.id) AS last,"
        " (SELECT t.title FROM turns t WHERE t.chat_id = c.id ORDER BY t.seq LIMIT 1) AS first"
        " FROM chats c JOIN projects p ON p.id = c.project_id WHERE c.hidden = 1 ORDER BY last DESC, c.rowid DESC"
    )
    return [{"id": r["id"], "title": r["title"] or r["first"] or "(질문 없음)", "site": r["site"],
             "date": display_date(r["last"] or r["created_at"]),
             "project": {"id": r["project_id"], "name": r["project"]}} for r in rows]


def find_turn(conn, chat_id, message_ref):
    return conn.execute(
        "SELECT * FROM turns WHERE chat_id = ? AND message_ref = ?", (chat_id, message_ref)
    ).fetchone()


def latest_open_turn(conn, chat_id):
    return conn.execute(
        "SELECT * FROM turns WHERE chat_id = ? AND state = 'open' ORDER BY seq DESC LIMIT 1", (chat_id,)
    ).fetchone()


def upsert_turn(conn, *, chat_id, message_ref, user=None, ai=None, state=None, created_at=None):
    """(chat_id, message_ref)가 같으면 새 역을 만들지 않고 덮어써요."""
    row = find_turn(conn, chat_id, message_ref)
    if row is None:
        seq = conn.execute(
            "SELECT COALESCE(MAX(seq), 0) + 1 FROM turns WHERE chat_id = ?", (chat_id,)
        ).fetchone()[0]
        turn_id = "t" + uuid.uuid4().hex[:10]
        conn.execute(
            "INSERT INTO turns(id, chat_id, seq, title, user, ai, message_ref, created_at, state)"
            " VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (turn_id, chat_id, seq, provisional_title(user or ""), user or "", ai or "",
             message_ref, norm_ts(created_at) if created_at else now(), state or "open"),
        )
    else:
        turn_id = row["id"]
        if user is not None and user != row["user"]:
            conn.execute("UPDATE turns SET user = ? WHERE id = ?", (user, turn_id))
            if not row["classified"]:
                conn.execute("UPDATE turns SET title = ? WHERE id = ?", (provisional_title(user), turn_id))
        if ai is not None:
            conn.execute("UPDATE turns SET ai = ? WHERE id = ?", (ai, turn_id))
        if state is not None:
            conn.execute("UPDATE turns SET state = ? WHERE id = ?", (state, turn_id))
    return conn.execute("SELECT * FROM turns WHERE id = ?", (turn_id,)).fetchone()


def append_answer(conn, turn_id, text) -> None:
    """답이 여러 조각으로 올 때 이어 붙여요. 너무 길면 가운데를 줄여요."""
    row = conn.execute("SELECT ai FROM turns WHERE id = ?", (turn_id,)).fetchone()
    if row is None or not text:
        return
    ai = (row["ai"] + "\n\n" + text) if row["ai"] else text
    if len(ai) > MAX_AI:
        head, _, rest = ai.partition(CUT)
        tail = rest or ai[AI_HEAD:]
        ai = head[:AI_HEAD] + CUT + tail[-(MAX_AI - AI_HEAD):]
    conn.execute("UPDATE turns SET ai = ? WHERE id = ?", (ai, turn_id))


def append_user(conn, turn_id, text) -> None:
    """답이 오기 전에 이어서 보낸 말을 같은 질문에 붙여요."""
    row = conn.execute("SELECT user FROM turns WHERE id = ?", (turn_id,)).fetchone()
    if row is not None and text:
        conn.execute("UPDATE turns SET user = ? WHERE id = ?", ((row["user"] + "\n\n" + text)[:MAX_AI], turn_id))


def clear_answers(conn, chat_id) -> None:
    """원본 파일을 처음부터 다시 읽을 때 답이 두 번 붙지 않게 비워요."""
    conn.execute("UPDATE turns SET ai = '' WHERE chat_id = ?", (chat_id,))


def close_open_turns(conn, chat_id, keep_ref=None) -> None:
    """새 질문이 오면 그 대화에서 답을 기다리던 앞 턴은 끝난 것으로 봐요."""
    conn.execute(
        "UPDATE turns SET state = 'done' WHERE chat_id = ? AND state = 'open' AND message_ref IS NOT ?",
        (chat_id, keep_ref),
    )


def add_edits(conn, turn_id, edits) -> None:
    """같은 변경이 다시 와도 한 번만 남겨요."""
    seen = {
        (r["file"], r["old"], r["new"])
        for r in conn.execute("SELECT file, old, new FROM edits WHERE turn_id = ?", (turn_id,))
    }
    idx = conn.execute(
        "SELECT COALESCE(MAX(idx), -1) + 1 FROM edits WHERE turn_id = ?", (turn_id,)
    ).fetchone()[0]
    for edit in edits or []:
        key = (edit.get("file"), edit.get("old"), edit.get("new"))
        if not key[0] or key in seen:
            continue
        seen.add(key)
        conn.execute(
            "INSERT INTO edits(turn_id, idx, file, old, new) VALUES(?, ?, ?, ?, ?)", (turn_id, idx, *key)
        )
        idx += 1
        add_file(conn, turn_id, key[0])


def add_file(conn, turn_id, name, url=None) -> None:
    base = Path(name).name
    conn.execute(
        "INSERT OR IGNORE INTO files(turn_id, name, url, base_name) VALUES(?, ?, ?, ?)",
        (turn_id, name, url, base),
    )


def set_classification(conn, turn_id, *, title, depth, seg=None, topic=None, dec=None, ret=False,
                       ref=None, parts=None, look=None, gist=None, dec_note=None) -> None:
    """1단 분류 결과를 역에 적어요 (backend/agent/classify.py). look은 2단이 확인할 까닭들이에요.
    gist는 답을 간추린 줄들이에요. 없으면 빈 목록으로 적어 둬요(다시 묻지 않게).
    dec_note는 정한 것을 대화 밖에서도 읽히게 풀어 쓴 한 문장이에요 (이어 가기 요약에 써요)."""
    conn.execute(
        "UPDATE turns SET title = ?, depth = ?, seg = ?, topic = ?, dec = ?, dec_note = ?, ret = ?, ref = ?, classified = 1,"
        " look = ?, checked = 0, gist = ? WHERE id = ?",
        (title, depth, seg, topic, dec, dec_note, 1 if ret else 0, ref, ",".join(look) if look else None,
         json.dumps(list(gist or []), ensure_ascii=False), turn_id),
    )
    conn.execute("DELETE FROM parts WHERE turn_id = ?", (turn_id,))
    for idx, part in enumerate(parts or []):
        conn.execute(
            "INSERT INTO parts(turn_id, idx, t, type, open, target) VALUES(?, ?, ?, ?, ?, ?)",
            (turn_id, idx, part["t"], part["type"], int(part.get("open") or 0), part.get("target")),
        )


def reset_classification(conn, turn_id) -> None:
    """답이 달라진 턴은 분류 전으로 돌려요. 그 턴에서 나눈 요청과 만든 할 일도 지워요 (다시 정리하면 새로 생겨요)."""
    conn.execute("UPDATE turns SET classified = 0, look = NULL, checked = 0, gist = NULL WHERE id = ?", (turn_id,))
    conn.execute("DELETE FROM parts WHERE turn_id = ?", (turn_id,))
    conn.execute("DELETE FROM items WHERE turn_id = ?", (turn_id,))


def set_gist(conn, turn_id, lines) -> None:
    """이미 분류한 역에 답 간추림만 채워요. 분류 · 할 일은 그대로 둬요."""
    conn.execute("UPDATE turns SET gist = ? WHERE id = ?", (json.dumps(list(lines or []), ensure_ascii=False), turn_id))


def without_gist(conn, chat_id) -> list:
    """분류는 됐는데 답 간추림이 아직 없는 턴 (gist 칸이 생기기 전에 분류한 것)."""
    return conn.execute(
        "SELECT * FROM turns WHERE chat_id = ? AND classified = 1 AND gist IS NULL ORDER BY seq", (chat_id,)
    ).fetchall()


def put_in_order(conn, chat_id, turn_ids) -> bool:
    """이 역들이 주어진 차례로 놓이게 해요. 이 역들이 쓰던 자리(seq)만 서로 바꾸고 다른 역은 그대로 둬요.
    바꾼 것이 있으면 True."""
    have = {r["id"]: r["seq"] for r in conn.execute("SELECT id, seq FROM turns WHERE chat_id = ?", (chat_id,))}
    seqs = [have[turn_id] for turn_id in turn_ids]
    if seqs == sorted(seqs):
        return False
    for turn_id, seq in zip(turn_ids, sorted(seqs)):
        if have[turn_id] != seq:
            conn.execute("UPDATE turns SET seq = ? WHERE id = ?", (seq, turn_id))
    return True


def waiting_checks(conn, chat_id) -> list:
    """2단이 아직 확인하지 않은 턴. 지금에 가까운 턴부터."""
    return conn.execute(
        "SELECT * FROM turns WHERE chat_id = ? AND classified = 1 AND checked = 0 AND look IS NOT NULL"
        " AND (SELECT hidden FROM chats WHERE id = turns.chat_id) = 0 ORDER BY seq DESC", (chat_id,),
    ).fetchall()


def set_checked(conn, turn_id, value) -> None:
    """2단 확인을 마쳤으면 1, 거듭 실패해 그만두면 -1."""
    conn.execute("UPDATE turns SET checked = ? WHERE id = ?", (value, turn_id))


def confirm_missing(conn, turn_id, missing) -> None:
    """1단이 빠진 것 같다고 본 요청 중 2단이 확인한 것만 빠짐(1)으로, 나머지는 답함(0)으로 적어요."""
    conn.execute(
        "UPDATE parts SET open = CASE WHEN idx IN (%s) THEN %d ELSE 0 END WHERE turn_id = ?"
        % (",".join(str(int(i)) for i in missing) or "NULL", MISSING),
        (turn_id,),
    )


RULE_KINDS = ("open", "repeat", "topic")   # 엔진 없이 규칙으로 만드는 할 일 (backend/agent/rules.py). 2단이 다시 써도 남겨요


def set_items(conn, turn_id, items) -> list:
    """2단이 그 턴에서 찾은 할 일을 적어요. id는 docs/schema.md대로 <turnId>:<n>. 상태는 item_states에 남아 있어요.
    규칙 할 일(RULE_KINDS · add_items)과 앞길 살피기가 낸 길(<turnId>:a<n> · set_ahead_items)은 건드리지 않아요."""
    conn.execute("DELETE FROM items WHERE turn_id = ? AND substr(id, length(turn_id) + 1, 2) != ':a' AND kind NOT IN (%s)"
                 % ",".join("?" * len(RULE_KINDS)), (turn_id, *RULE_KINDS))
    return _insert_items(conn, turn_id, items)


def add_items(conn, turn_id, items) -> list:
    """규칙 할 일을 덧붙여요. 그 턴에 같은 종류가 이미 있으면 두어요. 새로 넣은 것을 돌려줘요."""
    have = {r["kind"] for r in conn.execute("SELECT kind FROM items WHERE turn_id = ?", (turn_id,))}
    items = [it for it in items if it["kind"] not in have]
    _insert_items(conn, turn_id, items)
    return items


def _insert_items(conn, turn_id, items) -> list:
    """<turnId>:<n>에서 비어 있는 번호에 차례로 넣어요 (남겨 둔 규칙 할 일과 번호가 겹치지 않게)."""
    taken = {r["id"] for r in conn.execute("SELECT id FROM items WHERE turn_id = ?", (turn_id,))}
    ids, n = [], 0
    for item in items:
        while f"{turn_id}:{n}" in taken:
            n += 1
        taken.add(f"{turn_id}:{n}")
        ids.append(_add_item(conn, turn_id, f"{turn_id}:{n}", item))
    return ids


def set_ahead_items(conn, turn_id, items) -> list:
    """앞길 살피기(backend/agent/ahead.py)가 그 턴에서 낸 길을 적어요. id는 <turnId>:a<n>.
    다시 살피면 길이 달라지니, 앞서 낸 길과 그 상태(나중에 · 끝냄)는 지우고 새로 적어요."""
    old = [r["id"] for r in conn.execute(
        "SELECT id FROM items WHERE turn_id = ? AND substr(id, length(turn_id) + 1, 2) = ':a'", (turn_id,))]
    for item_id in old:
        conn.execute("DELETE FROM item_states WHERE id = ?", (item_id,))
        conn.execute("DELETE FROM items WHERE id = ?", (item_id,))
    return [_add_item(conn, turn_id, f"{turn_id}:a{n}", item) for n, item in enumerate(items)]


def _add_item(conn, turn_id, item_id, item) -> str:
    pop = item.get("pop")
    conn.execute(
        "INSERT INTO items(id, turn_id, kind, text, why, btn, prompt, effect, pop_json, at, state, created_at)"
        " VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, COALESCE((SELECT state FROM item_states WHERE id = ?), 'open'), ?)",
        (item_id, turn_id, item["kind"], item["text"], item.get("why"), item.get("btn"), item.get("prompt"),
         item.get("effect"), json.dumps(pop, ensure_ascii=False) if pop else None, item.get("at"),
         item_id, now()),
    )
    return item_id


def log_auto(conn, chat_id, kind, text, item_id=None) -> None:
    """가닥이 직접 보낸 것을 남겨요. 한마디를 보낸 것이면 그 id를, 새 대화에 넣은 요약이면 대화만 적어요."""
    conn.execute("INSERT INTO auto_log(chat_id, item_id, kind, text, created_at) VALUES(?, ?, ?, ?, ?)",
                 (chat_id, item_id, kind, text, now()))


def auto_sent(conn, chat_id, kind=None) -> list:
    """그 대화에서 가닥이 직접 보낸 것들 (오래된 순)."""
    if kind is None:
        return conn.execute("SELECT * FROM auto_log WHERE chat_id = ? ORDER BY id", (chat_id,)).fetchall()
    return conn.execute("SELECT * FROM auto_log WHERE chat_id = ? AND kind = ? ORDER BY id", (chat_id, kind)).fetchall()


def turn_items(conn, turn_id) -> list:
    """docs/schema.md의 Item 모양 (상태는 빼고). 화면은 상태를 itemStates로 받아요. 가닥이 직접 보낸 것은 sent = auto."""
    out = []
    sent = {r["item_id"] for r in conn.execute("SELECT item_id FROM auto_log WHERE item_id LIKE ?", (turn_id + ":%",))}
    for r in conn.execute("SELECT * FROM items WHERE turn_id = ? ORDER BY rowid", (turn_id,)):
        item = {"id": r["id"], "kind": r["kind"], "text": r["text"], "why": r["why"] or "", "btn": r["btn"] or ""}
        if r["id"] in sent:
            item["sent"] = "auto"
        for key in ("prompt", "effect", "at"):
            if r[key]:
                item[key] = r[key]
        if r["pop_json"]:
            item["pop"] = json.loads(r["pop_json"])
        out.append(item)
    return out


def give_up_classification(conn, turn_id) -> None:
    """분류에 거듭 실패한 턴. 임시 제목 그대로 두고 다시 시도하지 않아요."""
    conn.execute("UPDATE turns SET classified = -1 WHERE id = ?", (turn_id,))


def chat_row(conn, chat_id):
    return conn.execute("SELECT * FROM chats WHERE id = ?", (chat_id,)).fetchone()


def now_chat(conn, project=None):
    """지금 쓰는 대화: 가장 최근에 턴이 온 대화 (목록에서 뺀 것은 빼고). 없으면 None.
    project를 주면 그 프로젝트 안에서 골라요 (떠 있는 버튼의 프로젝트 버튼)."""
    return conn.execute(
        "SELECT c.* FROM turns t JOIN chats c ON c.id = t.chat_id WHERE c.hidden = 0 AND (? IS NULL OR c.project_id = ?)"
        " ORDER BY t.created_at DESC, t.rowid DESC LIMIT 1", (project, project)
    ).fetchone()


def chat_turns(conn, chat_id) -> list:
    return conn.execute("SELECT * FROM turns WHERE chat_id = ? ORDER BY seq", (chat_id,)).fetchall()


def _clip(text, limit):
    return text if limit is None or len(text) <= limit else text[:limit].rstrip() + "…"


def shown_name(name, cwd):
    """산출물 이름. 작업 폴더 안의 파일은 폴더 기준 경로로, 밖의 파일은 이름만."""
    if cwd and name.startswith(cwd.rstrip("/") + "/"):
        return name[len(cwd.rstrip("/")) + 1:]
    return Path(name).name if name.startswith("/") else name


def turn_public(conn, row, clip=False, cwd=None) -> dict:
    """docs/schema.md의 Turn 모양. clip이면 원문을 화면에 보일 만큼만 실어요."""
    user = _clip(row["user"], CLIP_USER if clip else None)
    ai = _clip(row["ai"], CLIP_AI if clip else None)
    turn = {
        "id": row["id"], "title": row["title"], "user": user, "ai": ai,
        "depth": row["depth"], "messageRef": row["message_ref"],
    }
    if clip and (len(user) != len(row["user"]) or len(ai) != len(row["ai"])):
        turn["long"] = True
    for key in ("seg", "topic", "dec", "ref"):
        if row[key]:
            turn[key] = row[key]
    if row["ret"]:
        turn["ret"] = True
    gist = json.loads(row["gist"]) if row["gist"] else []
    if gist:
        turn["gist"] = gist           # 답을 간추린 두세 줄. 원문은 ai에 있어요 (길면 turn_full)
    files = [
        {"n": shown_name(r["name"], cwd), "u": r["url"]} if r["url"] else shown_name(r["name"], cwd)
        for r in conn.execute("SELECT name, url FROM files WHERE turn_id = ? ORDER BY rowid", (row["id"],))
    ]
    if files:
        turn["files"] = files
    parts = []
    for r in conn.execute("SELECT t, type, open, target FROM parts WHERE turn_id = ? ORDER BY idx", (row["id"],)):
        part = {"t": r["t"], "type": r["type"]}
        if r["open"] == MISSING:      # 1단의 후보(2)는 2단이 확인하기 전까지 보이지 않아요
            part["open"] = True
        if r["target"]:
            part["target"] = r["target"]
        parts.append(part)
    if parts:
        turn["parts"] = parts
    todo = turn_items(conn, row["id"])
    if todo:
        turn["todo"] = todo
    return turn


def turn_full(conn, turn_id):
    row = conn.execute(
        "SELECT t.*, c.cwd FROM turns t JOIN chats c ON c.id = t.chat_id WHERE t.id = ?", (turn_id,)
    ).fetchone()
    return turn_public(conn, row, cwd=row["cwd"]) if row else None


AUTO_KINDS = ("unasked", "handoff")   # 가닥이 직접 보낼 수 있는 종류는 이 둘뿐이에요 (README 3-2)


def handoff_note(text) -> dict:
    """가닥이 새 대화에 넣은 이어 가기 요약을 할 일 장부에 보이는 모양으로. 이미 한 일이라 ‘done’이에요."""
    count = sum(1 for line in text.splitlines() if line[:1].isdigit() and ". " in line[:5])
    return {
        "kind": "handoff", "text": f"지난 대화에서 정한 것 {count}개를 이 대화에 붙였어요",
        "why": "같은 프로젝트의 새 대화라서, 시작할 때 가닥이 넣었어요.", "btn": "요약 보기",
        "pop": {"title": "이어 가기 요약", "text": text, "note": "새 대화가 시작될 때 가닥이 넣은 글이에요."},
        "state": "done", "sent": "auto",
    }


def display_date(created_at: str) -> str:
    day = datetime.fromisoformat(created_at).astimezone()
    today = datetime.now().astimezone().date()
    return "오늘" if day.date() == today else f"{day.month}/{day.day}"


def projects(conn) -> list:
    """최근에 쓴 프로젝트가 위로 와요."""
    rows = conn.execute(
        "SELECT p.id, p.name, COUNT(DISTINCT c.id) AS chats, COUNT(t.id) AS turns, MAX(t.created_at) AS last"
        " FROM projects p JOIN chats c ON c.project_id = p.id AND c.hidden = 0 LEFT JOIN turns t ON t.chat_id = c.id"
        " GROUP BY p.id ORDER BY last IS NULL, last DESC, p.name"      # 대화를 다 뺀 프로젝트는 목록에 없어요
    )
    lists = collections.defaultdict(list)    # 왼쪽 목록이 모든 프로젝트의 대화를 펼쳐 보여요. 최근에 쓴 대화가 위로
    for c in conn.execute(
        "SELECT c.id, c.project_id, c.title, COALESCE(MAX(t.created_at), c.created_at) AS last"
        " FROM chats c LEFT JOIN turns t ON t.chat_id = c.id WHERE c.hidden = 0 GROUP BY c.id ORDER BY last DESC"
    ):
        lists[c["project_id"]].append({"id": c["id"], "title": c["title"], "date": display_date(c["last"])})
    return [{**dict(r), "color": project_color(r["id"]), "list": lists[r["id"]]} for r in rows]   # 노선 색: 목록의 색 동그라미


def view(conn, project_id, scope="all", chat_id=None):
    """노선도를 그릴 턴 목록. scope=chat이면 그 대화만."""
    project_id = project_key(project_id)
    project = conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
    if project is None:
        return None
    chats = conn.execute(
        "SELECT * FROM chats WHERE project_id = ? AND hidden = 0 ORDER BY created_at, rowid", (project_id,)
    ).fetchall()
    last = conn.execute(
        "SELECT t.chat_id FROM turns t JOIN chats c ON c.id = t.chat_id"
        " WHERE c.project_id = ? AND c.hidden = 0 ORDER BY t.created_at DESC, t.rowid DESC LIMIT 1", (project_id,)
    ).fetchone()
    known = {c["id"] for c in chats}
    active_id = chat_id if chat_id in known else (last["chat_id"] if last else None)
    out, turn_ids = [], set()
    for chat in chats:
        if scope == "chat" and chat["id"] != active_id:
            continue
        turns = chat_turns(conn, chat["id"])
        if not turns:
            continue
        turn_ids.update(t["id"] for t in turns)
        entry = {
            "id": chat["id"],
            "title": chat["title"] or turns[0]["title"],
            "date": display_date(chat["created_at"]),
            "site": chat["site"],
            "turns": [turn_public(conn, t, clip=True, cwd=chat["cwd"]) for t in turns],
        }
        if chat["via"]:
            entry["via"] = chat["via"]
        pending = sum(1 for t in turns if t["classified"] == 0)
        if pending:
            entry["pending"] = pending
        checks = sum(1 for t in turns if t["look"] and t["checked"] == 0 and t["classified"] == 1)
        if checks:
            entry["checks"] = checks      # 2단이 아직 확인하지 않은 턴
        if chat["id"] == active_id:
            entry["active"] = True
        for sent in auto_sent(conn, chat["id"], "handoff"):
            if sent["item_id"] is None:      # 새 대화가 시작될 때 넣은 요약: 한마디 없이 보낸 것이라 첫 역에 달아 보여 줘요
                entry["turns"][0].setdefault("todo", []).append(handoff_note(sent["text"]))
        out.append(entry)
    states = {
        r["id"]: r["state"] for r in conn.execute("SELECT id, state FROM item_states")
        if r["id"].split(":")[0] in turn_ids
    }
    auto = {kind: setting(conn, "auto." + kind) == "1" for kind in AUTO_KINDS}
    return {"project": {"id": project["id"], "name": project["name"], "color": project_color(project["id"])},
            "chats": out, "itemStates": states, "auto": auto}


MAP_COLORS = ("#0039A6", "#FF6319", "#00933C", "#FCCC0A", "#B933AD", "#EE352E", "#6CBE45", "#00A1DE",
              "#996633", "#4D5357", "#C2185B", "#00796B", "#5C6BC0", "#8C8C8C")   # 비녤리 지도의 노선 색
MAP_LINKS = {"handoff": "이어 가기", "repeat": "지난 대화 참조"}   # 다른 대화를 근거(at)로 든 할 일 → 환승


def project_color(project_id) -> str:
    """프로젝트의 노선 색. 프로젝트 id로 정해서 가닥 창 노선도 · 레일 · 전체 지도가 늘 같은 색을 써요 (회색은 곁길 몫이라 빼요)."""
    return MAP_COLORS[zlib.crc32(str(project_id).encode()) % (len(MAP_COLORS) - 1)]


def map_data(conn, days=90, today=None) -> dict:
    """전체 지도(backend/web/map.html)용: 최근 days일의 프로젝트 · 대화 · 턴을 날짜(시작일부터 센 번호)와 함께.
    턴마다 정함 · 곁길 깊이 · 산출물 · 할 일을 싣고, 다른 대화를 근거로 든 할 일은 환승으로 이어요."""
    local = lambda ts: datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone().date()
    today = today or datetime.now().astimezone().date()
    # 지도는 첫 대화가 있는 날부터 (최대 days일 전까지). 대화가 오늘뿐이면 오늘 하루짜리 지도예요
    first = conn.execute("SELECT MIN(t.created_at) FROM turns t JOIN chats c ON c.id = t.chat_id WHERE c.hidden = 0").fetchone()[0]
    start = max(today - timedelta(days=days - 1), min(local(first), today) if first else today)
    days = (today - start).days + 1
    day = lambda ts: (local(ts) - start).days
    states = {r["id"]: r["state"] for r in conn.execute("SELECT id, state FROM item_states")}
    out, chat_of, links = [], {}, []
    rows = conn.execute(
        "SELECT p.id, p.name, MIN(t.created_at) AS first FROM projects p JOIN chats c ON c.project_id = p.id AND c.hidden = 0"
        " JOIN turns t ON t.chat_id = c.id GROUP BY p.id ORDER BY first"
    ).fetchall()
    for project in rows:
        chats = []
        for chat in conn.execute("SELECT * FROM chats WHERE project_id = ? AND hidden = 0 ORDER BY created_at, rowid",
                                 (project["id"],)):
            turns = []
            for row in chat_turns(conn, chat["id"]):
                d = day(row["created_at"])
                if d < 0:
                    continue                       # 지도보다 오래된 턴
                chat_of[row["id"]] = chat["id"]
                items = turn_items(conn, row["id"])
                for item in items:
                    if item["kind"] in MAP_LINKS and item.get("at"):
                        links.append((item["at"], chat["id"], MAP_LINKS[item["kind"]]))
                files = conn.execute("SELECT name FROM files WHERE turn_id = ? ORDER BY rowid", (row["id"],))
                turns.append({
                    "id": row["id"], "t": row["title"], "d": 1 if row["dec"] else 0, "side": min(row["depth"], 2), "day": min(d, days - 1),
                    "f": [Path(r["name"]).name for r in files],
                    "todo": [[item["text"], states.get(item["id"]) == "done"] for item in items],
                })
            if turns:
                chats.append({"id": chat["id"], "title": chat["title"] or turns[0]["t"], "from": turns[0]["day"],
                              "to": turns[-1]["day"], "active": False, "turns": turns})
        if chats:
            color = project_color(project["id"])
            out.append({"id": project["id"], "name": project["name"], "color": color, **({"ink": "#111"} if color == "#FCCC0A" else {}),
                        "chats": chats})
    links = [[chat_of[at], chat, why] for at, chat, why in links if at in chat_of and chat_of[at] != chat]
    # ‘지금’은 화면에 하나: 가장 최근에 턴이 온 대화만 (표기 규칙)
    latest = conn.execute("SELECT t.chat_id FROM turns t JOIN chats c ON c.id = t.chat_id WHERE c.hidden = 0"
                          " ORDER BY t.created_at DESC, t.rowid DESC LIMIT 1").fetchone()
    for project in out:
        for chat in project["chats"]:
            chat["active"] = latest is not None and chat["id"] == latest["chat_id"]
    return {"start": start.isoformat(), "today": days - 1, "projects": out, "links": links}


SITE_NAMES = {"claude-code": "Claude Code", "codex": "Codex", "cursor": "Cursor", "chatgpt": "ChatGPT",
              "claude": "Claude", "gemini": "Gemini"}
FIND_TURNS = 400          # 글이 맞는 턴은 이만큼만 훑어요 (최근 것부터)


def _like(query) -> str:
    return "%" + query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


def _snip(sources, query) -> str:
    """찾는 말이 든 글의 그 둘레만. 정한 것 · 제목 · 질문 · 답 차례로 먼저 맞는 것을 써요."""
    needle = query.lower()
    source = next((s for s in sources if s and needle in s.lower()), None) or next((s for s in sources if s), "")
    at = source.lower().find(needle)
    if at < 0:
        snip = source[:60]
    else:
        end = at + len(query) + 36
        snip = ("…" if at > 24 else "") + source[max(0, at - 24):end] + ("…" if end < len(source) else "")
    return " ".join(snip.split())


def find_chats(conn, query, limit=40) -> list:
    """모든 프로젝트의 대화에서 찾아요 (가닥 창 왼쪽의 ‘대화 찾기’).
    대화 제목 · 프로젝트 이름 · 쓴 곳(ChatGPT …)이 맞는 대화가 먼저, 그다음 글이 맞는 대화. 그 안에서는 최근에 쓴 대화가 위로."""
    query = (query or "").strip()
    if not query:
        return []
    like, needle = _like(query), query.lower()
    sites = [site for site, name in SITE_NAMES.items() if needle in name.lower()]
    hits = {}
    for row in conn.execute(
        "SELECT t.id, t.chat_id, t.title, t.user, t.ai, t.dec FROM turns t"
        " WHERE t.title LIKE ? ESCAPE '\\' OR t.user LIKE ? ESCAPE '\\' OR t.ai LIKE ? ESCAPE '\\'"
        " OR t.dec LIKE ? ESCAPE '\\' ORDER BY (t.dec IS NULL), t.created_at DESC, t.seq DESC LIMIT ?",
        (like, like, like, like, FIND_TURNS),
    ):
        hits.setdefault(row["chat_id"], row)             # 대화마다 가장 먼저 맞은 턴 하나
    out = []
    for chat in conn.execute(
        "SELECT c.id, c.title, c.site, c.created_at, c.project_id, p.name AS project,"
        " (SELECT MAX(t.created_at) FROM turns t WHERE t.chat_id = c.id) AS last,"
        " (SELECT t.title FROM turns t WHERE t.chat_id = c.id ORDER BY t.seq LIMIT 1) AS first"
        " FROM chats c JOIN projects p ON p.id = c.project_id WHERE c.hidden = 0"
    ):
        if chat["last"] is None:
            continue                                     # 턴이 없는 대화는 화면에도 없어요
        title = chat["title"] or chat["first"]
        named = needle in (title or "").lower() or chat["site"] in sites or (
            chat["project_id"] != NO_PROJECT and needle in chat["project"].lower())
        hit = hits.get(chat["id"])
        if not named and hit is None:
            continue
        entry = {"id": chat["id"], "title": title, "site": chat["site"], "date": display_date(chat["last"]),
                 "project": {"id": chat["project_id"], "name": chat["project"]}, "named": named, "last": chat["last"]}
        if hit is not None:
            entry["turn"] = hit["id"]
            entry["snip"] = _snip((hit["dec"], hit["title"], hit["user"], hit["ai"]), query)
        out.append(entry)
    out.sort(key=lambda e: e["last"], reverse=True)
    out.sort(key=lambda e: not e["named"])               # 이름이 맞는 대화가 먼저 (차례는 그대로)
    for entry in out:
        del entry["named"], entry["last"]
    return out[:limit]


def search(conn, project_id, query, limit=40) -> list:
    """지난 대화에서 찾기. 정한 것이 먼저, 그다음 최근 순 (README 7-9)."""
    query = (query or "").strip()
    if not query:
        return []
    like = _like(query)
    rows = conn.execute(
        "SELECT DISTINCT t.id, t.title, t.user, t.ai, t.dec, t.created_at, t.seq FROM turns t"
        " JOIN chats c ON c.id = t.chat_id LEFT JOIN files f ON f.turn_id = t.id"
        " WHERE c.project_id = ? AND c.hidden = 0 AND (t.title LIKE ? ESCAPE '\\' OR t.user LIKE ? ESCAPE '\\'"
        " OR t.ai LIKE ? ESCAPE '\\' OR t.dec LIKE ? ESCAPE '\\' OR f.name LIKE ? ESCAPE '\\')"
        " ORDER BY (t.dec IS NULL), t.created_at DESC, t.seq DESC LIMIT ?",
        (project_key(project_id), like, like, like, like, like, limit),
    ).fetchall()
    return [{"id": row["id"], "snip": _snip((row["dec"], row["title"], row["user"], row["ai"]), query)} for row in rows]


def set_item_state(conn, item_id, state) -> bool:
    """빠진 요청(<turnId>:p<n>)은 items에 줄이 없어서, 상태는 item_states 하나에 모아요. items.state는 같이 맞춰 둬요."""
    if state not in ITEM_STATES:
        return False
    conn.execute(
        "INSERT INTO item_states(id, state, updated_at) VALUES(?, ?, ?)"
        " ON CONFLICT(id) DO UPDATE SET state = excluded.state, updated_at = excluded.updated_at",
        (item_id, state, now()),
    )
    conn.execute("UPDATE items SET state = ? WHERE id = ?", (state, item_id))
    return True


def get_sync(conn, path):
    return conn.execute("SELECT * FROM sync_state WHERE path = ?", (str(path),)).fetchone()


def set_sync(conn, path, *, source, size, mtime, offset, state) -> None:
    conn.execute(
        "INSERT INTO sync_state(path, source, size, mtime, offset, state_json) VALUES(?, ?, ?, ?, ?, ?)"
        " ON CONFLICT(path) DO UPDATE SET size = excluded.size, mtime = excluded.mtime,"
        " offset = excluded.offset, state_json = excluded.state_json",
        (str(path), source, size, mtime, offset, json.dumps(state, ensure_ascii=False)),
    )


def setting(conn, key, default=None):
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else default


def set_setting(conn, key, value) -> None:
    conn.execute(
        "INSERT INTO settings(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )


def site_counts(conn) -> dict:
    return {r["site"]: r["n"] for r in conn.execute("SELECT site, COUNT(*) AS n FROM chats GROUP BY site")}
