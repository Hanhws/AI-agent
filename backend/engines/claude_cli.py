"""Claude 구독(Pro · Max)을 쓰는 엔진.

내 PC에 로그인된 Claude Code를 `claude -p`로 불러요. API 키가 없어도 되고, 구독 사용 한도를
같이 써요. 서버에 배포한 가닥에서는 쓸 수 없어요.
"""
import json
import os
import shutil
import subprocess

from .. import config
from . import EngineError

# 이 표시가 있으면 가닥 hook이 엔진 자신의 호출을 다시 읽지 않아요 (cursor-hooks/gadak-hook.py)
INTERNAL_ENV = "GADAK_INTERNAL"

# 구독 로그인으로 돌리려고 빼는 변수. API 키가 있으면 Claude Code가 그 키로 과금해요
_DROP_ENV = ("CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT", "ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")


class ClaudeCliEngine:
    name = "claude_cli"

    def __init__(self, model=None, timeout=120):
        self.bin = shutil.which("claude")
        self.model = model or config.ENGINE_MODEL
        self.timeout = timeout

    def _env(self) -> dict:
        env = {k: v for k, v in os.environ.items() if k not in _DROP_ENV}
        env[INTERNAL_ENV] = "1"
        # 분류에는 긴 생각이 필요 없어요. 켜 두면 턴 6개에 50초 넘게 걸리고 출력 토큰을 8배 써요 (10/3 측정: 52초 → 10초)
        env["MAX_THINKING_TOKENS"] = "0"
        return env

    def _cwd(self):
        # 프로젝트의 CLAUDE.md나 설정이 섞이지 않게 빈 폴더에서 돌려요
        path = config.HOME / "engine"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def check(self) -> dict:
        """로그인 상태만 봐요. 모델은 부르지 않아요."""
        if not self.bin:
            return {"ok": False, "reason": "claude 명령을 찾지 못했어요. Claude Code를 설치하고 로그인하세요."}
        out = subprocess.run(
            [self.bin, "auth", "status"], capture_output=True, text=True, env=self._env(), timeout=30
        )
        try:
            status = json.loads(out.stdout)
        except ValueError:
            return {"ok": False, "reason": (out.stdout or out.stderr).strip()[:200]}
        return {
            "ok": bool(status.get("loggedIn")),
            "authMethod": status.get("authMethod"),
            "subscriptionType": status.get("subscriptionType"),
        }

    def complete_json(self, system: str, prompt: str, schema: dict) -> dict:
        """schema에 맞는 JSON 하나를 받아요."""
        self.last_usage = None            # 이번 호출에서 쓴 토큰 (backend/tokens.py가 적어요)
        if not self.bin:
            raise EngineError("claude 명령을 찾지 못했어요")
        cmd = [
            self.bin, "-p",
            "--model", self.model,
            "--safe-mode",                # hook · MCP · CLAUDE.md를 싣지 않음 (구독 로그인은 유지)
            "--tools", "",                # 분류는 도구가 필요 없어요
            "--strict-mcp-config",
            "--no-session-persistence",   # 엔진 호출이 내 Claude Code 대화 목록에 쌓이지 않게
            "--output-format", "json",
            "--system-prompt", system,
            "--json-schema", json.dumps(schema, ensure_ascii=False),
        ]
        try:
            out = subprocess.run(
                cmd, input=prompt, capture_output=True, text=True,
                env=self._env(), cwd=self._cwd(), timeout=self.timeout,
            )
        except subprocess.TimeoutExpired as exc:
            raise EngineError(f"Claude Code가 {self.timeout}초 안에 답하지 않았어요") from exc
        try:
            result = json.loads(out.stdout)
        except ValueError as exc:
            raise EngineError(f"Claude Code 출력을 읽지 못했어요: {(out.stdout or out.stderr)[:200]}") from exc
        self.last_usage = dict(result.get("usage") or {}, cost=result.get("total_cost_usd"), model=self.model)
        if result.get("is_error") or "structured_output" not in result:
            raise EngineError(str(result.get("result") or result)[:300])
        return result["structured_output"]
