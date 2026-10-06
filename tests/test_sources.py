import io
import json
import os
import tempfile
import unicodedata
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from backend import store
from backend.runtime import Runtime
from backend.sources import claude_code, codex, exports

SESSION = "11111111-2222-3333-4444-555555555555"
CODEX_SESSION = "01a0f2aa-0000-7000-8000-b0a2d2a232f7"
CWD = "/Users/demo/dev/" + unicodedata.normalize("NFD", "환율 알리미")  # macOS는 한글 폴더 이름을 풀어서 주기도 해요


def user(ref, content, **extra):
    line = {"type": "user", "uuid": "u-" + ref, "promptId": ref, "sessionId": SESSION, "cwd": CWD,
            "entrypoint": "claude-vscode", "timestamp": "2026-10-01T02:00:00.000Z",
            "message": {"role": "user", "content": content}}
    line.update(extra)
    return line


def assistant(blocks, stop=None, **extra):
    line = {"type": "assistant", "uuid": "a", "sessionId": SESSION, "cwd": CWD,
            "message": {"role": "assistant", "model": "claude-demo", "content": blocks, "stop_reason": stop}}
    line.update(extra)
    return line


def text(value):
    return {"type": "text", "text": value}


# 만든 대화예요. 실제 세션 파일에서 본 줄의 종류를 하나씩 넣었어요
LINES = [
    {"type": "queue-operation", "operation": "enqueue", "sessionId": SESSION},
    user("p1", [text("<ide_opened_file>The user opened the file x.py in the IDE.</ide_opened_file>"),
                text("환율 가져오는 함수를 만들어 줘")], origin={"kind": "human"}),
    assistant([{"type": "thinking", "thinking": "…"}]),
    assistant([text("rate.py를 만들게요.")]),
    assistant([{"type": "tool_use", "name": "Write",
                "input": {"file_path": CWD + "/rate.py", "content": "def fetch_rate(): ..."}}], stop="tool_use"),
    user("p1", [{"type": "tool_result", "tool_use_id": "x", "content": "ok"}], toolUseResult={"type": "create"}),
    assistant([{"type": "tool_use", "name": "Read", "input": {"file_path": CWD + "/rate.py"}}], stop="tool_use"),
    assistant([text("fetch_rate()를 만들었어요.")], stop="end_turn"),
    {"type": "ai-title", "aiTitle": "환율 함수 만들기", "sessionId": SESSION},
    user("m1", "<local-command-caveat>Caveat</local-command-caveat>", isMeta=True),
    user("m2", "<command-name>/compact</command-name><command-message>compact</command-message>"),
    user("m3", "<task-notification>끝남</task-notification>", origin={"kind": "task-notification"}),
    user("p2", [text("목표가를 넘으면 알려 줘")], origin={"kind": "human"}),
    user("p3", [text("하루에 한 번만")], origin={"kind": "human"}),          # 답이 오기 전에 이어서 보낸 말
    assistant([text("check()를 더했어요."), {"type": "tool_use", "name": "Edit", "input": {
        "file_path": CWD + "/main.py", "old_string": "pass", "new_string": "check()"}}], stop="end_turn"),
    user("m4", [text("[Request interrupted by user]")]),
    {"type": "custom-title", "customTitle": "알림 봇", "sessionId": SESSION},
    {"type": "ai-title", "aiTitle": "나중에 온 자동 제목", "sessionId": SESSION},
    user("m5", "This session is being continued from a previous conversation…", isCompactSummary=True),
    user("m6", "Below is a conversation log from a Claude Code coding session.", promptSource="sdk", turnOrigin="sdk"),
    {"type": "assistant", "sessionId": SESSION, "isApiErrorMessage": True,
     "message": {"model": "<synthetic>", "content": [text("오류가 났어요")], "stop_reason": "stop_sequence"}},
    user("p4", [{"type": "image", "source": {}}]),
    "깨진 줄",
]


def shown_date(value) -> str:
    """화면에 보이는 날짜 (시험을 돌리는 곳의 시간대와 오늘 날짜에 따라 달라져요)."""
    return store.display_date(store.norm_ts(value))


def jsonl(lines) -> str:
    return "".join((line if isinstance(line, str) else json.dumps(line, ensure_ascii=False)) + "\n" for line in lines)


class SourcesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        base = Path(self.tmp.name)
        self.session = base / "claude" / "-Users-demo-dev" / f"{SESSION}.jsonl"
        self.session.parent.mkdir(parents=True)
        self.codex_home = base / "codex"
        env = mock.patch.dict(os.environ, {
            "GADAK_CLAUDE_PROJECTS": str(base / "claude"), "GADAK_CODEX_HOME": str(self.codex_home),
            "GADAK_CURSOR_HOME": str(base / "cursor"),
        })
        env.start()
        self.addCleanup(env.stop)
        self.rt = Runtime(base / "home" / "gadak.db", engine=None)
        self.conn = self.rt.connect()
        self.addCleanup(self.conn.close)

    def turns(self):
        return store.chat_turns(self.conn, SESSION)

    def view(self, project="환율 알리미"):
        return store.view(self.conn, project)


class ClaudeCodeReaderTest(SourcesTest):
    def test_only_what_a_person_typed_becomes_a_turn(self):
        self.session.write_text(jsonl(LINES), encoding="utf-8")
        self.rt.syncer.scan_once(self.conn)
        rows = self.turns()
        self.assertEqual([r["user"] for r in rows],
                         ["환율 가져오는 함수를 만들어 줘", "목표가를 넘으면 알려 줘\n\n하루에 한 번만", "(첨부 1개)"])
        self.assertEqual(rows[0]["ai"], "rate.py를 만들게요.\n\nfetch_rate()를 만들었어요.")
        self.assertEqual(rows[1]["ai"], "check()를 더했어요.")
        self.assertEqual([r["state"] for r in rows], ["done", "done", "open"])
        self.assertEqual([r["message_ref"] for r in rows], ["p1", "p2", "p4"])

    def test_chat_goes_to_the_folder_project_with_its_title(self):
        self.session.write_text(jsonl(LINES), encoding="utf-8")
        self.rt.syncer.scan_once(self.conn)
        (chat,) = self.view()["chats"]
        self.assertEqual((chat["id"], chat["title"], chat["site"], chat["via"], chat["date"]),
                         (SESSION, "알림 봇", "claude-code", "VS Code", shown_date("2026-10-01T02:00:00.000Z")))
        self.assertEqual([t.get("files") for t in chat["turns"]], [["rate.py"], ["main.py"], None])
        self.assertEqual(chat["pending"], 3)

    def test_reads_only_what_was_added_since_last_time(self):
        self.session.write_text(jsonl(LINES[:4]), encoding="utf-8")
        self.rt.syncer.scan_once(self.conn)
        self.assertEqual([r["ai"] for r in self.turns()], ["rate.py를 만들게요."])
        half = json.dumps(LINES[4], ensure_ascii=False)
        with open(self.session, "a", encoding="utf-8") as out:
            out.write(half[:40])                      # 쓰는 중인 줄
        self.assertEqual(self.rt.syncer.scan_once(self.conn, live=True), 0)
        with open(self.session, "a", encoding="utf-8") as out:
            out.write(half[40:] + "\n" + jsonl(LINES[5:]))
        self.rt.syncer.scan_once(self.conn, live=True)
        rows = self.turns()
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[0]["ai"], "rate.py를 만들게요.\n\nfetch_rate()를 만들었어요.")
        self.assertEqual(self.rt.syncer.scan_once(self.conn, live=True), 0)  # 바뀐 것이 없으면 다시 읽지 않아요

    def test_new_turns_of_a_live_chat_are_queued_for_classification(self):
        self.session.write_text(jsonl(LINES[:8]), encoding="utf-8")
        self.rt.syncer.scan_once(self.conn)
        self.assertEqual(len(self.rt.classifier.queue), 0)   # 지난 대화는 화면에서 열 때 정리해요
        with open(self.session, "a", encoding="utf-8") as out:
            out.write(jsonl(LINES[8:15]))
        self.rt.syncer.scan_once(self.conn, live=True)
        self.assertEqual(list(self.rt.classifier.queue), [SESSION])

    def test_a_session_without_questions_makes_no_chat(self):
        self.session.write_text(jsonl([LINES[0], LINES[8], LINES[9]]), encoding="utf-8")
        self.rt.syncer.scan_once(self.conn)
        self.assertEqual(store.projects(self.conn), [])

    def test_long_answers_keep_the_start_and_the_end(self):
        lines = [LINES[1]] + [assistant([text(f"{i:04d} " + "가" * 995)]) for i in range(30)]
        self.session.write_text(jsonl(lines), encoding="utf-8")
        self.rt.syncer.scan_once(self.conn)
        ai = self.turns()[0]["ai"]
        self.assertLessEqual(len(ai), store.MAX_AI + len(store.CUT))
        self.assertTrue(ai.startswith("0000 ") and "0029 " in ai and store.CUT in ai)

    def test_spooled_hook_events_are_taken_in(self):
        spool = self.rt.home / "spool.jsonl"
        events = [
            {"site": "cursor", "project": "환율 알리미", "chat_id": "conv-9", "message_ref": "g1", "kind": "prompt", "text": "질문"},
            {"site": "cursor", "project": "환율 알리미", "chat_id": "conv-9", "message_ref": "g1", "kind": "answer", "text": "답"},
        ]
        spool.write_text(jsonl(events) + "깨진 줄\n", encoding="utf-8")
        self.rt.syncer.scan_once(self.conn)
        (chat,) = self.view()["chats"]
        self.assertEqual((chat["site"], chat["turns"][0]["ai"]), ("cursor", "답"))
        self.assertFalse(spool.exists())
        self.assertEqual(list(self.rt.classifier.queue), ["conv-9"])


