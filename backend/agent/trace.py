"""판단 기록 (README 3-1). 2단이 돈 턴마다 쓴 도구와 순서, 본 것, 결론을 남겨요.

노선도 카드에는 넣지 않고 별도 페이지(/trace)에서 봐요. 시연 · 발표에서 에이전트 동작의 근거로 써요.
"""
import json
import uuid

from .. import store
from .tools import LABELS

DATA_KEEP = 4000  # 도구 결과는 이만큼(글자)까지 남겨요. 원문 전체는 그 턴에 있어요


def _keep(data):
    text = json.dumps(data, ensure_ascii=False)
    return data if len(text) <= DATA_KEEP else {"cut": True, "text": text[:DATA_KEEP] + "…"}


def save(conn, turn_id, triggers, result, engine=None) -> str:
    run_id = "r" + uuid.uuid4().hex[:10]
    body = {
        "engine": getattr(engine, "name", None) if engine is not None else None,
        "model": getattr(engine, "model", None) if engine is not None else None,
        "steps": [{"tool": s["tool"], "label": LABELS[s["tool"]], "arg": s["arg"], "think": s["think"],
                   "saw": s["saw"], "data": _keep(s["data"])} for s in result["steps"]],
        "think": result.get("think"),
        "ended": result["ended"],
        "calls": result["calls"],
        "items": result.get("saved", []),
        "missing": result["missing"],
        "dropped": result["dropped"],
    }
    conn.execute(
        "INSERT INTO agent_runs(id, turn_id, trigger, steps_json, created_at) VALUES(?, ?, ?, ?, ?)",
        (run_id, turn_id, ",".join(triggers), json.dumps(body, ensure_ascii=False), store.now()),
    )
    return run_id


def runs(conn, turn_id=None, project_id=None, limit=50) -> list:
    """최근 것부터. n은 노선도의 역 번호와 같아요(본류 역을 센 수, 곁길은 갈라진 역의 번호)."""
    where, values = [], []
    if turn_id:
        where.append("r.turn_id = ?")
        values.append(turn_id)
    if project_id:
        where.append("c.project_id = ?")
        values.append(store.project_key(project_id))
    rows = conn.execute(
        "SELECT r.*, t.chat_id, t.seq, t.title, t.depth, c.title AS chat_title, c.created_at AS chat_created,"
        " c.project_id, p.name AS project,"
        " (SELECT COUNT(*) FROM turns x WHERE x.chat_id = t.chat_id AND x.depth = 0 AND x.seq <= t.seq) AS n"
        " FROM agent_runs r JOIN turns t ON t.id = r.turn_id JOIN chats c ON c.id = t.chat_id"
        " JOIN projects p ON p.id = c.project_id"
        + (" WHERE " + " AND ".join(where) if where else "")
        + " ORDER BY r.created_at DESC, r.rowid DESC LIMIT ?", values + [limit],
    ).fetchall()
    out = []
    for r in rows:
        body = json.loads(r["steps_json"])
        out.append({
            "id": r["id"], "at": r["created_at"], "trigger": [t for t in r["trigger"].split(",") if t],
            "turn": {"id": r["turn_id"], "n": f"{max(r['n'], 1):02d}", "title": r["title"], "depth": r["depth"],
                     "chat": r["chat_title"], "chatId": r["chat_id"], "date": store.display_date(r["chat_created"]),
                     "project": r["project"], "projectId": r["project_id"]},
            **body,
        })
    return out
