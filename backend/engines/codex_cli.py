"""ChatGPT 구독(Plus · Pro)을 쓰는 엔진.

내 PC에 로그인된 Codex를 `codex exec`로 불러요. API 키가 없어도 되고, ChatGPT 구독의 Codex 사용 한도를 같이 써요.
Codex는 터미널 명령으로 깔려 있지 않아도 돼요. VS Code · Cursor의 ChatGPT 확장 안에 들어 있는 것과,
가닥이 받아 둔 것(~/.gadak/bin · backend/engines/connect.py)도 찾아 써요. 서버에 배포한 가닥에서는 쓸 수 없어요.
"""
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from .. import config
from . import BadOutput, EngineError

ENV_BIN = "GADAK_CODEX_BIN"       # 쓸 실행 파일을 직접 정할 때. none이면 찾지 않아요 (시험할 때)
# 구독 로그인으로 돌리려고 빼는 변수. API 키가 있으면 Codex가 그 키로 과금해요
_DROP_ENV = ("OPENAI_API_KEY", "CODEX_API_KEY")
# 가닥의 모델 이름(작은 것 · 중간 · 큰 것)은 Codex에서 생각 깊이로 옮겨요. 모델 자체는 Codex가 고르는 기본값을 써요
EFFORT = {"haiku": "low", "sonnet": "medium", "opus": "high"}
# 답 앞에 붙이는 말. Codex는 코딩 에이전트라서, 파일을 뒤지거나 명령을 돌리지 말고 형식대로만 답하게 해요
PREFIX = "아래 지시와 입력만 보고 답해. 파일을 읽거나 명령을 돌리는 도구는 쓰지 마. 정해 준 형식의 JSON 하나만 답해.\n\n"
LOGIN_WORDS = ("not logged in", "login required", "unauthorized", "401", "codex login", "sign in")


def extension_bins() -> list:
    """VS Code · Cursor의 ChatGPT 확장에 들어 있는 Codex. 새 판이 앞에 와요."""
    found = []
    for editor in (".vscode", ".cursor", ".vscode-insiders"):
        found += (Path.home() / editor / "extensions").glob("openai.chatgpt-*/bin/*/codex")
    return sorted((p for p in found if os.access(p, os.X_OK)), key=lambda p: p.stat().st_mtime, reverse=True)


def find_bin():
    """쓸 수 있는 Codex 실행 파일. 없으면 None."""
    named = os.environ.get(ENV_BIN)
    if named is not None:
        return named if named.lower() not in ("", "none") and os.access(named, os.X_OK) else None
    onpath = shutil.which("codex")
    if onpath:
        return onpath
    for spot in (config.HOME / "bin" / "codex", Path.home() / ".local" / "bin" / "codex",
                 Path("/opt/homebrew/bin/codex"), Path("/usr/local/bin/codex")):
        if os.access(spot, os.X_OK):
            return str(spot)
    inside = extension_bins()
    return str(inside[0]) if inside else None


