#!/bin/sh
# 가닥 설치 (macOS). Finder에서 이 파일을 더블클릭하면 가닥 앱을 만들어 응용 프로그램 폴더에 넣고 켜 줘요.
# 한 번만 하면 돼요. 다음부터는 Launchpad · Spotlight · Dock에서 ‘Gadak’을 켜요.
# 이 폴더를 옮기거나 이름을 바꾸면 다시 한 번 실행해 주세요 (앱이 이 폴더의 코드를 돌려요).
cd "$(dirname "$0")" || exit 1

# 백엔드가 쓰는 것(Flask)을 이 폴더의 .venv에 준비해요
if ! .venv/bin/python -c "import flask" 2>/dev/null; then
  echo "Getting ready for the first time. This takes about a minute…"
  [ -x .venv/bin/python ] || python3 -m venv .venv
  if ! .venv/bin/python -m pip install -q -r requirements.txt; then
    echo "Could not get ready. Check that Python 3 is installed: https://www.python.org/downloads/"
    printf "Press Enter to close this window. "; read -r _
    exit 1
  fi
fi

echo "Building the Gadak app…"
if .venv/bin/python -m backend.macapp --install --open; then
  echo "All done. You can close this window."
else
  echo
  echo "Could not build the app, so Gadak will open in a browser window this time. (Closing this window turns Gadak off.)"
  exec .venv/bin/python -m backend.launch
fi
