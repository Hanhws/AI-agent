"""SQLite 저장소.

테이블과 필드 이름은 docs/schema.md를 따라요. edits · item_states · sync_state 테이블과
turns의 state · classified, chats의 via · cwd는 10/3에 더한 것이에요 (CHANGES.md 4번).
"""
import json
import sqlite3
import threading
import unicodedata
import uuid
from datetime import datetime, timezone
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
  cwd TEXT
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
CREATE TABLE IF NOT EXISTS item_states(
  id TEXT PRIMARY KEY,
  state TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sync_state(
  path TEXT PRIMARY KEY,
  source TEXT NOT NULL,
  size INTEGER NOT NULL,
  mtime REAL NOT NULL,
  offset INTEGER NOT NULL,
  state_json TEXT NOT NULL
);
"""

# 먼저 만들어진 DB에 없는 열 (CREATE TABLE IF NOT EXISTS는 열을 더해 주지 않아요)
ADDED_COLUMNS = {"chats": {"via": "TEXT", "cwd": "TEXT"}}

NO_PROJECT = "_none"
TITLE_LEN = 16
MAX_AI = 20000            # 답이 아주 긴 턴은 앞 조금과 끝을 남겨요 (결론은 끝에 있어요)
AI_HEAD = 4000
CUT = "\n…(가운데 줄임)…\n"
CLIP_USER, CLIP_AI = 600, 700   # 노선도 화면에 보내는 길이. 전체는 turn_full
ITEM_STATES = {"open", "later", "done"}
SCHEMA_VERSION = 2
_setup = threading.Lock()  # 여러 스레드가 동시에 처음 열면 테이블 만들기가 서로 막혀요


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
    return conn


def _create(conn) -> None:
    if conn.execute("PRAGMA user_version").fetchone()[0] >= SCHEMA_VERSION:
        return
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(SCHEMA)
    for table, columns in ADDED_COLUMNS.items():
        have = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
        for name, kind in columns.items():
            if name not in have:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {kind}")
    conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
    conn.commit()


def provisional_title(text: str) -> str:
    """분류 전까지 쓰는 임시 역 제목. 제목은 원래 에이전트가 만들어요(README 3-1)."""
    first = next((line.strip() for line in (text or "").splitlines() if line.strip()), "")
    if not first:
        return "(질문 없음)"
    return first if len(first) <= TITLE_LEN else first[:TITLE_LEN] + "…"


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
                       ref=None, parts=None) -> None:
    """1단 분류 결과를 역에 적어요 (backend/agent/classify.py)."""
    conn.execute(
        "UPDATE turns SET title = ?, depth = ?, seg = ?, topic = ?, dec = ?, ret = ?, ref = ?, classified = 1"
        " WHERE id = ?",
        (title, depth, seg, topic, dec, 1 if ret else 0, ref, turn_id),
    )
    conn.execute("DELETE FROM parts WHERE turn_id = ?", (turn_id,))
    for idx, part in enumerate(parts or []):
        conn.execute(
            "INSERT INTO parts(turn_id, idx, t, type, open, target) VALUES(?, ?, ?, ?, ?, ?)",
            (turn_id, idx, part["t"], part["type"], 1 if part.get("open") else 0, part.get("target")),
        )


def give_up_classification(conn, turn_id) -> None:
    """분류에 거듭 실패한 턴. 임시 제목 그대로 두고 다시 시도하지 않아요."""
    conn.execute("UPDATE turns SET classified = -1 WHERE id = ?", (turn_id,))


def chat_row(conn, chat_id):
    return conn.execute("SELECT * FROM chats WHERE id = ?", (chat_id,)).fetchone()


def chat_turns(conn, chat_id) -> list:
    return conn.execute("SELECT * FROM turns WHERE chat_id = ? ORDER BY seq", (chat_id,)).fetchall()


def _clip(text, limit):
    return text if limit is None or len(text) <= limit else text[:limit].rstrip() + "…"


def _shown_name(name, cwd):
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
    files = [
        {"n": _shown_name(r["name"], cwd), "u": r["url"]} if r["url"] else _shown_name(r["name"], cwd)
        for r in conn.execute("SELECT name, url FROM files WHERE turn_id = ? ORDER BY rowid", (row["id"],))
    ]
    if files:
        turn["files"] = files
    parts = []
    for r in conn.execute("SELECT t, type, open, target FROM parts WHERE turn_id = ? ORDER BY idx", (row["id"],)):
        part = {"t": r["t"], "type": r["type"]}
        if r["open"]:
            part["open"] = True
        if r["target"]:
            part["target"] = r["target"]
        parts.append(part)
    if parts:
        turn["parts"] = parts
    return turn


def turn_full(conn, turn_id):
    row = conn.execute(
        "SELECT t.*, c.cwd FROM turns t JOIN chats c ON c.id = t.chat_id WHERE t.id = ?", (turn_id,)
    ).fetchone()
    return turn_public(conn, row, cwd=row["cwd"]) if row else None


def _display_date(created_at: str) -> str:
    day = datetime.fromisoformat(created_at).astimezone()
    today = datetime.now().astimezone().date()
    return "오늘" if day.date() == today else f"{day.month}/{day.day}"


def projects(conn) -> list:
    """최근에 쓴 프로젝트가 위로 와요."""
    rows = conn.execute(
        "SELECT p.id, p.name, COUNT(DISTINCT c.id) AS chats, COUNT(t.id) AS turns, MAX(t.created_at) AS last"
        " FROM projects p LEFT JOIN chats c ON c.project_id = p.id LEFT JOIN turns t ON t.chat_id = c.id"
        " GROUP BY p.id ORDER BY last IS NULL, last DESC, p.name"
    )
    return [dict(r) for r in rows]


def view(conn, project_id, scope="all", chat_id=None):
    """노선도를 그릴 턴 목록. scope=chat이면 그 대화만."""
    project_id = project_key(project_id)
    project = conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
    if project is None:
        return None
    chats = conn.execute(
        "SELECT * FROM chats WHERE project_id = ? ORDER BY created_at, rowid", (project_id,)
    ).fetchall()
    last = conn.execute(
        "SELECT t.chat_id FROM turns t JOIN chats c ON c.id = t.chat_id"
        " WHERE c.project_id = ? ORDER BY t.created_at DESC, t.rowid DESC LIMIT 1", (project_id,)
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
            "date": _display_date(chat["created_at"]),
            "site": chat["site"],
            "turns": [turn_public(conn, t, clip=True, cwd=chat["cwd"]) for t in turns],
        }
        if chat["via"]:
            entry["via"] = chat["via"]
        pending = sum(1 for t in turns if t["classified"] == 0)
        if pending:
            entry["pending"] = pending
        if chat["id"] == active_id:
            entry["active"] = True
        out.append(entry)
    states = {
        r["id"]: r["state"] for r in conn.execute("SELECT id, state FROM item_states")
        if r["id"].split(":")[0] in turn_ids
    }
    return {"project": {"id": project["id"], "name": project["name"]}, "chats": out, "itemStates": states}


def search(conn, project_id, query, limit=40) -> list:
    """지난 대화에서 찾기. 정한 것이 먼저, 그다음 최근 순 (README 7-9)."""
    query = (query or "").strip()
    if not query:
        return []
    like = "%" + query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
    rows = conn.execute(
        "SELECT DISTINCT t.id, t.title, t.user, t.ai, t.dec, t.created_at, t.seq FROM turns t"
        " JOIN chats c ON c.id = t.chat_id LEFT JOIN files f ON f.turn_id = t.id"
        " WHERE c.project_id = ? AND (t.title LIKE ? ESCAPE '\\' OR t.user LIKE ? ESCAPE '\\'"
        " OR t.ai LIKE ? ESCAPE '\\' OR t.dec LIKE ? ESCAPE '\\' OR f.name LIKE ? ESCAPE '\\')"
        " ORDER BY (t.dec IS NULL), t.created_at DESC, t.seq DESC LIMIT ?",
        (project_key(project_id), like, like, like, like, like, limit),
    ).fetchall()
    needle, hits = query.lower(), []
    for row in rows:
        source = next(
            (s for s in (row["dec"], row["title"], row["user"], row["ai"]) if s and needle in s.lower()),
            row["title"],
        )
        at = source.lower().find(needle)
        if at < 0:
            snip = source[:60]
        else:
            end = at + len(query) + 36
            snip = ("…" if at > 24 else "") + source[max(0, at - 24):end] + ("…" if end < len(source) else "")
        hits.append({"id": row["id"], "snip": " ".join(snip.split())})
    return hits


def set_item_state(conn, item_id, state) -> bool:
    if state not in ITEM_STATES:
        return False
    conn.execute(
        "INSERT INTO item_states(id, state, updated_at) VALUES(?, ?, ?)"
        " ON CONFLICT(id) DO UPDATE SET state = excluded.state, updated_at = excluded.updated_at",
        (item_id, state, now()),
    )
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


def site_counts(conn) -> dict:
    return {r["site"]: r["n"] for r in conn.execute("SELECT site, COUNT(*) AS n FROM chats GROUP BY site")}
