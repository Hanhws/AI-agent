"""Anthropic API 키로 부르는 엔진.

Claude Code(구독)가 없는 사람은 자기 API 키를 넣어 써요. 키는 macOS 키체인에 있어요(keys.py).
넣은 키가 OpenAI · Gemini 것이면 이 엔진 대신 openai_api · gemini_api가 불려요.
구독 엔진(claude_cli)과 같은 모양으로 불려요: complete_json(system, prompt, schema) → dict.
부를 때마다 그 사람의 키로 돈이 나가요. Haiku 4.5로 턴 8개를 한 번에 물으면 한 번에 1~2센트예요 (README 3-5).
"""
import copy
import json

from .. import config
from . import BadOutput, EngineError, keys

# 가닥 설정의 짧은 이름(GADAK_ENGINE_MODEL) → API의 모델 이름. claude-로 시작하는 이름은 그대로 써요
MODELS = {"haiku": "claude-haiku-4-5", "sonnet": "claude-sonnet-5-5", "opus": "claude-opus-5-5"}
MAX_TOKENS = 16000
# 분류에는 깊은 생각이 필요 없어요. 생각을 끌 수 없는 모델은 가장 낮은 단계로 돌려요 (Haiku 4.5는 이 칸을 받지 않아요)
LOW_EFFORT = ("claude-opus-5", "claude-sonnet-5", "claude-fable-5", "claude-opus-4-8", "claude-opus-4-7",
              "claude-opus-4-6", "claude-sonnet-4-6")
# 안전 장치가 요청을 거절하면 서버가 다른 모델로 한 번 더 돌려 줘요 (베타). 이 모델들에만 있어요
FALLBACKS = ("claude-fable-5-1", "claude-opus-5-5", "claude-opus-5", "claude-sonnet-5-5")
FALLBACK_BETA = "server-side-fallback-2026-07-01"
# 100만 토큰에 드는 값(달러): (입력, 출력). 2026-09-25에 본 값이에요. 평가에서 ‘약 얼마’를 보여 줄 때만 써요
PRICES = {"claude-haiku-4-5": (1.0, 5.0), "claude-sonnet-5-5": (2.0, 10.0), "claude-opus-5-5": (4.0, 20.0)}
USAGE_FIELDS = ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens", "output_tokens")   # backend/tokens.py가 읽는 칸


def model_id(name=None) -> str:
    name = (name or config.ENGINE_MODEL or "haiku").strip()
    if name.lower() in MODELS:
        return MODELS[name.lower()]
    return name if name.lower().startswith("claude-") else MODELS["haiku"]      # 다른 회사 모델 이름(gpt-… · gemini-…)이 적혀 있으면 작은 모델로


def api_schema(schema):
    """구조화 출력이 받는 모양으로: 여러 종류를 한 칸에 적은 것(type: [a, b])을 anyOf로 풀어요."""
    if isinstance(schema, list):
        return [api_schema(item) for item in schema]
    if not isinstance(schema, dict):
        return schema
    out = {key: api_schema(value) for key, value in schema.items()}
    if isinstance(out.get("type"), list):
        kinds = out.pop("type")
        rest = {key: out.pop(key) for key in ("enum", "items", "properties", "required", "additionalProperties") if key in out}
        out["anyOf"] = [dict(rest, type=kind) if kind != "null" else {"type": "null"} for kind in kinds]
    return out


def _sdk():
    try:
        import anthropic
    except ImportError as exc:
        raise EngineError("API 키 엔진에 필요한 것(anthropic)이 없어요. ‘가닥 설치.command’를 다시 실행해 주세요.") from exc
    return anthropic


def _trouble(anthropic, exc, model) -> EngineError:
    """SDK의 오류를 가닥 창에 한 줄로 보여 줄 말로."""
    if isinstance(exc, anthropic.AuthenticationError):
        return EngineError("API 키가 맞지 않아요. 키를 다시 넣어 주세요.")
    if isinstance(exc, anthropic.PermissionDeniedError):
        return EngineError("이 API 키로는 이 모델을 쓸 수 없어요.")
    if isinstance(exc, anthropic.NotFoundError):
        return EngineError(f"모델 이름이 맞지 않아요: {model}")
    if isinstance(exc, anthropic.RateLimitError):
        return EngineError("API 사용 한도에 걸렸어요. 잠시 뒤에 ‘정리 다시’를 눌러 주세요.")
    if isinstance(exc, anthropic.APIStatusError):
        text = str(getattr(exc, "message", "") or exc)
        if exc.status_code == 402 or "credit balance" in text.lower():
            return EngineError("API 크레딧이 모자라요. Anthropic 콘솔에서 충전한 뒤 ‘정리 다시’를 눌러 주세요.")
        if exc.status_code >= 500:
            return EngineError("Anthropic 서버가 잠시 답하지 못해요. 조금 뒤에 ‘정리 다시’를 눌러 주세요.")
        return EngineError("요청이 받아들여지지 않았어요: " + " ".join(text.split())[:140])
    if isinstance(exc, anthropic.APIConnectionError):
        return EngineError("Anthropic에 닿지 못했어요. 인터넷 연결을 확인해 주세요.")
    return EngineError(str(exc)[:200])


