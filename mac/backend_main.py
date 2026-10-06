"""가닥 앱 안에 묶는 백엔드의 첫 줄. PyInstaller가 이 파일을 실행 파일(gadak-backend)로 만들어요.
하는 일은 backend/frozen.py에 있어요. 만들기: python -m backend.macapp --bundle (README 5-1)."""
import sys

from backend import frozen

if __name__ == "__main__":
    sys.exit(frozen.main(sys.argv[1:]))
