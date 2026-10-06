"""가닥이 판단에 쓰는 LLM(엔진). 사용자가 가진 것에 맞춰 골라요 — docs/usage-guide.md 3장.

- claude_cli: Claude 구독(Pro · Max). 내 PC의 Claude Code를 불러요. API 키가 필요 없어요.
- anthropic_api: Anthropic API 키. Claude Code가 없는 사람이 자기 키로 써요. 키는 macOS 키체인에 있어요(keys.py).
- none: LLM 없이 기록만.

auto(기본)는 이 차례로 골라요: Claude Code가 있으면 구독 엔진 → API 키가 있으면 API 엔진 → 둘 다 없으면 none.
Claude Code가 깔려 있기만 하고 로그인이 안 된 Mac에 API 키가 있으면, 키 쪽을 써요(둘 다 있을 때만 로그인을 확인해요).
"""
import shutil
import time

from .. import config


class EngineError(RuntimeError):
    pass


class OutOfCalls(EngineError):
    """이번에 켠 동안 쓸 호출 수(GADAK_MAX_CALLS)를 다 썼어요. 턴 탓이 아니라서 실패로 세지 않아요."""


class BadOutput(RuntimeError):
    """엔진은 멀쩡한데 이번 답이 정해 준 모양이 아니에요(글로 답했거나, 잘렸거나, 거절했어요).
    로그인 · 한도 문제(EngineError)와 달리 정리를 멈추지 않아요. 그 묶음만 실패로 세고 다음으로 넘어가요."""


from . import keys  # noqa: E402  (위의 오류 클래스를 쓰는 모듈이라 그 뒤에 불러요)

NAMES = ("claude_cli", "anthropic_api", "none")


def cli_found() -> bool:
    return shutil.which("claude") is not None


_login = {"at": 0.0, "ok": True}


def cli_logged_in(remember=120.0) -> bool:
    """Claude Code에 로그인돼 있는지 (claude auth status · 모델은 부르지 않아요). 확인하지 못하면 돼 있다고 봐요.
    명령을 띄워야 해서, 한 번 본 답은 잠깐 기억해 둬요."""
    if time.time() - _login["at"] < remember:
        return _login["ok"]
    from .claude_cli import ClaudeCliEngine
    try:
        ok = bool(ClaudeCliEngine().check().get("ok"))
    except Exception:
        ok = True
    _login.update(at=time.time(), ok=ok)
    return ok


def resolve_name(name=None) -> str:
    name = (name or config.ENGINE).lower()
    if name != "auto":
        return name
    if cli_found():
        if keys.get() and not cli_logged_in():
            return "anthropic_api"
        return "claude_cli"
    return "anthropic_api" if keys.get() else "none"


def get_engine(name=None):
    name = resolve_name(name)
    if name == "claude_cli":
        from .claude_cli import ClaudeCliEngine
        return ClaudeCliEngine()
    if name == "anthropic_api":
        from .anthropic_api import AnthropicApiEngine
        return AnthropicApiEngine()
    if name == "none":
        return None
    raise EngineError(f"아직 지원하지 않는 엔진이에요: {name}")


def describe_engine() -> dict:
    return {"configured": config.ENGINE, "resolved": resolve_name()}


def overview(status=None) -> dict:
    """화면이 엔진을 안내할 때 보는 것 (GET /engine). 키 자체는 싣지 않아요.
    need: 쓸 엔진이 없으면 "engine" — Claude Code에 로그인하거나 API 키를 넣으라고 안내해요."""
    info = describe_engine()
    if status is not None and status.get("engine"):
        info["resolved"] = status["engine"]          # 지금 실제로 도는 엔진
    info.update(model=config.ENGINE_MODEL, cli=cli_found(), key=keys.describe(),
                need="engine" if info["resolved"] == "none" else None)
    if status is not None:
        info.update(error=status.get("error"), paused=bool(status.get("paused")))
    return info


def set_key(key, model=None) -> dict:
    """API 키를 확인하고 키체인에 넣어요. {ok, verified, reason}"""
    key = key.strip() if isinstance(key, str) else ""
    if not keys.looks_right(key):
        return {"ok": False, "verified": False, "reason": "API 키 모양이 아니에요. sk-ant-로 시작하는 키를 넣어 주세요."}
    if not keys.can_store():
        return {"ok": False, "verified": False, "reason": f"이 컴퓨터에는 키를 넣어 둘 키체인이 없어요. 환경 변수 {keys.ENV}로 넘겨 주세요."}
    try:
        from . import anthropic_api
        result = anthropic_api.verify(key, model)
        if result["ok"]:
            keys.save(key)
    except (EngineError, keys.KeyStoreError) as exc:
        return {"ok": False, "verified": False, "reason": str(exc)}
    return result
