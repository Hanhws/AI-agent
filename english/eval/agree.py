"""정답 일치율 — 둘이 따로 단 정답이 서로 얼마나 맞는지.

정답(data/example_conversations.json의 u1)은 한 사람이 정한 값이에요. 사람끼리도 갈리는 칸이라면 가닥의
정확도를 그 정답 하나로 말하기 어려워요. 그래서 둘이 따로 10~20턴에 정답을 달아 보고 일치율을 봐요 (README 11장).

1) 빈 시트 만들기 — 같은 시트를 두 사람이 각자 복사해 채워요
   python -m eval.agree sheet                 eval/local/정답-시트.csv (u1, 16턴에 ○ 표시)
   python -m eval.agree sheet --n 20 --seed 3
2) 채우기 — ○ 표시가 있는 줄만. 다른 줄은 앞뒤 흐름을 보라고 같이 실었어요
   depth  0 본류 · 1 곁길 · 2 곁길 안의 곁길
   dec    이 턴에서 무언가를 정했으면 1, 아니면 0
   parts  사용자 메시지에 든 요청의 수 (하나면 1)
3) 견주기
   python -m eval.agree compare eval/local/정답-A.csv eval/local/정답-B.csv

시트에는 실제 대화 글이 들어 있어요. eval/local/ 밖에 두지 말고, 커밋하지 마요.
"""
import argparse
import csv
import random
import sys
from collections import Counter
from pathlib import Path

from backend import config

from . import run as runner
from . import score as scoring

HERE = Path(__file__).resolve().parent
EXAMPLE = config.ROOT / "data" / "example_conversations.json"
DEMO = config.ROOT / "data" / "demo_conversations.json"
COLUMNS = ("label", "id", "chat", "user", "ai", "depth", "dec", "parts")
FIELDS = ("depth", "dec", "parts")
MARK = "○"
NAMES = {"depth": "depth (본류 · 곁길)", "dec": "dec (정함이 있나)", "parts": "parts (요청 수)"}


