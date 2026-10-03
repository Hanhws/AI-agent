#!/bin/sh
# 가닥 켜기. Finder에서 이 파일을 더블클릭해요 (macOS).
# 처음 한 번은 필요한 것(Flask)을 이 폴더의 .venv에 내려받아요.
cd "$(dirname "$0")" || exit 1
if [ ! -x .venv/bin/python ]; then
  echo "처음이라 준비하고 있어요. 1분쯤 걸려요…"
  if ! python3 -m venv .venv || ! .venv/bin/python -m pip install -q -r requirements.txt; then
    echo "준비하지 못했어요. Python 3이 깔려 있는지 확인해 주세요: https://www.python.org/downloads/"
    printf "창을 닫으려면 Enter를 누르세요. "; read -r _
    exit 1
  fi
fi
exec .venv/bin/python -m backend.launch "$@"
