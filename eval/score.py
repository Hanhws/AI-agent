"""정답과 견주기.

정답은 예시 파일의 시나리오예요(사람이 확정한 depth · dec · parts · todo). 가닥이 붙인 값은 화면이 받는 것과
같은 모양(store.view)에서 읽어요. 턴은 messageRef(= 정답 파일의 턴 id)로 맞춰요.

지표 넷 (docs/agent-prompt.md 5장)
- depth 정확도   턴마다 본류(0) · 곁길(1) · 곁길 안의 곁길(2)이 정답과 같은 비율.
                 본류가 대부분이라, 전부 본류라고 답했을 때의 값(baseline)과 곁길만 따로 센 값을 같이 봐요.
- dec 재현율     정답에 ‘정함’이 있는 턴 중 가닥도 정함을 붙인 턴의 비율. 글이 같은지는 보지 않아요.
                 남발하면 재현율이 저절로 높아지니 정밀도(가닥이 붙인 정함 중 맞은 비율)를 같이 봐요.
- parts 개수 일치율  턴마다 나눈 요청의 수가 정답과 같은 비율(나누지 않은 턴은 0개).
                 대부분의 턴은 요청이 하나라서, 정답에서 요청이 여럿인 턴만 따로 센 값을 같이 봐요.
- items 정밀도   가닥이 만든 한마디 중 정답에도 있는 것(같은 턴 · 같은 종류)의 비율. 1에서 빼면 쓸데없는 한마디 비율.
                 빠진 요청(parts.open)도 한마디로 세요. 새 대화를 열 때의 제안(startTodo)은 그 대화의 첫 턴에 단 것으로 봐요.
"""
from backend import store

# 지금 가닥이 만드는 한마디의 종류: 2단(backend/agent/investigate.py)의 셋 + 규칙(backend/agent/rules.py)의 셋.
# next는 앞길 살피기가 만들지만(누를 때 · 저절로 살피기를 켠 동안) 이 평가에서는 돌지 않아요
MADE = ("missing", "unasked", "handoff") + store.RULE_KINDS


def _files(turn) -> list:
    return [f["n"] if isinstance(f, dict) else f for f in turn.get("files") or []]


def gold_turns(scenario) -> dict:
    """{턴 id: 정답 칸}. 차례는 대화 · 턴 순서."""
    out = {}
    for chat in scenario["chats"]:
        for turn in chat["turns"]:
            out[turn["id"]] = {
                "chat": chat["id"], "depth": turn.get("depth") or 0, "dec": bool(turn.get("dec")),
                "parts": len(turn.get("parts") or []), "ret": bool(turn.get("ret")),
            }
    return out


def gold_items(scenario) -> set:
    """정답의 한마디: {(턴 id, 종류)}."""
    out = set()
    for chat in scenario["chats"]:
        for turn in chat["turns"]:
            out.update((turn["id"], item["kind"]) for item in turn.get("todo") or [])
            if any(part.get("open") for part in turn.get("parts") or []):
                out.add((turn["id"], "missing"))
    start = scenario.get("startTodo")
    if start and scenario["chats"]:
        active = next((c for c in scenario["chats"] if c.get("active")), scenario["chats"][-1])
        if active["turns"]:
            out.add((active["turns"][0]["id"], start["kind"]))
    return out


def made_turns(view) -> dict:
    """가닥이 붙인 값: {턴 id(messageRef): 칸}. 아직 분류되지 않은 턴은 pending이에요."""
    out = {}
    for chat in view["chats"]:
        for turn in chat["turns"]:
            out[turn["messageRef"]] = {
                "depth": turn.get("depth") or 0, "dec": bool(turn.get("dec")),
                "parts": len(turn.get("parts") or []), "ret": bool(turn.get("ret")),
            }
    return out


def made_items(view) -> set:
    out = set()
    for chat in view["chats"]:
        for turn in chat["turns"]:
            out.update((turn["messageRef"], item["kind"]) for item in turn.get("todo") or [])
            if any(part.get("open") for part in turn.get("parts") or []):
                out.add((turn["messageRef"], "missing"))
    return out


def _rate(hit, of):
    return round(hit / of, 4) if of else None