class CodexCliEngine:
    name = "codex_cli"

    def __init__(self, model=None, timeout=180, effort=None):
        self.bin = find_bin()
        self.model = model or config.ENGINE_MODEL      # 가닥의 모델 이름 그대로 (판단 기록에 남아요)
        self.timeout = timeout
        self.effort = effort      # 생각 깊이(low · medium · high). 비우면 모델 이름에서 정해요
        self.last = None          # 마지막 호출의 토큰 수 (정확도 평가가 봐요). 구독이라 값은 몰라요
        self.last_usage = None    # 마지막 호출이 쓴 토큰을 종류별로 (backend/tokens.py가 적어요)

    def _env(self) -> dict:
        return {k: v for k, v in os.environ.items() if k not in _DROP_ENV}

    def _cwd(self):
        # 프로젝트의 AGENTS.md나 코드가 섞이지 않게 빈 폴더에서 돌려요
        path = config.HOME / "engine"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def check(self) -> dict:
        """로그인 상태만 봐요. 모델은 부르지 않아요."""
        if not self.bin:
            return {"ok": False, "reason": "Codex를 찾지 못했어요. AI 연결에서 ChatGPT 구독을 연결해 주세요."}
        try:
            out = subprocess.run([self.bin, "login", "status"], capture_output=True, text=True, env=self._env(), timeout=30)
        except (OSError, subprocess.SubprocessError) as exc:
            return {"ok": False, "reason": str(exc)[:200]}
        said = (out.stdout + out.stderr).strip()
        ok = out.returncode == 0 and "logged in" in said.lower() and "not logged in" not in said.lower()
        method = "chatgpt" if "chatgpt" in said.lower() else ("api_key" if "api key" in said.lower() else None)
        return {"ok": ok, "authMethod": method} if ok else {"ok": False, "reason": said[:200] or "Codex에 로그인되어 있지 않아요."}

    def complete_json(self, system: str, prompt: str, schema: dict) -> dict:
        """schema에 맞는 JSON 하나를 받아요."""
        self.last_usage = None
        if not self.bin:
            raise EngineError("Codex를 찾지 못했어요. AI 연결에서 ChatGPT 구독을 다시 연결해 주세요.")
        with tempfile.TemporaryDirectory(prefix="gadak-codex-") as tmp:
            shape, answer = Path(tmp) / "schema.json", Path(tmp) / "answer.json"
            shape.write_text(json.dumps(schema, ensure_ascii=False), encoding="utf-8")
            cmd = [
                self.bin, "exec",
                "--ephemeral",                 # 엔진 호출이 내 Codex 대화 목록에 쌓이지 않게 (가닥이 그 기록을 다시 읽지 않게)
                "--skip-git-repo-check",
                "--ignore-user-config",        # 내 MCP · 설정을 싣지 않음 (로그인은 유지)
                "--ignore-rules",
                "--sandbox", "read-only",      # 무엇도 고치지 못해요
                "--color", "never",
                "--json",                      # 쓴 토큰과 오류를 읽으려고 걸음마다 받아요
                "--output-schema", str(shape),
                "-o", str(answer),
                "-C", str(self._cwd()),
                "-c", f'model_reasoning_effort="{self.effort or EFFORT.get(self.model, "low")}"',
            ]
            if config.CODEX_MODEL:
                cmd += ["-m", config.CODEX_MODEL]
            try:
                out = subprocess.run(
                    cmd + ["-"], input=PREFIX + system + "\n\n입력:\n" + prompt, capture_output=True, text=True,
                    env=self._env(), cwd=self._cwd(), timeout=self.timeout,
                )
            except subprocess.TimeoutExpired as exc:
                raise EngineError(f"Codex가 {self.timeout}초 안에 답하지 않았어요") from exc
            except OSError as exc:
                raise EngineError(f"Codex를 켜지 못했어요: {exc}") from exc
            events = self._events(out.stdout)
            self._used(events)
            text = answer.read_text(encoding="utf-8").strip() if answer.is_file() else ""
        if out.returncode != 0 or not text:
            self._trouble(events, out)
        try:
            data = json.loads(text)
        except ValueError as exc:
            raise BadOutput("엔진이 정해 준 형식으로 답하지 않았어요: " + text[:120]) from exc
        if not isinstance(data, dict):
            raise BadOutput("엔진이 정해 준 형식으로 답하지 않았어요")
        return data

    @staticmethod
    def _events(stdout) -> list:
        events = []
        for line in (stdout or "").splitlines():
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if isinstance(event, dict):
                events.append(event)
        return events

    def _used(self, events) -> None:
        """쓴 토큰. Codex의 input_tokens에는 캐시에서 읽은 것이 들어 있어서 빼고 적어요 (backend/tokens.py의 칸에 맞춰요)."""
        used = next((e.get("usage") for e in reversed(events) if e.get("type") == "turn.completed" and isinstance(e.get("usage"), dict)), None)
        if not used:
            return
        number = lambda key: int(used.get(key) or 0)
        cached = number("cached_input_tokens")
        self.last = {"input_tokens": number("input_tokens"), "output_tokens": number("output_tokens"), "cost": None}
        self.last_usage = {"input_tokens": max(number("input_tokens") - cached, 0), "cache_read_input_tokens": cached,
                           "cache_creation_input_tokens": number("cache_write_input_tokens"), "output_tokens": number("output_tokens"),
                           "cost": None, "model": config.CODEX_MODEL or "codex"}

    @staticmethod
    def _trouble(events, out) -> None:
        said = ""
        for event in reversed(events):
            if event.get("type") in ("error", "turn.failed"):
                inner = event.get("error") if isinstance(event.get("error"), dict) else event
                said = str(inner.get("message") or "")
                break
        said = said or (out.stderr or out.stdout or "").strip()[-300:]
        low = said.lower()
        if any(word in low for word in LOGIN_WORDS):
            raise EngineError("Codex에 로그인되어 있지 않아요. AI 연결에서 ChatGPT 구독을 다시 연결해 주세요.")
        if not said:
            raise BadOutput("엔진이 답을 내지 않았어요")
        raise EngineError(said[:300])                 # 사용 한도 같은 것