class AnthropicApiEngine:
    name = "anthropic_api"

    def __init__(self, model=None, timeout=120.0, client=None):
        self.model = model or config.ENGINE_MODEL       # 설정에 적힌 이름 (판단 기록에 남아요)
        self.model_id = model_id(self.model)
        self.timeout = timeout
        self.last = None      # 마지막 호출의 토큰 수와 값 (정확도 평가가 봐요)
        self.last_usage = None  # 마지막 호출이 쓴 토큰을 종류별로 (backend/tokens.py가 내 PC에 적어요)
        self._client = client

    def client(self):
        if self._client is None:
            anthropic = _sdk()
            key = keys.get("anthropic")      # 다른 회사 키가 들어 있으면 쓰지 않아요 (그 키는 그 회사 엔진이 써요)
            if not key:
                raise EngineError("API 키가 없어요. 키를 넣어 주세요.")
            self._client = anthropic.Anthropic(api_key=key, timeout=self.timeout)
        return self._client

    def check(self) -> dict:
        """키와 모델 이름만 봐요. 모델은 부르지 않아서 돈이 들지 않아요."""
        anthropic = _sdk()
        try:
            info = self.client().models.retrieve(self.model_id)
        except EngineError as exc:
            return {"ok": False, "reason": str(exc)}
        except anthropic.APIError as exc:
            return {"ok": False, "reason": str(_trouble(anthropic, exc, self.model_id))}
        return {"ok": True, "model": info.id, "key": keys.describe()["source"]}

    def _request(self, system, prompt, schema) -> dict:
        request = {
            "model": self.model_id, "max_tokens": MAX_TOKENS,
            # 정리 지시문은 호출마다 같아요. 길이가 되면 다시 읽을 때 싸져요 (짧으면 그냥 보통 값이에요)
            "system": [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
            "messages": [{"role": "user", "content": prompt}],
            "output_config": {"format": {"type": "json_schema", "schema": api_schema(copy.deepcopy(schema))}},
        }
        if self.model_id.startswith(LOW_EFFORT):
            request["output_config"]["effort"] = "low"
        return request

    def complete_json(self, system: str, prompt: str, schema: dict) -> dict:
        """schema에 맞는 JSON 하나를 받아요."""
        self.last_usage = None
        anthropic = _sdk()
        client, request = self.client(), self._request(system, prompt, schema)
        try:
            if self.model_id in FALLBACKS:
                response = client.beta.messages.create(betas=[FALLBACK_BETA], fallbacks="default", **request)
            else:
                response = client.messages.create(**request)
        except anthropic.APIError as exc:
            raise _trouble(anthropic, exc, self.model_id) from exc
        used = response.usage
        tokens_in = sum(getattr(used, k, 0) or 0 for k in ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens"))
        price = PRICES.get(self.model_id)
        self.last = {"input_tokens": tokens_in, "output_tokens": used.output_tokens,
                     "cost": (tokens_in * price[0] + used.output_tokens * price[1]) / 1_000_000 if price else None}
        self.last_usage = dict({k: getattr(used, k, 0) or 0 for k in USAGE_FIELDS}, cost=self.last["cost"], model=self.model)
        if response.stop_reason == "refusal":
            raise BadOutput("모델이 이 묶음은 다루지 않겠다고 했어요")
        if response.stop_reason == "max_tokens":
            raise BadOutput("답이 길어서 중간에 잘렸어요")
        text = next((block.text for block in response.content if block.type == "text"), "")
        try:
            data = json.loads(text)
        except ValueError as exc:
            raise BadOutput("엔진이 정해 준 형식으로 답하지 않았어요: " + text[:120]) from exc
        if not isinstance(data, dict):
            raise BadOutput("엔진이 정해 준 형식으로 답하지 않았어요")
        return data


def verify(key, model=None) -> dict:
    """새로 받은 키를 한 번 확인해요(모델 정보만 물어서 돈이 들지 않아요).
    {ok, verified, reason}: 키가 틀렸으면 ok가 False. 인터넷이 안 돼 확인하지 못했으면 ok는 True, verified가 False."""
    anthropic = _sdk()
    client = anthropic.Anthropic(api_key=key, timeout=10.0, max_retries=0)
    try:
        client.models.retrieve(model_id(model))
    except (anthropic.AuthenticationError, anthropic.PermissionDeniedError) as exc:
        return {"ok": False, "verified": True, "reason": str(_trouble(anthropic, exc, model_id(model)))}
    except anthropic.APIError as exc:
        return {"ok": True, "verified": False, "reason": str(_trouble(anthropic, exc, model_id(model)))}
    return {"ok": True, "verified": True, "reason": None}
