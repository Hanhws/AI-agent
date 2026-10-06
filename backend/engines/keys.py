"""API 키를 두는 곳: macOS 키체인.

키를 .env 같은 파일에 글자 그대로 두지 않아요. 로그인 키체인에 넣고, 쓸 때 꺼내요 (/usr/bin/security).
키체인이 없는 운영체제에서는 저장하지 않고, 환경 변수 ANTHROPIC_API_KEY가 있으면 그것만 써요.
키는 화면 · 기록 · 사용 기록 어디에도 내보내지 않아요. 보여 주는 것은 끝 네 글자뿐이에요(hint).
"""
import os
import re
import subprocess
import sys
import time
from pathlib import Path

SECURITY = "/usr/bin/security"
ACCOUNT = "anthropic-api-key"
ENV = "ANTHROPIC_API_KEY"
SHAPE = re.compile(r"sk-ant-[A-Za-z0-9_\-]{16,300}")      # 키체인 명령에 넣어도 되는 글자만
REMEMBER = 20.0       # 초. 키체인을 이 간격으로만 다시 물어요 (엔진을 고를 때마다 명령을 띄우지 않게)
_seen = {"at": 0.0, "service": None, "key": None}


class KeyStoreError(RuntimeError):
    """키를 저장하거나 지우지 못했어요. 글은 화면에 한 줄로 보여 줘도 되는 말이에요."""


def service() -> str:
    """키체인 항목의 이름. 시험할 때는 GADAK_KEYCHAIN_SERVICE로 딴 이름을 써요 (쓰던 키를 건드리지 않게)."""
    return os.environ.get("GADAK_KEYCHAIN_SERVICE", "local.gadak.app")


def can_store() -> bool:
    return sys.platform == "darwin" and Path(SECURITY).exists()


def looks_right(key) -> bool:
    return isinstance(key, str) and SHAPE.fullmatch(key) is not None


def _stored(fresh=False):
    if not can_store():
        return None
    if not fresh and _seen["service"] == service() and time.time() - _seen["at"] < REMEMBER:
        return _seen["key"]
    try:
        out = subprocess.run([SECURITY, "find-generic-password", "-s", service(), "-a", ACCOUNT, "-w"],
                             capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    key = out.stdout.strip() if out.returncode == 0 else ""
    _seen.update(at=time.time(), service=service(), key=key or None)
    return key or None


def find():
    """(키, 어디서 왔는지). 키체인이 먼저, 없으면 환경 변수. 둘 다 없으면 (None, None)."""
    key = _stored()
    if key:
        return key, "keychain"
    key = (os.environ.get(ENV) or "").strip()
    return (key, "env") if key else (None, None)


def get():
    return find()[0]


def save(key) -> None:
    """키체인에 넣어요(있으면 바꿔요). 키는 명령 줄이 아니라 표준 입력으로 넘겨서 프로세스 목록에 보이지 않아요."""
    if not looks_right(key):
        raise KeyStoreError("API 키 모양이 아니에요. sk-ant-로 시작하는 키를 넣어 주세요.")
    if not can_store():
        raise KeyStoreError(f"이 컴퓨터에는 키를 넣어 둘 키체인이 없어요. 환경 변수 {ENV}로 넘겨 주세요.")
    command = f'add-generic-password -U -s "{service()}" -a "{ACCOUNT}" -l "가닥 · Anthropic API 키" -w "{key}"\n'
    try:
        out = subprocess.run([SECURITY, "-i"], input=command, capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.SubprocessError) as exc:
        raise KeyStoreError("키체인에 넣지 못했어요.") from exc
    if out.returncode != 0 or _stored(fresh=True) != key:
        raise KeyStoreError("키체인에 넣지 못했어요. 키체인 접근을 허용했는지 확인해 주세요.")


def delete() -> bool:
    """키체인에서 지워요. 지운 것이 있으면 True."""
    if not can_store():
        return False
    try:
        out = subprocess.run([SECURITY, "delete-generic-password", "-s", service(), "-a", ACCOUNT],
                             capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return False
    _seen["at"] = 0.0
    return out.returncode == 0


def hint(key) -> str:
    """키를 알아볼 만큼만: 끝 네 글자."""
    return "sk-ant-…" + key[-4:] if key else ""


def describe() -> dict:
    key, source = find()
    return {"stored": bool(key), "source": source, "hint": hint(key), "can_store": can_store()}
