"""API 키를 두는 곳: macOS 키체인.

키를 .env 같은 파일에 글자 그대로 두지 않아요. 로그인 키체인에 넣고, 쓸 때 꺼내요 (/usr/bin/security).
넣어 두는 키는 하나예요. 어느 회사 키인지는 키의 앞머리로 알아봐요 (Anthropic · OpenAI · Google Gemini).
키체인이 없는 운영체제에서는 저장하지 않고, 환경 변수 GADAK_API_KEY(예전 이름 ANTHROPIC_API_KEY)가 있으면 그것만 써요.
키는 화면 · 기록 · 사용 기록 어디에도 내보내지 않아요. 보여 주는 것은 앞머리와 끝 네 글자뿐이에요(hint).
"""
import os
import re
import subprocess
import sys
import time
from pathlib import Path

SECURITY = "/usr/bin/security"
ACCOUNT = "api-key"
OLD_ACCOUNT = "anthropic-api-key"     # Anthropic 키만 받던 때(10/8까지)의 자리. 거기 남은 키도 읽어요
ENV = "GADAK_API_KEY"
# 뒤의 것은 예전부터 보던 이름이에요. 다른 도구에 쓰려고 둔 OPENAI_API_KEY 같은 것은 보지 않아요 (가닥에게 준 키만 써요)
ENVS = (ENV, "ANTHROPIC_API_KEY")
# 키 앞머리 → 회사. 위에서부터 봐요 (sk-ant-는 sk-보다 먼저). None은 가닥이 못 쓰는 키예요 (OpenRouter)
# Gemini는 2026-05-28부터 AI Studio가 AQ.로 시작하는 키를 줘요. 그 전에 만든 키는 AIza로 시작해요
HEADS = (("sk-ant-", "anthropic"), ("sk-or-", None), ("sk-", "openai"), ("AIza", "gemini"), ("AQ.", "gemini"))
COMPANIES = {"anthropic": "Anthropic", "openai": "OpenAI", "gemini": "Gemini"}      # 화면에 보이는 이름
ENGINES = {"anthropic": "anthropic_api", "openai": "openai_api", "gemini": "gemini_api"}
# 키체인 명령에 넣어도 되는 글자만. 모양은 앞머리까지만 봐요: 회사가 키의 길이나 생김새를 바꿔도 받게요 (맞는 키인지는 그 회사가 답해요)
SHAPE = re.compile(r"[A-Za-z0-9_\-.]{20,400}")
WRONG_SHAPE = "API 키 모양이 아니에요. Anthropic · OpenAI · Gemini의 키를 넣어 주세요."      # 화면에 한 줄로 떠요
REMEMBER = 20.0       # 초. 키체인을 이 간격으로만 다시 물어요 (엔진을 고를 때마다 명령을 띄우지 않게)
_seen = {"at": 0.0, "service": None, "key": None}


class KeyStoreError(RuntimeError):
    """키를 저장하거나 지우지 못했어요. 글은 화면에 한 줄로 보여 줘도 되는 말이에요."""


def service() -> str:
    """키체인 항목의 이름. 시험할 때는 GADAK_KEYCHAIN_SERVICE로 딴 이름을 써요 (쓰던 키를 건드리지 않게)."""
    return os.environ.get("GADAK_KEYCHAIN_SERVICE", "local.gadak.app")


def can_store() -> bool:
    return sys.platform == "darwin" and Path(SECURITY).exists()


def company(key):
    """어느 회사 키인지 (anthropic · openai · gemini). 가닥이 받는 모양이 아니면 None."""
    if not isinstance(key, str) or SHAPE.fullmatch(key) is None:
        return None
    return next((who for head, who in HEADS if key.startswith(head)), None)


def looks_right(key) -> bool:
    return company(key) is not None


def whose(key) -> str:
    """갖고 있는 키가 어느 회사 것인지. 모르는 모양은 Anthropic으로 봐요 (환경 변수 ANTHROPIC_API_KEY로 받던 키)."""
    return company(key) or "anthropic"


def _read(account):
    out = subprocess.run([SECURITY, "find-generic-password", "-s", service(), "-a", account, "-w"],
                         capture_output=True, text=True, timeout=10)
    return (out.stdout.strip() if out.returncode == 0 else "") or None


def _stored(fresh=False):
    if not can_store():
        return None
    if not fresh and _seen["service"] == service() and time.time() - _seen["at"] < REMEMBER:
        return _seen["key"]
    try:
        key = _read(ACCOUNT) or _read(OLD_ACCOUNT)
    except (OSError, subprocess.SubprocessError):
        return None
    _seen.update(at=time.time(), service=service(), key=key)
    return key


def find():
    """(키, 어디서 왔는지). 키체인이 먼저, 없으면 환경 변수. 둘 다 없으면 (None, None)."""
    key = _stored()
    if key:
        return key, "keychain"
    for name in ENVS:
        key = (os.environ.get(name) or "").strip()
        if key:
            return key, "env"
    return None, None


def get(who=None):
    """쓸 키. who(회사)를 주면 그 회사 키일 때만 줘요 — 한 회사의 키를 다른 회사로 보내지 않게요."""
    key = find()[0]
    return key if key and (who is None or whose(key) == who) else None


def engine():
    """갖고 있는 키로 쓸 엔진 이름 (anthropic_api · openai_api · gemini_api). 키가 없으면 None."""
    key = get()
    return ENGINES[whose(key)] if key else None


def save(key) -> None:
    """키체인에 넣어요(있으면 바꿔요). 키는 명령 줄이 아니라 표준 입력으로 넘겨서 프로세스 목록에 보이지 않아요."""
    if not looks_right(key):
        raise KeyStoreError(WRONG_SHAPE)
    if not can_store():
        raise KeyStoreError(f"이 컴퓨터에는 키를 넣어 둘 키체인이 없어요. 환경 변수 {ENV}로 넘겨 주세요.")
    command = f'add-generic-password -U -s "{service()}" -a "{ACCOUNT}" -l "가닥 · LLM API 키" -w "{key}"\n'
    try:
        out = subprocess.run([SECURITY, "-i"], input=command, capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.SubprocessError) as exc:
        raise KeyStoreError("키체인에 넣지 못했어요.") from exc
    if out.returncode != 0 or _stored(fresh=True) != key:
        raise KeyStoreError("키체인에 넣지 못했어요. 키체인 접근을 허용했는지 확인해 주세요.")
    _remove(OLD_ACCOUNT)      # 예전 자리의 키는 치워요 (새 키를 지웠을 때 되살아나지 않게)


def _remove(account) -> bool:
    try:
        out = subprocess.run([SECURITY, "delete-generic-password", "-s", service(), "-a", account],
                             capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return False
    return out.returncode == 0


def delete() -> bool:
    """키체인에서 지워요. 지운 것이 있으면 True."""
    if not can_store():
        return False
    removed = [_remove(account) for account in (ACCOUNT, OLD_ACCOUNT)]
    _seen["at"] = 0.0
    return any(removed)


def hint(key) -> str:
    """키를 알아볼 만큼만: 앞머리와 끝 네 글자."""
    if not key:
        return ""
    return next((head for head, who in HEADS if who and key.startswith(head)), "") + "…" + key[-4:]


def describe() -> dict:
    key, source = find()
    return {"stored": bool(key), "source": source, "hint": hint(key), "can_store": can_store(),
            "company": COMPANIES[whose(key)] if key else None}
