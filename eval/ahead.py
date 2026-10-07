"""앞길 살피기의 쓸모 재기 (backend/agent/ahead.py · ‘생각 못 한 방법 추천’).

가닥이 낸 길이 쓸 만한지는 정답 파일로 잴 수 없어요(정답에 ‘앞길’이 없어요). 그래서 사람 둘이 매겨요.

1) 돌리기 — 예시 대화를 1단으로 정리한 다음, 갈림길마다 그 턴에 서서(그 뒤의 대화는 못 보게) 앞길을 살펴요
   python -m eval.ahead run                   u1, 갈림길 10곳까지. 1단은 지금 모델, 앞길은 앞길 모델(GADAK_AHEAD_MODEL · 기본 sonnet)
   python -m eval.ahead run --max 3 --web     세 곳만, 웹에서도 찾아보게
   python -m eval.ahead run --model haiku --tag haiku     앞길을 다른 모델로
   python -m eval.ahead run --db eval/local/u1.db         1단으로 정리한 기록을 남겨 두고, 다음부터는 그걸 다시 써요 (1단 호출을 아껴요)
   python -m eval.ahead run --records ~/.gadak/gadak.db   예시 대신 내가 쓰는 가닥의 기록에서 (읽기만 하고 복사본으로 돌려요. 1단은 건너뛰어요)
   python -m eval.ahead run --db eval/local/u1.db --from 6 --append   멈춘 데서 이어서: 여섯째 갈림길부터 살피고 있던 시트 뒤에 붙여요
   python -m eval.ahead run --scenario u4 --append        다른 대화의 길을 같은 시트에 더해요 (10개를 채울 때)
   → eval/local/앞길-시트.csv (길마다 한 줄) · eval/results/앞길-<시나리오>-<모델>.json (숫자만)
2) 매기기 — 두 사람이 시트를 각자 복사해서, 서로 보지 않고 두 칸을 채워요
   쓸모   1 쓸 만해요 · 0 아니에요 (뻔해요 · 틀렸어요 · 이미 아는 거예요)
   갔나   ‘그 뒤 실제 대화’를 보고, 실제로 그 길로 갔으면 1 · 아니면 0 · 모르겠으면 비워요
3) 견주기
   python -m eval.ahead compare eval/local/앞길-A.csv eval/local/앞길-B.csv
   → 둘 다 쓸모 있다고 한 길의 비율 (켤 기준: 10개 이상 매겨서 70% 이상) · 일치도 κ · 실제로 간 길의 비율

엔진을 실제로 불러요(Claude 구독 엔진이면 구독 사용량). 58턴에 1단 8번쯤 + 갈림길마다 최대 AHEAD_STEPS번 + 웹은 갈림길마다 2번까지.
시트에는 실제 대화 글이 들어 있어요. eval/local/ 밖에 두지 말고, 커밋하지 마요.
"""
import argparse
import csv
import json
import shutil
import sqlite3
import sys
import tempfile
import time
from collections import Counter
from datetime import datetime
from pathlib import Path

from backend import config, replay, store
from backend.agent import ahead, classify, tools
from backend.engines import BadOutput, EngineError, get_engine, resolve_name
from backend.runtime import Runtime

from . import agree
from . import run as runner

HERE = Path(__file__).resolve().parent
EXAMPLE = config.ROOT / "data" / "example_conversations.json"
DEMO = config.ROOT / "data" / "demo_conversations.json"
RESULTS = HERE / "results"
LOCAL = HERE / "local"
COLUMNS = ("번호", "턴", "살핀 까닭", "대화", "지금 턴", "가닥이 읽은 목적지", "종류", "길", "까닭", "근거", "찾아본 것",
           "보낼 글", "그 뒤 실제 대화", "쓸모", "갔나", "메모")
WHY_NAMES = {"decided": "방금 정함", "stage": "구간이 바뀜", "asked": "다음 할 일을 물음", "button": "누름"}
AFTER = 5             # ‘그 뒤 실제 대화’에 싣는 턴 수
BAR, NEED = 0.7, 10   # 켤 기준: 둘 다 쓸모 있다고 한 길이 70% 이상, 매긴 길이 10개 이상