def score(scenario, view, exclude=(), unlabeled=()) -> dict:
    """지표 넷과, 그 숫자를 읽는 데 필요한 곁 숫자들. exclude는 재지 않을 턴 id(프롬프트 예시로 쓴 턴).
    unlabeled는 가닥이 분류하지 못한 턴이에요. 빼지 않고 화면에 보이는 그대로(본류 · 정함 없음 · 나누지 않음) 세요."""
    gold, made = gold_turns(scenario), made_turns(view)
    skip = set(exclude)
    ids = [i for i in gold if i not in skip and i in made]
    lost = [i for i in gold if i not in skip and i not in made]

    def count(test):
        return sum(1 for i in ids if test(gold[i], made[i]))

    n = len(ids)
    side_gold = count(lambda g, m: g["depth"] > 0)
    side_said = count(lambda g, m: m["depth"] > 0)
    side_hit = count(lambda g, m: g["depth"] > 0 and m["depth"] > 0)
    dec_gold, dec_said = count(lambda g, m: g["dec"]), count(lambda g, m: m["dec"])
    dec_hit = count(lambda g, m: g["dec"] and m["dec"])
    split_gold = count(lambda g, m: g["parts"] >= 2)
    split_said = count(lambda g, m: m["parts"] >= 2)
    split_hit = count(lambda g, m: g["parts"] >= 2 and m["parts"] >= 2)
    split_same = count(lambda g, m: g["parts"] >= 2 and m["parts"] == g["parts"])

    want = {(i, kind) for i, kind in gold_items(scenario) if i not in skip}
    got = {(i, kind) for i, kind in made_items(view) if i not in skip}
    right = want & got
    kinds = sorted({kind for _, kind in want | got})
    return {
        "turns": n, "excluded": len(skip & set(gold)), "unread": len(lost),
        "unlabeled": sum(1 for i in ids if i in set(unlabeled)),
        "depth": {
            "right": count(lambda g, m: g["depth"] == m["depth"]), "of": n,
            "acc": _rate(count(lambda g, m: g["depth"] == m["depth"]), n),
            "baseline": _rate(n - side_gold, n),          # 전부 본류라고 답했을 때
            "side": {"gold": side_gold, "said": side_said, "hit": side_hit,
                     "recall": _rate(side_hit, side_gold), "precision": _rate(side_hit, side_said)},
        },
        "dec": {"gold": dec_gold, "said": dec_said, "hit": dec_hit,
                "recall": _rate(dec_hit, dec_gold), "precision": _rate(dec_hit, dec_said)},
        "parts": {
            "right": count(lambda g, m: g["parts"] == m["parts"]), "of": n,
            "rate": _rate(count(lambda g, m: g["parts"] == m["parts"]), n),
            "split": {"gold": split_gold, "said": split_said, "hit": split_hit, "same": split_same},
        },
        "items": {
            "made": len(got), "right": len(right), "precision": _rate(len(right), len(got)),
            "gold": len(want), "gold_made_kinds": sum(1 for _, kind in want if kind in MADE),
            "by_kind": {kind: {"gold": sum(1 for _, k in want if k == kind), "made": sum(1 for _, k in got if k == kind),
                               "right": sum(1 for _, k in right if k == kind)} for kind in kinds},
        },
    }


def details(scenario, view, exclude=(), unlabeled=()) -> list:
    """턴마다 정답과 가닥의 값. 어디서 틀렸는지 볼 때 써요 (글은 싣지 않고 id와 칸만)."""
    gold, made, skip = gold_turns(scenario), made_turns(view), set(exclude)
    failed = set(unlabeled)
    want, got = gold_items(scenario), made_items(view)
    rows = []
    for i, g in gold.items():
        m = made.get(i)
        rows.append({
            "id": i, "chat": g["chat"], "excluded": i in skip, "read": m is not None, "labeled": i not in failed,
            "depth": [g["depth"], m["depth"] if m else None], "dec": [g["dec"], m["dec"] if m else None],
            "parts": [g["parts"], m["parts"] if m else None],
            "items": [sorted(k for t, k in want if t == i), sorted(k for t, k in got if t == i)],
        })
    return rows
