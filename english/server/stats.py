"""모인 사용 기록을 통계로 묶어요 (server/app.py의 /v1/stats).

들어오는 것은 backend/usage_schema.py의 표를 통과한 기록뿐이라 숫자 · 참거짓 · 정해 둔 낱말만 있어요.
같은 대화의 모양(chat)은 여러 번 올 수 있어서, 대화 표시(tag)마다 마지막 것만 세요.
"""
import collections

from backend.usage_schema import KINDS, SITES

TURN_BUCKETS = (("1~5", 1, 5), ("6~15", 6, 15), ("16~40", 16, 40), ("41 이상", 41, None))
PROJECT_BUCKETS = (("1", 1, 1), ("2~5", 2, 5), ("6 이상", 6, None))
ITEM_STEPS = ("made", "shown", "run", "later", "close")
TOOLS = ("get_request", "get_diff", "search_decisions", "list_open_items")


def _bucket(value, buckets) -> str:
    for label, low, high in buckets:
        if value >= low and (high is None or value <= high):
            return label
    return buckets[0][0]


def _share(part, whole) -> float:
    return round(part / whole, 3) if whole else 0.0


def _mean(total, count) -> float:
    return round(total / count, 1) if count else 0.0


def summarize(rows) -> dict:
    """rows: (install, seq, day, name, fields) 를 seq 순서로."""
    installs, per_day = set(), collections.defaultdict(lambda: {"installs": set(), "events": 0})
    opened, chats = {}, {}
    items = {kind: dict.fromkeys(ITEM_STEPS, 0) for kind in KINDS}
    ui, stops = collections.Counter(), collections.Counter()
    classify = collections.Counter()
    check, ended, tools = collections.Counter(), collections.Counter(), collections.Counter()
    events = 0
    for install, _seq, day, name, f in rows:
        events += 1
        installs.add(install)
        per_day[day]["installs"].add(install)
        per_day[day]["events"] += 1
        if name == "open":
            opened[install] = f                      # 그 PC의 가장 최근 모습
        elif name == "chat" and f.get("chat"):
            chats[(install, f["chat"])] = f
        elif name == "item" and f.get("kind") in items and f.get("did") in ITEM_STEPS:
            items[f["kind"]][f["did"]] += 1
        elif name == "ui" and f.get("what"):
            ui[f["what"]] += 1
        elif name == "classify":
            classify.update(calls=1, turns=f.get("turns", 0), done=f.get("done", 0), seconds=f.get("seconds", 0))
        elif name == "check":
            check.update(runs=1, steps=f.get("steps", 0), calls=f.get("calls", 0), seconds=f.get("seconds", 0),
                         made=1 if f.get("made") else 0)
            ended[f.get("ended", "odd")] += 1
            for tool in TOOLS:
                tools[tool] += f.get(tool, 0)
        elif name == "stop" and f.get("why"):
            stops[f["why"]] += 1

    shapes = list(chats.values())
    turns = collections.Counter(_bucket(s.get("turns", 0), TURN_BUCKETS) for s in shapes)
    grouped = collections.Counter(_bucket(s.get("in_project", 1), PROJECT_BUCKETS) for s in shapes)
    all_turns = sum(s.get("turns", 0) for s in shapes)
    return {
        "installs": len(installs),
        "events": events,
        "days": [{"day": day, "installs": len(v["installs"]), "events": v["events"]} for day, v in sorted(per_day.items())],
        "opened": {
            key: dict(collections.Counter(o.get(key) for o in opened.values() if o.get(key)))
            for key in ("via", "os", "engine")
        },
        "entrances": [
            {"site": site,
             "installs": sum(1 for o in opened.values() if o.get("chats_" + site.replace("-", "_"), 0) > 0),
             "chats": sum(o.get("chats_" + site.replace("-", "_"), 0) for o in opened.values())}
            for site in SITES
        ],
        "chats": {
            "count": len(shapes),
            "turns": [{"label": label, "count": turns[label]} for label, _, _ in TURN_BUCKETS],
            "in_project": [{"label": label, "count": grouped[label]} for label, _, _ in PROJECT_BUCKETS],
            "by_site": [{"site": site, "count": sum(1 for s in shapes if s.get("site") == site)} for site in SITES],
            "with_side": _share(sum(1 for s in shapes if s.get("side", 0) > 0), len(shapes)),
            "with_decision": _share(sum(1 for s in shapes if s.get("decided", 0) > 0), len(shapes)),
            "with_multi": _share(sum(1 for s in shapes if s.get("multi", 0) > 0), len(shapes)),
            "with_files": _share(sum(1 for s in shapes if s.get("files", 0) > 0), len(shapes)),
            "side_turns": _share(sum(s.get("side", 0) for s in shapes), all_turns),
            "decided_turns": _share(sum(s.get("decided", 0) for s in shapes), all_turns),
        },
        "items": [dict(kind=kind, **steps) for kind, steps in items.items() if any(steps.values())],
        "ui": [{"what": what, "count": count} for what, count in ui.most_common()],
        "classify": {
            "calls": classify["calls"], "turns": classify["turns"], "done": classify["done"],
            "kept": _share(classify["done"], classify["turns"]), "seconds": _mean(classify["seconds"], classify["calls"]),
        },
        "check": {
            "runs": check["runs"], "made": check["made"], "made_share": _share(check["made"], check["runs"]),
            "steps": _mean(check["steps"], check["runs"]), "seconds": _mean(check["seconds"], check["runs"]),
            "ended": dict(ended), "tools": [{"tool": tool, "count": tools[tool]} for tool in TOOLS],
        },
        "stops": dict(stops),
    }
