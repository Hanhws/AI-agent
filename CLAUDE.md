# 가닥 — 코딩 에이전트 작업 규칙

이 저장소는 ‘가닥’이에요. LLM 대화 옆에 붙어 흐름을 노선도로 정리하고 놓친 일을 먼저 알려 주는 에이전트예요. 작업 전에 `README.md`를 끝까지 읽어요.

## 기준
- **화면의 정답은 `prototype/index.html`**이에요. 크기 · 색 · 간격 · 움직임 · 문구를 바꾸지 말고 그대로 옮겨요. 값은 `docs/design/prototype.css`, 토큰은 `docs/design/tokens.css`.
- **데이터 형식은 `docs/schema.md`**예요. 필드 이름(`depth`, `dec`, `parts[].t`, `parts[].type`, `todo[].kind` …)을 바꾸지 마요.
- 화면 작업은 `data/example_conversations.json`만으로 먼저 끝내고, `screenshots/`와 나란히 비교해요.
- 가닥은 대답하지 않아요. 가닥 화면에 채팅 입력창을 만들지 마요.

## 표기 규칙 (절대 바꾸지 않음)
- 검정 테두리 ○ = 보통 질문, **빨간 테두리 = 정함**, **빨갛게 채운 점 + 빛 = 지금(화면에 하나)**, 회색 = 곁길, ■ = 산출물
- 빨강(`--accent`)은 ‘지금 · 정함 · 할 일’에만. 본선은 검은 굵은 선(4.5px)
- 이모지 · 그라데이션 · 반짝이 아이콘 금지

## 코드
- `shared/ui/`는 모든 입구(크롬 확장 · MCP · VS Code · Cursor)가 같이 써요. 입구별 차이는 `extension/content/sites/*`, `vscode/src/readers/*`, `cursor-hooks/`에만 둬요.
- 사이트 DOM 셀렉터는 사이트별 파일 위쪽 상수로 모아요.
- API 키는 `.env`에만. `.env`와 대화 원문이 든 DB는 커밋하지 않아요.
- 커밋: `feat:` `fix:` `docs:` `refactor:` + 한 줄 한국어. `main`에 직접 push하지 않아요.
- `docs/schema.md` · `prototype/` · `backend/prompts/`를 바꿔야 하면 먼저 사람에게 물어요.

## UI 문구
해요체, 한 줄, 사용자 쪽 말(“노드” 대신 “역”, “세그먼트” 대신 “구간”). 문구 목록은 README 7-2 · 8.
