#!/bin/sh
# 가닥 설치 안내를 PDF로 찍어요: docs/install-guide/guide.html → docs/가닥-설치-안내.pdf
# 크롬이 있어야 해요. 글꼴(SUIT)을 받아야 해서 인터넷도 필요해요. Finder에서 더블클릭해도 되고, 터미널에서 sh로 돌려도 돼요.
# 크롬은 PDF를 다 쓰고도 스스로 안 꺼질 때가 있어서, 파일이 다 쓰인 것을 보고 끝내요.
cd "$(dirname "$0")" || exit 1
CHROME="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
OUT="$(cd .. && pwd)/가닥-설치-안내.pdf"
[ -x "$CHROME" ] || { echo "크롬을 찾지 못했어요: $CHROME"; exit 1; }
PROFILE="$(mktemp -d)"
rm -f "$OUT"
"$CHROME" --headless=new --disable-gpu --no-pdf-header-footer --user-data-dir="$PROFILE" \
  --print-to-pdf="$OUT" "file://$(pwd)/guide.html" >/dev/null 2>&1 &
PID=$!
SIZE=-1; WAITED=0
while [ "$WAITED" -lt 90 ]; do
  sleep 1; WAITED=$((WAITED + 1))
  NOW=$(stat -f %z "$OUT" 2>/dev/null || echo 0)
  if [ "$NOW" -gt 0 ] && [ "$NOW" = "$SIZE" ]; then break; fi      # 크기가 더 늘지 않으면 다 쓴 것
  SIZE=$NOW
  kill -0 "$PID" 2>/dev/null || break
done
kill "$PID" 2>/dev/null
wait "$PID" 2>/dev/null
sleep 1
rm -rf "$PROFILE" 2>/dev/null
if [ -s "$OUT" ]; then echo "만들었어요: $OUT"; else echo "PDF를 만들지 못했어요."; exit 1; fi
