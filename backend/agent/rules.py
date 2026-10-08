"""엔진 없이 분류 결과만으로 만드는 할 일 (docs/schema.md kind 목록). 호출을 늘리지 않아요.

- open (끝나지 않은 곁길): 곁길에서 본류로 돌아왔는데 그 곁길에 정한 것(dec)이 없고,
  곁길이 3역 이상 이어졌거나 “나중에 · 다음에”처럼 미루고 끝났을 때. 곁길 한두 개로 뜻만 물은 것은 두어요
- repeat (반복 질문): 같은 프로젝트의 지난 대화에 이름이 거의 같은 역이 있을 때 (이름 글자 비교, 임베딩 대신)
- topic (주제 전환): 대화 전체를 보고 나눈 구간(seg)이 SEG_TRANSFER개 이상 쌓이면 대화마다 한 번, 환승하기를 권해요.
  노선을 나누는 대신(구간은 이미 나뉘어 있어요) 정한 것만 들고 새 대화로 가게요. 설문: 주제가 바뀌면 새 채팅 16/17

설문(docs/survey/설문분석.md): 곁길 뒤 흐름을 찾느라 스크롤 15/17 · 지난 대화를 못 찾아 다시 물음 9/17.
"""
import difflib
import re

from .. import store, usage

KINDS = ("open", "repeat", "topic")
SEG_TRANSFER = 3
SIDE_MIN = 3
POSTPONE = re.compile(r"나중에|다음에|이따가?|보류|미루|미뤄|일단 넘어")
SIMILAR = 0.8
TITLE_MIN = 4


def _q(title):
    return "‘" + (title or "").rstrip("…") + "’"


def open_side(rows, at) -> dict | None:
    """rows[at]가 곁길에서 본류로 돌아온 턴이면, 결론 없이 남은 곁길을 할 일로."""
    row = rows[at]
    if row["depth"] != 0 or at == 0 or rows[at - 1]["depth"] == 0:
        return None
    chain, i = [], at - 1
    while i >= 0 and rows[i]["depth"] > 0:
        chain.insert(0, rows[i])
        i -= 1
    if any(r["dec"] for r in chain):
        return None
    postponed = any(POSTPONE.search(r["user"] or "") for r in chain + [row])
    if len(chain) < SIDE_MIN and not postponed:
        return None
    first = next((r["title"] for r in chain if r["title"]), "")
    return {
        "kind": "open", "at": chain[0]["id"], "btn": "정리 받기",
        "text": f"{_q(first)}" + (f" 외 {len(chain) - 1}개" if len(chain) > 1 else "") + " 곁길이 결론 없이 끝났어요",
        "why": "곁길에서 본류로 돌아왔는데 그 곁길에서 정한 것이 없어요.",
        "prompt": "앞에서 곁길로 물어본 것들(" + ", ".join(_q(r["title"]) for r in chain if r["title"])
                  + ")을 하나씩 한두 줄로 정리하고, 지금 하던 일과 어떻게 이어지는지 알려 줘.",
    }


def repeat_question(conn, chat, row) -> dict | None:
    """지난 대화에 이름이 거의 같은 역이 있으면. 한 대화에서 이어진 대화(fork)끼리는 지난 대화로 치지 않아요:
    이어 받은 대화는 앞 대화의 턴을 처음부터 그대로 담고 있어서 만든 시각이 같고, 같은 자리에 같은 글의 턴이 있어요.
    (그런 대화를 지난 대화로 보면 같은 대화의 옆 턴과 짝지어져요. 구현 담당의 기록에서 반복 질문 28개 중 19개가 그랬어요)"""
    title = (row["title"] or "").rstrip("…")
    if len(title) < TITLE_MIN or chat["project_id"] == store.NO_PROJECT:
        return None
    best = None
    for r in conn.execute(
        "SELECT t.id, t.seq, t.title, t.user, t.ai, c.title AS chat_title, c.created_at FROM turns t"
        " JOIN chats c ON c.id = t.chat_id WHERE c.project_id = ? AND c.id != ? AND c.hidden = 0"
        " AND c.created_at < ? AND t.classified = 1 AND t.title IS NOT NULL"      # 같은 시각에 시작한 대화 = 이어 받은 대화
        " AND NOT EXISTS (SELECT 1 FROM turns x WHERE x.chat_id = c.id AND x.seq = ? AND x.user = ?)"
        " ORDER BY t.created_at DESC",
        (chat["project_id"], chat["id"], chat["created_at"], row["seq"], row["user"]),
    ):
        if difflib.SequenceMatcher(None, title, r["title"].rstrip("…")).ratio() >= SIMILAR:
            best = r
            break
    if best is None:
        return None
    day = store.display_date(best["created_at"])
    return {
        "kind": "repeat", "at": best["id"], "btn": "지난 답 보기",
        "text": f"{_q(best['title'])}, {day} 대화에서도 물으셨어요",
        "why": "같은 프로젝트의 지난 대화에 이름이 거의 같은 역이 있어요.",
        "pop": {"title": f"{day} · {best['chat_title'] or '지난 대화'}",
                "text": (best["ai"] or "")[:600] + ("…" if len(best["ai"] or "") > 600 else ""),
                "note": "지난 대화의 답 앞부분이에요. 노선도에서 그 역을 누르면 그 대화로 가요."},
    }


def transfer(conn, chat_id) -> bool:
    """구간 나누기(classify.segment_chat)가 끝난 뒤 불러요. 권했으면 True."""
    rows = [r for r in store.chat_turns(conn, chat_id) if r["classified"] != 0]
    starts = [r for r in rows if r["seg"]]
    if len(starts) < SEG_TRANSFER or conn.execute(
        "SELECT 1 FROM items i JOIN turns t ON t.id = i.turn_id WHERE t.chat_id = ? AND i.kind = 'topic' LIMIT 1", (chat_id,)
    ).fetchone():
        return False
    item = {
        "kind": "topic", "effect": "transfer", "btn": "환승하기",
        "text": f"이 대화에 주제가 {len(starts)}개 쌓였어요 · 새 대화로 갈아탈까요?",
        "why": f"‘{starts[0]['seg']}’부터 ‘{starts[-1]['seg']}’까지 한 대화에서 이어졌어요. "
               "정한 것만 들고 새 대화로 가면 답이 앞 내용을 덜 끌고 와요.",
    }
    if store.add_items(conn, starts[-1]["id"], [item]):
        usage.record(conn, "item", kind="topic", did="made", at="list")
        return True
    return False


def make(conn, chat_id, turn_ids) -> int:
    """방금 분류한 턴들에 규칙 할 일을 붙여요. 만든 수를 돌려줘요."""
    chat = store.chat_row(conn, chat_id)
    rows = [r for r in store.chat_turns(conn, chat_id) if r["classified"] == 1]
    made = 0
    for at, row in enumerate(rows):
        if row["id"] not in turn_ids:
            continue
        items = [it for it in (open_side(rows, at), repeat_question(conn, chat, row)) if it]
        for item in store.add_items(conn, row["id"], items):
            usage.record(conn, "item", kind=item["kind"], did="made", at="list")
            made += 1
    return made
