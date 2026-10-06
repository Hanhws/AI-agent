"""저장해 둔 것을 가닥에 다시 흘려보내요. 평가 · 측정 · 데모 백업용.

python -m backend.replay                    백엔드가 꺼져 있는 동안 쌓인 ~/.gadak/spool.jsonl (hook 이벤트)
python -m backend.replay tests/fixtures/cursor_events.jsonl

예시 대화(data/*_conversations.json의 시나리오)는 feed()로 저장소에 넣어요. 정확도 평가(eval/)가 이 길로
정답이 달린 대화를 넣고, 가닥이 붙인 값과 견줘요. 넣는 것은 질문 · 답 글뿐이고 정답 칸은 넣지 않아요.
"""
import json
import sys
import urllib.request
from datetime import datetime, timedelta, timezone

from . import config, store

# 예시 데이터의 site는 화면에 보이는 이름이에요. 저장소가 쓰는 이름으로 바꿔요
SITES = {"claude": "claude", "chatgpt": "chatgpt", "gemini": "gemini", "cursor": "cursor",
         "claude code": "claude-code", "vs code": "claude-code", "codex": "codex"}
STARTED = datetime(2026, 1, 5, 9, 0, tzinfo=timezone.utc)   # 예시에는 시각이 없어서, 대화마다 하루 · 턴마다 2분씩 띄워요


def replay(path, url) -> int:
    sent = 0
    with open(path, encoding="utf-8") as lines:
        for line in lines:
            line = line.strip()
            if not line:
                continue
            request = urllib.request.Request(
                url + "/events", data=line.encode("utf-8"),
                headers={"Content-Type": "application/json"}, method="POST",
            )
            with urllib.request.urlopen(request, timeout=10) as response:
                json.load(response)
            sent += 1
    return sent


def scenario(path, key) -> dict:
    """예시 파일에서 시나리오 하나. 없으면 KeyError."""
    with open(path, encoding="utf-8") as file:
        return json.load(file)["scenarios"][key]


def _edits(item, names):
    """예시의 ‘바뀐 곳 보기’(todo의 pop.diff: [종류, 줄])를 hook이 넘기는 변경(file · old · new)으로 되돌려요."""
    pop = item.get("pop") or {}
    title = (pop.get("title") or "").split("·")[-1].strip()
    name = title if title in names else (names[-1] if names else title)
    lines = [(kind, text[1:] if kind in ("a", "d") and text[:1] in "+-" else text) for kind, text in pop.get("diff") or []]
    old = "\n".join(text for kind, text in lines if kind != "a")
    new = "\n".join(text for kind, text in lines if kind != "d")
    return [{"file": name, "old": old, "new": new}] if name and old != new else []


def feed(conn, data, edits=True) -> dict:
    """시나리오의 대화를 저장소에 넣어요. 불러오기(sources/exports.py)와 같은 길이고, 대화 · 턴의 차례는 그대로예요.
    돌려주는 것: {정답 파일의 턴 id: 저장소의 턴 id}, 넣은 대화 id들(오래된 것부터).
    edits: 코드 도구(Cursor · Claude Code)의 예시는 바뀐 파일 이름과, 예시에 실린 변경 내용을 hook이 준 것처럼 같이 넣어요."""
    site = SITES.get(str(data.get("site") or "").lower(), "claude")
    project = data.get("project") or data.get("name") or data.get("key")
    ids, chats = {}, []
    with conn:
        for c, chat in enumerate(data["chats"]):
            chat_id = f"{data.get('key', 'example')}:{chat['id']}"
            began = STARTED + timedelta(days=c)
            store.upsert_chat(conn, project=project, chat_id=chat_id, site=site, title=chat.get("title"),
                              created_at=began.isoformat())
            chats.append(chat_id)
            for t, turn in enumerate(chat["turns"]):
                row = store.upsert_turn(
                    conn, chat_id=chat_id, message_ref=turn["id"], user=turn.get("user") or "", ai=turn.get("ai") or "",
                    state="done", created_at=(began + timedelta(minutes=2 * t)).isoformat(),
                )
                ids[turn["id"]] = row["id"]
                if not edits or site not in ("cursor", "claude-code", "codex"):
                    continue      # 웹 대화에서는 가닥이 파일 변경을 받지 못해요. 실제 입구가 주는 만큼만 넣어요
                names = [f["n"] if isinstance(f, dict) else f for f in turn.get("files") or []]
                for item in turn.get("todo") or []:
                    if item.get("kind") == "unasked":
                        store.add_edits(conn, row["id"], _edits(item, names))
                for name in names:
                    store.add_file(conn, row["id"], name)
    return {"turns": ids, "chats": chats}


def main(argv) -> int:
    spool = config.HOME / "spool.jsonl"
    path = argv[0] if argv else spool
    url = f"http://{config.HOST}:{config.PORT}"
    print(f"{replay(path, url)}개 이벤트를 {url}로 보냈어요")
    if not argv:
        spool.write_text("", encoding="utf-8")  # 쌓아 둔 것은 다 보냈으니 비워요
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
