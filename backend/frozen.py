"""가닥 앱 안에 묶인 백엔드가 시작하는 곳 (설치하면 바로 켜지는 앱 · backend/macapp.py --bundle).

묶인 앱에는 파이썬도 저장소 폴더도 없어요. PyInstaller로 만든 실행 파일 하나가 두 가지 일을 해요.
- gadak-backend --shell --parent <pid>   가닥 앱(mac/Gadak.swift)이 뒤에서 부르는 백엔드 (backend/launch.py와 같아요)
- gadak-backend hook [--auto]            Cursor · Claude Code의 hook (cursor-hooks/gadak-hook.py와 같아요).
                                         파이썬이 없는 Mac에서도 hook이 돌게 이 실행 파일이 대신 돌려요
"""
import importlib.util
import sys

from . import config


def hook(argv) -> int:
    """hook 스크립트는 표준 라이브러리만 쓰는 파일 하나예요. 앱 안의 그 파일을 그대로 불러 돌려요 (Flask는 싣지 않아요)."""
    spec = importlib.util.spec_from_file_location("gadak_hook", config.ROOT / "cursor-hooks" / "gadak-hook.py")
    module = importlib.util.module_from_spec(spec)
    sys.argv = [sys.argv[0]] + list(argv)
    spec.loader.exec_module(module)
    return module.main() or 0


def main(argv) -> int:
    for stream in (sys.stdout, sys.stderr):      # 앱이 한 줄씩 듣고 있어요. 쌓아 두지 않고 바로 내보내요
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(line_buffering=True)
    if argv[:1] == ["hook"]:
        return hook(argv[1:])
    if argv[:1] == ["--version"]:
        print(f"가닥 {config.VERSION} · {config.CODE}")
        return 0
    from . import launch
    return launch.main(argv)
