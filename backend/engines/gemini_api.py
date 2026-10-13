"""Google Gemini API 키로 부르는 엔진.

‘AI 연결’에 넣은 키가 Gemini 것(AIza… · AQ.…)이면 이 엔진으로 정리해요. Anthropic 키 엔진(anthropic_api)과 같은 모양으로 불려요:
complete_json(system, prompt, schema) → dict. SDK 없이 generateContent를 직접 불러요(rest.py).
Google AI Studio에서 받은 무료 키로도 돌아요. 무료 등급은 돈이 들지 않는 대신 분 · 하루 한도가 낮고, 보낸 글이 Google의 제품 개선에 쓰여요.
요청의 모양은 2026-10-08에 실제 서버로 확인했어요(키보다 모양을 먼저 검사해요). 실제 키로 답을 받아 보지는 못했어요 (docs/usage-guide.md 3-2).
"""
from urllib.parse import quote

from .. import config
from . import BadOutput, EngineError, keys, rest

WHO = "Gemini"
URL = "https://generativelanguage.googleapis.com/v1beta"
# 가닥 설정의 짧은 이름(GADAK_ENGINE_MODEL: 작은 것 · 중간 · 큰 것) → Gemini의 모델 이름. gemini-로 시작하는 이름은 그대로 써요
# 큰 것(Pro)은 무료 등급에서는 쓸 수 없어요
MODELS = {"haiku": "gemini-3.5-flash-lite", "sonnet": "gemini-3.8-flash", "opus": "gemini-3.1-pro-preview"}
MAX_TOKENS = 16000
# 생각 단계(thinkingLevel)는 Gemini 3부터 받아요. 분류에는 깊은 생각이 필요 없어서 낮춰 돌려요.
# Flash-Lite는 처음부터 가장 낮아서(minimal) 그대로 둬요
THINKS = "gemini-3"
LEVELS = {"low": "LOW", "medium": "MEDIUM", "high": "HIGH"}
# 100만 토큰에 드는 값(달러): (입력, 출력). 2026-10-08에 본 유료 등급의 값이에요. 평가에서 ‘약 얼마’를 보여 줄 때만 써요
PRICES = {"gemini-3.5-flash-lite": (0.3, 2.5), "gemini-3.8-flash": (0.75, 3.75), "gemini-3.1-pro-preview": (2.0, 12.0)}


def model_id(name=None) -> str:
    name = (name or config.ENGINE_MODEL or "haiku").strip()
    if name.lower() in MODELS:
        return MODELS[name.lower()]
    return name if name.lower().startswith("gemini-") else MODELS["haiku"]      # 다른 회사 모델 이름(claude-…)이 적혀 있으면 작은 모델로


def _headers(key) -> dict:
    return {"x-goog-api-key": key, "Content-Type": "application/json"}      # 새 키(AQ.…)는 OpenAI 호환 주소의 Bearer로는 안 받아서 이 머리로 보내요


def _details(error) -> list:
    return [d for d in error.get("details") or [] if isinstance(d, dict)]


def _for_today(error) -> bool:
    """하루 치 한도를 다 쓴 것인지 (분 한도와 달리 조금 기다려서는 풀리지 않아요)."""
    limits = [v for d in _details(error) for v in d.get("violations") or [] if isinstance(v, dict)]
    return any("PerDay" in str(v.get("quotaId") or "") for v in limits)


def _wait(status, data, headers):
    """다시 보내기 전에 기다릴 초 (rest.call이 물어요). Gemini는 답 안에 retryDelay("32s")로 적어 줘요."""
    error = rest.error_of(data)
    if status == 429 and _for_today(error):
        return float("inf")
    for detail in _details(error):
        delay = detail.get("retryDelay")
        if isinstance(delay, str) and delay.endswith("s"):
            try:
                return max(float(delay[:-1]), 0.0)
            except ValueError:
                pass
    return rest.retry_after(headers)


def _bad_key(status, error) -> bool:
    """키가 틀렸거나 못 쓰게 된 것. Gemini는 이것을 401만이 아니라 400(API_KEY_INVALID)으로도 답해요."""
    text = str(error.get("message") or "").lower()
    return (status == 401 or any(d.get("reason") == "API_KEY_INVALID" for d in _details(error))
            or "api key not valid" in text or "api key expired" in text)


def _trouble(status, data, model) -> EngineError:
    """Gemini가 안 된다고 한 답을 가닥 창에 한 줄로 보여 줄 말로."""
    error = rest.error_of(data)
    text = rest.line(error.get("message"))
    if _bad_key(status, error):
        return EngineError("API 키가 맞지 않아요. 키를 다시 넣어 주세요.")
    if status == 403:
        return EngineError("이 API 키로는 쓸 수 없어요: " + (text or "권한이 없어요"))
    if status == 404:
        return EngineError(f"이 키로 쓸 수 없는 모델이에요: {model}")      # 이름이 틀렸거나, 이 키에 권한이 없거나
    if status == 429:
        if _for_today(error):
            return EngineError("Gemini의 하루 사용 한도를 다 썼어요. 한도가 다시 채워진 뒤 ‘정리 다시’를 눌러 주세요.")
        return EngineError("API 사용 한도에 걸렸어요. 잠시 뒤에 ‘정리 다시’를 눌러 주세요.")
    if status >= 500:
        return EngineError("Gemini 서버가 잠시 답하지 못해요. 조금 뒤에 ‘정리 다시’를 눌러 주세요.")
    return EngineError("요청이 받아들여지지 않았어요: " + (text or f"HTTP {status}"))


