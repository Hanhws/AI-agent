"""설정. 값은 환경 변수나 저장소 루트의 .env에서 읽어요.

가닥 앱 안에 묶인 백엔드(FROZEN · backend/macapp.py --bundle)에는 저장소 폴더가 없어요. 그때 ROOT는 앱 안의
자료 폴더(화면 · 프롬프트 · hook)이고, 내 설정은 ~/.gadak/.env에서 읽어요.
"""
import json
import os
import sys
from pathlib import Path

FROZEN = bool(getattr(sys, "frozen", False))
ROOT = Path(sys._MEIPASS) if FROZEN else Path(__file__).resolve().parent.parent


def _load_dotenv(path: Path) -> None:
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


if FROZEN:
    _load_dotenv(Path(os.environ.get("GADAK_HOME", Path.home() / ".gadak")).expanduser() / ".env")
else:
    _load_dotenv(ROOT / "backend" / ".env")
    _load_dotenv(ROOT / ".env")


def _build() -> dict:
    """묶인 앱을 만들 때 적어 둔 것 (ROOT/BUILD.json: 만든 때 · 판 · 사용 기록을 받을 서버). 묶인 앱이 아니면 비어 있어요."""
    try:
        data = json.loads((ROOT / "BUILD.json").read_text(encoding="utf-8")) if FROZEN else {}
    except (OSError, ValueError):
        data = {}
    return data if isinstance(data, dict) else {}


BUILD = _build()

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
COLLECT_URL = (os.environ.get("GADAK_COLLECT_URL") or BUILD.get("collect") or "").rstrip("/")
SEND_EVERY = int(os.environ.get("GADAK_SEND_EVERY", "300"))   # 초. 사용 기록을 보내는 간격
VERSION = "0.1.0"


def _code_stamp() -> str:
    """이 폴더에 있는 가닥 코드를 마지막으로 고친 때. 켜져 있는 가닥이 예전 코드인지 알아보는 데 써요 (launch.py)."""
    if FROZEN:
        return str(BUILD.get("built") or "bundle")        # 묶인 앱은 만든 때가 곧 코드의 판이에요
    newest = 0.0
    for pattern in ("backend/**/*.py", "backend/prompts/*.txt"):
        for path in ROOT.glob(pattern):
            newest = max(newest, path.stat().st_mtime)
    return str(int(newest))


CODE = _code_stamp()   # 이 프로세스가 켜질 때의 코드
# 지난 결정 다시 꺼내기(‘생각 못 한 방법 추천’): 사용자가 길을 물을 때, 전에 스스로 정한 것 중 쓸 만한 것을 한마디로 짚어요.
# 쓸데없는 한마디가 늘 수 있어서 기본은 꺼 둬요. 정확도 평가(eval/)로 재 보고 켜요 (docs/changes-detail.md 20번)
SUGGEST = os.environ.get("GADAK_SUGGEST", "0") == "1"
# 2단에 쓸 모델. 비우면 1단과 같은 모델
CHECK_MODEL = os.environ.get("GADAK_CHECK_MODEL") or ENGINE_MODEL
