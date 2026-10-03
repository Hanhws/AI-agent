"""가닥이 판단에 쓰는 LLM(엔진). 사용자가 가진 것에 맞춰 골라요 — docs/usage-guide.md.

- claude_cli: Claude 구독(Pro · Max). 내 PC의 Claude Code를 불러요. API 키가 필요 없어요.
- none: LLM 없이 기록만.
"""
import shutil

from .. import config


class EngineError(RuntimeError):
    pass


class OutOfCalls(EngineError):
    """이번에 켠 동안 쓸 호출 수(GADAK_MAX_CALLS)를 다 썼어요. 턴 탓이 아니라서 실패로 세지 않아요."""


def resolve_name(name=None) -> str:
    name = (name or config.ENGINE).lower()
    if name != "auto":
        return name
    return "claude_cli" if shutil.which("claude") else "none"


def get_engine(name=None):
    name = resolve_name(name)
    if name == "claude_cli":
        from .claude_cli import ClaudeCliEngine
        return ClaudeCliEngine()
    if name == "none":
        return None
    raise EngineError(f"아직 지원하지 않는 엔진이에요: {name}")


def describe_engine() -> dict:
    return {"configured": config.ENGINE, "resolved": resolve_name()}