def junctions(conn, chat_ids) -> list:
    """갈림길 [(턴, 까닭)]. 실제로 쓸 때처럼 대화마다 간격을 지켜요 (ahead.due와 같은 규칙. 마지막 턴 · 방금 일인지는 따지지 않아요)."""
    out = []
    for chat_id in chat_ids:
        rows, last = store.chat_turns(conn, chat_id), None
        for row in rows:
            if row["classified"] != 1 or sum(1 for r in rows if r["seq"] < row["seq"]) < ahead.MIN_BEFORE:
                continue
            why = ahead.reason(row["user"], row["dec"], row["seg"], row["depth"])
            if why is None:
                continue
            gap = ahead.ASK_GAP if why == "asked" else config.AHEAD_EVERY
            if last is not None and row["seq"] - last < gap:
                continue
            out.append((row, why))
            last = row["seq"]
    return out


def spread(items, limit) -> list:
    """많으면 대화의 앞 · 가운데 · 뒤에서 고루 골라요."""
    if limit is None or len(items) <= limit:
        return list(items)
    if limit <= 1:
        return list(items[:max(limit, 0)])
    return [items[round(i * (len(items) - 1) / (limit - 1))] for i in range(limit)]


def _clip(text, limit):
    text = " ".join((text or "").split())
    return text if len(text) <= limit else text[:limit - 1] + "…"


def what_came_after(conn, row) -> str:
    rows = conn.execute("SELECT title, user FROM turns WHERE chat_id = ? AND seq > ? ORDER BY seq LIMIT ?",
                        (row["chat_id"], row["seq"], AFTER)).fetchall()
    return "\n".join(f"{n}. {r['title']} — {_clip(r['user'], 70)}" for n, r in enumerate(rows, 1)) or "(대화가 여기서 끝나요)"


def sheet_rows(conn, n, row, why, result) -> list:
    """길마다 한 줄. 길을 하나도 내지 않은 갈림길도 한 줄 남겨요(매기지는 않아요)."""
    chat = store.chat_row(conn, row["chat_id"])
    head = [n, row["message_ref"], WHY_NAMES.get(why, why), chat["title"] or chat["id"], _clip(row["user"], 240),
            result.get("goal") or ""]
    after = what_came_after(conn, row)
    if not result["paths"]:
        return [head + ["—", "(길을 내지 않았어요)", "", "", "", "", after, "", "", ""]]
    out = []
    for path in result["paths"]:
        found = "\n".join(f"· {f['line']} ({'기록' if f['from'] == 'turn' else f['source']})" for f in path["found"])
        out.append(head + [ahead.LABELS[path["kind"]], path["title"], path["why"],
                           " / ".join(b["title"] for b in path["basis"]), found, path["ask"], after, "", "", ""])
    return out


def snapshot(source, target) -> None:
    """가닥의 기록을 읽기 전용으로 열어 통째로 떠 와요. 켜져 있는 가닥이 쓰고 있는 파일이어도 원본은 건드리지 않아요."""
    src = sqlite3.connect(f"file:{Path(source).expanduser()}?mode=ro", uri=True, timeout=5)
    dst = sqlite3.connect(target)
    try:
        src.backup(dst)
    finally:
        src.close()
        dst.close()


