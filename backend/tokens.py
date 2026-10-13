"""가닥이 엔진에 쓴 토큰과, 같은 대화에서 내 LLM이 쓴 토큰을 견줘요 (실험용).

엔진 호출마다 <가닥 홈>/engine_usage.jsonl에 한 줄씩 적어요. 내 PC에만 남고 서버로 보내지 않아요.
내 LLM 쪽은 Claude Code 기록(~/.claude/projects/*/<대화>.jsonl)의 답마다 붙은 usage를 읽어요.
    python -m backend.tokens        # 대화별 표
"""
import collections
import json
import sys
import time
from pathlib import Path

LOG = "engine_usage.jsonl"
FIELDS = ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens", "output_tokens")
SHORT = ("in", "cache_w", "cache_r", "out")


def record(home, kind, chat, usage) -> None:
    if not usage:
        return
    line = {"at": time.time(), "kind": kind, "chat": chat, "model": usage.get("model"), "cost": usage.get("cost"),
            **{s: int(usage.get(f) or 0) for f, s in zip(FIELDS, SHORT)}}
    try:
        with open(Path(home) / LOG, "a", encoding="utf-8") as out:
            out.write(json.dumps(line) + "\n")
    except OSError:
        pass                         # 실험 기록이 정리를 막으면 안 돼요


def gadak_usage(home) -> dict:
    """대화 id → 호출 종류 → 토큰 합."""
    out = collections.defaultdict(lambda: collections.defaultdict(collections.Counter))
    path = Path(home) / LOG
    for raw in path.read_text(encoding="utf-8").splitlines() if path.is_file() else []:
        try:
            line = json.loads(raw)
        except ValueError:
            continue
        bucket = out[line.get("chat")][line.get("kind")]
        bucket.update({s: line.get(s, 0) for s in SHORT}, calls=1)
        bucket["cost_micro"] += round((line.get("cost") or 0) * 1e6)
    return out


def llm_usage(session_file) -> collections.Counter:
    """Claude Code 기록 하나에서 내 LLM이 쓴 토큰. 한 답이 여러 줄로 나뉘어 적혀서 답 id로 한 번만 세요."""
    total, seen = collections.Counter(), set()
    for raw in Path(session_file).read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            message = json.loads(raw).get("message") or {}
        except (ValueError, AttributeError):
            continue
        usage = message.get("usage") if isinstance(message, dict) else None
        if not usage or message.get("id") in seen or message.get("model") == "<synthetic>":
            continue
        seen.add(message.get("id"))
        total.update({s: int(usage.get(f) or 0) for f, s in zip(FIELDS, SHORT)}, replies=1)
    return total


def report(home, projects_root, titles=None) -> list:
    """가닥이 정리한 대화마다 {chat, title, llm, gadak, by_kind}."""
    rows = []
    for chat, kinds in gadak_usage(home).items():
        files = list(Path(projects_root).glob(f"*/{chat}.jsonl")) if chat else []
        if not files:
            continue                 # Claude Code 대화만 견줄 수 있어요 (웹 대화는 토큰 기록이 없어요)
        gadak = sum(kinds.values(), collections.Counter())
        rows.append({"chat": chat, "title": (titles or {}).get(chat) or chat[:8], "llm": llm_usage(files[0]),
                     "gadak": gadak, "by_kind": kinds})
    return rows


def _sum(c, keys=SHORT):
    return sum(c[k] for k in keys)


def main() -> None:
    import sqlite3
    from . import config
    from .sources import claude_code
    titles = {}
    try:
        titles = dict(sqlite3.connect(config.DB_PATH).execute("SELECT id, title FROM chats").fetchall())
    except sqlite3.Error:
        pass
    rows = report(config.HOME, claude_code.root(), titles)
    if not rows:
        sys.exit("아직 견줄 기록이 없어요. 가닥을 켠 채로 Claude Code 대화를 몇 턴 해 보세요.")
    head = f"{'대화':<24} {'내 LLM 전체':>12} {'캐시 뺀':>10} {'가닥 전체':>10} {'캐시 뺀':>9} {'비율(전체)':>9} {'비율(캐시 뺀)':>11}  가닥 비용"
    print(head)
    fresh = ("in", "cache_w", "out")
    totals = [collections.Counter(), collections.Counter()]
    for r in sorted(rows, key=lambda r: -_sum(r["llm"])):
        totals[0].update(r["llm"]); totals[1].update(r["gadak"])
        lt, lf, gt, gf = _sum(r["llm"]), _sum(r["llm"], fresh), _sum(r["gadak"]), _sum(r["gadak"], fresh)
        print(f"{r['title'][:24]:<24} {lt:>12,} {lf:>10,} {gt:>10,} {gf:>9,} {gt / max(lt, 1):>9.1%} {gf / max(lf, 1):>11.1%}"
              f"  ${r['gadak']['cost_micro'] / 1e6:.4f}")
    lt, lf, gt, gf = _sum(totals[0]), _sum(totals[0], fresh), _sum(totals[1]), _sum(totals[1], fresh)
    print(f"{'합계':<24} {lt:>12,} {lf:>10,} {gt:>10,} {gf:>9,} {gt / max(lt, 1):>9.1%} {gf / max(lf, 1):>11.1%}"
          f"  ${totals[1]['cost_micro'] / 1e6:.4f}")
    kinds = collections.defaultdict(collections.Counter)
    for r in rows:
        for kind, c in r["by_kind"].items():
            kinds[kind].update(c)
    print("\n가닥 호출 종류별:", ", ".join(f"{k} {c['calls']}번 {_sum(c):,}토큰" for k, c in sorted(kinds.items(), key=str)))
    print("캐시 뺀 = 새로 읽은 입력 + 캐시에 쓴 입력 + 출력. 내 LLM과 가닥(Haiku)은 모델이 달라 토큰 값이 달라요.")


if __name__ == "__main__":
    main()
