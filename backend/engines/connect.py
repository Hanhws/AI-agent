"""‘AI 연결’의 한 번 누르기: 구독으로 쓰는 엔진(Claude Code · Codex)을 대신 받고, 로그인 창을 띄워요.

사용자가 화면에서 ‘연결하기’를 눌렀을 때만 돌아요. 터미널을 열 일이 없게 하려는 것이에요. 하는 일은 셋이에요.

1. 없으면 받기 — Claude Code는 Anthropic의 공식 설치 스크립트(CLAUDE_INSTALLER)를 받아 돌려요(받은 파일의 검사는 그 스크립트가 해요).
   Codex는 OpenAI의 공식 배포 파일(CODEX_RELEASE)을 받아 ~/.gadak/bin에 풀어요. 둘 다 https로, 적어 둔 주소에서만 받아요.
2. 로그인 — `claude auth login` · `codex login`을 띄워요. 브라우저가 열리고, 로그인은 사용자가 거기서 해요.
   가닥은 암호도 토큰도 보지 않아요. 로그인은 그 도구가 자기 자리에 보관해요.
3. 다 되면 불러 준 쪽(backend/app.py)이 그 엔진을 고른 것으로 적어요.

한 번에 하나만 돌아요. 어디까지 갔는지는 status()로 봐요 (화면이 GET /engine으로 물어요).
"""
import os
import platform
import shutil
import ssl
import subprocess
import sys
import tarfile
import tempfile
import threading
import time
import urllib.request
from pathlib import Path

from .. import config

CLAUDE_INSTALLER = "https://claude.ai/install.sh"
CODEX_RELEASE = "https://github.com/openai/codex/releases/latest/download/codex-{arch}-apple-darwin.tar.gz"
NAMES = {"claude_cli": "Claude Code", "codex_cli": "Codex"}
INSTALL_SECONDS = 600       # 받는 데 주는 시간
LOGIN_SECONDS = 300         # 브라우저에서 로그인을 마칠 때까지 기다리는 시간
SCRIPT_MAX = 200_000        # 설치 스크립트로 보기에는 너무 큰 답은 돌리지 않아요

_lock = threading.Lock()
_job = {"name": None, "step": None, "state": "idle", "message": "", "at": 0.0}
_running = {"process": None, "stop": False}


class Problem(RuntimeError):
    """연결하지 못한 까닭. 글은 화면에 한 줄로 보여 줘도 되는 말이에요."""


def status() -> dict:
    """{name, step: install · login · None, state: idle · running · done · failed, message}"""
    with _lock:
        return dict(_job)


def _say(**fields) -> None:
    with _lock:
        _job.update(fields, at=time.time())


def start(name, done=None) -> dict:
    """연결을 시작해요(뒤에서 돌아요). done(name)은 다 됐을 때 한 번 불려요."""
    if name not in NAMES:
        return {"ok": False, "reason": "구독으로 연결할 수 있는 것은 Claude와 ChatGPT예요."}
    with _lock:
        if _job["state"] == "running":
            return {"ok": False, "reason": f"{NAMES[_job['name']]}를 연결하는 중이에요. 끝난 뒤에 다시 눌러 주세요."}
        _job.update(name=name, step=None, state="running", message="준비하고 있어요…", at=time.time())
        _running.update(process=None, stop=False)
    threading.Thread(target=_run, args=(name, done), daemon=True).start()
    return {"ok": True}


def cancel() -> None:
    """기다리던 것을 그만두고(로그인 창을 닫았을 때), 끝난 결과도 치워요."""
    _running["stop"] = True
    process = _running["process"]
    if process is not None and process.poll() is None:
        process.terminate()
    with _lock:
        _job.update(name=None, state="idle", step=None, message="", at=time.time())


