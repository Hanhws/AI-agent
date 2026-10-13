"""구독 사용 한도: 5시간 · 이번 주에 얼마나 썼는지 (가닥 창 오른쪽 아래 게이지 · GET /limits). Claude는 아래쪽에.

ChatGPT(Codex): Codex가 이 PC에 남기는 세션 기록(rollout-*.jsonl)의 마지막 rate_limits를 읽어요. 읽기만 하고 밖으로 보내지 않아요.
값은 {"five_hour": {"used": 0~100, "resets_at": ISO 또는 None}, "week": {...}} 이거나 None(읽을 기록이 없음)이에요.
"""
import json
import sys
import time
from datetime import datetime, timezone

from . import config
from .sources import codex


def _pct(v):
    """0~100 사이 숫자만 받아요. 아니면 형식이 바뀐 거예요."""
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not 0 <= v <= 100:
        raise ValueError(v)
    return round(float(v), 1)


def _window(w, stamp, now):
    used = _pct(w.get("used_percent"))
    reset = w.get("resets_at")
    if reset is None and w.get("resets_in_seconds") is not None:
        reset = stamp + float(w["resets_in_seconds"])
    if reset is not None and float(reset) <= now:
        used = 0.0                        # 기록한 뒤 이미 풀렸어요
    return {"used": used, "resets_at": datetime.fromtimestamp(float(reset), timezone.utc).isoformat() if reset is not None else None}


def parse_codex(lines, now=None):
    """세션 기록 줄들에서 마지막 rate_limits (primary = 5시간 · secondary = 주간). 없으면 None."""
    now = time.time() if now is None else now
    for line in reversed(list(lines)):
        if '"rate_limits"' not in line:
            continue
        try:
            row = json.loads(line)
            limits = (row.get("payload") or {}).get("rate_limits") or {}
            stamp = datetime.fromisoformat(row["timestamp"].replace("Z", "+00:00")).timestamp() if row.get("timestamp") else now
            out = {name: _window(limits[key], stamp, now) for name, key in (("five_hour", "primary"), ("week", "secondary")) if limits.get(key)}
            if out:
                return out
        except (ValueError, KeyError, TypeError, AttributeError):
            continue
    return None


def codex_usage():
    try:
        files = sorted(codex.session_files(), key=lambda p: p.stat().st_mtime, reverse=True)[:3]
    except OSError:
        return None
    for path in files:
        try:
            with open(path, encoding="utf-8", errors="replace") as fh:
                got = parse_codex(fh.readlines()[-400:])
        except OSError:
            continue
        if got:
            return got
    return None


# ---------- Claude: Claude Code 로그인으로 Anthropic에 물어요 (Claude Code의 /usage와 같은 숫자) ----------
# CLAUDE.md의 예외 하나: 사용량을 읽을 때만 Claude Code의 열쇠를 키체인에서 읽고, api.anthropic.com에만 보내요.
# 열쇠는 메모리에만 두고 화면 · 기록에 내보내지 않아요. 공개 문서가 없는 주소라, 답이 조금이라도 다르면 None → 화면에서 Claude 칸을 지워요(10/11 결정).
CLAUDE_URL = "https://api.anthropic.com/api/oauth/usage"
CLAUDE_KEYCHAIN = "Claude Code-credentials"
CACHE_S = 60                                       # Anthropic에는 1분에 한 번까지만 물어요
_claude = {"at": 0.0, "value": None, "token": None, "until": 0.0}
# 마지막으로 읽은 값 (퍼센트 · 시각만). Claude Code 열쇠는 터미널의 claude를 쓸 때만 새로 바뀌어서 몇 시간 뒤면 만료돼요.
# 만료 · 연결 끊김 때는 이 값을 ‘몇 시 기준’으로 보여 줘요. 형식이 바뀐 것만은 저장한 값까지 지우고 칸을 없애요 (10/12 결정)
LAST = config.HOME / "limits-claude.json"


def _save_last(value):
    try:
        LAST.parent.mkdir(parents=True, exist_ok=True)
        LAST.write_text(json.dumps({"as_of": datetime.now(timezone.utc).isoformat(), "value": value}), encoding="utf-8")
    except OSError:
        pass


def stale_claude(now=None):
    """저장해 둔 마지막 값 + stale 표시. 그 뒤 이미 풀린 창은 0%로 봐요. 없으면 None."""
    now = time.time() if now is None else now
    try:
        saved = json.loads(LAST.read_text(encoding="utf-8"))
        out = {}
        for name in ("five_hour", "week"):
            w = dict(saved["value"][name])
            reset = w.get("resets_at")
            if reset and datetime.fromisoformat(reset.replace("Z", "+00:00")).timestamp() <= now:
                w.update(used=0.0, resets_at=None)
            out[name] = w
        out.update(stale=True, as_of=saved["as_of"])
        return out
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return None


def parse_claude(body):
    """Anthropic의 답 → 게이지 값. 형식이 다르면 ValueError."""
    return {name: {"used": _pct(body[key]["utilization"]), "resets_at": body[key].get("resets_at")}
            for name, key in (("five_hour", "five_hour"), ("week", "seven_day"))}


def _claude_token():
    if sys.platform != "darwin":
        return None                                # 키체인은 macOS에만 있어요. 다른 곳에서는 Claude 칸을 그리지 않아요
    if _claude["token"] and time.time() < _claude["until"]:
        return _claude["token"]
    import subprocess
    try:
        raw = subprocess.run(["/usr/bin/security", "find-generic-password", "-s", CLAUDE_KEYCHAIN, "-w"],
                             capture_output=True, text=True, timeout=20).stdout
        oauth = json.loads(raw)["claudeAiOauth"]
        until = float(oauth.get("expiresAt") or 0) / 1000 - 60
    except (OSError, subprocess.SubprocessError, ValueError, KeyError, TypeError):
        return None
    if until <= time.time():
        return None                                # 만료됐어요. Claude Code를 한 번 쓰면 새로 받아요
    _claude.update(token=oauth["accessToken"], until=until)
    return _claude["token"]


def claude_usage():
    if time.time() - _claude["at"] < CACHE_S:
        return _claude["value"]
    got, broken, token = None, False, _claude_token()
    if token:
        try:
            import httpx2
            r = httpx2.get(CLAUDE_URL, timeout=10.0, headers={"Authorization": f"Bearer {token}", "anthropic-beta": "oauth-2025-04-20"})
            if r.status_code == 401:
                _claude["token"] = None
            elif r.status_code == 200:
                got = parse_claude(r.json())
                _save_last(got)
            elif r.status_code == 404:
                broken = True                      # 주소가 없어졌어요
        except (ValueError, KeyError, TypeError, AttributeError):
            broken = True                          # 답의 형식이 바뀌었어요
        except Exception:                          # 닿지 않아요 (인터넷 · 서버)
            got = None
    if broken:
        LAST.unlink(missing_ok=True)               # 형식이 바뀌면 칸을 아예 없애요
    elif got is None:
        got = stale_claude()                       # 열쇠 만료 · 연결 끊김: 마지막 값을 ‘몇 시 기준’으로
    _claude.update(at=time.time(), value=got)
    return got


def usage():
    return {"claude": claude_usage(), "codex": codex_usage()}
