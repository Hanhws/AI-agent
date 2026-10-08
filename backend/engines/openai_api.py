"""OpenAI API 키로 부르는 엔진.

‘AI 연결’에 넣은 키가 OpenAI 것(sk-…)이면 이 엔진으로 정리해요. Anthropic 키 엔진(anthropic_api)과 같은 모양으로 불려요:
complete_json(system, prompt, schema) → dict. SDK 없이 Responses API(POST /v1/responses)를 직접 불러요(rest.py).
부를 때마다 그 사람의 키로 돈이 나가요.
요청과 답의 모양은 2026-10-08의 공식 문서를 따랐어요. 실제 키로는 불러 보지 못했어요 (docs/usage-guide.md 3-2).
"""
from urllib.parse import quote

from .. import config
from . import BadOutput, EngineError, keys, rest

WHO = "OpenAI"
URL = "https://api.openai.com/v1"
# 가닥 설정의 짧은 이름(GADAK_ENGINE_MODEL: 작은 것 · 중간 · 큰 것) → OpenAI의 모델 이름. gpt-로 시작하는 이름은 그대로 써요
MODELS = {"haiku": "gpt-6-luna", "sonnet": "gpt-6.1-sol", "opus": "gpt-6-astra"}
OWN = ("gpt-", "chatgpt-", "o1", "o3", "o4")      # OpenAI의 모델 이름으로 볼 앞머리
MAX_TOKENS = 16000
# 생각하는 모델들. 분류에는 깊은 생각이 필요 없어서 가장 낮은 단계로 돌려요 (위의 세 모델이 다 받는 가장 낮은 단계가 low예요)
REASONING = ("gpt-6", "gpt-5")
EFFORTS = ("low", "medium", "high")
# 100만 토큰에 드는 값(달러): (입력, 출력). 2026-10-08에 본 값이에요. 평가에서 ‘약 얼마’를 보여 줄 때만 써요
PRICES = {"gpt-6-luna": (0.1, 0.5), "gpt-6.1-sol": (2.0, 10.0), "gpt-6-astra": (10.0, 50.0)}
# 넣어 둔 돈이나 정해 둔 한도를 다 쓴 것. 기다려도 풀리지 않아서 다시 보내지 않아요
SPENT = ("credit_balance_exhausted", "insufficient_quota", "organization_spend_limit_exceeded",
         "project_spend_limit_exceeded", "organization_usage_limit_exceeded")


def model_id(name=None) -> str:
    name = (name or config.ENGINE_MODEL or "haiku").strip()
    if name.lower() in MODELS:
        return MODELS[name.lower()]
    return name if name.lower().startswith(OWN) else MODELS["haiku"]      # 다른 회사 모델 이름(claude-…)이 적혀 있으면 작은 모델로


def _headers(key) -> dict:
    return {"Authorization": "Bearer " + key, "Content-Type": "application/json"}


def _spent(error) -> bool:
    return error.get("code") in SPENT or error.get("type") in SPENT


def _wait(status, data, headers):
    """다시 보내기 전에 기다릴 초 (rest.call이 물어요)."""
    if status == 429 and _spent(rest.error_of(data)):
        return float("inf")
    return rest.retry_after(headers)


def _trouble(status, data, model) -> EngineError:
    """OpenAI가 안 된다고 한 답을 가닥 창에 한 줄로 보여 줄 말로."""
    error = rest.error_of(data)
    text = rest.line(error.get("message"))
    if status == 401:
        return EngineError("API 키가 맞지 않아요. 키를 다시 넣어 주세요.")
    if status == 403:
        return EngineError("이 API 키로는 쓸 수 없어요: " + (text or "권한이 없어요"))
    if status == 404 or error.get("code") == "model_not_found":
        return EngineError(f"이 키로 쓸 수 없는 모델이에요: {model}")      # 이름이 틀렸거나, 이 키에 권한이 없거나
    if status == 429:
        if _spent(error):
            return EngineError("API 크레딧이 모자라요(또는 정해 둔 사용 한도를 넘었어요). OpenAI 콘솔에서 확인한 뒤 ‘정리 다시’를 눌러 주세요.")
        return EngineError("API 사용 한도에 걸렸어요. 잠시 뒤에 ‘정리 다시’를 눌러 주세요.")
    if status >= 500:
        return EngineError("OpenAI 서버가 잠시 답하지 못해요. 조금 뒤에 ‘정리 다시’를 눌러 주세요.")
    return EngineError("요청이 받아들여지지 않았어요: " + (text or f"HTTP {status}"))


def _said(data):
    """답에서 (모델이 쓴 글, 거절했는지)를 찾아요. 생각한 것(reasoning) 같은 다른 항목은 지나쳐요."""
    text, refused = "", False
    for item in data.get("output") or []:
        if not isinstance(item, dict) or item.get("type") != "message":
            continue
        for part in item.get("content") or []:
            if isinstance(part, dict) and part.get("type") == "output_text":
                text += str(part.get("text") or "")
            elif isinstance(part, dict) and part.get("type") == "refusal":
                refused = True
    return text, refused


