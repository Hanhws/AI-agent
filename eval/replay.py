"""내 PC의 가닥 기록으로 전 · 후를 다시 재요 (발표 2부 · 사람이 따로 재지 않음). 읽기만 하고 숫자만 내요.

  python -m eval.replay [~/.gadak/gadak.db]

전 = 가닥 없이 사람이 해야 했던 양(읽을 줄 · 칠 글자 · 비교할 버전), 후 = 가닥이 있을 때 남는 양.
시간(분)이 아니라 양으로 재요. 스톱워치로 잰 값이 아니라서 발표에서도 ‘양’이라고 말해요.
"""
import json
import re
import sqlite3
import statistics
import sys
from pathlib import Path

from backend.agent import rules


def lines(t):
    return (t or "").count("\n") + 1 if t else 0


def med(xs):
    return round(statistics.median(xs)) if xs else 0


def measure(conn):
    out = {}
    # A1 요청 외 변경: 그 턴에 바뀐 줄 전체를 읽는 대신, 가닥이 짚은 줄만
    read_all, read_flag = [], []
    for turn_id, pop in conn.execute("SELECT turn_id, pop_json FROM items WHERE kind = 'unasked'"):
        total = sum(lines(o) + lines(n) for o, n in conn.execute("SELECT old, new FROM edits WHERE turn_id = ?", (turn_id,)))
        diff = (json.loads(pop or "{}")).get("diff") or []
        more = re.match(r"…\(바뀐 곳 (\d+)줄 더\)", diff[-1][1]) if diff else None   # 미리보기는 40줄까지 (investigate.DIFF_SHOWN)
        flagged = len(diff) - 1 + int(more.group(1)) if more else len(diff)
        if total:
            read_all.append(total)
            read_flag.append(min(flagged, total))
    out["A1"] = {"turns": len(read_all), "before_lines": sum(read_all), "after_lines": sum(read_flag)}
    # A3 되돌리기: 가닥이 대신 쓰고 보낸 되돌리기 요청 (사람이 쳤다면 이만큼 · 사람이 친 글자는 0).
    # 사람이 직접 친 되돌리기는 글로 가려낼 수 없어서(긴 붙여 넣기에도 ‘되돌’이 걸려요) 세지 않아요
    sent = [len(t) for (t,) in conn.execute("SELECT text FROM auto_log WHERE kind = 'unasked'")]
    out["A3"] = {"gadak_sent": len(sent), "median_chars": med(sent)}
    # B1 지난 결정: 대화 끝에서 그 결정까지 위로 스크롤할 줄 수 → 역 한 번 누르기
    dist = []
    for (chat_id,) in conn.execute("SELECT id FROM chats WHERE hidden = 0"):
        rows = conn.execute("SELECT dec, user, ai FROM turns WHERE chat_id = ? ORDER BY seq", (chat_id,)).fetchall()
        for i, r in enumerate(rows):
            if r["dec"]:
                dist.append(sum(lines(x["user"]) + lines(x["ai"]) for x in rows[i + 1:]))
    out["B1"] = {"decisions": len(dist), "median_lines": med(dist), "max_lines": max(dist, default=0)}
    # B2 최신본: 같은 파일의 버전 여럿을 견줘 고르기 → ‘산출물’ 칸의 최신 하나
    vers = [n for (n,) in conn.execute(
        "SELECT count(*) FROM files f JOIN turns t ON t.id = f.turn_id GROUP BY t.chat_id, coalesce(f.base_name, f.name) HAVING count(*) > 1")]
    out["B2"] = {"files": len(vers), "median_versions": med(vers), "max_versions": max(vers, default=0)}
    # B3 새 대화로 옮기기: 대화 전체를 다시 읽고 요약해 치기 → 가닥 요약(사람이 친 글자 0)
    reread, summ = [], []
    for chat_id, text in conn.execute("SELECT chat_id, text FROM auto_log WHERE kind = 'handoff'"):
        n = conn.execute("SELECT sum(length(user) + length(ai)) FROM turns WHERE chat_id = ?", (chat_id,)).fetchone()[0]
        if n:
            reread.append(n)
            summ.append(len(text))
    out["B3"] = {"handoffs": len(reread), "median_chat_chars": med(reread), "median_summary_chars": med(summ)}
    # B4 다시 묻기: 지난 대화에 거의 같은 역이 있던 질문 (rules.repeat_question을 기록 전체에 다시 돌림)
    hits = 0
    for chat in conn.execute("SELECT * FROM chats WHERE hidden = 0").fetchall():
        for row in conn.execute("SELECT * FROM turns WHERE chat_id = ? AND classified = 1", (chat["id"],)).fetchall():
            hits += rules.repeat_question(conn, chat, row) is not None
    out["B4"] = {"turns": conn.execute("SELECT count(*) FROM turns WHERE classified = 1").fetchone()[0], "repeats": hits}
    return out


if __name__ == "__main__":
    db = Path(sys.argv[1] if len(sys.argv) > 1 else "~/.gadak/gadak.db").expanduser()
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    print(json.dumps(measure(conn), ensure_ascii=False, indent=1))
