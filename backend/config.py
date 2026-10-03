"""설정. 값은 환경 변수나 저장소 루트의 .env에서 읽어요."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _load_dotenv(path: Path) -> None:
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_dotenv(ROOT / "backend" / ".env")
_load_dotenv(ROOT / ".env")

# 대화 원문이 든 DB는 저장소 밖(내 PC의 홈)에 둬요
HOME = Path(os.environ.get("GADAK_HOME", Path.home() / ".gadak")).expanduser()
HOST = os.environ.get("GADAK_HOST", "127.0.0.1")
PORT = int(os.environ.get("GADAK_PORT", "7311"))
DB_PATH = Path(os.environ.get("GADAK_DB", HOME / "gadak.db")).expanduser()

# auto | claude_cli | none  (docs/usage-guide.md)
ENGINE = os.environ.get("GADAK_ENGINE", "auto")
ENGINE_MODEL = os.environ.get("GADAK_ENGINE_MODEL", "haiku")
# 한 번 켠 동안 정리(1단 분류 + 2단 확인)에 쓰는 LLM 호출 수의 한도. 구독 한도를 모르는 사이에 다 쓰지 않게 해요
MAX_CALLS = int(os.environ.get("GADAK_MAX_CALLS", "150"))
# 2단(확인)이 한 턴에서 엔진에 묻는 걸음 수의 한도 (README 3-1: 초깃값 5)
MAX_STEPS = int(os.environ.get("GADAK_MAX_STEPS", "5"))
# 사용 기록을 받는 가닥 팀 서버(server/). 비어 있으면 아무것도 보내지 않고, 동의도 묻지 않아요 (docs/usage-guide.md 6번)
COLLECT_URL = os.environ.get("GADAK_COLLECT_URL", "").rstrip("/")
SEND_EVERY = int(os.environ.get("GADAK_SEND_EVERY", "300"))   # 초. 사용 기록을 보내는 간격
VERSION = "0.1.0"
# 2단에 쓸 모델. 비우면 1단과 같은 모델
CHECK_MODEL = os.environ.get("GADAK_CHECK_MODEL") or ENGINE_MODEL
