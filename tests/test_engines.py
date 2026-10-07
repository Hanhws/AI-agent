"""엔진(가닥이 판단에 쓰는 LLM)을 부르는 쪽. 실제 모델도, 실제 키체인도 건드리지 않아요: 명령 · SDK를 가짜로 바꿔 끼워요."""
import json
import re
import subprocess
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

import anthropic
import httpx2

from backend import config, engines
from backend.app import create_app
from backend.engines import BadOutput, EngineError, anthropic_api, claude_cli, keys

KEY = "sk-ant-api03-" + "Ab1_" * 8 + "wxyz"

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
        keys.os.environ.pop(keys.ENV, None)
        self.addCleanup(keys._seen.update, at=0.0, service=None, key=None)


class KeysTest(WithKeychain):
    def test_a_key_is_kept_in_the_keychain_and_never_on_a_command_line(self):
        self.assertEqual((keys.find(), keys.describe()["stored"]), ((None, None), False))
        keys.save(KEY)
        self.assertEqual(self.keychain.items, {("local.gadak.test", keys.ACCOUNT): KEY})
        for argv, _stdin in self.keychain.calls:
            self.assertNotIn(KEY, " ".join(argv))                      # 프로세스 목록에 보이지 않게 표준 입력으로만
        self.assertEqual(keys.find(), (KEY, "keychain"))
        self.assertEqual(keys.describe(), {"stored": True, "source": "keychain", "hint": "sk-ant-…wxyz", "can_store": True})
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


class ChoosingTest(WithKeychain):
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


class EngineRoutesTest(WithKeychain):
    def setUp(self):
        super().setUp()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        for patch in (mock.patch.object(engines, "cli_found", lambda: False), mock.patch.object(config, "ENGINE", "auto"),
                      mock.patch.object(config, "ENGINE_MODEL", "haiku")):
            patch.start()
            self.addCleanup(patch.stop)
        app = create_app(db_path=Path(self.tmp.name) / "gadak.db", engine="auto")
        self.rt, self.client = app.config["GADAK"], app.test_client()

    def post(self, key, verdict=None):
        verdict = verdict or {"ok": True, "verified": True, "reason": None}
        with mock.patch.object(anthropic_api, "verify", return_value=verdict) as verify:
            response = self.client.post("/engine/key", json={"key": key})
        return response, verify

    def test_with_no_engine_the_screen_is_told_what_is_needed(self):
        state = self.client.get("/engine").get_json()
        self.assertEqual(state, {
            "configured": "auto", "resolved": "none", "model": "haiku", "cli": False, "need": "engine", "error": None, "paused": False,
            "key": {"stored": False, "source": None, "hint": "", "can_store": True}})

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
        self.assertEqual(body["engine"]["key"], {"stored": True, "source": "keychain", "hint": "sk-ant-…wxyz", "can_store": True})
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
            self.assertIn("sk-ant-로 시작하는", response.get_json()["reason"])
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


if __name__ == "__main__":
    unittest.main()
