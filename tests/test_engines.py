"""엔진(가닥이 판단에 쓰는 LLM)을 부르는 쪽. 실제 모델도, 실제 키체인도 건드리지 않아요: 명령 · SDK를 가짜로 바꿔 끼워요."""
import json
import re
import subprocess
import tempfile
import threading
import time
import types
import unittest
from pathlib import Path
from unittest import mock

import anthropic
import httpx2

from backend import config, engines
from backend.app import create_app
from backend.engines import (BadOutput, EngineError, anthropic_api, claude_cli, codex_cli, connect, gemini_api, keys,
                             openai_api, rest)

KEY = "sk-ant-api03-" + "Ab1_" * 8 + "wxyz"
OPENAI_KEY = "sk-proj-" + "Cd2_" * 30 + "qrst"
GEMINI_KEY = "AIzaSy" + "Ef3-" * 7 + "hijkl"            # 예전부터 쓰던 모양 (39자)
GEMINI_NEW_KEY = "AQ.Ab8" + "Gh4_" * 12 + "mnop"        # 2026-05-28부터 AI Studio가 주는 모양

SCHEMA = {"type": "object", "properties": {"ok": {"type": "boolean"}}, "required": ["ok"], "additionalProperties": False}


def said(**result):
    return subprocess.CompletedProcess([], 0, stdout=json.dumps(result, ensure_ascii=False), stderr="")


class ClaudeCliTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        for patch in (mock.patch.object(config, "HOME", Path(self.tmp.name)),
                      mock.patch.object(claude_cli.shutil, "which", return_value="/usr/local/bin/claude")):
            patch.start()
            self.addCleanup(patch.stop)

    def ask(self, *answers):
        with mock.patch.object(claude_cli.subprocess, "run", side_effect=list(answers)) as run:
            engine = claude_cli.ClaudeCliEngine(model="haiku")
            try:
                return engine.complete_json("정리해", "{}", SCHEMA), run, engine
            except Exception as exc:
                return exc, run, engine

    def test_the_structured_answer_comes_back_with_what_it_used(self):
        out, run, engine = self.ask(said(is_error=False, structured_output={"ok": True}, total_cost_usd=0.012,
                                         usage={"input_tokens": 900, "cache_read_input_tokens": 100, "output_tokens": 40}))
        self.assertEqual(out, {"ok": True})
        self.assertEqual(engine.last, {"input_tokens": 1000, "output_tokens": 40, "cost": 0.012})
        command, kwargs = run.call_args.args[0], run.call_args.kwargs
        self.assertEqual(command[command.index("--model") + 1], "haiku")
        self.assertEqual(json.loads(command[command.index("--json-schema") + 1]), SCHEMA)
        self.assertEqual((kwargs["input"], kwargs["env"]["MAX_THINKING_TOKENS"], kwargs["env"][claude_cli.INTERNAL_ENV]), ("{}", "0", "1"))
        self.assertNotIn("ANTHROPIC_API_KEY", kwargs["env"])            # 구독 로그인으로 돌려요
        self.assertNotIn("--effort", command)                           # Haiku는 생각을 끈 채로 돌아요

    def test_bigger_models_are_run_at_low_effort(self):
        with mock.patch.object(claude_cli.subprocess, "run", return_value=said(is_error=False, structured_output={"ok": True})) as run:
            claude_cli.ClaudeCliEngine(model="sonnet").complete_json("정리해", "{}", SCHEMA)
        command = run.call_args.args[0]
        self.assertEqual(command[command.index("--effort") + 1], "low")

    def test_an_answer_in_prose_is_asked_once_more(self):
        prose = said(is_error=False, result="죄송합니다. 새로운 턴이 아직 제공되지 않았네요.")
        out, run, _ = self.ask(prose, said(is_error=False, structured_output={"ok": True}))
        self.assertEqual((out, run.call_count), ({"ok": True}, 2))
        out, run, _ = self.ask(prose, prose)
        self.assertIsInstance(out, BadOutput)                           # 그래도 안 되면 그 묶음만 실패예요
        self.assertNotIsInstance(out, EngineError)                      # 정리 전체를 멈추는 오류가 아니에요
        self.assertEqual(run.call_count, claude_cli.ASK_TRIES)
        # Claude Code가 안에서 여러 번 다시 시켜도 형식을 못 맞춘 것도 그 묶음만의 실패예요 (깨진 JSON)
        broken = said(is_error=True, subtype="error_max_structured_output_retries", result=None,
                      errors=["Failed to provide valid structured output after 5 attempts"])
        out, run, _ = self.ask(broken)
        self.assertIsInstance(out, BadOutput)
        self.assertNotIsInstance(out, EngineError)

    def test_what_a_call_spent_is_kept_for_the_token_log(self):
        """backend/tokens.py가 읽는 값. 형식이 틀려 다시 물은 것도, 실패한 답도 쓴 것으로 세요."""
        used = {"input_tokens": 10, "cache_read_input_tokens": 100, "output_tokens": 5, "service_tier": "standard"}
        prose = said(is_error=False, result="글로 답했어요", usage=used, total_cost_usd=0.001)
        _, _, engine = self.ask(prose, said(is_error=False, structured_output={"ok": True}, usage=used, total_cost_usd=0.002))
        spent = dict(engine.last_usage)
        self.assertAlmostEqual(spent.pop("cost"), 0.003)
        self.assertEqual(spent, {"input_tokens": 20, "cache_read_input_tokens": 200, "output_tokens": 10, "model": "haiku"})
        self.assertEqual(engine.last["input_tokens"], 110)                # 평가가 보는 값은 마지막 답 하나 그대로
        out, _, engine = self.ask(said(is_error=True, result="Claude AI usage limit reached|1791234567", usage=used))
        self.assertIsInstance(out, EngineError)
        self.assertEqual((engine.last_usage["input_tokens"], engine.last_usage["cost"]), (10, None))
        _, _, engine = self.ask(subprocess.TimeoutExpired("claude", 120))
        self.assertIsNone(engine.last_usage)                              # 답을 못 받았으면 적을 것이 없어요

    def test_login_or_limit_trouble_stops_at_once(self):
        out, run, _ = self.ask(said(is_error=True, result="Not logged in · Please run /login"))
        self.assertIsInstance(out, EngineError)
        self.assertIn("로그인되어 있지 않아요", str(out))                  # 가닥 창에 한 줄로 보이는 말
        self.assertEqual(run.call_count, 1)
        out, _, _ = self.ask(said(is_error=True, result="Claude AI usage limit reached|1791234567"))
        self.assertIn("usage limit", str(out))
        out, _, _ = self.ask(subprocess.CompletedProcess([], 1, stdout="", stderr="boom"))
        self.assertIsInstance(out, EngineError)
        out, _, _ = self.ask(subprocess.TimeoutExpired("claude", 120))
        self.assertIsInstance(out, EngineError)


