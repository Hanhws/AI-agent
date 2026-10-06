"""python -m eval — 가닥이 붙인 값을 정답과 견줘 숫자 넷을 내요.

python -m eval                          u1(실제 대화 58턴)을 지금 엔진 · 지금 모델로
python -m eval --model sonnet --model haiku   모델을 바꿔 가며 (큰 모델을 기준선으로, 작은 모델이 비슷한지)
python -m eval --no-check               1단만. 한마디(items)는 재지 않아요
python -m eval --demo                   만든 예시(data/demo_conversations.json)로. 정답 파일이 없어도 돼요
python -m eval --save                   숫자를 eval/results/에 남겨요 (글은 남기지 않아요)
python -m eval --keep-examples          프롬프트 예시로 쓴 턴도 같이 재요 (보통은 빼요: eval/exclude.json)

엔진을 실제로 불러요. Claude 구독 엔진이면 구독 사용량을, API 키 엔진이면 돈을 써요 (58턴에 1단 8번 + 2단 몇 번).
"""
import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

from backend import config
from backend.engines import EngineError, get_engine, resolve_name

from . import run as runner
from . import score as scoring

HERE = Path(__file__).resolve().parent
EXAMPLE = config.ROOT / "data" / "example_conversations.json"
DEMO = config.ROOT / "data" / "demo_conversations.json"
EXCLUDE = HERE / "exclude.json"          # 프롬프트 예시로 쓴 턴 (id만). 평가에서 빼요
RESULTS = HERE / "results"               # 숫자만. 커밋해도 돼요
LOCAL = HERE / "local"                   # 턴마다 맞고 틀린 것. 내 PC에만 (.gitignore)


def pct(value) -> str:
    return "–" if value is None else f"{value * 100:.1f}%"


