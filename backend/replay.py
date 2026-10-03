"""저장해 둔 hook 이벤트(JSONL)를 백엔드에 다시 흘려보내요. 평가 · 측정 · 데모 백업용.

python -m backend.replay                    백엔드가 꺼져 있는 동안 쌓인 ~/.gadak/spool.jsonl
python -m backend.replay tests/fixtures/cursor_events.jsonl
"""
import json
import sys
import urllib.request

from . import config


def replay(path, url) -> int:
    sent = 0
    with open(path, encoding="utf-8") as lines:
        for line in lines:
            line = line.strip()
            if not line:
                continue
            request = urllib.request.Request(
                url + "/events", data=line.encode("utf-8"),
                headers={"Content-Type": "application/json"}, method="POST",
            )
            with urllib.request.urlopen(request, timeout=10) as response:
                json.load(response)
            sent += 1
    return sent


def main(argv) -> int:
    spool = config.HOME / "spool.jsonl"
    path = argv[0] if argv else spool
    url = f"http://{config.HOST}:{config.PORT}"
    print(f"{replay(path, url)}개 이벤트를 {url}로 보냈어요")
    if not argv:
        spool.write_text("", encoding="utf-8")  # 쌓아 둔 것은 다 보냈으니 비워요
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