def _run(name, done) -> None:
    from . import forget_logins
    try:
        if _find(name) is None:
            _say(step="install", message=f"{NAMES[name]}를 받고 있어요. 1~2분 걸려요…")
            (_install_claude if name == "claude_cli" else _install_codex)()
            if _find(name) is None:
                raise Problem(f"{NAMES[name]}를 받았는데 찾지 못했어요. 가닥을 껐다 켠 뒤 다시 눌러 주세요.")
        forget_logins()
        if not _logged_in(name):
            _say(step="login", message="브라우저에서 로그인을 마쳐 주세요. 끝나면 여기가 저절로 바뀌어요.")
            _login(name)
            forget_logins()
            if not _running["stop"] and not _logged_in(name):
                raise Problem("로그인이 끝나지 않았어요. 브라우저에서 로그인을 마친 뒤 다시 눌러 주세요.")
        forget_logins()
        if _running["stop"]:
            return
        if done:
            done(name)
        _say(step=None, state="done", message="연결했어요.")
    except Problem as exc:
        if not _running["stop"]:
            _say(step=None, state="failed", message=str(exc))
    except Exception as exc:                                       # 예상하지 못한 것도 화면에 한 줄로
        if not _running["stop"]:
            _say(step=None, state="failed", message=f"연결하지 못했어요: {str(exc)[:160]}")
    finally:
        _running["process"] = None
        forget_logins()


def _find(name):
    from . import claude_cli, codex_cli
    return claude_cli.find_bin() if name == "claude_cli" else codex_cli.find_bin()


def _logged_in(name) -> bool:
    from . import claude_cli, codex_cli
    engine = claude_cli.ClaudeCliEngine() if name == "claude_cli" else codex_cli.CodexCliEngine()
    try:
        return bool(engine.check().get("ok"))
    except Exception:
        return False


def _trust():
    """https 인증서를 확인할 때 쓸 것. python.org의 파이썬은 Mac의 인증서를 몰라서, 같이 깔린 certifi의 것을 써요."""
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return ssl.create_default_context()


def _fetch(url, target, what) -> None:
    """https 주소의 파일을 받아 target에 적어요. 받는 동안 얼마나 받았는지 알려요."""
    if not url.startswith("https://"):
        raise Problem("https 주소에서만 받아요.")
    try:
        _download(url, target, what)
    except Problem:
        raise
    except Exception as exc:
        # 파이썬이 인증서를 확인하지 못하는 Mac이 있어요. 그때는 Mac에 들어 있는 curl로 받아요 (Mac의 인증서를 써요)
        curl = "/usr/bin/curl"
        if not os.access(curl, os.X_OK):
            raise Problem(f"{what}를 받지 못했어요. 인터넷을 확인하고 다시 눌러 주세요. ({str(exc)[:80]})") from exc
        _say(message=f"{what}를 받고 있어요…")
        done = _wait(subprocess.Popen([curl, "-fsSL", "--proto", "=https", "--max-time", str(INSTALL_SECONDS), "-o", str(target), url],
                                      stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True),
                     INSTALL_SECONDS + 10, f"{what}를 받는 데 너무 오래 걸려요. 인터넷을 확인하고 다시 눌러 주세요.")
        if done.returncode != 0:
            raise Problem(f"{what}를 받지 못했어요. 인터넷을 확인하고 다시 눌러 주세요.") from exc


def _download(url, target, what) -> None:
    request = urllib.request.Request(url, headers={"User-Agent": "gadak"})
    with urllib.request.urlopen(request, timeout=60, context=_trust()) as response, open(target, "wb") as out:
        total, got, began = int(response.headers.get("Content-Length") or 0), 0, time.time()
        while True:
            if _running["stop"]:
                raise Problem("그만뒀어요.")
            if time.time() - began > INSTALL_SECONDS:
                raise Problem(f"{what}를 받는 데 너무 오래 걸려요. 인터넷을 확인하고 다시 눌러 주세요.")
            chunk = response.read(1 << 16)
            if not chunk:
                break
            out.write(chunk)
            got += len(chunk)
            if total:
                _say(message=f"{what}를 받고 있어요 · {got * 100 // total}%")


def _mac_only() -> None:
    if sys.platform != "darwin":
        raise Problem("이 컴퓨터에서는 대신 받아 줄 수 없어요. 그 도구의 안내대로 설치한 뒤 다시 눌러 주세요.")