class GeminiApiEngine:
    name = "gemini_api"

    def __init__(self, model=None, timeout=120.0, effort=None):
        self.model = model or config.ENGINE_MODEL       # 설정에 적힌 이름 (판단 기록에 남아요)
        self.model_id = model_id(self.model)
        self.timeout = timeout
        self.effort = effort      # 생각 깊이(low · medium · high). 비우면 가장 낮게: 분류에는 그거면 돼요
        self.last = None          # 마지막 호출의 토큰 수와 값 (정확도 평가가 봐요)
        self.last_usage = None    # 마지막 호출이 쓴 토큰을 종류별로 (backend/tokens.py가 내 PC에 적어요)

    def _key(self) -> str:
        key = keys.get("gemini")
        if not key:
            raise EngineError("API 키가 없어요. 키를 넣어 주세요.")
        return key

    def _url(self, verb="") -> str:
        return f"{URL}/models/{quote(self.model_id, safe='')}{verb}"

    def check(self) -> dict:
        """키와 모델 이름만 봐요. 모델은 부르지 않아서 돈이 들지 않아요."""
        try:
            status, data = rest.call(WHO, "GET", self._url(), _headers(self._key()), timeout=min(self.timeout, 30.0))
        except EngineError as exc:
            return {"ok": False, "reason": str(exc)}
        if status != 200:
            return {"ok": False, "reason": str(_trouble(status, data, self.model_id))}
        return {"ok": True, "model": str(data.get("name") or self.model_id).removeprefix("models/"), "key": keys.describe()["source"]}

    def _level(self):
        """보낼 생각 단계. 보내지 않으면(None) 그 모델의 기본값이에요."""
        if not self.model_id.startswith(THINKS):
            return None
        if self.effort in LEVELS:
            return LEVELS[self.effort]
        return None if "flash-lite" in self.model_id else "LOW"

    def _request(self, system, prompt, schema) -> dict:
        # 형식은 responseFormat으로 줘요. mimeType은 문서 예시의 "application/json"이 아니라 이 이름이어야 서버가 받아요 (10/8 확인)
        settings = {"maxOutputTokens": MAX_TOKENS,
                    "responseFormat": {"text": {"mimeType": "APPLICATION_JSON", "schema": schema}}}
        if self._level():
            settings["thinkingConfig"] = {"thinkingLevel": self._level()}
        return {"systemInstruction": {"parts": [{"text": system}]},
                "contents": [{"role": "user", "parts": [{"text": prompt}]}],
                "generationConfig": settings}

    def complete_json(self, system: str, prompt: str, schema: dict) -> dict:
        """schema에 맞는 JSON 하나를 받아요."""
        self.last_usage = None
        status, data = rest.call(WHO, "POST", self._url(":generateContent"), _headers(self._key()),
                                 self._request(system, prompt, schema), timeout=self.timeout, wait=_wait)
        if status != 200:
            raise _trouble(status, data, self.model_id)
        self._used(data.get("usageMetadata"))
        blocked = data.get("promptFeedback") if isinstance(data.get("promptFeedback"), dict) else {}
        first = (data.get("candidates") or [None])[0]
        if blocked.get("blockReason") or not isinstance(first, dict):
            raise BadOutput("모델이 이 묶음은 다루지 않겠다고 했어요")      # 보낸 글이 막혔어요. 답이 아예 없어요
        if first.get("finishReason") == "MAX_TOKENS":
            raise BadOutput("답이 길어서 중간에 잘렸어요")
        if first.get("finishReason") not in (None, "STOP"):
            raise BadOutput("모델이 이 묶음은 다루지 않겠다고 했어요")      # SAFETY · RECITATION 같은 까닭으로 멈췄어요
        content = first.get("content") if isinstance(first.get("content"), dict) else {}
        parts = [p for p in content.get("parts") or [] if isinstance(p, dict) and not p.get("thought")]      # 생각을 간추린 조각은 빼요
        return rest.answer("".join(str(p.get("text") or "") for p in parts))

    def _used(self, used) -> None:
        """쓴 토큰. promptTokenCount에는 캐시에서 읽은 것이 들어 있어서 빼고 적어요. 생각에 쓴 토큰은 출력 값으로 나가요."""
        if not isinstance(used, dict):
            return
        number = lambda name: int(used.get(name) or 0)
        tokens_in, read = number("promptTokenCount"), number("cachedContentTokenCount")
        tokens_out = number("candidatesTokenCount") + number("thoughtsTokenCount")
        price = PRICES.get(self.model_id)
        self.last = {"input_tokens": tokens_in, "output_tokens": tokens_out,
                     "cost": (tokens_in * price[0] + tokens_out * price[1]) / 1_000_000 if price else None}
        self.last_usage = {"input_tokens": max(tokens_in - read, 0), "cache_creation_input_tokens": 0, "cache_read_input_tokens": read,
                           "output_tokens": tokens_out, "cost": self.last["cost"], "model": self.model_id}


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
    refused = status == 403 or _bad_key(status, rest.error_of(data))
    return {"ok": not refused, "verified": refused, "reason": str(_trouble(status, data, name))}