def run(scenario, engine, limit=10, web=False, max_calls=150, say=None, labeler=None, db=None, records=None,
        start=1, number=0) -> dict:
    """시나리오를 1단으로 정리하고, 갈림길마다 앞길을 살펴요. 돌려주는 것: rows(시트 줄) · numbers(숫자만) · raw · error.
    engine은 앞길을 살피는 엔진, labeler는 1단(분류)에 쓸 엔진이에요(비우면 같은 엔진). 실제로 쓸 때도 둘의 모델이 달라요.
    db를 주면 1단으로 정리한 기록을 거기 남기고, 이미 있으면 1단을 건너뛰고 그 기록에서 시작해요(대화 글이 든 파일이에요).
    records를 주면 시나리오 대신 그 가닥 기록(이미 정리된 것)에서 갈림길을 골라요. 목록에서 뺀 대화는 보지 않아요.
    start는 고른 갈림길 중 몇째부터 살필지(멈춘 데서 이을 때), number는 시트의 번호를 어디서부터 이어 매길지예요."""
    meter = runner.Meter(engine)
    label = runner.Meter(labeler) if labeler is not None else meter
    rows, raw, error = [], [], None
    made, dropped, ended, used = Counter(), 0, Counter(), Counter()
    kept = config.AHEAD
    config.AHEAD = False                      # 1단이 도는 동안에는 걸지 않아요. 갈림길은 아래에서 따로 골라요
    try:
        with tempfile.TemporaryDirectory() as tmp:
            kept_db = Path(db) if db else None
            ready = Path(records).expanduser() if records else kept_db if kept_db is not None and kept_db.is_file() else None
            if ready is not None:
                snapshot(ready, Path(tmp) / "gadak.db")
            rt = Runtime(Path(tmp) / "gadak.db", engine=label)
            clf = classify.Classifier(rt, label, max_calls=max_calls)
            rt.classifier = clf
            conn = rt.connect()
            try:
                if ready is not None:
                    chats = [r["id"] for r in conn.execute("SELECT id FROM chats WHERE hidden = 0 ORDER BY created_at, rowid")]
                    if say:
                        say(f"정리해 둔 기록에서 시작해요 ({ready.name} · 대화 {len(chats)}개)")
                else:
                    chats = replay.feed(conn, scenario)["chats"]
                    for chat_id in chats:
                        clf.request(chat_id)
                    while clf.queue and not clf.status["paused"]:
                        clf.step(conn)
                        if say:
                            say(f"1단 {clf.status['turns']}턴 · 호출 {label.calls['classify']}번")
                    clf.checker.queue.clear()     # 2단의 다른 확인(빠진 요청 · 요청 외 변경 · 이어 가기)은 여기서 재지 않아요
                    unlabeled = conn.execute("SELECT COUNT(*) FROM turns WHERE classified != 1").fetchone()[0]
                    if kept_db is not None and not clf.status["error"] and not unlabeled:
                        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                        kept_db.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copyfile(Path(tmp) / "gadak.db", kept_db)
                    elif kept_db is not None and say:
                        say(f"1단이 못 붙인 턴이 {unlabeled}개 있어서 기록을 남기지 않았어요. 다시 돌리면 1단부터 해요")
                error = clf.status["error"]
                found = junctions(conn, chats)
                picked = spread(found, limit)[max(start, 1) - 1:] if not error else []
                for n, (row, why) in enumerate(picked, max(start, 1) + number):
                    if label.calls["classify"] + meter.calls["ahead"] + label.calls["lookup"] >= max_calls:
                        error = f"호출 한도(--max-calls {max_calls})에 닿아 {sum(ended.values())}곳까지만 살폈어요."
                        break
                    ctx = tools.Context(conn, row)
                    ctx.until = row["created_at"]
                    if web and callable(getattr(label, "research", None)):
                        ctx.lookup = label.research       # 웹에서 찾아 간추리는 일은 1단 · 2단의 (작은) 모델로 해요
                    try:
                        result = ahead.scout(ctx, why, meter.complete_json)
                    except BadOutput:
                        ended["bad"] += 1
                        continue
                    except EngineError as exc:
                        error = " ".join(str(exc).split())[:200]
                        break
                    rows += sheet_rows(conn, n, row, why, result)
                    raw.append({"n": n, "turn": row["message_ref"], "why": why, "goal": result["goal"], "paths": result["paths"],
                                "dropped": result["dropped"], "tools": [s["tool"] for s in result["steps"]],
                                "calls": result["calls"], "ended": result["ended"]})
                    made.update(p["kind"] for p in result["paths"])
                    dropped += sum(1 for d in result["dropped"] if "길은 남겼어요" not in d["why"])
                    ended[result["ended"]] += 1
                    used.update(s["tool"] for s in result["steps"])
                    if say:
                        say(f"갈림길 {sum(ended.values())}/{len(picked)} · 길 {len(result['paths'])}개 · 호출 {meter.calls['ahead']}번"
                            + (f" · 웹 {label.calls['lookup']}번" if label.calls["lookup"] else ""))
                turns = conn.execute("SELECT COUNT(*) FROM turns WHERE classified = 1").fetchone()[0]
            finally:
                conn.close()
    finally:
        config.AHEAD = kept
    looked = sum(ended.values())
    stats = meter.stats()
    if label is not meter:                    # 1단을 다른 엔진으로 돌렸으면 그쪽에서 센 것을 합쳐요
        mine = label.stats()
        for stage in ("classify", "lookup"):
            stats["calls"][stage], stats["seconds"][stage] = mine["calls"][stage], mine["seconds"][stage]
        stats["label_model"] = mine["model"]
        if "cost_usd" in mine or "cost_usd" in stats:
            stats["cost_usd"] = round(stats.get("cost_usd", 0) + mine.get("cost_usd", 0), 4)
    numbers = {
        "turns": turns, "junctions": len(found), "by_why": dict(Counter(why for _, why in found)),
        "looked": looked, "paths": sum(made.values()), "by_kind": dict(made), "silent": sum(1 for r in raw if not r["paths"]),
        "with_found": sum(1 for r in raw for p in r["paths"] if p["found"]),
        "dropped": dropped, "cut_lines": sum(1 for r in raw for d in r["dropped"] if "길은 남겼어요" in d["why"]),
        "ended": dict(ended), "tools": dict(used), "web": bool(web and callable(getattr(label, "research", None))),
        "steps": config.AHEAD_STEPS, "every": config.AHEAD_EVERY, "stats": stats,
    }
    return {"rows": rows, "numbers": numbers, "raw": raw, "error": error}