def _install_claude() -> None:
    """Anthropic의 공식 설치 스크립트를 받아 돌려요. ~/.local/bin/claude가 생겨요."""
    _mac_only()
    with tempfile.TemporaryDirectory(prefix="gadak-claude-") as tmp:
        script = Path(tmp) / "install.sh"
        _fetch(CLAUDE_INSTALLER, script, "Claude Code 설치 파일")
        text = script.read_text(encoding="utf-8", errors="replace")
        if not text.startswith("#!") or "claude" not in text.lower() or len(text) > SCRIPT_MAX:
            raise Problem("받은 설치 파일이 평소와 달라서 돌리지 않았어요. 잠시 뒤에 다시 눌러 주세요.")
        _say(message="Claude Code를 받아 설치하고 있어요. 1~2분 걸려요…")
        out = _wait(subprocess.Popen(["/bin/bash", str(script)], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                     stderr=subprocess.STDOUT, text=True, env=dict(os.environ)), INSTALL_SECONDS,
                    "Claude Code를 설치하는 데 너무 오래 걸려요. 다시 눌러 주세요.")
        if out.returncode != 0:
            tail = " ".join((out.stdout_text or "").split())[-160:]
            raise Problem(f"Claude Code를 설치하지 못했어요. {tail}")


def _install_codex() -> None:
    """OpenAI의 공식 배포 파일을 받아 ~/.gadak/bin/codex로 풀어요."""
    _mac_only()
    arch = "aarch64" if platform.machine() == "arm64" else "x86_64"
    with tempfile.TemporaryDirectory(prefix="gadak-codex-") as tmp:
        packed = Path(tmp) / "codex.tar.gz"
        _fetch(CODEX_RELEASE.format(arch=arch), packed, "Codex")
        _say(message="Codex를 풀고 있어요…")
        try:
            with tarfile.open(packed) as archive:
                inside = [m for m in archive.getmembers() if m.isfile() and Path(m.name).name.startswith("codex")]
                if len(inside) != 1:
                    raise Problem("받은 Codex 파일이 평소와 달라서 쓰지 않았어요.")
                source = archive.extractfile(inside[0])
                target = config.HOME / "bin" / "codex"
                target.parent.mkdir(parents=True, exist_ok=True)
                with open(str(target) + ".new", "wb") as out:
                    shutil.copyfileobj(source, out)
        except (tarfile.TarError, OSError) as exc:
            raise Problem(f"Codex를 풀지 못했어요. ({str(exc)[:80]})") from exc
        os.chmod(str(target) + ".new", 0o755)
        os.replace(str(target) + ".new", target)
    try:
        ok = subprocess.run([str(target), "--version"], capture_output=True, text=True, timeout=30).returncode == 0
    except (OSError, subprocess.SubprocessError):
        ok = False
    if not ok:
        target.unlink(missing_ok=True)
        raise Problem("받은 Codex가 이 Mac에서 켜지지 않았어요.")


def _login(name) -> None:
    """로그인 명령을 띄우고 끝날 때까지 기다려요. 브라우저는 그 도구가 열어요."""
    command = [_find(name), "auth", "login"] if name == "claude_cli" else [_find(name), "login"]
    try:
        process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                   text=True, env=dict(os.environ))
    except OSError as exc:
        raise Problem(f"로그인 창을 띄우지 못했어요. ({str(exc)[:80]})") from exc
    late = "5분 안에 로그인이 끝나지 않았어요. 다시 눌러 주세요."
    _wait(process, LOGIN_SECONDS, late, until=lambda: _logged_in(name))


def _wait(process, seconds, late, until=None):
    """명령이 끝나기를 기다려요. 그만두라고 했거나(stop) 너무 오래 걸리면 끝내요. until이 참이 되어도 다 된 것으로 봐요."""
    _running["process"] = process
    began, checked = time.time(), time.time()
    try:
        while process.poll() is None:
            if _running["stop"]:
                process.terminate()
                raise Problem("그만뒀어요.")
            if time.time() - began > seconds:
                process.terminate()
                raise Problem(late)
            if until and time.time() - checked > 2:
                checked = time.time()
                if until():
                    time.sleep(0.5)              # 로그인을 받아 적을 틈
                    if process.poll() is None:
                        process.terminate()
                    break
            time.sleep(0.5)
    finally:
        try:
            process.stdout_text = process.stdout.read() if process.stdout else ""
        except (OSError, ValueError):
            process.stdout_text = ""
        _running["process"] = None
    return process