class CodexReaderTest(SourcesTest):
    def test_codex_session_and_its_title(self):
        path = self.codex_home / "sessions" / "2026" / "10" / "01" / f"rollout-2026-10-01T10-00-00-{CODEX_SESSION}.jsonl"
        path.parent.mkdir(parents=True)
        ts = "2026-10-01T01:00:00.000Z"
        path.write_text(jsonl([
            {"type": "session_meta", "timestamp": ts, "payload": {"id": CODEX_SESSION, "cwd": "/Users/demo/dev/nba-analysis",
                                                                  "originator": "codex_vscode", "timestamp": ts}},
            {"type": "event_msg", "timestamp": ts, "payload": {"type": "task_started", "turn_id": "turn-1"}},
            {"type": "response_item", "timestamp": ts, "payload": {"type": "message", "role": "developer", "content": []}},
            {"type": "event_msg", "timestamp": ts, "payload": {"type": "user_message", "message": "alpha를 낮춰 줘"}},
            {"type": "event_msg", "timestamp": ts, "payload": {"type": "agent_message", "message": "볼게요."}},
            {"type": "event_msg", "timestamp": ts, "payload": {"type": "agent_message", "message": "0.5로 낮췄어요."}},
            {"type": "event_msg", "timestamp": ts, "payload": {"type": "task_complete", "turn_id": "turn-1"}},
        ]), encoding="utf-8")
        (self.codex_home / "session_index.jsonl").write_text(
            json.dumps({"id": CODEX_SESSION, "thread_name": "alpha 낮추기"}, ensure_ascii=False) + "\n", encoding="utf-8")
        self.rt.syncer.scan_once(self.conn)
        (chat,) = self.view("nba-analysis")["chats"]
        self.assertEqual((chat["id"], chat["site"], chat["via"], chat["title"]),
                         (CODEX_SESSION, "codex", "VS Code", "alpha 낮추기"))
        (turn,) = chat["turns"]
        self.assertEqual((turn["user"], turn["ai"], turn["messageRef"]), ("alpha를 낮춰 줘", "볼게요.\n\n0.5로 낮췄어요.", "turn-1"))


