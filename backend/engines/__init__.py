"""가닥이 판단에 쓰는 LLM(엔진). 사용자가 가진 것에 맞춰 골라요 — docs/usage-guide.md 3장.

- claude_cli: Claude 구독(Pro · Max). 내 PC의 Claude Code를 불러요. API 키가 필요 없어요.
- codex_cli: ChatGPT 구독(Plus · Pro). 내 PC의 Codex를 불러요. API 키가 필요 없어요.
- anthropic_api · openai_api · gemini_api: LLM API 키. 구독이 없는 사람이 자기 키로 써요. 키는 하나를 macOS 키체인에 두고(keys.py),
  그 키가 어느 회사 것인지(Anthropic · OpenAI · Google Gemini)에 따라 셋 중 하나가 돼요. 화면에서는 ‘LLM API 키’ 한 칸이에요.
- none: LLM 없이 기록만.

사용자가 화면의 ‘AI 연결’에서 고른 것(prefer)이 있으면 그것을 써요. 없으면 설정(GADAK_ENGINE)이고, 그 기본값 auto는
이 차례로 골라요: Claude Code가 있으면 Claude 구독 → API 키가 있으면 API 엔진 → Codex에 로그인돼 있으면 ChatGPT 구독 → none.
Claude Code가 깔려 있기만 하고 로그인이 안 된 Mac에 다른 길(API 키 · Codex 로그인)이 있으면 그쪽을 써요.
설치와 로그인을 대신 해 주는 것은 connect.py예요.
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

API_NAMES = ("anthropic_api", "openai_api", "gemini_api")      # API 키 엔진. 어느 이름을 골라도 갖고 있는 키의 회사를 따라가요
NAMES = ("claude_cli", "codex_cli") + API_NAMES + ("none",)
CHOICES = ("auto",) + NAMES       # 사용자가 ‘AI 연결’에서 고를 수 있는 것
CHOICE_KEY = "engine.choice"      # 고른 것을 적어 두는 settings 칸
_choice = {"name": None}          # 고른 것. 고른 적이 없으면 None (그때는 설정 GADAK_ENGINE)


def prefer(name) -> None:
    """사용자가 화면에서 고른 엔진. auto나 None이면 고른 것이 없는 것으로 봐요. (저장은 backend/app.py가 settings에 해요)"""
    name = (name or "").lower()
    _choice["name"] = name if name in NAMES else None


def preferred():
    return _choice["name"]


def cli_found() -> bool:
    from . import claude_cli
    return claude_cli.find_bin() is not None


_login = {"at": 0.0, "ok": True, "plan": None}


def cli_logged_in(remember=120.0) -> bool:
    """Claude Code에 로그인돼 있는지 (claude auth status · 모델은 부르지 않아요). 확인하지 못하면 돼 있다고 봐요.
    명령을 띄워야 해서, 한 번 본 답은 잠깐 기억해 둬요."""
    if time.time() - _login["at"] < remember:
        return _login["ok"]
    from .claude_cli import ClaudeCliEngine
    plan = None
    try:
        seen = ClaudeCliEngine().check()
        ok, plan = bool(seen.get("ok")), seen.get("subscriptionType")
    except Exception:
        ok = True
    _login.update(at=time.time(), ok=ok, plan=plan)
    return ok


def codex_found() -> bool:
    from . import codex_cli
    return codex_cli.find_bin() is not None


_codex = {"at": 0.0, "ok": False}


def codex_logged_in(remember=120.0) -> bool:
    """Codex에 로그인돼 있는지 (codex login status · 모델은 부르지 않아요). 확인하지 못하면 안 돼 있다고 봐요."""
    if time.time() - _codex["at"] < remember:
        return _codex["ok"]
    from .codex_cli import CodexCliEngine
    try:
        ok = bool(CodexCliEngine().check().get("ok"))
    except Exception:
        ok = False
    _codex.update(at=time.time(), ok=ok)
    return ok


def codex_ready() -> bool:
    return codex_found() and codex_logged_in()


def forget_logins() -> None:
    """로그인 · 설치가 방금 바뀌었어요. 기억해 둔 답을 버리고 다음에 다시 물어요."""
    _login["at"] = _codex["at"] = 0.0


def resolve_name(name=None) -> str:
    name = (name or preferred() or config.ENGINE).lower()
    if name in API_NAMES:
        return keys.engine() or name      # 키가 OpenAI 것인데 anthropic_api를 골라 뒀어도 그 키의 회사로 불러요
    if name != "auto":
        return name
    if cli_found():
        other = keys.engine() or ("codex_cli" if codex_ready() else None)
        if other and not cli_logged_in():
            return other
        return "claude_cli"
    return keys.engine() or ("codex_cli" if codex_ready() else "none")


def _api(name):
    """API 키 엔진의 모듈. 회사마다 하나예요 (필요할 때 불러요)."""
    from . import anthropic_api, gemini_api, openai_api
    return {"anthropic_api": anthropic_api, "openai_api": openai_api, "gemini_api": gemini_api}[name]


def get_engine(name=None):
    name = resolve_name(name)
    if name == "claude_cli":
        from .claude_cli import ClaudeCliEngine
        return ClaudeCliEngine()
    if name == "codex_cli":
        from .codex_cli import CodexCliEngine
        return CodexCliEngine()
    if name == "anthropic_api":
        from .anthropic_api import AnthropicApiEngine
        return AnthropicApiEngine()
    if name == "openai_api":
        from .openai_api import OpenAiApiEngine
        return OpenAiApiEngine()
    if name == "gemini_api":
        from .gemini_api import GeminiApiEngine
        return GeminiApiEngine()
    if name == "none":
        return None
    raise EngineError(f"아직 지원하지 않는 엔진이에요: {name}")


def describe_engine() -> dict:
    return {"configured": config.ENGINE, "resolved": resolve_name()}


def options(fresh=False) -> list:
    """‘AI 연결’ 창이 보여 주는 것: 엔진마다 깔려 있는지(found) · 바로 쓸 수 있는지(ready). 모델은 부르지 않아요.
    fresh면 기억해 둔 로그인 답을 버리고 다시 물어요(연결을 기다리는 동안)."""
    if fresh:
        forget_logins()
    claude, codex, key = cli_found(), codex_found(), keys.describe()
    return [
        {"name": "claude_cli", "found": claude, "ready": claude and cli_logged_in(), "plan": _login["plan"] if claude else None},
        {"name": "codex_cli", "found": codex, "ready": codex and codex_logged_in()},
        # API 키 칸은 하나예요. 이름은 갖고 있는 키의 회사를 따라가요 (키가 없으면 예전 그대로 anthropic_api)
        {"name": keys.engine() or "anthropic_api", "found": True, "ready": key["stored"], "hint": key["hint"],
         "source": key["source"], "company": key["company"]},
    ]


def overview(status=None) -> dict:
    """화면이 엔진을 안내할 때 보는 것 (GET /engine). 키 자체는 싣지 않아요.
    need: 쓸 엔진이 없으면 "engine" — Claude Code에 로그인하거나 API 키를 넣으라고 안내해요."""
    info = describe_engine()
    if status is not None and status.get("engine"):
        info["resolved"] = status["engine"]          # 지금 실제로 도는 엔진
    info.update(model=config.ENGINE_MODEL, cli=cli_found(), key=keys.describe(), choice=preferred() or "auto",
                need="engine" if info["resolved"] == "none" else None)
    if status is not None:
        info.update(error=status.get("error"), paused=bool(status.get("paused")))
    return info


def set_key(key, model=None) -> dict:
    """API 키를 확인하고 키체인에 넣어요. 어느 회사 키인지는 앞머리로 알아보고, 그 회사에만 물어요. {ok, verified, reason}"""
    key = key.strip() if isinstance(key, str) else ""
    who = keys.company(key)
    if not who:
        return {"ok": False, "verified": False, "reason": keys.WRONG_SHAPE}
    if not keys.can_store():
        return {"ok": False, "verified": False, "reason": f"이 컴퓨터에는 키를 넣어 둘 키체인이 없어요. 환경 변수 {keys.ENV}로 넘겨 주세요."}
    try:
        result = _api(keys.ENGINES[who]).verify(key, model)
        if result["ok"]:
            keys.save(key)
    except (EngineError, keys.KeyStoreError) as exc:
        return {"ok": False, "verified": False, "reason": str(exc)}
    return result
