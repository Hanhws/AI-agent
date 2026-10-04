"""크롬 확장이 읽어 보낸 대화 화면 (README 4장의 웹 입구 · extension/).

확장은 열어 둔 claude.ai · chatgpt.com 탭에 지금 보이는 대화를 질문 · 답의 목록으로 통째로 보내요.
여기서 그 목록을 저장소의 역과 맞춰요.
- 같은 대화를 다시 열어도, 내보내기 파일로 먼저 넣은 대화여도 역이 겹치지 않아요.
  사이트가 메시지 id를 주면(ChatGPT) 그것으로, 없으면(Claude) 질문 글과 그 글이 나온 차례로 맞춰요.
- 화면에서 읽은 지난 턴은 빈 곳만 채워요. 이미 있는 답은 덮어쓰지 않아요 (내보내기 파일의 글이 원문이에요).
- 확장이 지켜보는 동안 새로 생기거나 바뀐 턴(fresh)만 답을 고쳐 쓰고 정리 줄에 세워요.
  지난 대화를 열어 보기만 한 것은 다른 기록처럼 가닥 창에서 볼 때 정리해요 (README 5장 · 보는 대화부터).
"""
import collections
import hashlib
import itertools
import re
import unicodedata

from .. import store

SITES = ("claude", "chatgpt", "gemini")
VIA = "크롬 확장"
MAX_TURNS = 3000
KEY_LEN = 120             # 질문을 알아보는 데 쓰는 앞부분 (글자 · 숫자만)
TITLE_MAX, PROJECT_MAX = 200, 80
_ID = re.compile(r"[A-Za-z0-9_-]{1,80}")


class BadPage(ValueError):
    pass


class Elsewhere(ValueError):
    """이 화면의 메시지가 다른 대화에 이미 있어요. 주소만 먼저 바뀌고 화면은 앞 대화 그대로일 때 생겨요."""


def _clean(text) -> str:
    """오는 중인 답에서는 이모지가 반만 온 채로 읽히기도 해요. 그런 글자는 저장소에 넣을 수 없어서 바꿔 둬요."""
    try:
        text.encode("utf-8")
        return text
    except UnicodeEncodeError:
        return text.encode("utf-8", "replace").decode("utf-8")


def fit(text) -> str:
    """아주 긴 글은 앞 조금과 끝을 남겨요 (store.append_answer와 같은 길이)."""
    text = _clean(text or "").strip()
    if len(text) <= store.MAX_AI:
        return text
    return text[:store.AI_HEAD] + store.CUT + text[-(store.MAX_AI - store.AI_HEAD - len(store.CUT)):]


def _bare(text):
    return (ch for ch in unicodedata.normalize("NFC", text or "") if ch.isalnum())


def key(text) -> str:
    """질문 글에서 글자와 숫자만 남긴 앞부분. 화면의 글과 내보내기 파일의 글은 띄어쓰기 · 기호가 조금씩 달라요."""
    return "".join(itertools.islice(_bare(text), KEY_LEN)).casefold()


def same_text(a, b) -> bool:
    return "".join(_bare(a)) == "".join(_bare(b))


def text_ref(text_key, nth) -> str:
    """메시지 id가 없는 사이트의 messageRef: 질문 글 + 같은 글 중 몇 번째인지."""
    return "w" + hashlib.sha1(text_key.encode("utf-8")).hexdigest()[:12] + "-" + str(nth)


def _line(value, limit):
    value = " ".join(_clean(value).split()) if isinstance(value, str) else ""
    return value[:limit] or None


def _check(body):
    if not isinstance(body, dict):
        raise BadPage("요청은 JSON 객체여야 해요")
    site, chat, turns = body.get("site"), body.get("chat"), body.get("turns")
    if site not in SITES:
        raise BadPage("site는 " + " · ".join(SITES) + " 중 하나여야 해요")
    if not isinstance(chat, dict) or not isinstance(chat.get("id"), str) or not _ID.fullmatch(chat["id"]):
        raise BadPage("chat.id가 필요해요")
    if not isinstance(turns, list) or len(turns) > MAX_TURNS:
        raise BadPage("turns는 목록이어야 해요")
    out, seen = [], collections.Counter()
    for turn in turns:
        if not isinstance(turn, dict):
            raise BadPage("턴은 JSON 객체여야 해요")
        user, ai, ref = turn.get("user"), turn.get("ai"), turn.get("ref")
        if not isinstance(user, str) or not (ai is None or isinstance(ai, str)):
            raise BadPage("턴에는 user(글)와 ai(글 또는 null)가 필요해요")
        if ref is not None and not (isinstance(ref, str) and _ID.fullmatch(ref)):
            raise BadPage("ref는 사이트의 메시지 id여야 해요")
        user, ai = fit(user), (None if ai is None else fit(ai))
        if not user and not ai:
            continue
        text_key = key(user)
        out.append({"ref": ref, "user": user, "ai": ai, "fresh": turn.get("fresh") is True, "open": False,
                    "key": text_key, "nth": seen[text_key]})
        seen[text_key] += 1
    if not out:
        raise BadPage("읽은 턴이 없어요")
    out[-1]["open"] = turns[-1].get("open") is True     # 답이 오는 중일 수 있는 건 마지막 턴뿐이에요
    return site, {"id": chat["id"], "title": _line(chat.get("title"), TITLE_MAX),
                  "project": _line(chat.get("project"), PROJECT_MAX)}, out