class OpenAiApiEngine:
    name = "openai_api"

    def __init__(self, model=None, timeout=120.0, effort=None):
        self.model = model or config.ENGINE_MODEL       # 설정에 적힌 이름 (판단 기록에 남아요)
        self.model_id = model_id(self.model)
        self.timeout = timeout
        self.effort = effort      # 생각 깊이(low · medium · high). 비우면 가장 낮게: 분류에는 그거면 돼요
        self.last = None          # 마지막 호출의 토큰 수와 값 (정확도 평가가 봐요)
        self.last_usage = None    # 마지막 호출이 쓴 토큰을 종류별로 (backend/tokens.py가 내 PC에 적어요)

    def _key(self) -> str:
        key = keys.get("openai")
        if not key:
            raise EngineError("API 키가 없어요. 키를 넣어 주세요.")
        return key

    def check(self) -> dict:
        """키와 모델 이름만 봐요. 모델은 부르지 않아서 돈이 들지 않아요."""
        try:
            status, data = rest.call(WHO, "GET", f"{URL}/models/{quote(self.model_id, safe='')}", _headers(self._key()),
                                     timeout=min(self.timeout, 30.0))
        except EngineError as exc:
            return {"ok": False, "reason": str(exc)}
        if status != 200:
            return {"ok": False, "reason": str(_trouble(status, data, self.model_id))}
        return {"ok": True, "model": data.get("id") or self.model_id, "key": keys.describe()["source"]}

    def _request(self, system, prompt, schema) -> dict:
        request = {
            "model": self.model_id, "max_output_tokens": MAX_TOKENS,
            "input": [{"role": "system", "content": system}, {"role": "user", "content": prompt}],
            "text": {"format": {"type": "json_schema", "name": "gadak", "schema": schema, "strict": True}},
            "store": False,       # 보낸 글과 답을 OpenAI에 보관해 두지 않게 (말하지 않으면 30일 보관해요)
        }
        if self.model_id.startswith(REASONING):
            request["reasoning"] = {"effort": self.effort if self.effort in EFFORTS else "low"}
        return request

    def complete_json(self, system: str, prompt: str, schema: dict) -> dict:
        """schema에 맞는 JSON 하나를 받아요."""
        self.last_usage = None
        status, data = rest.call(WHO, "POST", URL + "/responses", _headers(self._key()), self._request(system, prompt, schema),
                                 timeout=self.timeout, wait=_wait)
        if status != 200:
            raise _trouble(status, data, self.model_id)
        self._used(data.get("usage"))
        if data.get("status") == "failed":
            code = str(rest.error_of(data).get("code") or "")
            if code in ("server_error", "rate_limit_exceeded"):
                raise EngineError("OpenAI가 답을 만들지 못했어요. 조금 뒤에 ‘정리 다시’를 눌러 주세요.")
            raise BadOutput("모델이 답을 만들지 못했어요: " + code[:60])
        text, refused = _said(data)
        if refused:
            raise BadOutput("모델이 이 묶음은 다루지 않겠다고 했어요")
        if data.get("status") == "incomplete":
            why = data.get("incomplete_details") if isinstance(data.get("incomplete_details"), dict) else {}
            raise BadOutput("답이 길어서 중간에 잘렸어요" if why.get("reason") == "max_output_tokens"
                            else "모델이 이 묶음은 다루지 않겠다고 했어요")
        return rest.answer(text)

    def _used(self, used) -> None:
        """쓴 토큰. OpenAI의 input_tokens에는 캐시에서 읽은 것 · 캐시에 쓴 것이 들어 있어서 빼고 적어요 (backend/tokens.py의 칸에 맞춰요)."""
        if not isinstance(used, dict):
            return
        detail = used.get("input_tokens_details") if isinstance(used.get("input_tokens_details"), dict) else {}
        number = lambda value: int(value or 0)
        tokens_in, tokens_out = number(used.get("input_tokens")), number(used.get("output_tokens"))
        read, written = number(detail.get("cached_tokens")), number(detail.get("cache_write_tokens"))
        price = PRICES.get(self.model_id)
        self.last = {"input_tokens": tokens_in, "output_tokens": tokens_out,
                     "cost": (tokens_in * price[0] + tokens_out * price[1]) / 1_000_000 if price else None}
        self.last_usage = {"input_tokens": max(tokens_in - read - written, 0), "cache_creation_input_tokens": written,
                           "cache_read_input_tokens": read, "output_tokens": tokens_out, "cost": self.last["cost"], "model": self.model_id}


def verify(key, model=None) -> dict:
    """새로 받은 키를 한 번 확인해요(모델 정보만 물어서 돈이 들지 않아요).
    {ok, verified, reason}: 키가 틀렸으면 ok가 False. 인터넷이 안 돼 확인하지 못했으면 ok는 True, verified가 False."""
    name = model_id(model)
    try:
        status, data = rest.call(WHO, "GET", f"{URL}/models/{quote(name, safe='')}", _headers(key), timeout=10.0, retries=0)
    except rest.Unreachable as exc:
        return {"ok": True, "verified": False, "reason": str(exc)}
    if status == 200:
        return {"ok": True, "verified": True, "reason": None}
    refused = status in (401, 403)
    return {"ok": not refused, "verified": refused, "reason": str(_trouble(status, data, name))}