CLAUDE_EXPORT = [{
    "uuid": "conv-claude-1", "name": "보고서 목차", "created_at": "2026-09-30T01:00:00.000000Z",
    "chat_messages": [
        {"uuid": "m1", "sender": "human", "text": "목차를 잡아 줘", "created_at": "2026-09-30T01:00:00.000000Z",
         "attachments": [{"file_name": "초안.docx"}], "files": []},
        {"uuid": "m2", "sender": "assistant", "text": "", "content": [{"type": "text", "text": "세 장으로 나눌게요."}]},
        {"uuid": "m3", "sender": "human", "text": "2장을 더 자세히", "created_at": "2026-09-30T01:05:00.000000Z"},
        {"uuid": "m4", "sender": "assistant", "text": "2장을 넷으로 나눴어요."},
    ],
}]
CHATGPT_EXPORT = [{
    "conversation_id": "conv-gpt-1", "title": "발표 대본", "create_time": 1790000000.0, "current_node": "n4",
    "mapping": {
        "n0": {"id": "n0", "message": None, "parent": None},
        "n1": {"id": "n1", "parent": "n0", "message": {"id": "n1", "author": {"role": "system"}, "create_time": None,
                                                        "content": {"content_type": "text", "parts": [""]}, "metadata": {"is_visually_hidden_from_conversation": True}}},
        "n2": {"id": "n2", "parent": "n1", "message": {"id": "n2", "author": {"role": "user"}, "create_time": 1790000001.0,
                                                        "content": {"content_type": "text", "parts": ["대본을 써 줘"]}, "metadata": {}}},
        "n3x": {"id": "n3x", "parent": "n2", "message": {"id": "n3x", "author": {"role": "assistant"}, "create_time": 1790000002.0,
                                                          "content": {"content_type": "text", "parts": ["(다시 만들기 전의 답)"]}, "metadata": {}}},
        "n3": {"id": "n3", "parent": "n2", "message": {"id": "n3", "author": {"role": "assistant"}, "create_time": 1790000003.0,
                                                        "content": {"content_type": "code", "text": "search()"}, "metadata": {}}},
        "n4": {"id": "n4", "parent": "n3", "message": {"id": "n4", "author": {"role": "assistant"}, "create_time": 1790000004.0,
                                                        "content": {"content_type": "text", "parts": ["3분 대본이에요."]}, "metadata": {}}},
    },
}]


class ExportReaderTest(SourcesTest):
    def test_claude_export(self):
        (chat,) = exports.read(json.dumps(CLAUDE_EXPORT, ensure_ascii=False).encode("utf-8"))
        self.assertEqual((chat["site"], chat["id"], chat["title"]), ("claude", "conv-claude-1", "보고서 목차"))
        self.assertEqual([(t["ref"], t["user"], t["ai"], t["files"]) for t in chat["turns"]], [
            ("m1", "목차를 잡아 줘", "세 장으로 나눌게요.", ["초안.docx"]),
            ("m3", "2장을 더 자세히", "2장을 넷으로 나눴어요.", []),
        ])

    def test_chatgpt_export_follows_the_visible_branch(self):
        (chat,) = exports.read(json.dumps(CHATGPT_EXPORT, ensure_ascii=False).encode("utf-8"))
        self.assertEqual((chat["site"], chat["id"], chat["title"]), ("chatgpt", "conv-gpt-1", "발표 대본"))
        self.assertEqual([(t["ref"], t["user"], t["ai"]) for t in chat["turns"]], [("n2", "대본을 써 줘", "3분 대본이에요.")])

    def test_zip_and_importing_twice(self):
        packed = io.BytesIO()
        with zipfile.ZipFile(packed, "w") as archive:
            archive.writestr("users.json", "[]")
            archive.writestr("conversations.json", json.dumps(CLAUDE_EXPORT + CHATGPT_EXPORT, ensure_ascii=False))
        for _ in range(2):
            result = exports.ingest(self.conn, exports.read(packed.getvalue()))
        self.assertEqual((result["chats"], result["turns"]), (2, 3))
        chats = self.view(store.NO_PROJECT)["chats"]
        self.assertEqual([(c["site"], c["date"], len(c["turns"])) for c in chats], [
            ("chatgpt", shown_date(1790000000.0), 1), ("claude", shown_date("2026-09-30T01:00:00Z"), 2),
        ])

    def test_other_files_are_refused(self):
        for data in (b"not json", b"{}", b"[]", json.dumps([{"hello": 1}]).encode(), b"PK\x03\x04broken"):
            with self.assertRaises(exports.BadExport):
                exports.read(data)


class CleanPromptTest(unittest.TestCase):
    def test_injected_parts_are_removed(self):
        self.assertEqual(claude_code.clean_prompt(
            "<system-reminder>지침</system-reminder>질문이에요 <pasted_content id=\"a\">붙인 글</pasted_content>"),
            "질문이에요 붙인 글")
        self.assertIsNone(claude_code.clean_prompt("<command-name>/clear</command-name>"))
        self.assertIsNone(claude_code.clean_prompt([{"type": "tool_result", "content": "x"}, {"type": "text", "text": "y"}]))
        self.assertIsNone(claude_code.clean_prompt(None))

    def test_codex_chat_id_is_the_session_id(self):
        self.assertEqual(codex.chat_id(f"/x/rollout-2026-10-01T10-00-00-{CODEX_SESSION}.jsonl"), CODEX_SESSION)


if __name__ == "__main__":
    unittest.main()