def report(key, result, stats, checks, check) -> str:
    d, c, p, i = result["depth"], result["dec"], result["parts"], result["items"]
    side, split = d["side"], p["split"]
    head = f"{key} · {result['turns']}턴"
    if result["excluded"]:
        head += f" (프롬프트 예시로 쓴 {result['excluded']}턴은 뺌)"
    lines = [
        f"{head} · {stats['engine']} / {stats['model']}",
        f"  depth 정확도       {pct(d['acc'])} ({d['right']}/{d['of']})   전부 본류라고 하면 {pct(d['baseline'])}"
        f" · 곁길 재현율 {pct(side['recall'])} ({side['hit']}/{side['gold']}) · 곁길 정밀도 {pct(side['precision'])} ({side['hit']}/{side['said']})",
        f"  dec 재현율         {pct(c['recall'])} ({c['hit']}/{c['gold']})   정밀도 {pct(c['precision'])} ({c['hit']}/{c['said']})",
        f"  parts 개수 일치율  {pct(p['rate'])} ({p['right']}/{p['of']})   요청이 여럿인 턴 {split['gold']}개 중 나눈 턴 {split['hit']}개"
        f" · 개수까지 같은 턴 {split['same']}개 · 가닥이 나눈 턴 {split['said']}개",
    ]
    if check:
        lines.append(
            f"  items 정밀도       {pct(i['precision'])} ({i['right']}/{i['made']})   정답의 한마디 {i['gold']}개 중 가닥이 만드는 종류는"
            f" {i['gold_made_kinds']}개 · 2단이 본 턴 {checks['ran']}개 · 버린 결론 {checks['dropped']}개")
    else:
        lines.append("  items 정밀도       재지 않음 (--no-check)")
    calls, seconds = stats["calls"], stats["seconds"]
    tail = f"  호출 1단 {calls['classify']}번 ({seconds['classify']:.0f}초) · 2단 {calls['check']}번 ({seconds['check']:.0f}초)"
    if "cost_usd" in stats:
        tail += f" · API로 치면 약 ${stats['cost_usd']:.3f}"
    lines.append(tail)
    if result["unlabeled"] or result["unread"]:
        lines.append(f"  ! 가닥이 분류하지 못한 턴 {result['unlabeled'] + result['unread']}개 — 화면에 보이는 대로(본류 · 정함 없음 · 나누지 않음) 셌어요")
    return "\n".join(lines)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="python -m eval", description="가닥 분류 정확도 평가")
    parser.add_argument("--scenario", default=None, help="시나리오 키 (기본 u1, --demo면 demo)")
    parser.add_argument("--data", default=None, help="정답이 달린 예시 파일")
    parser.add_argument("--demo", action="store_true", help="만든 예시로 돌려요")
    parser.add_argument("--model", action="append", help="엔진 모델 (여러 번 쓰면 차례로 재요)")
    parser.add_argument("--engine", default=None, help="엔진 이름 (기본: 지금 가닥이 고르는 것)")
    parser.add_argument("--no-check", action="store_true", help="2단을 돌리지 않아요")
    parser.add_argument("--keep-examples", action="store_true", help="프롬프트 예시로 쓴 턴도 재요")
    parser.add_argument("--max-calls", type=int, default=120)
    parser.add_argument("--timeout", type=float, default=300, help="엔진을 한 번 부를 때 기다리는 초 (큰 모델은 오래 걸려요)")
    parser.add_argument("--save", action="store_true", help="결과 숫자를 eval/results/에 남겨요")
    parser.add_argument("--tag", default="", help="결과 파일 이름에 붙일 말")
    args = parser.parse_args(argv)

    path = Path(args.data) if args.data else (DEMO if args.demo else EXAMPLE)
    key = args.scenario or ("demo" if args.demo else "u1")
    if not path.is_file():
        print(f"정답 파일이 없어요: {path}\n실제 대화가 든 파일이라 저장소에 없어요. 팀 내부 링크에서 받아 같은 자리에 두세요."
              "\n정답 파일 없이 돌려 보려면: python -m eval --demo")
        return 2
    try:
        scenario = runner.load(path, key)
    except KeyError:
        print(f"{path.name}에 ‘{key}’ 시나리오가 없어요.")
        return 2
    exclude = [] if args.keep_examples else (runner.read_json(EXCLUDE, {}) or {}).get(key, [])
    name = resolve_name(args.engine)
    if name == "none":
        print("엔진이 없어요. Claude Code에 로그인하거나 API 키를 넣어 주세요 (docs/usage-guide.md 3장).")
        return 2
    print(f"가닥 정확도 평가 · 정답 {path.name}의 {key}")
    code = 0
    for model in args.model or [config.ENGINE_MODEL]:
        try:
            engine = type(get_engine(name))(model=model, timeout=args.timeout)
        except EngineError as exc:
            print(exc)
            return 2
        began = time.time()
        out = runner.run(scenario, engine, check=not args.no_check, max_calls=args.max_calls,
                         say=lambda text: print("   …", text, flush=True))
        result = scoring.score(scenario, out["view"], exclude, out["unlabeled"])
        print(report(key, result, out["stats"], out["checks"], not args.no_check))
        if out["error"]:
            print("  ! 엔진이 멈춰서 끝까지 재지 못했어요. 위 숫자는 쓰지 마세요:", " ".join(out["error"].split())[:160])
            code = 1
        if out["checks"]["waiting"]:
            print(f"  ! 2단이 못 본 턴 {out['checks']['waiting']}개 (호출 한도 --max-calls {args.max_calls})")
        if args.save and out["error"]:
            print("  끝까지 재지 못한 결과라 남기지 않았어요.")
        elif args.save:
            stamp = datetime.now().strftime("%Y%m%d-%H%M")
            body = {"at": stamp, "scenario": key, "data": path.name, "excluded_ids": sorted(exclude),
                    "check": not args.no_check, "seconds": round(time.time() - began, 1), "prompt": config.CODE,
                    "result": result, "stats": out["stats"], "checks": out["checks"], "error": out["error"]}
            label = "-".join(x for x in (key, str(model), args.tag) if x)
            RESULTS.mkdir(exist_ok=True)
            (RESULTS / f"{label}.json").write_text(json.dumps(body, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            LOCAL.mkdir(exist_ok=True)
            (LOCAL / f"{label}-{stamp}.json").write_text(
                json.dumps(scoring.details(scenario, out["view"], exclude, out["unlabeled"]), ensure_ascii=False, indent=1) + "\n",
                encoding="utf-8")
            print(f"  남김: eval/results/{label}.json")
    return code


if __name__ == "__main__":
    sys.exit(main())
