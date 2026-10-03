#!/bin/sh
# 가닥 설치 (macOS). Finder에서 이 파일을 더블클릭하면 가닥 앱을 만들어 응용 프로그램 폴더에 넣고 켜 줘요.
# 한 번만 하면 돼요. 다음부터는 Launchpad · Spotlight · Dock에서 ‘가닥’을 켜요.
# 이 폴더를 옮기거나 이름을 바꾸면 다시 한 번 실행해 주세요 (앱이 이 폴더의 코드를 돌려요).
cd "$(dirname "$0")" || exit 1

# 백엔드가 쓰는 것(Flask)을 이 폴더의 .venv에 준비해요
if ! .venv/bin/python -c "import flask" 2>/dev/null; then
  echo "처음이라 준비하고 있어요. 1분쯤 걸려요…"
  [ -x .venv/bin/python ] || python3 -m venv .venv
  if ! .venv/bin/python -m pip install -q -r requirements.txt; then
    echo "준비하지 못했어요. Python 3이 깔려 있는지 확인해 주세요: https://www.python.org/downloads/"
    printf "창을 닫으려면 Enter를 누르세요. "; read -r _
    exit 1
  fi
fi

echo "가닥 앱을 만들고 있어요…"
if .venv/bin/python -m backend.macapp --install --open; then
  echo "다 됐어요. 이 창은 닫아도 돼요."
else
  echo
  echo "앱을 만들지 못해서, 이번에는 브라우저 창으로 켤게요. (이 창을 닫으면 가닥도 꺼져요)"
  exec .venv/bin/python -m backend.launch
fi