def _elsewhere(conn, site, chat_id, refs) -> bool:
    for start in range(0, len(refs), 400):
        part = refs[start:start + 400]
        hit = conn.execute(
            "SELECT 1 FROM turns t JOIN chats c ON c.id = t.chat_id"
            " WHERE c.site = ? AND t.chat_id != ? AND t.message_ref IN (%s) LIMIT 1" % ",".join("?" * len(part)),
            [site, chat_id, *part],
        ).fetchone()
        if hit:
            return True
    return False


def _match(turn, by_ref, by_key, used):
    """이 턴이 저장소의 어느 역인지: 메시지 id → 글로 만든 ref → 같은 질문 글 중 같은 차례."""
    row = by_ref.get(turn["ref"]) if turn["ref"] else None
    if row is None:
        row = by_ref.get(text_ref(turn["key"], turn["nth"]))
    if row is None:
        same = by_key.get(turn["key"]) or []
        row = same[turn["nth"]] if turn["nth"] < len(same) else None
    return None if row is None or row["id"] in used else row


def ingest(conn, body) -> dict:
    """화면 하나를 저장소에 맞춰 넣어요. live면 방금 끝난 턴이 있어요(정리 줄에 세울 대화)."""
    site, chat, turns = _check(body)
    chat_id = chat["id"]
    refs = [t["ref"] for t in turns if t["ref"]]
    if refs and body.get("sure") is not True and _elsewhere(conn, site, chat_id, refs):
        raise Elsewhere("이 화면의 메시지가 다른 대화에 이미 있어요. 화면이 바뀌는 중일 수 있어서 넣지 않았어요.")
    new = changed = 0
    live = False
    with conn:
        store.upsert_chat(conn, project=chat["project"], chat_id=chat_id, site=site, title=chat["title"], via=VIA)
        if chat["title"] and store.chat_row(conn, chat_id)["title"] != chat["title"]:
            store.set_chat_title(conn, chat_id, chat["title"])     # 사이트가 제목을 나중에 붙이거나 바꿔요
            changed += 1
        if chat["project"] and store.move_chat(conn, chat_id, chat["project"]):
            changed += 1
        rows = store.chat_turns(conn, chat_id)
        by_ref = {r["message_ref"]: r for r in rows}
        by_key = collections.defaultdict(list)
        for r in rows:
            by_key[key(r["user"])].append(r)
        used, order = set(), []
        for turn in turns:
            want = "open" if turn["open"] else "done"
            row = _match(turn, by_ref, by_key, used)
            if row is None:
                ref = base = turn["ref"] or text_ref(turn["key"], turn["nth"])
                n = 0
                while ref in by_ref:
                    n += 1
                    ref = f"{base}~{n}"
                row = store.upsert_turn(conn, chat_id=chat_id, message_ref=ref, user=turn["user"],
                                        ai=turn["ai"] or "", state=want)
                by_ref[ref] = row
                new += 1
                live = live or (turn["fresh"] and want == "done")
            else:
                touched = False
                if turn["user"] and not row["user"]:
                    store.upsert_turn(conn, chat_id=chat_id, message_ref=row["message_ref"], user=turn["user"])
                    touched = True
                ai = turn["ai"]
                # 답을 고쳐 쓰는 때: 비어 있었거나, 오는 중이던 답이거나, 지켜보는 동안 바뀐 답
                if ai is not None and ai != row["ai"] and (
                        not row["ai"] or row["state"] == "open"
                        or (turn["fresh"] and not same_text(ai, row["ai"]))):
                    store.upsert_turn(conn, chat_id=chat_id, message_ref=row["message_ref"], ai=ai)
                    if row["classified"] != 0:
                        store.reset_classification(conn, row["id"])   # 답이 달라졌으니 다시 정리해요
                    touched = True
                # 끝난 턴을 다시 ‘오는 중’으로 돌리는 건 지켜보는 중인 턴(다시 생성)뿐이에요
                if row["state"] != want and (turn["fresh"] or row["state"] == "open"):
                    store.upsert_turn(conn, chat_id=chat_id, message_ref=row["message_ref"], state=want)
                    touched = True
                if touched:
                    changed += 1
                    live = live or (turn["fresh"] and want == "done")
            used.add(row["id"])
            order.append(row["id"])
        if store.put_in_order(conn, chat_id, order):
            changed += 1
    return {"chat": chat_id, "turns": len(turns), "new": new, "changed": changed, "live": live}


def note_seen(conn, version=None) -> None:
    """확장이 다녀갔어요. 찾은 곳에 ‘연결됨’으로 보여 주려고 적어 둬요."""
    store.set_setting(conn, "extension_seen", store.now())
    if isinstance(version, str) and version:
        store.set_setting(conn, "extension_version", version[:20])


def status(conn) -> dict:
    return {
        "seen": store.setting(conn, "extension_seen"),
        "version": store.setting(conn, "extension_version"),
        "chats": conn.execute("SELECT COUNT(*) FROM chats WHERE via = ?", (VIA,)).fetchone()[0],
    }