def write_sheet(path, rows) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8-sig", newline="") as file:        # 엑셀에서 한글이 깨지지 않게
        sheet = csv.writer(file)
        sheet.writerow(COLUMNS)
        sheet.writerows(rows)


def _mark(text):
    text = (text or "").strip()
    return {"1": 1, "0": 0}.get(text[:1]) if text else None


def read_sheet(path) -> dict:
    """{번호:턴:종류: {useful, went, kind}} — 길이 있는 줄만."""
    out = {}
    with open(path, encoding="utf-8-sig", newline="") as file:
        for row in csv.DictReader(file):
            kind = (row.get("종류") or "").strip()
            if not row.get("번호") or kind in ("", "—"):
                continue
            key = f"{row['번호'].strip()}:{(row.get('턴') or '').strip()}:{kind}"
            out[key] = {"useful": _mark(row.get("쓸모")), "went": _mark(row.get("갔나")), "kind": kind}
    return out


def sheet_so_far(path) -> list:
    """이미 있는 시트의 줄들 (--append로 뒤에 붙일 때). 없으면 빈 목록."""
    try:
        with open(path, encoding="utf-8-sig", newline="") as file:
            rows = list(csv.reader(file))
    except OSError:
        return []
    return rows[1:] if rows and tuple(rows[0]) == COLUMNS else []


def compare(one, two) -> dict:
    ids = [k for k in one if k in two and one[k]["useful"] is not None and two[k]["useful"] is not None]
    a, b = [one[k]["useful"] for k in ids], [two[k]["useful"] for k in ids]
    both = sum(1 for x, y in zip(a, b) if x and y)
    rate = round(both / len(ids), 4) if ids else None
    kinds = {}
    for kind in sorted({one[k]["kind"] for k in ids}):
        mine = [k for k in ids if one[k]["kind"] == kind]
        kinds[kind] = {"of": len(mine), "both": sum(1 for k in mine if one[k]["useful"] and two[k]["useful"])}
    gone = [k for k in ids if one[k]["went"] is not None and two[k]["went"] is not None]
    return {
        "paths": len(ids), "unrated": len(set(one) | set(two)) - len(ids),
        "both": both, "rate": rate, "one": sum(a), "two": sum(b),
        "same": sum(1 for x, y in zip(a, b) if x == y), "kappa": agree.kappa(a, b), "by_kind": kinds,
        "went": {"of": len(gone), "both": sum(1 for k in gone if one[k]["went"] and two[k]["went"])},
        "useful_but_new": sum(1 for k in gone if one[k]["useful"] and two[k]["useful"]
                              and not one[k]["went"] and not two[k]["went"]),
        "enough": len(ids) >= NEED, "passed": len(ids) >= NEED and rate is not None and rate >= BAR,
    }


def pct(hit, of) -> str:
    return "–" if not of else f"{hit / of * 100:.0f}% ({hit}/{of})"


