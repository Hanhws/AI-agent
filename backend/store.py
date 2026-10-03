"""SQLite 저장소.

테이블과 필드 이름은 docs/schema.md를 따라요. edits 테이블과 turns의 state · classified는
10/3에 더한 것이에요 (CHANGES.md 4번).
"""
import sqlite3
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
  created_at TEXT NOT NULL
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
"""

NO_PROJECT = "_none"
TITLE_LEN = 16


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect(db_path) -> sqlite3.Connection:
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(SCHEMA)
    return conn


def provisional_title(text: str) -> str:
    """분류 전까지 쓰는 임시 역 제목. 제목은 원래 에이전트가 만들어요(README 3-1)."""
    first = next((line.strip() for line in (text or "").splitlines() if line.strip()), "")
    if not first:
        return "(질문 없음)"
    return first if len(first) <= TITLE_LEN else first[:TITLE_LEN] + "…"


def upsert_chat(conn, *, project, chat_id, site, title=None) -> None:
    project_id = project or NO_PROJECT
    conn.execute(
        "INSERT OR IGNORE INTO projects(id, name) VALUES(?, ?)",
        (project_id, project or "(프로젝트 없음)"),
    )
    conn.execute(
        "INSERT OR IGNORE INTO chats(id, project_id, title, site, created_at) VALUES(?, ?, ?, ?, ?)",
        (chat_id, project_id, title, site, now()),
    )
    if title:
        conn.execute("UPDATE chats SET title = ? WHERE id = ? AND title IS NULL", (title, chat_id))


def find_turn(conn, chat_id, message_ref):
    return conn.execute(
        "SELECT * FROM turns WHERE chat_id = ? AND message_ref = ?", (chat_id, message_ref)
    ).fetchone()


def latest_open_turn(conn, chat_id):
    return conn.execute(
        "SELECT * FROM turns WHERE chat_id = ? AND state = 'open' ORDER BY seq DESC LIMIT 1", (chat_id,)
    ).fetchone()


def upsert_turn(conn, *, chat_id, message_ref, user=None, ai=None, state=None):
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
             message_ref, now(), state or "open"),
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


def turn_public(conn, row) -> dict:
    """docs/schema.md의 Turn 모양."""
    turn = {
        "id": row["id"], "title": row["title"], "user": row["user"], "ai": row["ai"],
        "depth": row["depth"], "messageRef": row["message_ref"],
    }
    for key in ("seg", "topic", "dec", "ref"):
        if row[key]:
            turn[key] = row[key]
    if row["ret"]:
        turn["ret"] = True
    files = [
        {"n": r["name"], "u": r["url"]} if r["url"] else r["name"]
        for r in conn.execute("SELECT name, url FROM files WHERE turn_id = ? ORDER BY rowid", (row["id"],))
    ]
    if files:
        turn["files"] = files
    return turn


def _display_date(created_at: str) -> str:
    day = datetime.fromisoformat(created_at).astimezone()
    today = datetime.now().astimezone().date()
    return "오늘" if day.date() == today else f"{day.month}/{day.day}"


def projects(conn) -> list:
    rows = conn.execute(
        "SELECT p.id, p.name, COUNT(c.id) AS chats FROM projects p"
        " LEFT JOIN chats c ON c.project_id = p.id GROUP BY p.id ORDER BY p.name"
    )
    return [dict(r) for r in rows]


def view(conn, project_id, scope="all", chat_id=None):
    """노선도를 그릴 턴 목록. scope=chat이면 그 대화만."""
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
    active_id = chat_id or (last["chat_id"] if last else None)
    out = []
    for chat in chats:
        if scope == "chat" and chat["id"] != active_id:
            continue
        turns = conn.execute("SELECT * FROM turns WHERE chat_id = ? ORDER BY seq", (chat["id"],)).fetchall()
        entry = {
            "id": chat["id"],
            "title": chat["title"] or (turns[0]["title"] if turns else ""),
            "date": _display_date(chat["created_at"]),
            "site": chat["site"],
            "turns": [turn_public(conn, t) for t in turns],
        }
        if chat["id"] == active_id:
            entry["active"] = True
        out.append(entry)
    return {"project": {"id": project["id"], "name": project["name"]}, "chats": out}