class CodexCliTest(unittest.TestCase):
    """ChatGPT 구독 엔진. 실제 Codex는 부르지 않아요: 명령을 가짜로 바꿔 끼우고, 답 파일을 대신 적어요."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.bin = Path(self.tmp.name) / "codex"
        self.bin.write_text("#!/bin/sh\n", encoding="utf-8")
        self.bin.chmod(0o755)
        for patch in (mock.patch.object(config, "HOME", Path(self.tmp.name) / "home"), mock.patch.object(config, "CODEX_MODEL", ""),
                      mock.patch.dict(codex_cli.os.environ, {codex_cli.ENV_BIN: str(self.bin), "OPENAI_API_KEY": "sk-쓰면-안-되는-키"})):
            patch.start()
            self.addCleanup(patch.stop)
        self.seen = {}

    def ask(self, answer, events=(), code=0, model="haiku", effort=None, stderr=""):
        def run(command, **kwargs):
            self.seen.update(command=command, kwargs=kwargs,
                             schema=json.loads(Path(command[command.index("--output-schema") + 1]).read_text(encoding="utf-8")))
            if isinstance(answer, Exception):
                raise answer
            if answer is not None:
                Path(command[command.index("-o") + 1]).write_text(answer, encoding="utf-8")
            return subprocess.CompletedProcess(command, code, stdout="\n".join(json.dumps(e) for e in events), stderr=stderr)
        with mock.patch.object(codex_cli.subprocess, "run", side_effect=run):
            engine = codex_cli.CodexCliEngine(model=model, effort=effort)
            try:
                return engine.complete_json("정리해", '{"turns": []}', SCHEMA), engine
            except Exception as exc:
                return exc, engine

    def test_the_answer_comes_back_in_the_given_shape_and_nothing_is_kept(self):
        used = {"type": "turn.completed", "usage": {"input_tokens": 13400, "cached_input_tokens": 12000, "cache_write_input_tokens": 0,
                                                    "output_tokens": 19, "reasoning_output_tokens": 0}}
        out, engine = self.ask('{"ok": true}', [{"type": "thread.started"}, used])
        self.assertEqual(out, {"ok": True})
        command, kwargs = self.seen["command"], self.seen["kwargs"]
        self.assertEqual(command[:2], [str(self.bin), "exec"])
        for flag in ("--ephemeral", "--skip-git-repo-check", "--ignore-user-config", "--json"):      # 내 Codex 대화 목록 · 설정과 섞이지 않게
            self.assertIn(flag, command)
        self.assertEqual(command[command.index("--sandbox") + 1], "read-only")                      # 무엇도 고치지 못해요
        self.assertEqual(self.seen["schema"], SCHEMA)
        self.assertEqual(command[command.index("-c") + 1], 'model_reasoning_effort="low"')
        self.assertNotIn("-m", command)                                                              # 모델은 Codex의 기본값
        self.assertTrue(kwargs["input"].endswith('정리해\n\n입력:\n{"turns": []}'))
        self.assertNotIn("OPENAI_API_KEY", kwargs["env"])                                            # 구독 로그인으로 돌려요
        self.assertEqual(engine.last, {"input_tokens": 13400, "output_tokens": 19, "cost": None})
        self.assertEqual(engine.last_usage, {"input_tokens": 1400, "cache_read_input_tokens": 12000, "cache_creation_input_tokens": 0,
                                             "output_tokens": 19, "cost": None, "model": "codex"})   # 캐시에서 읽은 것은 따로 세요
        self.assertEqual((engine.name, engine.model), ("codex_cli", "haiku"))

    def test_bigger_models_think_deeper_and_a_named_model_is_passed_on(self):
        self.ask('{"ok": true}', model="sonnet")
        self.assertIn('model_reasoning_effort="medium"', self.seen["command"])
        self.ask('{"ok": true}', model="sonnet", effort="high")
        self.assertIn('model_reasoning_effort="high"', self.seen["command"])
        with mock.patch.object(config, "CODEX_MODEL", "gpt-작은-것"):
            self.ask('{"ok": true}')
        self.assertEqual(self.seen["command"][self.seen["command"].index("-m") + 1], "gpt-작은-것")

    def test_login_or_limit_trouble_stops_and_an_odd_answer_fails_only_that_batch(self):
        out, _ = self.ask(None, [{"type": "error", "message": "401 Unauthorized: not logged in"}], code=1)
        self.assertIsInstance(out, EngineError)
        self.assertIn("ChatGPT 구독을 다시 연결", str(out))                    # 가닥 창에 한 줄로 보이는 말
        out, _ = self.ask(None, [{"type": "turn.failed", "error": {"message": "You've hit your usage limit. Try again at 3pm."}}], code=1)
        self.assertIsInstance(out, EngineError)
        self.assertIn("usage limit", str(out))
        out, _ = self.ask(subprocess.TimeoutExpired("codex", 180))
        self.assertIsInstance(out, EngineError)
        for odd in ("죄송하지만 형식대로 답할 수 없어요", "[1, 2]", None):        # 글로 답함 · 모양이 다름 · 답이 없음
            out, _ = self.ask(odd)
            self.assertIsInstance(out, BadOutput, odd)
            self.assertNotIsInstance(out, EngineError)

    def test_login_is_checked_without_calling_a_model(self):
        def status(said, code=0):
            done = subprocess.CompletedProcess([], code, stdout=said, stderr="")
            with mock.patch.object(codex_cli.subprocess, "run", return_value=done) as run:
                return codex_cli.CodexCliEngine().check(), run.call_args.args[0]
        seen, command = status("Logged in using ChatGPT\n")
        self.assertEqual((seen, command[1:]), ({"ok": True, "authMethod": "chatgpt"}, ["login", "status"]))
        self.assertFalse(status("Not logged in\n", 1)[0]["ok"])
        with mock.patch.dict(codex_cli.os.environ, {codex_cli.ENV_BIN: "none"}):
            self.assertEqual(codex_cli.CodexCliEngine().check()["ok"], False)
            self.assertIsInstance(self.ask('{"ok": true}')[0], EngineError)

    def test_codex_is_found_inside_the_editor_extension_or_where_gadak_put_it(self):
        home = Path(self.tmp.name) / "me"
        inside = home / ".vscode" / "extensions" / "openai.chatgpt-26.1002.5-darwin-arm64" / "bin" / "macos-aarch64" / "codex"
        inside.parent.mkdir(parents=True)
        inside.write_text("#!/bin/sh\n", encoding="utf-8")
        inside.chmod(0o755)
        env = {k: v for k, v in codex_cli.os.environ.items() if k != codex_cli.ENV_BIN}
        with mock.patch.dict(codex_cli.os.environ, env, clear=True), mock.patch.object(codex_cli.shutil, "which", return_value=None), \
                mock.patch.object(codex_cli.Path, "home", return_value=home):
            self.assertEqual(codex_cli.find_bin(), str(inside))               # 터미널 명령이 없어도 ChatGPT 확장 안의 것을 써요
            mine = config.HOME / "bin" / "codex"                              # 가닥이 받아 둔 것이 있으면 그것이 먼저
            mine.parent.mkdir(parents=True)
            mine.write_text("#!/bin/sh\n", encoding="utf-8")
            mine.chmod(0o755)
            self.assertEqual(codex_cli.find_bin(), str(mine))


class FakeKeychain:
    """macOS의 security 명령 흉내. 넣은 것은 여기에만 있어요."""

    def __init__(self):
        self.items, self.calls = {}, []

    def run(self, argv, input=None, **_kwargs):
        self.calls.append((list(argv), input))
        what = argv[1]
        if what == "-i":      # 넣기: 명령을 표준 입력으로 받아요
            got = re.fullmatch(r'add-generic-password -U -s "([^"]+)" -a "([^"]+)" -l "[^"]*" -w "([^"]+)"\n', input)
            self.items[(got[1], got[2])] = got[3]
            return subprocess.CompletedProcess(argv, 0, "", "")
        where = (argv[argv.index("-s") + 1], argv[argv.index("-a") + 1])
        if what == "find-generic-password":
            key = self.items.get(where)
            return subprocess.CompletedProcess(argv, 0 if key else 44, (key + "\n") if key else "", "")
        if what == "delete-generic-password":
            return subprocess.CompletedProcess(argv, 0 if self.items.pop(where, None) else 44, "", "")
        raise AssertionError(argv)


class WithKeychain(unittest.TestCase):
    def setUp(self):
        self.keychain = FakeKeychain()
        keys._seen.update(at=0.0, service=None, key=None)
        for patch in (mock.patch.object(keys.subprocess, "run", self.keychain.run),
                      mock.patch.object(keys, "can_store", lambda: True),
                      mock.patch.dict(keys.os.environ, {"GADAK_KEYCHAIN_SERVICE": "local.gadak.test"})):
            patch.start()
            self.addCleanup(patch.stop)
        for name in keys.ENVS:
            keys.os.environ.pop(name, None)
        self.addCleanup(keys._seen.update, at=0.0, service=None, key=None)


class KeysTest(WithKeychain):
    def test_a_key_is_kept_in_the_keychain_and_never_on_a_command_line(self):
        self.assertEqual((keys.find(), keys.describe()["stored"]), ((None, None), False))
        keys.save(KEY)
        self.assertEqual(self.keychain.items, {("local.gadak.test", keys.ACCOUNT): KEY})
        for argv, _stdin in self.keychain.calls:
            self.assertNotIn(KEY, " ".join(argv))                      # 프로세스 목록에 보이지 않게 표준 입력으로만
        self.assertEqual(keys.find(), (KEY, "keychain"))
        self.assertEqual(keys.describe(), {"stored": True, "source": "keychain", "hint": "sk-ant-…wxyz", "can_store": True,
                                           "company": "Anthropic"})
        self.assertNotIn(KEY[:-4], json.dumps(keys.describe(), ensure_ascii=False))
        self.assertTrue(keys.delete())
        self.assertEqual(keys.find(), (None, None))
        self.assertFalse(keys.delete())

    def test_the_keychain_is_not_asked_every_time(self):
        keys.save(KEY)
        asked = len(self.keychain.calls)
        for _ in range(5):
            self.assertEqual(keys.get(), KEY)
        self.assertEqual(len(self.keychain.calls), asked)              # 잠깐은 기억해 둬요

    def test_things_that_are_not_keys_are_refused_before_anything_runs(self):
        for bad in ("", "hello", "sk-ant-short", KEY + '" -T /bin/sh "', "sk-ant-한글" + "a" * 20, None, 7):
            with self.assertRaises(keys.KeyStoreError):
                keys.save(bad)
        self.assertEqual(self.keychain.calls, [])

    def test_without_a_keychain_only_the_environment_is_used(self):
        with mock.patch.object(keys, "can_store", lambda: False), mock.patch.dict(keys.os.environ, {keys.ENV: KEY}):
            self.assertEqual(keys.find(), (KEY, "env"))
            with self.assertRaises(keys.KeyStoreError):
                keys.save(KEY)
        self.assertEqual(self.keychain.calls, [])

    def test_the_head_of_a_key_tells_whose_it_is(self):
        seen = {key: (keys.company(key), keys.hint(key)) for key in (KEY, OPENAI_KEY, GEMINI_KEY, GEMINI_NEW_KEY)}
        self.assertEqual(seen, {KEY: ("anthropic", "sk-ant-…wxyz"), OPENAI_KEY: ("openai", "sk-…qrst"),
                                GEMINI_KEY: ("gemini", "AIza…ijkl"), GEMINI_NEW_KEY: ("gemini", "AQ.…mnop")})
        for other in ("sk-or-v1-" + "a" * 60, "gsk_" + "a" * 50, "xai-" + "a" * 60, OPENAI_KEY + "!", "AQ." + "가" * 30, "AQ.short"):
            self.assertIsNone(keys.company(other), other)             # 가닥이 못 쓰는 키는 어느 회사로도 보내지 않아요
        for key, name in ((KEY, "anthropic_api"), (OPENAI_KEY, "openai_api"), (GEMINI_KEY, "gemini_api"), (GEMINI_NEW_KEY, "gemini_api")):
            keys.save(key)                                            # 넣어 두는 키는 하나예요. 새로 넣으면 바뀌어요
            self.assertEqual(self.keychain.items, {("local.gadak.test", keys.ACCOUNT): key})
            self.assertEqual((keys.engine(), keys.describe()["company"]), (name, keys.COMPANIES[keys.company(key)]))
            others = [who for who in keys.COMPANIES if who != keys.company(key)]
            self.assertEqual((keys.get(keys.company(key)), [keys.get(who) for who in others]), (key, [None, None]))   # 다른 회사에는 내주지 않아요
        keys.delete()
        self.assertIsNone(keys.engine())

    def test_a_key_left_in_the_old_place_is_still_read_and_then_tidied(self):
        """Anthropic 키만 받던 때에 넣어 둔 키. 다시 넣으라고 하지 않아요."""
        old, new = ("local.gadak.test", keys.OLD_ACCOUNT), ("local.gadak.test", keys.ACCOUNT)
        self.keychain.items[old] = KEY
        self.assertEqual((keys.find(), keys.engine()), ((KEY, "keychain"), "anthropic_api"))
        keys.save(OPENAI_KEY)                                         # 새 키를 넣으면 예전 자리는 비워요
        self.assertEqual((self.keychain.items, keys.engine()), ({new: OPENAI_KEY}, "openai_api"))
        self.keychain.items[old] = KEY
        self.assertTrue(keys.delete())                                # 지울 때는 두 자리 다
        self.assertEqual((self.keychain.items, keys.find()), ({}, (None, None)))

    def test_only_a_key_meant_for_gadak_is_taken_from_the_environment(self):
        with mock.patch.object(keys, "can_store", lambda: False):
            with mock.patch.dict(keys.os.environ, {"OPENAI_API_KEY": OPENAI_KEY, "GEMINI_API_KEY": GEMINI_KEY, "GOOGLE_API_KEY": GEMINI_KEY}):
                self.assertEqual(keys.find(), (None, None))           # 다른 도구에 쓰려고 둔 키로 돈을 쓰지 않아요
            with mock.patch.dict(keys.os.environ, {keys.ENV: GEMINI_KEY, "ANTHROPIC_API_KEY": KEY}):
                self.assertEqual((keys.find(), keys.engine()), ((GEMINI_KEY, "env"), "gemini_api"))
            with mock.patch.dict(keys.os.environ, {"ANTHROPIC_API_KEY": KEY}):
                self.assertEqual((keys.find(), keys.engine()), ((KEY, "env"), "anthropic_api"))     # 예전부터 보던 이름은 그대로 봐요


def reply(text, stop="end_turn", tokens=(1200, 300)):
    return types.SimpleNamespace(
        content=[types.SimpleNamespace(type="text", text=text)], stop_reason=stop,
        usage=types.SimpleNamespace(input_tokens=tokens[0], cache_read_input_tokens=0, cache_creation_input_tokens=None,
                                    output_tokens=tokens[1]))


class FakeClient:
    def __init__(self, answer):
        self.calls = []

        def create(where):
            def call(**request):
                self.calls.append((where, request))
                if isinstance(answer, Exception):
                    raise answer
                return answer
            return call
        self.messages = types.SimpleNamespace(create=create("messages"))
        self.beta = types.SimpleNamespace(messages=types.SimpleNamespace(create=create("beta")))


def api_error(kind, status, message="x"):
    request = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    return kind(message, response=httpx2.Response(status, request=request), body=None)


NULLABLE = {"type": "object", "properties": {"dec": {"type": ["string", "null"]}, "depth": {"type": "integer", "enum": [0, 1, 2]}},
            "required": ["dec", "depth"], "additionalProperties": False}


class AnthropicApiTest(WithKeychain):
    def ask(self, answer, model="haiku", schema=NULLABLE):
        client = FakeClient(answer)
        engine = anthropic_api.AnthropicApiEngine(model=model, client=client)
        try:
            return engine.complete_json("정리해", '{"turns": []}', schema), client, engine
        except Exception as exc:
            return exc, client, engine

    def test_haiku_is_asked_for_json_in_the_given_shape(self):
        out, client, engine = self.ask(reply('{"dec": null, "depth": 1}'))
        self.assertEqual(out, {"dec": None, "depth": 1})
        where, request = client.calls[0]
        self.assertEqual((where, request["model"], request["max_tokens"]), ("messages", "claude-haiku-4-5", 16000))
        self.assertEqual(request["messages"], [{"role": "user", "content": '{"turns": []}'}])
        self.assertEqual(request["system"], [{"type": "text", "text": "정리해", "cache_control": {"type": "ephemeral"}}])
        shape = request["output_config"]["format"]
        self.assertEqual(shape["type"], "json_schema")
        self.assertEqual(shape["schema"]["properties"]["dec"], {"anyOf": [{"type": "string"}, {"type": "null"}]})   # type: [..]는 풀어서
        self.assertEqual(shape["schema"]["properties"]["depth"], {"type": "integer", "enum": [0, 1, 2]})
        self.assertNotIn("effort", request["output_config"])                 # Haiku 4.5는 받지 않는 칸
        for gone in ("thinking", "temperature", "tools", "tool_choice"):
            self.assertNotIn(gone, request)
        self.assertEqual(NULLABLE["properties"]["dec"], {"type": ["string", "null"]})          # 받은 schema는 그대로 둬요
        self.assertEqual(engine.last, {"input_tokens": 1200, "output_tokens": 300, "cost": (1200 * 1.0 + 300 * 5.0) / 1_000_000})
        self.assertEqual(engine.last_usage, {"input_tokens": 1200, "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0,
                                             "output_tokens": 300, "cost": engine.last["cost"], "model": "haiku"})   # 토큰 기록이 읽는 모양
        self.assertEqual((engine.name, engine.model), ("anthropic_api", "haiku"))

    def test_bigger_models_run_at_low_effort_with_a_server_side_fallback(self):
        out, client, _ = self.ask(reply('{"dec": "A안", "depth": 0}'), model="sonnet")
        where, request = client.calls[0]
        self.assertEqual((out["dec"], where, request["model"]), ("A안", "beta", "claude-sonnet-5-5"))
        self.assertEqual((request["betas"], request["fallbacks"]), (["server-side-fallback-2026-07-01"], "default"))
        self.assertEqual(request["output_config"]["effort"], "low")
        self.assertNotIn("thinking", request)                                # 끌 수 없는 모델이에요. 단계만 낮춰요
        _, client, _ = self.ask(reply("{}"), model="claude-opus-4-8")
        self.assertEqual((client.calls[0][0], client.calls[0][1]["output_config"]["effort"]), ("messages", "low"))
        self.assertEqual([anthropic_api.model_id(n) for n in ("haiku", "Sonnet", "opus", "claude-haiku-4-5")],
                         ["claude-haiku-4-5", "claude-sonnet-5-5", "claude-opus-5-5", "claude-haiku-4-5"])
        self.assertEqual([anthropic_api.model_id(n) for n in ("gpt-6-luna", "gemini-3.8-flash")], ["claude-haiku-4-5"] * 2)   # 남의 모델 이름이면 작은 모델로

    def test_a_refusal_a_cut_off_or_prose_fails_only_that_batch(self):
        for answer in (reply("", stop="refusal"), reply('{"dec": nu', stop="max_tokens"), reply("죄송하지만…"), reply("[1, 2]")):
            out, _, _ = self.ask(answer)
            self.assertIsInstance(out, BadOutput)
            self.assertNotIsInstance(out, EngineError)

    def test_api_trouble_becomes_one_line_for_the_window(self):
        cases = [
            (api_error(anthropic.AuthenticationError, 401), "API 키가 맞지 않아요"),
            (api_error(anthropic.PermissionDeniedError, 403), "이 모델을 쓸 수 없어요"),
            (api_error(anthropic.NotFoundError, 404), "모델 이름이 맞지 않아요: claude-haiku-4-5"),
            (api_error(anthropic.RateLimitError, 429), "한도에 걸렸어요"),
            (api_error(anthropic.BadRequestError, 400, "Your credit balance is too low to access the API"), "크레딧이 모자라요"),
            (api_error(anthropic.BadRequestError, 400, "messages: bad shape"), "받아들여지지 않았어요: messages: bad shape"),
            (api_error(anthropic.InternalServerError, 529), "서버가 잠시 답하지 못해요"),
            (anthropic.APIConnectionError(request=httpx2.Request("POST", "https://api.anthropic.com")), "인터넷 연결"),
        ]
        for raised, words in cases:
            out, _, _ = self.ask(raised)
            self.assertIsInstance(out, EngineError, words)
            self.assertIn(words, str(out))
            self.assertNotIn(KEY, str(out))

    def test_without_a_key_it_says_so(self):
        engine = anthropic_api.AnthropicApiEngine(model="haiku")
        with self.assertRaises(EngineError) as caught:
            engine.complete_json("정리해", "{}", NULLABLE)
        self.assertIn("API 키가 없어요", str(caught.exception))
        keys.save(KEY)
        with mock.patch.object(anthropic, "Anthropic") as made:
            anthropic_api.AnthropicApiEngine(model="haiku").client()
        self.assertEqual(made.call_args.kwargs["api_key"], KEY)              # 키체인의 키로

    def test_a_new_key_is_checked_without_spending_money(self):
        def checked(raises=None):
            client = mock.Mock()
            client.models.retrieve.side_effect = raises
            with mock.patch.object(anthropic, "Anthropic", return_value=client) as made:
                return anthropic_api.verify(KEY, "haiku"), client, made
        result, client, made = checked()
        self.assertEqual(result, {"ok": True, "verified": True, "reason": None})
        client.models.retrieve.assert_called_once_with("claude-haiku-4-5")   # 모델 정보만 물어요 (모델은 안 불러요)
        client.messages.create.assert_not_called()
        self.assertEqual((made.call_args.kwargs["api_key"], made.call_args.kwargs["max_retries"]), (KEY, 0))
        result, _, _ = checked(api_error(anthropic.AuthenticationError, 401))
        self.assertEqual((result["ok"], result["verified"]), (False, True))
        self.assertIn("API 키가 맞지 않아요", result["reason"])
        result, _, _ = checked(anthropic.APIConnectionError(request=httpx2.Request("GET", "https://api.anthropic.com")))
        self.assertEqual((result["ok"], result["verified"]), (True, False))  # 인터넷이 안 되면 확인은 못 했지만 넣어는 둬요


class FakeWire:
    """rest.send 흉내. 준 답을 차례로 돌려주고(마지막 답은 되풀이), 받은 요청과 기다린 초를 적어 둬요. 아무 데도 보내지 않아요."""

    def __init__(self, *answers):
        self.answers, self.calls, self.slept = list(answers), [], []

    def send(self, who, method, url, headers, body=None, timeout=120.0):
        self.calls.append({"who": who, "method": method, "url": url, "headers": dict(headers), "body": body, "timeout": timeout})
        answer = self.answers.pop(0) if len(self.answers) > 1 else self.answers[0]
        if isinstance(answer, Exception):
            raise answer
        status, data, *headers = answer
        return status, data, (headers[0] if headers else {})


class WithWire(WithKeychain):
    def wire(self, *answers) -> FakeWire:
        wire = FakeWire(*answers)
        for patch in (mock.patch.object(rest, "send", wire.send), mock.patch.object(rest.time, "sleep", wire.slept.append)):
            patch.start()
            self.addCleanup(patch.stop)
        return wire


class RestTest(WithWire):
    """OpenAI · Gemini를 HTTP로 직접 부르는 길. 잠깐의 문제는 기다렸다 다시 보내고, 기다려도 안 풀릴 것은 바로 돌려줘요."""

    def test_a_busy_answer_is_sent_again_after_the_wait_the_server_asked_for(self):
        wire = self.wire((429, {}, {"retry-after": "3"}), (503, {}), (200, {"ok": True}))
        self.assertEqual(rest.call("OpenAI", "POST", "https://x/y", {}, {"a": 1}), (200, {"ok": True}))
        self.assertEqual((len(wire.calls), wire.slept), (3, [3.0, 1.0]))          # 서버가 말한 3초. 말이 없으면 조금씩 늘려서
        wire = self.wire((500, {"error": {"message": "x"}}))
        self.assertEqual(rest.call("OpenAI", "POST", "https://x/y", {}), (500, {"error": {"message": "x"}}))
        self.assertEqual((len(wire.calls), wire.slept), (1 + rest.RETRIES, [0.5, 1.0]))   # 두 번 더 보내도 안 되면 마지막 답 그대로

    def test_what_waiting_cannot_fix_comes_straight_back(self):
        wire = self.wire((429, {}, {"retry-after": "3600"}), (200, {}))
        self.assertEqual(rest.call("Gemini", "POST", "https://x/y", {})[0], 429)
        self.assertEqual((len(wire.calls), wire.slept), (1, []))                   # 한 시간 기다리라는 답: 붙잡고 있지 않아요
        wire = self.wire((401, {}), (200, {}))
        self.assertEqual((rest.call("Gemini", "GET", "https://x/y", {})[0], len(wire.calls)), (401, 1))   # 틀린 키는 다시 보내도 틀려요
        wire = self.wire((429, {}), (200, {}))
        rest.call("Gemini", "POST", "https://x/y", {}, wait=lambda status, data, headers: float("inf"))
        self.assertEqual(len(wire.calls), 1)

    def test_a_dropped_line_is_tried_again_but_a_slow_answer_is_not(self):
        wire = self.wire(rest.Unreachable("닿지 못했어요"), (200, {"ok": True}))
        self.assertEqual(rest.call("OpenAI", "POST", "https://x/y", {}), (200, {"ok": True}))
        wire = self.wire(rest.Unreachable("닿지 못했어요"))
        with self.assertRaises(rest.Unreachable):
            rest.call("OpenAI", "POST", "https://x/y", {})
        self.assertEqual(len(wire.calls), 1 + rest.RETRIES)
        wire = self.wire(rest.TooSlow("늦어요"), (200, {}))
        with self.assertRaises(rest.TooSlow):
            rest.call("OpenAI", "POST", "https://x/y", {})
        self.assertEqual(len(wire.calls), 1)                                       # 같은 요청에 돈이 두 번 나가지 않게

    def test_one_request_goes_out_as_json_and_trouble_on_the_line_gets_a_name(self):
        request = httpx2.Request("POST", "https://x/y")
        fine = httpx2.Response(200, json={"a": 1}, headers={"Retry-After": "2"}, request=request)
        with mock.patch.object(httpx2, "request", return_value=fine) as sent:
            status, data, headers = rest.send("OpenAI", "POST", "https://x/y", {"Authorization": "Bearer k"}, {"q": "한글"}, timeout=7)
        self.assertEqual((status, data, rest.retry_after(headers)), (200, {"a": 1}, 2.0))
        self.assertEqual((sent.call_args.args, sent.call_args.kwargs),
                         (("POST", "https://x/y"), {"headers": {"Authorization": "Bearer k"}, "json": {"q": "한글"}, "timeout": 7}))
        with mock.patch.object(httpx2, "request", return_value=httpx2.Response(502, text="<html>bad gateway</html>", request=request)):
            self.assertEqual(rest.send("OpenAI", "GET", "https://x/y", {})[:2], (502, {}))       # JSON이 아닌 답은 빈 것으로
        for raised, kind, words in ((httpx2.ConnectError("no route"), rest.Unreachable, "OpenAI에 닿지 못했어요"),
                                    (httpx2.ReadTimeout("slow"), rest.TooSlow, "OpenAI가 7초 안에 답하지 않았어요")):
            with mock.patch.object(httpx2, "request", side_effect=raised), self.assertRaises(kind) as caught:
                rest.send("OpenAI", "POST", "https://x/y", {}, {}, timeout=7)
            self.assertIn(words, str(caught.exception))
            self.assertIsInstance(caught.exception, EngineError)                   # 가닥 창에 한 줄로 보이는 말


def openai_reply(text, status="completed", tokens=(1200, 300), cached=0, **more):
    """OpenAI Responses API의 답 모양 (2026-10-08의 공식 문서). 생각한 것(reasoning) 항목이 답 앞에 와요."""
    said = [{"type": "output_text", "text": text, "annotations": [], "logprobs": []}]
    return 200, dict({"id": "resp_1", "object": "response", "status": status, "error": None, "incomplete_details": None,
                      "model": "gpt-6-luna", "store": False,
                      "output": [{"type": "reasoning", "id": "rs_1", "summary": []},
                                 {"type": "message", "id": "msg_1", "role": "assistant", "status": "completed", "content": said}],
                      "usage": {"input_tokens": tokens[0], "input_tokens_details": {"cached_tokens": cached, "cache_write_tokens": 0},
                                "output_tokens": tokens[1], "output_tokens_details": {"reasoning_tokens": 64},
                                "total_tokens": sum(tokens)}}, **more)


def openai_error(status, code=None, message="x", kind="invalid_request_error"):
    return status, {"error": {"message": message, "type": kind, "param": None, "code": code}}


class OpenAiApiTest(WithWire):
    """OpenAI 키 엔진. 실제 OpenAI는 부르지 않아요: 보내는 길(rest.send)을 가짜로 바꿔 끼워요."""

    def ask(self, *answers, model="haiku", schema=NULLABLE, effort=None, key=OPENAI_KEY):
        if key:
            keys.save(key)
        wire = self.wire(*answers)
        engine = openai_api.OpenAiApiEngine(model=model, effort=effort)
        try:
            return engine.complete_json("정리해", '{"turns": []}', schema), wire, engine
        except Exception as exc:
            return exc, wire, engine

    def test_the_smallest_model_is_asked_for_json_in_the_given_shape(self):
        out, wire, engine = self.ask(openai_reply('{"dec": null, "depth": 1}', cached=200))
        self.assertEqual(out, {"dec": None, "depth": 1})
        sent = wire.calls[0]
        self.assertEqual((sent["who"], sent["method"], sent["url"]), ("OpenAI", "POST", "https://api.openai.com/v1/responses"))
        self.assertEqual(sent["headers"]["Authorization"], "Bearer " + OPENAI_KEY)
        body = sent["body"]
        self.assertEqual((body["model"], body["max_output_tokens"], body["store"]), ("gpt-6-luna", 16000, False))   # OpenAI에 보관해 두지 않게
        self.assertEqual(body["input"], [{"role": "system", "content": "정리해"}, {"role": "user", "content": '{"turns": []}'}])
        self.assertEqual(body["text"], {"format": {"type": "json_schema", "name": "gadak", "schema": NULLABLE, "strict": True}})
        self.assertEqual(body["reasoning"], {"effort": "low"})                   # 분류에는 깊은 생각이 필요 없어요
        for gone in ("temperature", "tools", "instructions", "stream"):
            self.assertNotIn(gone, body)
        self.assertEqual(json.loads(json.dumps(body)), body)                     # 그대로 JSON으로 나갈 수 있는 것만
        self.assertEqual(engine.last, {"input_tokens": 1200, "output_tokens": 300, "cost": (1200 * 0.1 + 300 * 0.5) / 1_000_000})
        self.assertEqual(engine.last_usage, {"input_tokens": 1000, "cache_creation_input_tokens": 0, "cache_read_input_tokens": 200,
                                             "output_tokens": 300, "cost": engine.last["cost"], "model": "gpt-6-luna"})   # 토큰 기록이 읽는 모양
        self.assertEqual((engine.name, engine.model), ("openai_api", "haiku"))

    def test_the_model_and_the_depth_of_thought_follow_the_settings(self):
        named = [openai_api.model_id(n) for n in ("haiku", "Sonnet", "opus", "gpt-6.1-sol", "claude-haiku-4-5", "gemini-3.8-flash")]
        self.assertEqual(named, ["gpt-6-luna", "gpt-6.1-sol", "gpt-6-astra", "gpt-6.1-sol", "gpt-6-luna", "gpt-6-luna"])   # 남의 모델 이름이면 작은 모델로
        for model, effort, sent_model, sent_effort in (("sonnet", None, "gpt-6.1-sol", "low"), ("sonnet", "medium", "gpt-6.1-sol", "medium"),
                                                       ("opus", "아주 깊게", "gpt-6-astra", "low")):
            _, wire, _ = self.ask(openai_reply("{}"), model=model, effort=effort)
            self.assertEqual((wire.calls[0]["body"]["model"], wire.calls[0]["body"]["reasoning"]), (sent_model, {"effort": sent_effort}))
        _, wire, _ = self.ask(openai_reply("{}"), model="gpt-4.1-mini")
        self.assertNotIn("reasoning", wire.calls[0]["body"])                     # 생각 단계를 받지 않는 모델에는 보내지 않아요

    def test_a_refusal_a_cut_off_or_prose_fails_only_that_batch(self):
        refused = openai_reply("")
        refused[1]["output"][1]["content"] = [{"type": "refusal", "refusal": "I'm sorry, I cannot assist with that request."}]
        cases = (refused, openai_reply('{"dec": nu', status="incomplete", incomplete_details={"reason": "max_output_tokens"}),
                 openai_reply("", status="incomplete", incomplete_details={"reason": "content_filter"}),
                 openai_reply("죄송하지만…"), openai_reply("[1, 2]"),
                 openai_reply("", status="failed", error={"code": "invalid_prompt", "message": "x"}))
        for answer in cases:
            out, wire, engine = self.ask(answer)
            self.assertIsInstance(out, BadOutput)
            self.assertNotIsInstance(out, EngineError)
            self.assertEqual((len(wire.calls), engine.last_usage["output_tokens"]), (1, 300))      # 쓴 토큰은 적어 둬요

    def test_api_trouble_becomes_one_line_for_the_window(self):
        cases = [
            (openai_error(401, "invalid_api_key", "Incorrect API key provided: sk-proj-****qrst."), "API 키가 맞지 않아요", 1),
            (openai_error(403, "unsupported_country_region_territory", "Country, region, or territory not supported"),
             "이 API 키로는 쓸 수 없어요: Country", 1),
            (openai_error(404, "model_not_found", "The model `gpt-6-luna` does not exist or you do not have access to it."),
             "이 키로 쓸 수 없는 모델이에요: gpt-6-luna", 1),
            (openai_error(429, "rate_limit_exceeded", "Rate limit reached", "rate_limit_error"), "한도에 걸렸어요", 3),
            (openai_error(429, "credit_balance_exhausted", "Your organization has no prepaid credits remaining"), "크레딧이 모자라요", 1),
            (openai_error(429, None, "You exceeded your current quota", "insufficient_quota"), "크레딧이 모자라요", 1),
            (openai_error(400, "invalid_json_schema", "Invalid schema for response_format 'gadak'"), "받아들여지지 않았어요: Invalid schema", 1),
            (openai_error(503, "server_is_overloaded", "overloaded", "service_unavailable_error"), "서버가 잠시 답하지 못해요", 3),
            (rest.Unreachable("OpenAI에 닿지 못했어요. 인터넷 연결을 확인해 주세요."), "인터넷 연결", 3),
            (openai_reply("", status="failed", error={"code": "server_error", "message": "x"}), "답을 만들지 못했어요", 1),
        ]
        for answer, words, sent in cases:
            out, wire, _ = self.ask(answer)
            self.assertIsInstance(out, EngineError, words)
            self.assertIn(words, str(out))
            self.assertNotIn(OPENAI_KEY, str(out))
            self.assertEqual(len(wire.calls), sent, words)                         # 기다리면 풀릴 것만 다시 보내요

    def test_without_an_openai_key_nothing_is_sent(self):
        for key in (None, KEY, GEMINI_NEW_KEY):                                    # 키가 없거나, 다른 회사 키만 있을 때
            keys.delete()
            out, wire, _ = self.ask(openai_reply("{}"), key=key)
            self.assertIsInstance(out, EngineError)
            self.assertIn("API 키가 없어요", str(out))
            self.assertEqual(wire.calls, [])                                       # 남의 회사 키를 OpenAI로 보내지 않아요

    def test_check_looks_at_the_key_and_the_model_only(self):
        keys.save(OPENAI_KEY)
        wire = self.wire((200, {"id": "gpt-6-luna", "object": "model"}))
        self.assertEqual(openai_api.OpenAiApiEngine(model="haiku").check(), {"ok": True, "model": "gpt-6-luna", "key": "keychain"})
        self.assertEqual((wire.calls[0]["method"], wire.calls[0]["url"], wire.calls[0]["body"]),
                         ("GET", "https://api.openai.com/v1/models/gpt-6-luna", None))
        self.wire(openai_error(401, "invalid_api_key"))
        self.assertEqual(openai_api.OpenAiApiEngine(model="haiku").check(), {"ok": False, "reason": "API 키가 맞지 않아요. 키를 다시 넣어 주세요."})

    def test_a_new_key_is_checked_without_spending_money(self):
        wire = self.wire((200, {"id": "gpt-6-luna", "object": "model"}))
        self.assertEqual(openai_api.verify(OPENAI_KEY, "haiku"), {"ok": True, "verified": True, "reason": None})
        sent = wire.calls[0]
        self.assertEqual((sent["method"], sent["url"], sent["body"]), ("GET", "https://api.openai.com/v1/models/gpt-6-luna", None))   # 모델 정보만 물어요
        self.assertEqual((sent["headers"]["Authorization"], len(wire.calls)), ("Bearer " + OPENAI_KEY, 1))
        self.assertEqual(self.keychain.items, {})                                  # 확인만 해요. 넣는 것은 부른 쪽이 해요
        for answer, ok, verified, words in ((openai_error(401, "invalid_api_key"), False, True, "API 키가 맞지 않아요"),
                                            (openai_error(403, None, "Missing scopes: api.model.read"), False, True, "쓸 수 없어요: Missing scopes"),
                                            (openai_error(404, "model_not_found"), True, False, "이 키로 쓸 수 없는 모델이에요"),
                                            (openai_error(500), True, False, "서버가 잠시"),
                                            (rest.Unreachable("OpenAI에 닿지 못했어요. 인터넷 연결을 확인해 주세요."), True, False, "닿지 못했어요")):
            wire = self.wire(answer)
            result = openai_api.verify(OPENAI_KEY)
            self.assertEqual((result["ok"], result["verified"], len(wire.calls)), (ok, verified, 1), words)   # 한 번만 물어요
            self.assertIn(words, result["reason"])


def gemini_reply(text, finish="STOP", tokens=(1200, 300), thoughts=0, cached=0):
    """Gemini generateContent의 답 모양 (2026-10-08의 공식 문서)."""
    return 200, {"candidates": [{"content": {"role": "model", "parts": [{"text": text}]}, "finishReason": finish, "index": 0}],
                 "usageMetadata": {"promptTokenCount": tokens[0], "cachedContentTokenCount": cached, "candidatesTokenCount": tokens[1],
                                   "thoughtsTokenCount": thoughts, "totalTokenCount": sum(tokens) + thoughts},
                 "modelVersion": "gemini-3.5-flash-lite"}


def gemini_error(status, state, message="x", *details):
    return status, {"error": {"code": status, "message": message, "status": state, "details": list(details)}}


# 틀린 키에 실제 서버가 한 답 그대로 (2026-10-08). 401이 아니라 400이에요
GEMINI_BAD_KEY = gemini_error(400, "INVALID_ARGUMENT", "API key not valid. Please pass a valid API key.",
                              {"@type": "type.googleapis.com/google.rpc.ErrorInfo", "reason": "API_KEY_INVALID", "domain": "googleapis.com",
                               "metadata": {"service": "generativelanguage.googleapis.com"}})


def gemini_limit(per, wait):
    return gemini_error(429, "RESOURCE_EXHAUSTED", "You exceeded your current quota, please check your plan and billing details.",
                        {"@type": "type.googleapis.com/google.rpc.QuotaFailure",
                         "violations": [{"quotaId": f"GenerateRequestsPer{per}PerProjectPerModel-FreeTier", "quotaValue": "15"}]},
                        {"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": wait})


class GeminiApiTest(WithWire):
    """Gemini 키 엔진. 실제 Gemini는 부르지 않아요: 보내는 길(rest.send)을 가짜로 바꿔 끼워요."""

    def ask(self, *answers, model="haiku", schema=NULLABLE, effort=None, key=GEMINI_NEW_KEY):
        if key:
            keys.save(key)
        wire = self.wire(*answers)
        engine = gemini_api.GeminiApiEngine(model=model, effort=effort)
        try:
            return engine.complete_json("정리해", '{"turns": []}', schema), wire, engine
        except Exception as exc:
            return exc, wire, engine

    def test_the_smallest_model_is_asked_for_json_in_the_given_shape(self):
        out, wire, engine = self.ask(gemini_reply('{"dec": null, "depth": 1}', thoughts=40, cached=200))
        self.assertEqual(out, {"dec": None, "depth": 1})
        sent = wire.calls[0]
        self.assertEqual((sent["who"], sent["method"]), ("Gemini", "POST"))
        self.assertEqual(sent["url"], "https://generativelanguage.googleapis.com/v1beta/models/gemini-3.5-flash-lite:generateContent")
        self.assertEqual(sent["headers"]["x-goog-api-key"], GEMINI_NEW_KEY)
        self.assertNotIn(GEMINI_NEW_KEY, sent["url"])                              # 키는 주소에 싣지 않아요
        body = sent["body"]
        self.assertEqual(sorted(body), ["contents", "generationConfig", "systemInstruction"])
        self.assertEqual(body["systemInstruction"], {"parts": [{"text": "정리해"}]})
        self.assertEqual(body["contents"], [{"role": "user", "parts": [{"text": '{"turns": []}'}]}])
        # mimeType은 이 이름이어야 서버가 받아요. Flash-Lite는 처음부터 가장 낮게 생각해서 생각 단계를 보내지 않아요
        self.assertEqual(body["generationConfig"], {"maxOutputTokens": 16000,
                                                    "responseFormat": {"text": {"mimeType": "APPLICATION_JSON", "schema": NULLABLE}}})
        self.assertEqual(json.loads(json.dumps(body)), body)
        self.assertEqual(engine.last, {"input_tokens": 1200, "output_tokens": 340, "cost": (1200 * 0.3 + 340 * 2.5) / 1_000_000})   # 생각에 쓴 것도 출력 값
        self.assertEqual(engine.last_usage, {"input_tokens": 1000, "cache_creation_input_tokens": 0, "cache_read_input_tokens": 200,
                                             "output_tokens": 340, "cost": engine.last["cost"], "model": "gemini-3.5-flash-lite"})
        self.assertEqual((engine.name, engine.model), ("gemini_api", "haiku"))

    def test_both_shapes_of_gemini_key_go_in_the_same_header(self):
        for key in (GEMINI_KEY, GEMINI_NEW_KEY):
            out, wire, _ = self.ask(gemini_reply("{}"), key=key)
            self.assertEqual((out, wire.calls[0]["headers"]["x-goog-api-key"]), ({}, key))

    def test_the_model_and_the_depth_of_thought_follow_the_settings(self):
        named = [gemini_api.model_id(n) for n in ("haiku", "Sonnet", "opus", "gemini-3.6-flash", "claude-haiku-4-5", "gpt-6-luna")]
        self.assertEqual(named, ["gemini-3.5-flash-lite", "gemini-3.8-flash", "gemini-3.1-pro-preview", "gemini-3.6-flash",
                                 "gemini-3.5-flash-lite", "gemini-3.5-flash-lite"])           # 남의 모델 이름이면 작은 모델로
        for model, effort, level in (("sonnet", None, "LOW"), ("sonnet", "medium", "MEDIUM"), ("opus", "아주 깊게", "LOW"), ("haiku", "high", "HIGH")):
            _, wire, _ = self.ask(gemini_reply("{}"), model=model, effort=effort)
            self.assertEqual(wire.calls[0]["body"]["generationConfig"]["thinkingConfig"], {"thinkingLevel": level}, (model, effort))
        self.assertIn("/models/gemini-3.8-flash:generateContent", self.ask(gemini_reply("{}"), model="sonnet")[1].calls[0]["url"])
        _, wire, _ = self.ask(gemini_reply("{}"), model="gemini-2.5-flash")
        self.assertNotIn("thinkingConfig", wire.calls[0]["body"]["generationConfig"])        # 생각 단계는 Gemini 3부터 받아요

    def test_a_block_a_cut_off_or_prose_fails_only_that_batch(self):
        thought = gemini_reply('{"dec": null, "depth": 0}')
        thought[1]["candidates"][0]["content"]["parts"].insert(0, {"text": "먼저 턴을 훑어보면…", "thought": True})
        self.assertEqual(self.ask(thought)[0], {"dec": None, "depth": 0})                    # 생각을 간추린 조각은 답이 아니에요
        blocked = (200, {"promptFeedback": {"blockReason": "PROHIBITED_CONTENT"}, "usageMetadata": {"promptTokenCount": 1200, "totalTokenCount": 1200}})
        stopped = gemini_reply("", finish="SAFETY")
        del stopped[1]["candidates"][0]["content"]
        for answer in (blocked, stopped, gemini_reply('{"dec": nu', finish="MAX_TOKENS"), gemini_reply("죄송하지만…"), gemini_reply("[1, 2]"), (200, {})):
            out, wire, _ = self.ask(answer)
            self.assertIsInstance(out, BadOutput)
            self.assertNotIsInstance(out, EngineError)
            self.assertEqual(len(wire.calls), 1)

    def test_api_trouble_becomes_one_line_for_the_window(self):
        cases = [
            (GEMINI_BAD_KEY, "API 키가 맞지 않아요", 1, []),
            (gemini_error(401, "UNAUTHENTICATED", "Request had invalid authentication credentials."), "API 키가 맞지 않아요", 1, []),
            (gemini_error(400, "INVALID_ARGUMENT", "API key expired. Please renew the API key."), "API 키가 맞지 않아요", 1, []),
            (gemini_error(403, "PERMISSION_DENIED", "Your API key was reported as leaked."), "이 API 키로는 쓸 수 없어요: Your API key was reported", 1, []),
            (gemini_error(404, "NOT_FOUND", "models/gemini-3.5-flash-lite is not found"), "이 키로 쓸 수 없는 모델이에요: gemini-3.5-flash-lite", 1, []),
            (gemini_limit("Minute", "7s"), "한도에 걸렸어요", 3, [7.0, 7.0]),                # 분 한도: 서버가 말한 만큼 기다렸다 다시
            (gemini_limit("Day", "41s"), "하루 사용 한도를 다 썼어요", 1, []),               # 하루 한도: 기다려도 안 풀려요
            (gemini_error(503, "UNAVAILABLE", "The model is overloaded."), "서버가 잠시 답하지 못해요", 3, [0.5, 1.0]),
            (gemini_error(400, "FAILED_PRECONDITION", "User location is not supported for the API use."), "받아들여지지 않았어요: User location", 1, []),
            (rest.Unreachable("Gemini에 닿지 못했어요. 인터넷 연결을 확인해 주세요."), "인터넷 연결", 3, [0.5, 1.0]),
        ]
        for answer, words, sent, waited in cases:
            out, wire, _ = self.ask(answer)
            self.assertIsInstance(out, EngineError, words)
            self.assertIn(words, str(out))
            self.assertNotIn(GEMINI_NEW_KEY, str(out))
            self.assertEqual((len(wire.calls), wire.slept), (sent, waited), words)

    def test_without_a_gemini_key_nothing_is_sent(self):
        for key in (None, KEY, OPENAI_KEY):                                        # 키가 없거나, 다른 회사 키만 있을 때
            keys.delete()
            out, wire, _ = self.ask(gemini_reply("{}"), key=key)
            self.assertIsInstance(out, EngineError)
            self.assertIn("API 키가 없어요", str(out))
            self.assertEqual(wire.calls, [])                                       # 남의 회사 키를 Google로 보내지 않아요

    def test_check_looks_at_the_key_and_the_model_only(self):
        keys.save(GEMINI_KEY)
        wire = self.wire((200, {"name": "models/gemini-3.5-flash-lite", "displayName": "Gemini 3.5 Flash-Lite"}))
        self.assertEqual(gemini_api.GeminiApiEngine(model="haiku").check(), {"ok": True, "model": "gemini-3.5-flash-lite", "key": "keychain"})
        self.assertEqual((wire.calls[0]["method"], wire.calls[0]["url"], wire.calls[0]["body"]),
                         ("GET", "https://generativelanguage.googleapis.com/v1beta/models/gemini-3.5-flash-lite", None))
        self.wire(GEMINI_BAD_KEY)
        self.assertEqual(gemini_api.GeminiApiEngine(model="haiku").check(), {"ok": False, "reason": "API 키가 맞지 않아요. 키를 다시 넣어 주세요."})

    def test_a_new_key_is_checked_without_spending_money(self):
        wire = self.wire((200, {"name": "models/gemini-3.5-flash-lite"}))
        self.assertEqual(gemini_api.verify(GEMINI_NEW_KEY, "haiku"), {"ok": True, "verified": True, "reason": None})
        sent = wire.calls[0]
        self.assertEqual((sent["method"], sent["url"], sent["body"]),
                         ("GET", "https://generativelanguage.googleapis.com/v1beta/models/gemini-3.5-flash-lite", None))   # 모델 정보만 물어요
        self.assertEqual((sent["headers"]["x-goog-api-key"], len(wire.calls)), (GEMINI_NEW_KEY, 1))
        self.assertEqual(self.keychain.items, {})
        for answer, ok, verified, words in ((GEMINI_BAD_KEY, False, True, "API 키가 맞지 않아요"),
                                            (gemini_error(401, "UNAUTHENTICATED", "Request had invalid authentication credentials."), False, True, "API 키가 맞지 않아요"),
                                            (gemini_error(403, "PERMISSION_DENIED", "Requests from unrestricted keys are blocked."), False, True, "쓸 수 없어요: Requests"),
                                            (gemini_error(404, "NOT_FOUND"), True, False, "이 키로 쓸 수 없는 모델이에요"),
                                            (gemini_error(503, "UNAVAILABLE"), True, False, "서버가 잠시"),
                                            (rest.Unreachable("Gemini에 닿지 못했어요. 인터넷 연결을 확인해 주세요."), True, False, "닿지 못했어요")):
            wire = self.wire(answer)
            result = gemini_api.verify(GEMINI_NEW_KEY)
            self.assertEqual((result["ok"], result["verified"], len(wire.calls)), (ok, verified, 1), words)   # 한 번만 물어요
            self.assertIn(words, result["reason"])


class ChoosingTest(WithKeychain):
    def setUp(self):
        super().setUp()
        self.codex = False                 # Codex에 로그인돼 있는 Mac인지 (실제 Codex는 묻지 않아요)
        patch = mock.patch.object(engines, "codex_ready", lambda: self.codex)
        patch.start()
        self.addCleanup(patch.stop)
        self.addCleanup(engines.prefer, None)

    def test_a_chatgpt_subscription_is_used_when_nothing_else_is_there(self):
        def resolved(cli, logged_in=True):
            with mock.patch.object(engines, "cli_found", lambda: cli), mock.patch.object(engines, "cli_logged_in", lambda: logged_in), \
                    mock.patch.object(config, "ENGINE", "auto"):
                return engines.resolve_name()
        self.codex = True
        self.assertEqual((resolved(False), resolved(True), resolved(True, logged_in=False)), ("codex_cli", "claude_cli", "codex_cli"))
        keys.save(KEY)                                                         # 키가 있으면 키가 먼저예요
        self.assertEqual((resolved(False), resolved(True, logged_in=False)), ("anthropic_api", "anthropic_api"))
        with mock.patch.object(engines, "cli_found", lambda: False), mock.patch.object(codex_cli, "find_bin", lambda: "/x/codex"):
            self.assertIsInstance(engines.get_engine("codex_cli"), codex_cli.CodexCliEngine)

    def test_what_the_user_chose_comes_before_the_setting(self):
        with mock.patch.object(engines, "cli_found", lambda: True), mock.patch.object(config, "ENGINE", "auto"):
            engines.prefer("codex_cli")
            self.assertEqual((engines.preferred(), engines.resolve_name()), ("codex_cli", "codex_cli"))
            self.assertEqual(engines.resolve_name("none"), "none")             # 이름을 직접 주면 그 이름
            for nothing in ("auto", None, "", "없는-엔진"):
                engines.prefer(nothing)
                self.assertEqual((engines.preferred(), engines.resolve_name()), (None, "claude_cli"), nothing)

    def test_auto_prefers_the_subscription_then_a_key_then_nothing(self):
        def resolved(cli, engine="auto"):
            with mock.patch.object(engines, "cli_found", lambda: cli), mock.patch.object(config, "ENGINE", engine):
                return engines.resolve_name()
        self.assertEqual((resolved(True), resolved(False)), ("claude_cli", "none"))
        keys.save(KEY)
        with mock.patch.object(engines, "cli_logged_in", lambda: True):
            self.assertEqual((resolved(True), resolved(False)), ("claude_cli", "anthropic_api"))
        with mock.patch.object(engines, "cli_logged_in", lambda: False):       # 깔려만 있고 로그인이 안 됐으면 키를 써요
            self.assertEqual(resolved(True), "anthropic_api")
        self.assertEqual((resolved(True, "anthropic_api"), resolved(False, "none")), ("anthropic_api", "none"))
        with mock.patch.object(engines, "cli_found", lambda: False):
            self.assertIsInstance(engines.get_engine(), anthropic_api.AnthropicApiEngine)

    def test_whose_key_it_is_decides_which_api_engine_runs(self):
        def resolved(name=None, cli=False):
            with mock.patch.object(engines, "cli_found", lambda: cli), mock.patch.object(engines, "cli_logged_in", lambda: False), \
                    mock.patch.object(config, "ENGINE", "auto"):
                return engines.resolve_name(name)
        for key, name, kind in ((OPENAI_KEY, "openai_api", openai_api.OpenAiApiEngine), (GEMINI_KEY, "gemini_api", gemini_api.GeminiApiEngine),
                                (GEMINI_NEW_KEY, "gemini_api", gemini_api.GeminiApiEngine), (KEY, "anthropic_api", anthropic_api.AnthropicApiEngine)):
            keys.save(key)
            self.assertEqual((resolved(), resolved(cli=True)), (name, name))             # 알아서 고를 때
            self.assertEqual({resolved(asked) for asked in engines.API_NAMES}, {name})    # API 키 엔진은 어느 이름으로 골라 뒀어도 그 키의 회사로
            with mock.patch.object(engines, "cli_found", lambda: False), mock.patch.object(config, "ENGINE", "auto"):
                self.assertIsInstance(engines.get_engine(), kind)
        self.codex = True
        self.assertEqual(resolved(), "anthropic_api")                                     # 넣어 둔 키가 ChatGPT 구독보다 먼저인 것은 그대로
        keys.delete()
        self.assertEqual((resolved(), resolved("openai_api")), ("codex_cli", "openai_api"))   # 키가 없으면 고른 이름 그대로 (부를 때 키를 넣으라고 해요)
        self.assertLessEqual(set(engines.API_NAMES), set(engines.CHOICES))


class EngineRoutesTest(WithKeychain):
    def setUp(self):
        super().setUp()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.ready = {"claude_cli": False, "codex_cli": False}      # 깔려 있고 로그인된 구독 엔진 (실제 명령은 묻지 않아요)
        for patch in (mock.patch.object(engines, "cli_found", lambda: self.ready["claude_cli"]), mock.patch.object(config, "ENGINE", "auto"),
                      mock.patch.object(engines, "cli_logged_in", lambda remember=0: self.ready["claude_cli"]),
                      mock.patch.object(engines, "codex_found", lambda: self.ready["codex_cli"]),
                      mock.patch.object(engines, "codex_logged_in", lambda remember=0: self.ready["codex_cli"]),
                      mock.patch.object(config, "ENGINE_MODEL", "haiku")):
            patch.start()
            self.addCleanup(patch.stop)
        self.addCleanup(engines.prefer, None)
        self.addCleanup(connect.cancel)
        connect.cancel()
        self.db = Path(self.tmp.name) / "gadak.db"
        app = create_app(db_path=self.db, engine="auto")
        self.rt, self.client = app.config["GADAK"], app.test_client()

    def post(self, key, verdict=None, api=anthropic_api):
        verdict = verdict or {"ok": True, "verified": True, "reason": None}
        with mock.patch.object(api, "verify", return_value=verdict) as verify:
            response = self.client.post("/engine/key", json={"key": key})
        return response, verify

    def test_with_no_engine_the_screen_is_told_what_is_needed(self):
        state = self.client.get("/engine").get_json()
        self.assertEqual(state.pop("job")["state"], "idle")
        self.assertEqual(state, {
            "configured": "auto", "resolved": "none", "model": "haiku", "cli": False, "need": "engine", "error": None, "paused": False,
            "choice": "auto", "key": {"stored": False, "source": None, "hint": "", "can_store": True, "company": None},
            # ‘AI 연결’ 창이 그리는 것: 엔진마다 깔려 있는지 · 바로 쓸 수 있는지
            "options": [{"name": "claude_cli", "found": False, "ready": False, "plan": None},
                        {"name": "codex_cli", "found": False, "ready": False},
                        {"name": "anthropic_api", "found": True, "ready": False, "hint": "", "source": None, "company": None}]})

    def test_the_engine_the_user_picks_is_used_and_remembered(self):
        self.ready.update(claude_cli=True, codex_cli=True)
        self.assertEqual(self.client.get("/engine").get_json()["resolved"], "claude_cli")     # 고르기 전: 알아서
        before = self.client.get("/status").get_json()["rev"]
        picked = self.client.post("/engine/choose", json={"name": "codex_cli"}).get_json()
        self.assertEqual((picked["ok"], picked["engine"]["choice"], picked["engine"]["resolved"]), (True, "codex_cli", "codex_cli"))
        self.assertGreater(self.client.get("/status").get_json()["rev"], before)
        engines.prefer(None)                                                                  # 가닥을 껐다 켜도 기억해요
        again = create_app(db_path=self.db, engine="auto").test_client().get("/engine").get_json()
        self.assertEqual((again["choice"], again["resolved"]), ("codex_cli", "codex_cli"))
        back = self.client.post("/engine/choose", json={"name": "auto"}).get_json()["engine"]
        self.assertEqual((back["choice"], back["resolved"]), ("auto", "claude_cli"))
        self.assertEqual(self.client.post("/engine/choose", json={"name": "gpt"}).status_code, 400)
        self.assertEqual(self.client.post("/engine/choose", data="name=none").status_code, 415)   # 다른 사이트가 폼으로 못 바꾸게

    def test_one_press_connects_a_subscription_and_then_uses_it(self):
        steps = []
        def install():
            steps.append("install")
            self.ready["codex_cli"] = "installed"
        def login(name):
            steps.append("login " + name)
            self.ready["codex_cli"] = True
        with mock.patch.object(connect, "_find", lambda name: "/x/codex" if self.ready[name] else None), \
                mock.patch.object(connect, "_logged_in", lambda name: self.ready[name] is True), \
                mock.patch.object(connect, "_install_codex", install), mock.patch.object(connect, "_login", login):
            started = self.client.post("/engine/connect", json={"name": "codex_cli"})
            self.assertEqual((started.status_code, started.get_json()["ok"]), (200, True))
            for _ in range(100):
                job = self.client.get("/engine?fresh=1").get_json()["job"]
                if job["state"] != "running":
                    break
                time.sleep(0.02)
        self.assertEqual((steps, job["state"], job["name"]), (["install", "login codex_cli"], "done", "codex_cli"))
        state = self.client.get("/engine").get_json()
        self.assertEqual((state["choice"], state["resolved"]), ("codex_cli", "codex_cli"))      # 다 되면 그 엔진을 골라요
        self.assertEqual(self.client.post("/engine/connect", json={"name": "anthropic_api"}).status_code, 409)
        cleared = self.client.post("/engine/cancel", json={}).get_json()
        self.assertEqual((cleared["ok"], cleared["engine"]["job"]["state"]), (True, "idle"))    # 끝난 결과를 치워요

    def test_a_good_key_goes_to_the_keychain_and_the_engine_starts(self):
        self.client.get("/engine")                                       # 엔진 없음으로 굳어 있던 상태에서
        self.rt.classifier.pause()
        before = self.client.get("/status").get_json()["rev"]
        response, verify = self.post("  " + KEY + "\n")
        self.assertEqual(response.status_code, 200)
        verify.assert_called_once_with(KEY, None)
        body = response.get_json()
        self.assertEqual((body["ok"], body["verified"]), (True, True))
        self.assertEqual((body["engine"]["resolved"], body["engine"]["need"], body["engine"]["paused"]), ("anthropic_api", None, False))
        self.assertEqual(body["engine"]["key"], {"stored": True, "source": "keychain", "hint": "sk-ant-…wxyz", "can_store": True,
                                                 "company": "Anthropic"})
        self.assertNotIn(KEY[:-4], response.get_data(as_text=True))       # 키는 돌려보내지 않아요
        self.assertEqual(self.keychain.items[("local.gadak.test", keys.ACCOUNT)], KEY)
        self.assertIsInstance(self.rt.classifier.engine(), anthropic_api.AnthropicApiEngine)
        self.assertGreater(self.client.get("/status").get_json()["rev"], before)
        self.assertEqual(self.client.get("/health").get_json()["engine"], {"configured": "auto", "resolved": "anthropic_api"})

        gone = self.client.delete("/engine/key").get_json()
        self.assertEqual((gone["removed"], gone["engine"]["resolved"], gone["engine"]["need"]), (True, "none", "engine"))
        self.assertEqual(self.keychain.items, {})

    def test_a_wrong_key_is_not_kept_and_the_reason_is_one_line(self):
        for key in ("", "hello", None, 42):
            response, verify = self.post(key)
            self.assertEqual(response.status_code, 400)
            self.assertIn("API 키 모양이 아니에요", response.get_json()["reason"])
            verify.assert_not_called()                                   # 모양이 아니면 물어보지도 않아요
        response, _ = self.post(KEY, {"ok": False, "verified": True, "reason": "API 키가 맞지 않아요. 키를 다시 넣어 주세요."})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json()["reason"], "API 키가 맞지 않아요. 키를 다시 넣어 주세요.")
        self.assertEqual((self.keychain.items, response.get_json()["engine"]["resolved"]), ({}, "none"))
        self.assertEqual(self.client.post("/engine/key", data="key=" + KEY).status_code, 415)   # 다른 사이트가 폼으로 못 보내게

    def test_unchecked_keys_are_kept_when_the_network_is_down(self):
        response, _ = self.post(KEY, {"ok": True, "verified": False, "reason": "Anthropic에 닿지 못했어요. 인터넷 연결을 확인해 주세요."})
        self.assertEqual((response.status_code, response.get_json()["verified"]), (200, False))
        self.assertIn(("local.gadak.test", keys.ACCOUNT), self.keychain.items)

    def test_a_key_from_another_company_is_checked_there_and_used(self):
        for key, api, name, company, hint in ((OPENAI_KEY, openai_api, "openai_api", "OpenAI", "sk-…qrst"),
                                              (GEMINI_NEW_KEY, gemini_api, "gemini_api", "Gemini", "AQ.…mnop")):
            with mock.patch.object(anthropic_api, "verify") as elsewhere:
                response, verify = self.post(key, api=api)
            verify.assert_called_once_with(key, None)
            elsewhere.assert_not_called()                                # 그 키의 회사에만 물어요
            engine = response.get_json()["engine"]
            self.assertEqual((response.status_code, engine["resolved"], engine["need"]), (200, name, None))
            self.assertEqual(engine["key"], {"stored": True, "source": "keychain", "hint": hint, "can_store": True, "company": company})
            self.assertEqual(engine["options"][2], {"name": name, "found": True, "ready": True, "hint": hint, "source": "keychain",
                                                    "company": company})   # ‘AI 연결’의 API 키 칸은 하나예요
            self.assertEqual(self.keychain.items, {("local.gadak.test", keys.ACCOUNT): key})     # 넣어 두는 키도 하나예요
            self.assertEqual(self.rt.classifier.engine().name, name)
            self.assertNotIn(key[:-4], response.get_data(as_text=True))
        picked = self.client.post("/engine/choose", json={"name": "anthropic_api"}).get_json()["engine"]
        self.assertEqual((picked["choice"], picked["resolved"]), ("anthropic_api", "gemini_api"))   # 예전에 골라 둔 이름이어도 지금 키의 회사로
        response, verify = self.post(OPENAI_KEY, {"ok": False, "verified": True, "reason": "API 키가 맞지 않아요. 키를 다시 넣어 주세요."}, api=openai_api)
        self.assertEqual((response.status_code, self.keychain.items), (400, {("local.gadak.test", keys.ACCOUNT): GEMINI_NEW_KEY}))   # 틀린 키는 있던 키를 밀어내지 않아요

    def test_a_key_that_stops_working_shows_as_one_line_in_the_status(self):
        keys.save(KEY)
        client = FakeClient(api_error(anthropic.AuthenticationError, 401))
        with mock.patch.object(anthropic_api.AnthropicApiEngine, "client", lambda self: client):
            conn = self.rt.connect()
            self.addCleanup(conn.close)
            self.client.post("/turns", json={"project": "환율 알리미", "chat": {"id": "c1", "site": "claude"},
                                             "turn": {"messageRef": "m1", "user": "임계값은 얼마가 좋아?", "ai": "1,380원이 무난해요."}})
            self.assertTrue(self.rt.classifier.step(conn))
        status = self.client.get("/status").get_json()["classify"]
        self.assertEqual((status["engine"], status["paused"], status["error"]), ("anthropic_api", True, "API 키가 맞지 않아요. 키를 다시 넣어 주세요."))
        self.assertEqual(self.client.get("/engine").get_json()["error"], "API 키가 맞지 않아요. 키를 다시 넣어 주세요.")


class ConnectTest(unittest.TestCase):
    """한 번 눌러 연결하기. 실제로 받거나 로그인 창을 띄우지 않아요: 그 걸음들을 가짜로 바꿔 끼워요."""

    def setUp(self):
        self.addCleanup(connect.cancel)
        self.state = {"found": False, "logged_in": False}
        self.steps, self.done = [], []
        for patch in (mock.patch.object(connect, "_find", lambda name: "/x/bin" if self.state["found"] else None),
                      mock.patch.object(connect, "_logged_in", lambda name: self.state["logged_in"])):
            patch.start()
            self.addCleanup(patch.stop)

    def run_job(self, name="claude_cli", install=None, login=None):
        def installed():
            self.steps.append("install")
            self.state["found"] = True
        def logged(which):
            self.steps.append("login")
            self.state["logged_in"] = True
        with mock.patch.object(connect, "_install_claude", install or installed), mock.patch.object(connect, "_install_codex", install or installed), \
                mock.patch.object(connect, "_login", login or logged):
            started = connect.start(name, self.done.append)
            for _ in range(200):
                if connect.status()["state"] != "running":
                    break
                time.sleep(0.01)
        return started, connect.status()

    def test_what_is_missing_is_fetched_and_then_the_login_window_opens(self):
        started, job = self.run_job()
        self.assertEqual((started, self.steps, self.done), ({"ok": True}, ["install", "login"], ["claude_cli"]))
        self.assertEqual((job["state"], job["message"]), ("done", "연결했어요."))
        self.steps.clear()
        self.state.update(found=True, logged_in=False)            # 깔려 있으면 로그인만
        self.assertEqual((self.run_job("codex_cli")[1]["state"], self.steps), ("done", ["login"]))
        self.steps.clear()                                         # 다 돼 있으면 고르기만
        self.assertEqual((self.run_job()[1]["state"], self.steps, self.done[-1]), ("done", [], "claude_cli"))

    def test_trouble_is_one_line_for_the_window_and_nothing_is_chosen(self):
        def broken():
            raise connect.Problem("Claude Code 설치 파일를 받지 못했어요. 인터넷을 확인하고 다시 눌러 주세요.")
        _, job = self.run_job(install=broken)
        self.assertEqual((job["state"], self.done), ("failed", []))
        self.assertIn("인터넷을 확인", job["message"])
        _, job = self.run_job(login=lambda name: None)             # 로그인 창을 닫아 버렸어요: 받기는 됐지만 고르지 않아요
        self.assertEqual((job["state"], self.done, self.state["found"]), ("failed", [], True))
        self.assertIn("로그인이 끝나지 않았어요", job["message"])
        def odd(name):
            raise ValueError("예상하지 못한 것")
        self.state.update(found=True, logged_in=False)
        _, job = self.run_job(login=odd)
        self.assertEqual(job["state"], "failed")
        self.assertIn("연결하지 못했어요", job["message"])

    def test_only_subscriptions_connect_this_way_and_one_at_a_time(self):
        self.assertEqual(connect.start("anthropic_api")["ok"], False)
        gate = threading.Event()
        def slow():
            gate.wait(2)
            self.state["found"] = True
        with mock.patch.object(connect, "_install_claude", slow), mock.patch.object(connect, "_login", lambda name: None):
            self.assertEqual(connect.start("claude_cli"), {"ok": True})
            second = connect.start("codex_cli")
            self.assertEqual(second["ok"], False)
            self.assertIn("연결하는 중", second["reason"])
            self.assertEqual(connect.status()["step"], "install")
            gate.set()
            for _ in range(200):                       # 뒤에서 돌던 것이 끝난 뒤에 가짜를 걷어요 (다음 테스트로 새지 않게)
                if connect.status()["state"] != "running":
                    break
                time.sleep(0.01)

    def test_downloads_come_only_over_https_from_the_makers(self):
        self.assertTrue(connect.CLAUDE_INSTALLER.startswith("https://claude.ai/"))
        self.assertTrue(connect.CODEX_RELEASE.startswith("https://github.com/openai/codex/releases/"))
        with self.assertRaises(connect.Problem):
            connect._fetch("http://example.com/x", "/tmp/x", "파일")


if __name__ == "__main__":
    unittest.main()