def show(result) -> str:
    n = result["paths"]
    kappa = "–" if result["kappa"] is None else f"{result['kappa']:.2f}"
    lines = [
        f"둘 다 매긴 길 {n}개" + (f" (한쪽만 매겼거나 안 매긴 길 {result['unrated']}개는 뺐어요)" if result["unrated"] else ""),
        f"  둘 다 쓸모 있다고 한 길   {pct(result['both'], n)}",
        f"  한 사람씩                 첫째 {pct(result['one'], n)} · 둘째 {pct(result['two'], n)} · 같게 매긴 길 {pct(result['same'], n)} · κ {kappa}",
        "  종류별(둘 다 쓸모)        " + (" · ".join(f"{kind} {v['both']}/{v['of']}" for kind, v in result["by_kind"].items()) or "–"),
        f"  실제로 그 길로 감         {pct(result['went']['both'], result['went']['of'])}"
        f" · 가지 않았지만 쓸모 있다고 한 길 {result['useful_but_new']}개 (‘생각 못 한 길’)",
    ]
    if not result["enough"]:
        lines.append(f"  아직 정할 수 없어요: 매긴 길이 {NEED}개가 안 돼요.")
    elif result["passed"]:
        lines.append(f"  켤 기준({BAR * 100:.0f}% 이상)을 넘었어요.")
    else:
        lines.append(f"  켤 기준({BAR * 100:.0f}% 이상)에 못 미쳐요. 꺼 둔 채로 둬요.")
    return "\n".join(lines)


