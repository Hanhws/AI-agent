#!/usr/bin/env python3
"""가닥 hook을 붙여요.

python3 cursor-hooks/install.py claude                  Claude Code 설정을 화면에 보여 줘요 (파일은 안 건드림)
python3 cursor-hooks/install.py cursor                  Cursor 설정을 화면에 보여 줘요 (파일은 안 건드림)
python3 cursor-hooks/install.py cursor --project 폴더   그 프로젝트의 .cursor/ 에 설정과 실행기를 만들어요
python3 cursor-hooks/install.py cursor --user           모든 프로젝트에 (~/.cursor/)

--debug 를 붙이면 hook이 받은 원본 입력을 ~/.gadak/raw.jsonl 에도 남겨요 (형식 확인용).
이미 hooks.json 이 있으면 덮어쓰지 않고, 합칠 내용만 보여 줘요.
"""
import json
import shlex
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
HOOK = HERE / "gadak-hook.py"
TEMPLATES = {"cursor": "hooks.json", "claude": "claude-settings.json"}
PLACEHOLDER = "__GADAK_HOOK__"
LAUNCHER = "gadak.sh"


def render(target: str, command=None) -> str:
    command = command or f"python3 {shlex.quote(str(HOOK))}"
    template = (HERE / TEMPLATES[target]).read_text(encoding="utf-8")
    config = json.loads(template.replace(PLACEHOLDER, json.dumps(command)[1:-1]))
    return json.dumps(config, ensure_ascii=False, indent=2)


def launcher_script(debug=False, runner=None) -> str:
    """runner: hook을 돌리는 명령. 비우면 python3로 이 폴더의 hook 스크립트를 돌려요.
    가닥 앱 안에 묶인 백엔드는 자기 실행 파일을 넘겨요(파이썬이 없는 Mac에서도 돌게 · backend/sources)."""
    env = "GADAK_DEBUG=1 " if debug else ""
    runner = runner or f"python3 {shlex.quote(str(HOOK))}"
    return (
        "#!/bin/sh\n"
        "# 가닥 hook 실행기 (cursor-hooks/install.py 가 만든 파일). 지우면 가닥이 이 프로젝트를 읽지 않아요.\n"
        f"{env}exec {runner}\n"
    )


def write_cursor(base: Path, command: str, debug=False, runner=None) -> bool:
    """base/.cursor(프로젝트) 또는 base(~/.cursor)에 hooks.json 과 실행기를 만들어요."""
    hooks_dir = base / "hooks"
    hooks_dir.mkdir(parents=True, exist_ok=True)
    (hooks_dir / LAUNCHER).write_text(launcher_script(debug, runner), encoding="utf-8")
    config = base / "hooks.json"
    if config.exists():
        print(f"{config} 이 이미 있어서 덮어쓰지 않았어요. 아래 hooks 항목을 직접 합쳐 주세요.\n")
        print(render("cursor", command))
        return False
    config.write_text(render("cursor", command) + "\n", encoding="utf-8")
    print(f"만들었어요: {config}\n만들었어요: {hooks_dir / LAUNCHER}")
    return True


def main(argv) -> int:
    args = [a for a in argv if not a.startswith("--")]
    debug = "--debug" in argv
    if not args or args[0] not in TEMPLATES:
        print(__doc__.strip())
        return 1
    target = args[0]
    if target == "cursor" and "--project" in argv:
        project = Path(args[1] if len(args) > 1 else ".").expanduser().resolve()
        if not project.is_dir():
            print(f"폴더가 없어요: {project}")
            return 1
        # 프로젝트 hook은 프로젝트 루트에서 돌아요
        return 0 if write_cursor(project / ".cursor", f"sh .cursor/hooks/{LAUNCHER}", debug) else 2
    if target == "cursor" and "--user" in argv:
        # 사용자 hook은 ~/.cursor 에서 돌아요
        return 0 if write_cursor(Path.home() / ".cursor", f"sh hooks/{LAUNCHER}", debug) else 2
    print(render(target))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
