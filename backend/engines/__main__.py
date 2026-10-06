"""엔진 확인.

python -m backend.engines          어떤 엔진이 잡혔는지, 로그인 · 키 상태 (모델은 부르지 않아요)
python -m backend.engines --ping   실제로 한 번 불러 봐요 (구독 사용량을, API 키 엔진이면 돈을 조금 써요)
"""
import json
import sys
import time

from . import EngineError, describe_engine, get_engine

PING_SCHEMA = {
    "type": "object",
    "properties": {"ok": {"type": "boolean"}},
    "required": ["ok"],
    "additionalProperties": False,
}


def main(argv) -> int:
    print(json.dumps(describe_engine(), ensure_ascii=False))
    try:
        engine = get_engine()
    except EngineError as exc:
        print(exc)
        return 1
    if engine is None:
        print("엔진 없음: 대화를 기록만 하고 분류하지 않아요.")
        return 0
    status = engine.check()
    print(json.dumps(status, ensure_ascii=False))
    if not status.get("ok"):
        return 1
    if "--ping" in argv:
        start = time.time()
        try:
            answer = engine.complete_json("스키마에 맞는 값만 내.", "ok를 true로 답해.", PING_SCHEMA)
        except EngineError as exc:
            print("실패:", exc)
            return 1
        print(f"응답 {json.dumps(answer, ensure_ascii=False)} · {time.time() - start:.1f}초")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