def report(key, numbers) -> str:
    stats, by = numbers["stats"], numbers["by_kind"]
    calls, seconds = stats["calls"], stats["seconds"]
    lines = [
        f"{key} · {numbers['turns']}턴 · {stats['engine']} / {stats['model']}"
        + (f" (1단은 {stats['label_model']})" if stats.get("label_model") and stats["label_model"] != stats["model"] else "")
        + (" · 웹에서도 찾아봄" if numbers["web"] else ""),
        f"  갈림길 {numbers['junctions']}곳 ({' · '.join(f'{WHY_NAMES.get(k, k)} {v}' for k, v in numbers['by_why'].items()) or '없음'})"
        f" 중 {numbers['looked']}곳을 살폈어요",
        f"  낸 길 {numbers['paths']}개 ({' · '.join(f'{ahead.LABELS[k]} {by[k]}' for k in ahead.KINDS if by.get(k)) or '없음'})"
        f" · 찾아본 것이 붙은 길 {numbers['with_found']}개 · 길을 내지 않은 곳 {numbers['silent']}곳",
        f"  버린 길 {numbers['dropped']}개 · 출처가 없어 뺀 줄이 있는 길 {numbers['cut_lines']}개",
        f"  호출 1단 {calls['classify']}번 ({seconds['classify']:.0f}초) · 앞길 {calls['ahead']}번 ({seconds['ahead']:.0f}초)"
        f" · 웹 {calls['lookup']}번 ({seconds['lookup']:.0f}초)" + (f" · API로 치면 약 ${stats['cost_usd']:.3f}" if "cost_usd" in stats else ""),
    ]
    return "\n".join(lines)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="python -m eval.ahead", description="앞길 살피기의 쓸모 재기")
    sub = parser.add_subparsers(dest="what", required=True)
    go = sub.add_parser("run", help="갈림길마다 앞길을 살피고 매길 시트를 만들어요")
    go.add_argument("--scenario", default=None)
    go.add_argument("--data", default=None)
    go.add_argument("--demo", action="store_true")
    go.add_argument("--model", default=None, help="앞길을 살필 모델 (기본: GADAK_AHEAD_MODEL)")
    go.add_argument("--label-model", default=None, help="1단(분류)에 쓸 모델 (기본: 지금 가닥의 모델)")
    go.add_argument("--engine", default=None)
    go.add_argument("--max", type=int, default=10, help="살필 갈림길 수 (많으면 고루 골라요)")
    go.add_argument("--web", action="store_true", help="웹에서도 찾아보게 해요 (검색어가 밖으로 나가요)")
    go.add_argument("--max-calls", type=int, default=150)
    go.add_argument("--timeout", type=float, default=300)
    go.add_argument("--out", default=None, help="시트를 둘 곳 (기본 eval/local/앞길-시트.csv)")
    go.add_argument("--db", default=None, help="1단으로 정리한 기록을 남기고 다시 쓸 파일 (대화 글이 들어 있어요. eval/local/ 안에 둬요)")
    go.add_argument("--records", default=None, help="예시 대신 쓸 가닥 기록 (예: ~/.gadak/gadak.db). 읽기만 하고 복사본으로 돌려요")
    go.add_argument("--from", dest="start", type=int, default=1, help="고른 갈림길 중 몇째부터 살필지 (멈춘 데서 이을 때)")
    go.add_argument("--append", action="store_true", help="있던 시트의 뒤에 붙여요 (번호를 이어 매겨요)")
    go.add_argument("--tag", default="")
    both = sub.add_parser("compare", help="두 사람이 매긴 시트 견주기")
    both.add_argument("one")
    both.add_argument("two")
    args = parser.parse_args(argv)

    if args.what == "compare":
        one, two = read_sheet(args.one), read_sheet(args.two)
        if not one or not two:
            print("길이 든 줄이 없는 시트가 있어요.")
            return 2
        print(show(compare(one, two)))
        print("κ는 우연히 맞을 만큼을 뺀 일치도예요. 길의 수가 적으면 크게 흔들려요.")
        return 0

    path = Path(args.data) if args.data else (DEMO if args.demo else EXAMPLE)
    key = args.scenario or ("demo" if args.demo else "u1")
    scenario = None
    if args.records:
        path, key = Path(args.records).expanduser(), "내기록"
        if not path.is_file():
            print(f"가닥 기록이 없어요: {path}")
            return 2
    elif not path.is_file():
        print(f"예시 파일이 없어요: {path}\n실제 대화가 든 파일이라 저장소에 없어요. 만든 예시로 돌려 보려면: python -m eval.ahead run --demo")
        return 2
    else:
        try:
            scenario = runner.load(path, key)
        except KeyError:
            print(f"{path.name}에 ‘{key}’ 시나리오가 없어요.")
            return 2
    name = resolve_name(args.engine)
    if name == "none":
        print("엔진이 없어요. Claude Code에 로그인하거나 API 키를 넣어 주세요 (docs/usage-guide.md 3장).")
        return 2
    model = args.model or config.AHEAD_MODEL or config.ENGINE_MODEL
    try:
        engine = type(get_engine(name))(model=model, timeout=args.timeout)
        labeler = type(get_engine(name))(model=args.label_model or config.ENGINE_MODEL, timeout=args.timeout)
    except EngineError as exc:
        print(exc)
        return 2
    if hasattr(engine, "effort"):
        engine.effort = config.AHEAD_EFFORT        # 실제로 쓸 때와 같은 깊이로 (backend/agent/investigate.py의 scout_engine)
    print(f"앞길 살피기 재기 · " + ("내 가닥 기록 (읽기만 해요)" if args.records else f"{path.name}의 {key}"))
    began = time.time()
    sheet = Path(args.out) if args.out else LOCAL / ("-".join(x for x in ("앞길-시트", "내기록" if args.records else "", args.tag) if x) + ".csv")
    before = sheet_so_far(sheet) if args.append else []
    numbers = [int(r[0]) for r in before if r and str(r[0]).isdigit()]
    # 멈춘 데서 잇는 것(--from)이면 갈림길의 차례가 곧 번호예요. 다른 대화를 더하는 것이면 있던 번호 뒤부터 매겨요
    offset = max(numbers, default=0) if args.append and args.start <= 1 else 0
    out = run(scenario, engine, limit=args.max, web=args.web, max_calls=args.max_calls,
              say=lambda text: print("   …", text, flush=True), labeler=labeler, db=args.db, records=args.records,
              start=args.start, number=offset)
    print(report(key, out["numbers"]))
    if out["error"]:
        print("  ! 끝까지 돌지 못했어요:", out["error"])
    stamp = datetime.now().strftime("%Y%m%d-%H%M")
    label = "-".join(x for x in ("앞길", key, str(model), args.tag) if x)
    if out["rows"]:
        write_sheet(sheet, before + out["rows"])
        LOCAL.mkdir(exist_ok=True)
        (LOCAL / f"{label}-{stamp}.json").write_text(json.dumps(out["raw"], ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        print(f"  시트: {sheet}\n  두 사람이 각자 복사해서 ‘쓸모’(1 · 0)와 ‘갔나’(1 · 0 · 비움)를 채운 다음: python -m eval.ahead compare A.csv B.csv")
        print("  실제 대화 글이 들어 있으니 eval/local/ 밖에 두지 말고 커밋하지 마요.")
    if not out["error"] and args.start <= 1:      # 이어서 돈 것은 전체의 숫자가 아니라서 남기지 않아요
        RESULTS.mkdir(exist_ok=True)
        body = {"at": stamp, "scenario": key, "data": "records" if args.records else path.name, "seconds": round(time.time() - began, 1), "prompt": config.CODE,
                **out["numbers"]}
        (RESULTS / f"{label}.json").write_text(json.dumps(body, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"  남김: eval/results/{label}.json")
    return 1 if out["error"] else 0


if __name__ == "__main__":
    sys.exit(main())
