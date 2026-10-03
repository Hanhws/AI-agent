"""내 PC에 남은 대화 기록을 찾아 저장소에 옮겨요.

켜면 한 번 훑고(지난 대화), 그 뒤로는 바뀐 파일의 새로 붙은 부분만 읽어요(지금 하는 대화).
읽는 곳(reader)마다 파일 형식만 다르고, 옮기는 방법은 여기 하나예요.
"""
import json
import time
from pathlib import Path

from .. import assemble, store
from . import claude_code, codex

READERS = (claude_code, codex)
INTERVAL = 2.5  # 초. 바뀐 파일이 있는지만 보는 거라 가벼워요


def _project(cwd):
    return store.project_key(Path(cwd).name) if cwd else None


def apply_ops(conn, reader, chat_id, ops, state=None) -> dict:
    """reader.parse가 돌려준 할 일을 저장소에 적어요. 무엇이 바뀌었는지 돌려줘요."""
    changed = {"turns": 0, "done": False}
    state = state or {}
    if store.chat_row(conn, chat_id) is None:
        if not any(op[0] == "prompt" for op in ops):
            return changed  # 아직 질문이 없는 대화예요. 제목은 state에 있으니 첫 질문과 같이 적어요
        store.upsert_chat(
            conn, project=_project(state.get("cwd")), chat_id=chat_id, site=reader.SITE, title=state.get("title"),
            created_at=state.get("started"), via=state.get("via"), cwd=state.get("cwd"),
        )
    for op in ops:
        kind = op[0]
        if kind == "title":
            store.set_chat_title(conn, chat_id, op[1])
        elif kind == "prompt":
            store.close_open_turns(conn, chat_id, keep_ref=op[1])
            store.upsert_turn(conn, chat_id=chat_id, message_ref=op[1], user=op[2], created_at=op[3])
            changed["turns"] += 1
        elif kind in ("more", "answer", "edits", "done"):
            row = store.find_turn(conn, chat_id, op[1])
            if row is None:
                continue
            if kind == "more":
                store.append_user(conn, row["id"], op[2])
                changed["turns"] += 1
            elif kind == "answer":
                store.append_answer(conn, row["id"], op[2])
            elif kind == "edits":
                store.add_edits(conn, row["id"], op[2])
            else:
                store.upsert_turn(conn, chat_id=chat_id, message_ref=op[1], state="done")
                changed["done"] = True
    return changed


class Syncer:
    def __init__(self, runtime, readers=READERS):
        self.rt = runtime
        self.readers = readers
        self.status = {"phase": "idle", "done": 0, "total": 0, "scans": 0, "files": {}}

    def sync_file(self, conn, reader, path) -> dict:
        """파일 하나에서 지난번 이후로 붙은 줄만 읽어요."""
        stat = path.stat()
        seen = store.get_sync(conn, path)
        if seen and seen["size"] == stat.st_size and seen["mtime"] == stat.st_mtime:
            return {"turns": 0, "done": False}
        chat_id = reader.chat_id(path)
        offset, state = 0, reader.new_state()
        if seen and stat.st_size >= seen["offset"]:
            offset, state = seen["offset"], json.loads(seen["state_json"])
        with open(path, "rb") as source:
            source.seek(offset)
            data = source.read()
        end = data.rfind(b"\n") + 1  # 쓰는 중인 마지막 줄은 다음에 읽어요
        lines = [raw.decode("utf-8", "replace") for raw in data[:end].split(b"\n") if raw.strip()]
        ops = reader.parse(lines, state)
        with conn:
            if seen and offset == 0:
                store.clear_answers(conn, chat_id)  # 파일이 새로 쓰였어요. 처음부터 다시 읽어요
            changed = apply_ops(conn, reader, chat_id, ops, state)
            store.set_sync(conn, path, source=reader.KEY, size=stat.st_size, mtime=stat.st_mtime,
                           offset=offset + end, state=state)
        changed["chat"] = chat_id
        changed["any"] = bool(ops)
        return changed

    def ingest_spool(self, conn) -> int:
        """가닥이 꺼져 있는 동안 hook이 쌓아 둔 이벤트를 넣어요 (cursor-hooks/gadak-hook.py)."""
        spool = self.rt.home / "spool.jsonl"
        if not spool.is_file() or spool.stat().st_size == 0:
            return 0
        taking = spool.with_suffix(".taking")
        spool.replace(taking)
        count = 0
        for raw in taking.read_bytes().split(b"\n"):
            try:
                event = json.loads(raw.decode("utf-8", "replace"))
                assemble.ingest_event(conn, event)
            except (ValueError, KeyError):
                continue
            count += 1
            if event.get("kind") in ("answer", "stop"):
                self.rt.classifier.request(event.get("chat_id"))
        taking.unlink()
        return count

    def scan_once(self, conn, live=False) -> int:
        """모든 reader의 파일을 한 번 훑어요. live면 새로 끝난 턴을 분류기에 알려요."""
        files = []
        for reader in self.readers:
            found = reader.session_files()
            self.status["files"][reader.KEY] = len(found)
            files.extend((path.stat().st_mtime, reader, path) for path in found)
        files.sort(key=lambda item: item[0], reverse=True)  # 최근에 쓴 대화부터
        if not live:
            self.status.update(phase="scan", done=0, total=len(files))
        touched = 0
        for index, (_, reader, path) in enumerate(files):
            try:
                changed = self.sync_file(conn, reader, path)
            except OSError:
                continue
            if changed.get("any"):
                touched += 1
                self.rt.bump()
                if live and (changed["turns"] or changed["done"]):
                    self.rt.classifier.request(changed["chat"])
            if not live:
                self.status["done"] = index + 1
        for reader in self.readers:
            with conn:
                if reader.after_scan(conn):
                    self.rt.bump()
        if self.ingest_spool(conn):
            self.rt.bump()
        self.status["scans"] += 1
        self.status["phase"] = "idle"
        return touched

    def run_forever(self, stop) -> None:
        conn = self.rt.connect()
        first = True
        while not stop.is_set():
            try:
                self.scan_once(conn, live=not first)
            except Exception as exc:  # 한 번 실패해도 다음 차례에 다시 봐요
                self.status.update(phase="idle", error=str(exc)[:200])
            first = False
            stop.wait(INTERVAL)
        conn.close()