def pick(scenario, n, seed) -> list:
    """정답을 달 턴을 골라요. 곁길 · 정함 · 요청이 여럿인 턴이 빠지지 않게 넷 중 하나씩은 그런 턴에서 뽑아요."""
    gold = scoring.gold_turns(scenario)
    rng = random.Random(seed)
    picked = []
    for test in (lambda g: g["depth"] > 0, lambda g: g["dec"], lambda g: g["parts"] >= 2):
        pool = [i for i, g in gold.items() if test(g) and i not in picked]
        picked += rng.sample(pool, min(len(pool), n // 4))
    rest = [i for i in gold if i not in picked]
    picked += rng.sample(rest, max(0, min(len(rest), n - len(picked))))
    return [i for i in gold if i in set(picked)]          # 대화 차례대로


def write_sheet(scenario, path, n=16, seed=13) -> int:
    marked = set(pick(scenario, n, seed))
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8-sig", newline="") as file:        # 엑셀에서 한글이 깨지지 않게
        sheet = csv.writer(file)
        sheet.writerow(COLUMNS)
        for chat in scenario["chats"]:
            for turn in chat["turns"]:
                sheet.writerow([MARK if turn["id"] in marked else "", turn["id"], chat.get("title") or chat["id"],
                                turn.get("user") or "", turn.get("ai") or "", "", "", ""])
    return len(marked)


def _number(text):
    text = (text or "").strip()
    try:
        return int(float(text))
    except ValueError:
        return None


def read_sheet(path) -> dict:
    """{턴 id: {depth, dec, parts}} — 세 칸을 다 채운 줄만. parts는 1(요청 하나)을 0(나누지 않음)으로 맞춰요."""
    out = {}
    with open(path, encoding="utf-8-sig", newline="") as file:
        for row in csv.DictReader(file):
            depth, dec, parts = (_number(row.get(k)) for k in FIELDS)
            if depth is None or dec is None or parts is None or not row.get("id"):
                continue
            out[row["id"].strip()] = {"depth": min(max(depth, 0), 2), "dec": 1 if dec else 0, "parts": parts if parts >= 2 else 0}
    return out


def kappa(a, b):
    """Cohen의 κ: 우연히 맞을 만큼을 뺀 일치도. 1이면 완전히 같고 0이면 우연 수준. 잴 수 없으면 None."""
    n = len(a)
    if not n:
        return None
    seen = sum(1 for x, y in zip(a, b) if x == y) / n
    ca, cb = Counter(a), Counter(b)
    chance = sum(ca[k] * cb[k] for k in ca) / (n * n)
    if chance >= 1:
        return None                      # 둘 다 한 가지 값만 썼어요
    return round((seen - chance) / (1 - chance), 3)


def compare(one, two) -> dict:
    ids = [i for i in one if i in two]
    out = {"turns": len(ids), "only_one": len(one) - len(ids), "only_two": len(two) - len(ids)}
    for field in FIELDS:
        a, b = [one[i][field] for i in ids], [two[i][field] for i in ids]
        same = sum(1 for x, y in zip(a, b) if x == y)
        out[field] = {"same": same, "of": len(ids), "rate": round(same / len(ids), 4) if ids else None,
                      "kappa": kappa(a, b), "differ": [i for i, x, y in zip(ids, a, b) if x != y]}
    return out


def gold_labels(scenario) -> dict:
    return {i: {"depth": g["depth"], "dec": 1 if g["dec"] else 0, "parts": g["parts"]}
            for i, g in scoring.gold_turns(scenario).items()}


def show(title, result) -> str:
    lines = [f"{title} · 같이 단 턴 {result['turns']}개"]
    for field in FIELDS:
        r = result[field]
        rate = "–" if r["rate"] is None else f"{r['rate'] * 100:.0f}%"
        k = "–" if r["kappa"] is None else f"{r['kappa']:.2f}"
        lines.append(f"  {NAMES[field]:<22} 일치 {rate} ({r['same']}/{r['of']}) · κ {k}"
                     + (f" · 갈린 턴 {', '.join(r['differ'])}" if r["differ"] else ""))
    return "\n".join(lines)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="python -m eval.agree", description="정답 일치율")
    sub = parser.add_subparsers(dest="what", required=True)
    sheet = sub.add_parser("sheet", help="빈 시트 만들기")
    sheet.add_argument("--out", default=str(HERE / "local" / "정답-시트.csv"))
    sheet.add_argument("--n", type=int, default=16)
    sheet.add_argument("--seed", type=int, default=13)
    both = sub.add_parser("compare", help="두 시트 견주기")
    both.add_argument("one")
    both.add_argument("two")
    for part in (sheet, both):
        part.add_argument("--scenario", default=None)
        part.add_argument("--data", default=None)
        part.add_argument("--demo", action="store_true")
    args = parser.parse_args(argv)

    path = Path(args.data) if args.data else (DEMO if args.demo else EXAMPLE)
    key = args.scenario or ("demo" if args.demo else "u1")
    scenario = runner.load(path, key) if path.is_file() else None
    if args.what == "sheet":
        if scenario is None:
            print(f"정답 파일이 없어요: {path}")
            return 2
        marked = write_sheet(scenario, args.out, args.n, args.seed)
        print(f"시트를 만들었어요: {args.out}\n{MARK} 표시가 있는 {marked}줄의 depth · dec · parts를 채워 주세요. 두 사람이 각자 복사해서, 서로 보지 않고요.")
        print("실제 대화 글이 들어 있으니 eval/local/ 밖에 두지 말고 커밋하지 마요.")
        return 0
    one, two = read_sheet(args.one), read_sheet(args.two)
    if not one or not two:
        print("채운 줄이 없는 시트가 있어요. depth · dec · parts 세 칸을 숫자로 채워 주세요.")
        return 2
    print(show("두 사람", compare(one, two)))
    if scenario is not None:
        gold = gold_labels(scenario)
        print(show("첫째 시트와 지금 정답", compare(one, gold)))
        print(show("둘째 시트와 지금 정답", compare(two, gold)))
    print("κ는 우연히 맞을 만큼을 뺀 일치도예요. 보통 0.6을 넘으면 꽤 맞는다고 봐요. 턴 수가 적으면 크게 흔들려요.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
