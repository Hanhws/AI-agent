# 영어판 인계 (10/13 기준)

작성: 한윤주 (Claude Code와 함께) → 영어판 배포를 맡을 조원

영어판은 **한국어판과 따로 배포**해요. 앱 안에서 언어를 바꾸는 스위치는 만들지 않았어요.

---

## 0. 한눈에

| | 한국어판 | 영어판 |
|---|---|---|
| 브랜치 | `main` | `english` (main에서 땀 · PR #13) |
| 앱 | `가닥.app` (번들 id `local.gadak.app`) | `Gadak.app` (번들 id `local.gadak.app.en`) |
| 설치 스크립트 | `가닥 설치.command` | `Install Gadak.command` |
| 받는 파일 | `가닥-0.1.0-*.dmg` · `가닥-0.1.0-windows-x64-설치.exe` | `Gadak-0.1.0-*.dmg` · `Gadak-0.1.0-windows-x64-setup.exe` |
| 설치 안내 PDF | `docs/가닥-설치-안내.pdf` | `docs/gadak-install-guide.pdf` (아홉 쪽) |
| 릴리스 | `v0.1.0` (올라가 있음) | **아직 없음** ← 할 일 |

기능은 한국어판과 같아요. 테스트 362개 통과(5개 건너뜀).

## 1. 영어판에서 바뀐 것

- **화면 전부**: 가닥 창 · 도움말 · 전체 지도 · 포스터 · 판단 기록 · 떠 있는 버튼 편집 · Mac 메뉴와 떠 있는 버튼 · 크롬 확장 · 서버가 돌려주는 안내 · 엔진 오류 문구.
- **프롬프트 여섯 개**(`backend/prompts/`)를 영어로. 가닥이 만드는 글(역 이름 · 구간 · 간추림 · 할 일 · 이어 가기 요약)은 **대화 언어와 상관없이 늘 영어**예요.
- **만든 예시**: `data/demo_conversations.json`(환율 알리미) · 전체 지도의 예시 프로젝트를 영어로.
- **설치 안내**: `docs/install-guide/guide.html`을 영어로 다시 쓰고 PDF를 새로 찍었어요. 그림도 영어 화면으로 다시 찍었어요.
- **README**: 한글 인수인계 `README.md`는 그대로. 사용자용 짧은 `README.en.md`를 새로 둠.
- **그대로 둔 것**: 코드 주석 · `docs/usage-guide.md` · eval 재기 시트(`eval/ahead.py`는 한글 라벨을 따로 가짐) · 개발자용 빌드 오류 문구.
- **로고는 두 말 그대로**: 가닥 창 · 전체 지도의 ‘가닥 GADAK’, 포스터 제목, 떠 있는 버튼 가운데의 ‘가닥’ (영어 사이트의 표기와 같게).

### 낱말 (영어 사이트 `gh-pages:en/index.html`을 따름)

| 한국어 | 영어 | 한국어 | 영어 |
|---|---|---|---|
| 역 | station | 노선도 | strip map |
| 본선 · 본류 | main line | 전체 지도 | system map |
| 곁길 | side trip | 환승하기 | Transfer |
| 정함 · 정한 것 | Decided | 산출물 | Files |
| 지금 | Now | 구간 | section |
| 할 일 | To do | 앞길 · 앞길 보기 | Ahead · Look ahead |
| 놓친 일 · 제안 | Missed · Suggestions | 찾은 곳 | Sources |
| AI 연결 | Connect AI | 판단 기록 | Decision trace |
| 빠진 요청 | Missed request | 요청 외 변경 | Unrequested change |
| 끝나지 않은 곁길 | Unfinished side trip | 내가 할 일 | Yours to do |
| 이어 가기 | Carry on | 다음 할 일 | Next step |
| 떠 있는 버튼 | floating button | 가닥 토글 | Gadak button |

떠 있는 버튼 둘레: Map · To do · Decided · Files · Ahead · Search · Window · Help (7자까지 44px 동그라미에 들어가게 글자를 줄여요, `mac/Float.swift`).

### 영어 때문에 손본 값

- 분류 전 임시 역 제목 길이 16 → 28자 (`store.TITLE_LEN`)
- 사용 한도 게이지 ‘이번 주’ → `Week` (줄바꿈 방지)
- 수에 따라 단수 · 복수 (`store.many` · `app.js`의 `many`)
- 테스트: 도움말 한 주제의 글자 한도 800 → 1800 (영어가 두 배쯤 길어요)

## 2. 남은 일 (조원 몫)

1. **영어판 만들기** — `english` 브랜치에서:
   ```sh
   git switch english
   .venv/bin/python -m backend.macapp --dmg                       # Apple Silicon용
   GADAK_BUILD_PYTHON=<x86_64 파이썬>/bin/python .venv/bin/python -m backend.macapp --dmg --arch x86_64   # Intel용 (backend/macapp.py 머리말)
   .venv/bin/python -m backend.winapp --installer                 # Windows 설치 파일 + zip
   ```
   사용 기록 서버 주소를 넣으려면 한국어판처럼 `--collect`.
2. **GitHub Releases에 따로 올리기** — 한국어판 `v0.1.0`과 겹치지 않게 예: `v0.1.0-en`. 파일 SHA-256도 같이.
3. **영어 사이트 고치기** — `gh-pages`의 `en/`:
   - 받기 링크를 영어판 릴리스로
   - ‘The app itself is in Korean for now, so the demo is too.’ 문구 빼기
   - 영어 데모(`en/demo`)가 영어 화면 · 영어 예시(`data/demo_conversations.json`)를 쓰게
   - ‘Install guide (PDF, Korean)’ → `gadak-install-guide.pdf`
4. **(선택) 떠 있는 버튼 그림 두 장** — `docs/install-guide/img/float-fan.png` · `float-six.png`는 한글 버튼 그대로예요. 영어판 앱을 `GADAK_FLOAT_SNAPSHOT=<폴더>`로 켜면 새로 찍혀요(`mac/FloatCheck.swift`). 바꾼 뒤 `sh docs/install-guide/make-pdf.sh`.
5. **(선택) 한글 인수인계 `README.md` 영어로** — 지금은 그대로 두기로 했어요.

## 3. 조심할 것

- **한국어판 고친 것을 영어판에 옮기기**: `main`의 변경은 `english`로 저절로 안 가요. `main`을 `english`에 머지하면 같은 문구를 양쪽에서 고친 곳마다 충돌이 나요. 충돌은 영어 쪽을 남기고, **새로 생긴 한글 문구는 위 낱말표대로 번역**해요. 번역할 문구 찾기: 주석 밖의 한글 (`git grep -n "[가-힣]" -- shared backend/web extension mac` 뒤 주석 줄 빼고).
- **새 문구를 만들 때**: 테스트가 화면 문구를 그대로 비교하는 곳이 많아요(`tests/test_app.py` · `test_engines.py` · `test_investigate.py` …). 문구를 바꾸면 테스트도 같이.
- **한 Mac에 둘 다 깔면**: 앱은 따로 깔리지만 기록 폴더(`~/.gadak`)와 포트(7311)를 같이 써요. 동시에 켜면 먼저 켠 쪽에 붙어요. 한 번에 하나만.
- **저장소 폴더에서 돌리는 앱**(`가닥 설치.command` · `Install Gadak.command`로 깐 것)은 그 폴더의 지금 브랜치 코드를 돌려요. 폴더를 `english`로 바꾸면 깔아 둔 `가닥.app`도 영어로 떠요.
- **화면 확인**: 가닥 창을 `?demo`로 열면 영어 예시가 떠요. 시험용으로 켤 때는 `GADAK_HOME` · `GADAK_PORT`를 따로 주고, 내 실제 대화가 섞이지 않게 `GADAK_CLAUDE_PROJECTS` · `GADAK_CODEX_HOME`도 빈 폴더로.
