"""API 키 엔진이 회사 API를 HTTP로 직접 부르는 길 (OpenAI · Gemini 엔진이 같이 써요).

Anthropic 엔진은 공식 SDK가 이 일을 해요. 이 둘은 SDK를 더 깔지 않고, 그 SDK가 쓰는 것(httpx2)으로 직접 불러요.
잠깐의 문제(연결 끊김 · 사용 한도 · 서버 과부하)면 조금 기다렸다 다시 보내요. 그 SDK가 하는 만큼이에요(두 번까지).
안 된 답을 가닥의 말로 바꾸는 것은 회사마다 달라서 각 엔진이 해요. 키는 요청 머리(header)에만 실어서 주소나 오류 글에 남지 않아요.
"""
import json
import time

from . import BadOutput, EngineError

RETRIES = 2                                          # 다시 보내는 횟수
AGAIN = (408, 409, 429, 500, 502, 503, 504, 529)     # 기다렸다 다시 보내 볼 만한 답
WAIT_MAX = 60.0                                      # 서버가 이보다 오래 기다리라고 하면 다시 보내지 않고 그 답을 돌려줘요


class Unreachable(EngineError):
    """그 회사에 닿지 못했어요 (인터넷 · 연결)."""


class TooSlow(Unreachable):
    """닿았는데 답이 늦어요. 다시 보내지 않아요 (같은 요청에 돈이 또 나가요)."""


def _http():
    try:
        import httpx2
    except ImportError as exc:
        raise EngineError("API 키 엔진에 필요한 것(httpx2)이 없어요. ‘가닥 설치.command’를 다시 실행해 주세요.") from exc
    return httpx2


def send(who, method, url, headers, body=None, timeout=120.0):
    """요청 한 번. (상태 코드, 답, 답의 머리)를 돌려줘요. 답이 JSON 객체가 아니면 빈 것으로 봐요."""
    http = _http()
    try:
        response = http.request(method, url, headers=headers, json=body, timeout=timeout)
    except http.ReadTimeout as exc:
        raise TooSlow(f"{who}가 {int(timeout)}초 안에 답하지 않았어요") from exc
    except http.HTTPError as exc:
        raise Unreachable(f"{who}에 닿지 못했어요. 인터넷 연결을 확인해 주세요.") from exc
    try:
        data = response.json()
    except ValueError:
        data = None
    return response.status_code, data if isinstance(data, dict) else {}, response.headers


def retry_after(headers):
    """답의 머리에 적힌 ‘이만큼 기다렸다 다시’(Retry-After)의 초. 없거나 읽지 못하면 None."""
    try:
        return max(float(headers.get("retry-after")), 0.0)
    except (TypeError, ValueError):
        return None


def call(who, method, url, headers, body=None, timeout=120.0, retries=RETRIES, wait=None):
    """보내고, 잠깐의 문제면 기다렸다 다시 보내요. (상태 코드, 답)을 돌려줘요. 다시 보내도 안 되면 마지막 답 그대로예요.
    wait(status, data, headers)는 서버가 기다리라고 한 초예요. 말이 없으면 None, 기다려도 소용없으면 무한대."""
    for attempt in range(retries + 1):
        pause = min(0.5 * 2 ** attempt, 8.0)
        try:
            status, data, seen = send(who, method, url, headers, body, timeout)
        except TooSlow:
            raise
        except Unreachable:
            if attempt == retries:
                raise
            time.sleep(pause)
            continue
        if status not in AGAIN or attempt == retries:
            return status, data
        asked = wait(status, data, seen) if wait else retry_after(seen)
        if asked is not None and asked > WAIT_MAX:
            return status, data
        time.sleep(pause if asked is None else asked)


def error_of(data) -> dict:
    """안 된 답에 든 까닭 (두 회사 다 error 칸에 적어요)."""
    error = data.get("error")
    return error if isinstance(error, dict) else {}


def line(text, limit=140) -> str:
    return " ".join(str(text or "").split())[:limit]


def answer(text) -> dict:
    """모델이 낸 글을 JSON 하나로 읽어요. 아니면 그 묶음만 실패예요."""
    try:
        data = json.loads(text)
    except ValueError as exc:
        raise BadOutput("엔진이 정해 준 형식으로 답하지 않았어요: " + text[:120]) from exc
    if not isinstance(data, dict):
        raise BadOutput("엔진이 정해 준 형식으로 답하지 않았어요")
    return data
