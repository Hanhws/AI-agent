# 가닥 — 코딩 에이전트 작업 규칙

이 저장소는 ‘가닥’이에요. LLM 대화 옆에 붙어 흐름을 노선도로 정리하고 놓친 일을 먼저 알려 주는 에이전트예요. 작업 전에 `README.md`를 끝까지 읽어요.

## 기준
- **화면의 정답은 `prototype/index.html`**이에요. 크기 · 색 · 간격 · 움직임 · 문구를 바꾸지 말고 그대로 옮겨요. 값은 `docs/design/prototype.css`, 토큰은 `docs/design/tokens.css`. 단, 아래 ‘표기 규칙’(2026-10-06)과 글꼴 · 자간(2026-10-08) 결정이 프로토타입보다 앞서요.
- **데이터 형식은 `docs/schema.md`**예요. 필드 이름(`depth`, `dec`, `parts[].t`, `parts[].type`, `todo[].kind` …)을 바꾸지 마요.
- 화면 작업은 `data/example_conversations.json`만으로 먼저 끝내고, `screenshots/`와 나란히 비교해요.
- 가닥은 대답하지 않아요. 가닥 화면에 채팅 입력창을 만들지 마요.
- `prototype/index.html` · `data/example_conversations.json` · `screenshots/`는 실제 대화가 들어 있어 공개 저장소에 없어요. 없으면 팀원에게 받아 같은 자리에 두고, 커밋하지 마요.

## 표기 규칙 (디자인 담당과 합의 없이 바꾸지 않음)
2026-10-06 노선 문법을 전체 지도(`backend/web/map.html`, 마시모 비녤리의 뉴욕 지하철 지도)에 맞춰 통일했어요.
- 본선 = **프로젝트 색의 굵은 선**(노선도 카드 10px). 색은 `store.project_color`가 프로젝트 id로 정해서 노선도 카드 · 레일 · 전체 지도가 같아요
- 검은 점 = 보통 질문, **큰 검은 점 + 굵은 역 이름 = 정함**, **빨갛게 채운 점 + 빛 = 지금(화면에 하나)**, 굵은 회색 지선 = 곁길, 작은 검은 점 = 산출물
- 빨강(`--accent`)은 ‘지금 · 할 일’에만
- 글꼴은 한 벌: 로마자 · 숫자 Helvetica Neue + 한글 Pretendard(`shared/ui/tokens.css`의 `--body` · `--display`). 자간은 큰 제목(28px 이상) -0.08em · 본문 -0.05em · 13px 이하 -0.03em(`--tr-title` · `--tr-body` · `--tr-small`). 2026-10-08
- 역 이름 · 본문은 가로 글씨로 13px 이상 (45° 역 이름은 전체 지도 · 한 줄 노선도에서만)
- 이모지 · 그라데이션 · 반짝이 아이콘 금지

## 코드
- `shared/ui/`는 모든 입구(크롬 확장 · MCP · VS Code · Cursor)가 같이 써요. 입구별 차이는 `extension/content/sites/*`, `cursor-hooks/`(Cursor · Claude Code 어댑터), `mcp/`, `backend/sources/`(내 PC의 기록 읽기), `backend/web/`(가닥 창), `mac/`(macOS 앱의 겉: 창 · Dock · 메뉴 · 다른 앱 위에 떠 있는 버튼)에만 둬요. 입구마다 다른 동작은 `shared/ui/view.js` 머리말의 hooks로 넘겨요.
- 화면을 고치면 가닥 창을 `?demo`(만든 예시)와 `?demo=example&scen=u1`(각자 PC의 실제 예시)로 열어 `screenshots/`와 나란히 비교해요.
- 사용자가 설정하지 않아도 돌아야 해요. 켜면 알아서 찾고 읽어요(`backend/sources/`). 다른 프로그램의 설정을 고치는 일(Cursor hook 연결)만 사용자가 한 번 눌러요.
- 에이전트는 2단이에요. 매 턴 분류 1회(`backend/agent/classify.py`) + 조건이 걸린 턴만 도구 루프(`backend/agent/investigate.py`). 2단이 돈 턴은 판단 기록을 남겨요. README 3-1.
- 가닥이 직접 보내는 건 사용자가 승인한 종류(요청 외 변경 되돌리기 · 이어 가기 요약)뿐이에요. 그 밖에는 글을 넣어 주기만 해요. README 3-2. 보낼 수 있는 종류는 `store.AUTO_KINDS`, 보낼지 정하는 곳은 `backend/auto.py` 하나예요. 종류를 늘리려면 먼저 사람에게 물어요.
- 사이트 DOM 셀렉터는 사이트별 파일 위쪽 상수로 모아요.
- 크롬 확장이 대화를 보내는 곳은 내 PC의 가닥(`127.0.0.1:7311`) 하나예요. 읽는 쪽(`extension/content/`)은 화면을 읽기만 하고 고치지 않아요. 다른 주소나 다른 보내는 길을 넣지 않아요(`tests/test_extension.py`가 확인). 화면에서 읽은 대화를 역과 맞추는 일은 가닥이 해요(`backend/sources/pages.py`).
- API 키는 `.env`에만. `.env`와 대화 원문이 든 DB는 커밋하지 않아요.
- 사용 기록에는 글을 넣지 않아요. 적을 수 있는 이름과 칸은 `backend/usage_schema.py`의 표가 전부이고, 값은 숫자 · 참거짓 · 정해 둔 낱말뿐이에요. 칸을 더하려면 그 표를 고치고 사람에게 먼저 물어요. 대화 글 · 제목 · 파일 이름 · 경로는 서버로 보내지 않아요.
- 커밋: `feat:` `fix:` `docs:` `refactor:` + 한 줄 한국어. `main`에 직접 push하지 않아요.
- `docs/schema.md` · `prototype/` · `backend/prompts/`를 바꿔야 하면 먼저 사람에게 물어요.

## UI 문구
해요체, 한 줄, 사용자 쪽 말(“노드” 대신 “역”, “세그먼트” 대신 “구간”). 문구 목록은 README 7-2 · 8.
