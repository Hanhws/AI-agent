#!/usr/bin/env python3
"""hook 설정을 이 PC의 경로로 채워서 보여 줘요. 파일은 건드리지 않아요.

python3 cursor-hooks/install.py cursor    → .cursor/hooks.json 에 넣을 내용
python3 cursor-hooks/install.py claude    → .claude/settings.json 의 hooks 에 넣을 내용
"""
import json
import shlex
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
TEMPLATES = {"cursor": "hooks.json", "claude": "claude-settings.json"}
PLACEHOLDER = "__GADAK_HOOK__"


def render(target: str) -> str:
    command = f"python3 {shlex.quote(str(HERE / 'gadak-hook.py'))}"
    template = (HERE / TEMPLATES[target]).read_text(encoding="utf-8")
    config = json.loads(template.replace(PLACEHOLDER, json.dumps(command)[1:-1]))
    return json.dumps(config, ensure_ascii=False, indent=2)


def main(argv) -> int:
    if len(argv) != 1 or argv[0] not in TEMPLATES:
        print(__doc__.strip())
        return 1
    print(render(argv[0]))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
