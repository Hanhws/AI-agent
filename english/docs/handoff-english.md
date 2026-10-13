# 영어판 인계 (10/13 기준)

작성: 한윤주 (Claude Code와 함께) → 영어판 배포를 맡을 조원
10/13 오후 갱신: 구현 담당 (Claude Code와 함께) — 2장의 일을 하고, 한 것 · 고친 것 · 확인한 것을 적었어요 (2 · 4 · 5장)
10/13 저녁 갱신: `main`에 이 브랜치를 통째로 가져다 둔 사본(`english/` 폴더)을 뒀어요 (6장)

영어판은 **한국어판과 따로 배포**해요. 앱 안에서 언어를 바꾸는 스위치는 만들지 않았어요.

---

## 0. 한눈에

| | 한국어판 | 영어판 |
|---|---|---|
| 브랜치 | `main` | `english` (main에서 땀 · PR #13) |
| `main` 안의 사본 | — | `english/` 폴더 (이 브랜치를 통째로 · 10/13 저녁 · 6장) |
| 앱 | `가닥.app` (번들 id `local.gadak.app`) | `Gadak.app` (번들 id `local.gadak.app.en`) |
| 설치 스크립트 | `가닥 설치.command` | `Install Gadak.command` |
| 만든 파일 (`dist/`) | `가닥-0.1.0-*.dmg` · `가닥-0.1.0-windows-x64-설치.exe` · `.zip` | `Gadak-0.1.0-arm64.dmg` · `Gadak-0.1.0-x86_64.dmg` · `Gadak-0.1.0-windows-x64-setup.exe` · `.zip` |
| 릴리스 | `v0.1.0` (이름을 로마자로 바꿔 올림) | `v0.1.0-en` (만든 이름 그대로 올림 · 10/13) |
| 받는 곳 | https://hanhws.github.io/AI-agent/download/ | https://hanhws.github.io/AI-agent/en/download/ |
| 설치 안내 PDF | `docs/가닥-설치-안내.pdf` | `docs/gadak-install-guide.pdf` (아홉 쪽) |
| 쓰는 법 | `docs/usage-guide.md` | `docs/usage-guide.en.md` (10/13에 새로 씀) |
| 저장소 첫머리 | `README.md` (인수인계) | `README.en.md` (사용자용 · 짧게) |

기능은 한국어판과 같아요. 테스트는 `english`에서 387개 통과(21개 건너뜀 — 사이트 만들기 확인 16개는 `main`에서만 돌아요).

**두 브랜치에 같이 있는 파일**: `homepage/` · `tests/test_homepage.py` · `README.en.md` · `docs/gadak-install-guide.pdf` · `docs/usage-guide.en.md` · 이 문서 · `CHANGES.md` · `docs/changes-detail.md` · `CLAUDE.md`. 한쪽에서 고치면 다른 쪽에도 같은 내용으로 올려요(그래야 `main`을 `english`에 합칠 때 안 부딪혀요). 사이트의 원본은 `main`의 `homepage/`이고, 이 브랜치의 것은 따라가는 사본이에요.

## 1. 영어판에서 바뀐 것

- **화면 전부**: 가닥 창 · 도움말 · 전체 지도 · 포스터 · 판단 기록 · 떠 있는 버튼 편집 · Mac 메뉴와 떠 있는 버튼 · 크롬 확장 · 서버가 돌려주는 안내 · 엔진 오류 문구.
- **프롬프트 여섯 개**(`backend/prompts/`)를 영어로. 가닥이 만드는 글(역 이름 · 구간 · 간추림 · 할 일 · 이어 가기 요약)은 **대화 언어와 상관없이 늘 영어**예요.
- **만든 예시**: `data/demo_conversations.json`(환율 알리미) · 전체 지도의 예시 프로젝트를 영어로.
- **설치 안내**: `docs/install-guide/guide.html`을 영어로 다시 쓰고 PDF를 새로 찍었어요. 그림도 영어 화면으로 다시 찍었어요(떠 있는 버튼 두 장은 10/13 오후에).
- **README**: 한글 인수인계 `README.md`는 그대로. 사용자용 짧은 `README.en.md`를 새로 둠.
- **그대로 둔 것**: 코드 주석 · eval 재기 시트(`eval/ahead.py`는 한글 라벨을 따로 가짐) · 개발자용 빌드 오류 문구.
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
- **(10/13 오후) 가닥이 쓴 글을 자르는 한도** — 4장 ④

## 2. 한 일 (10/13 오후 · 구현 담당)

| 맡긴 일 | 한 것 |
|---|---|
| 영어판 만들기 | `english`에서 Mac용 디스크 이미지 둘(Apple Silicon · Intel)과 Windows 설치 파일 · zip을 만들었어요. 사용 기록 서버 주소는 넣지 않았어요(`--collect` 없이 · 한국어판과 같게) |
| GitHub Releases에 따로 | **`v0.1.0-en`** — 설치 파일 넷 · 크롬 확장 zip(영어판의 `extension/`) · `SHA256SUMS.txt`. 파일 이름은 만든 그대로예요(영어 설치 안내와 ‘How to open Gadak.txt’에 적힌 이름과 같게) |
| 영어 사이트 | 영어 쪽(`en/`)이 영어판을 받게 했어요: 받기 링크 → `v0.1.0-en`, ‘앱은 아직 한국어’ 문구 뺌, 데모(`en/app/`)가 영어 화면 · 영어 예시, 화면 그림 다섯 장이 영어, 설치 안내 → `en/gadak-install-guide.pdf`, 글 속의 한글 버튼 이름(AI 연결 · 찾은 곳 …)을 영어 화면의 이름으로 |
| (선택) 떠 있는 버튼 그림 두 장 | 영어판 앱의 스스로 확인(`GADAK_FLOAT_SNAPSHOT`)이 남긴 그림에서 전과 같은 자리를 잘라 넣고 PDF를 다시 찍었어요. 8쪽만 달라지고 글은 그대로예요 |
| `main`의 고침 옮기기 | 만드는 동안 `main`에 올라온 #17(포스터 ‘지금’ 이름표의 테두리 없애기)을 `english`에도 옮겼어요. 설치 파일과 사이트의 영어 데모에 들어 있어요 |
| (선택) 한글 `README.md` 영어로 | 그대로 뒀어요. 대신 영어 문서를 채웠어요: `README.en.md`에 받는 곳과 두 판의 관계, `docs/usage-guide.en.md`(쓰는 법 전체 · 영어판 화면의 이름으로 새로 씀) |

만드는 명령은 그대로예요. Windows 것은 `--zip --installer`를 둘 다 줘야 zip과 설치 파일이 같이 나와요.

```sh
git switch english
.venv/bin/python -m backend.macapp --dmg                       # Apple Silicon용
GADAK_BUILD_PYTHON=<x86_64 파이썬>/bin/python .venv/bin/python -m backend.macapp --dmg --arch x86_64   # Intel용 (backend/macapp.py 머리말)
.venv/bin/python -m backend.winapp --zip --installer           # Windows zip + 설치 파일 (NSIS · Mac에서는 Wine)
```

## 3. 조심할 것

- **한국어판 고친 것을 영어판에 옮기기**: `main`의 변경은 `english`로 저절로 안 가요. `main`을 `english`에 머지하면 같은 문구를 양쪽에서 고친 곳마다 충돌이 나요. 충돌은 영어 쪽을 남기고, **새로 생긴 한글 문구는 위 낱말표대로 번역**해요. 번역할 문구 찾기: 주석 밖의 한글 (`git grep -n "[가-힣]" -- shared backend/web extension mac` 뒤 주석 줄 빼고).
- **새 문구를 만들 때**: 테스트가 화면 문구를 그대로 비교하는 곳이 많아요(`tests/test_app.py` · `test_engines.py` · `test_investigate.py` …). 문구를 바꾸면 테스트도 같이.
- **사이트는 `main`에서 만들어요 (10/13)**: 사이트의 영어 쪽은 `main`의 `english/` 폴더(이 브랜치의 사본 · 6장)에 있는 가닥 창 · `shared/ui` · 예시 · 그림을 읽어요. **영어 화면을 고치면** 이 브랜치에 올린 뒤 `main`에서 폴더를 다시 가져오고(6장의 두 줄), 사이트를 다시 만들어 올려요(`homepage/README.md`). `english`에서는 사이트 만들기가 멈춰요(한국어 데모를 만들 수 없어서).
- **설치 파일을 다시 만들면**: `main`의 `english/` 폴더에서 만들고(`cd english` 뒤 2장의 명령 · 파이썬은 `../.venv/bin/python`), 뿌리에서 `python -m homepage.build --stamp-english --stage <빈 폴더>`가 받기 버튼의 크기 · 확인 값을 다시 적고 올릴 파일을 모아요. 그 폴더의 것을 `v0.1.0-en`에(판을 올렸으면 새 릴리스에) 올려요.
- **한 Mac에 둘 다 깔면**: 앱은 따로 깔리지만 기록 폴더(`~/.gadak`)와 포트(7311)를 같이 써요. 동시에 켜면 먼저 켠 쪽에 붙어요. 한 번에 하나만.
- **저장소 폴더에서 돌리는 앱**(`가닥 설치.command` · `Install Gadak.command`로 깐 것)은 그 폴더의 지금 브랜치 코드를 돌려요. 폴더를 `english`로 바꾸면 깔아 둔 `가닥.app`도 영어로 떠요.
- **화면 확인**: 가닥 창을 `?demo`로 열면 영어 예시가 떠요. 시험용으로 켤 때는 `GADAK_HOME` · `GADAK_PORT`를 따로 주고, 내 실제 대화가 섞이지 않게 `GADAK_CLAUDE_PROJECTS` · `GADAK_CODEX_HOME`도 빈 폴더로.

## 4. 인계 뒤에 고친 것 (10/13 오후 · 봐 주세요)

만들어서 켜 보다가 영어 사용자에게 한글로 보이거나 영어가 잘리는 곳을 넷 찾아 고쳤어요. 값은 구현 담당이 정한 것이라 다르게 가고 싶으면 알려 주세요.

| | 무엇이 | 어떻게 |
|---|---|---|
| ① | **macOS가 그리는 것이 한글로 떴어요.** `Info.plist`의 말이 `ko`라서, 영어만 쓰는 Mac에서도 앱이 `ko`로 돌았어요(파일 고르기 창 · 시스템이 넣는 메뉴 항목) | `CFBundleDevelopmentRegion` · `CFBundleLocalizations`를 `en`으로 (`backend/macapp.py`) |
| ② | 정보 창(About)의 한 줄이 한글 | Windows 설치 프로그램과 같은 “Keep the thread of every long chat.” |
| ③ | 왼쪽 목록의 머리글 ‘(프로젝트 없음)’ · ‘폴더 없는 대화’ | 새로 만들 때의 이름을 ‘(No project)’ · ‘Chats without a folder’로. **id는 한글판과 같게 뒀어요**(두 판이 `~/.gadak`을 같이 써요). 한글판이 먼저 만든 기록에서는 한글 이름 그대로 보여요 (`backend/store.py`) |
| ④ | **가닥이 쓴 역 이름 · 구간이 거의 다 잘렸어요.** 영어 프롬프트는 역 이름을 2–5 낱말로 쓰라고 하는데 자르는 한도가 한글 기준 18자였어요. 만든 예시의 역 이름 ‘What is the base rate?’가 ‘What is the base…’로, 프롬프트가 든 예 ‘Views and independence’(구간)가 ‘Views and i…’로 잘려요 | 역 이름 18 → 28자(임시 제목과 같게) · 구간 12 → 28 · 간추림 한 줄 70 → 100 · 프로젝트 이름 20 → 30, 앞길의 가려는 곳 80 → 100 · 길의 제목 44 → 56 · 할 일에 뜨는 글 60 → 76. 넘치면 낱말 사이에서 끊어요 (`backend/agent/classify.py` · `ahead.py`) |

④는 실제로 불러서 봤어요: Claude 구독(Haiku)으로 만든 예시의 둘째 대화 6턴을 정리했더니(호출 2번 · 13초) 글은 모두 영어로 나오고, 곁길 둘 · 정함 하나 · 빠진 것 같은 요청 하나가 잡혔어요. **역 이름 여섯 중 넷이 29~32자**라서 28자에서도 끝 낱말이 떨어져요(‘Polling vs webhook difference’ → ‘Polling vs webhook…’). 더 줄이려면 프롬프트의 “2–5 words”를 “2–4 words”로 좁히는 길이 있어요 — 프롬프트는 건드리지 않았어요.

## 5. 확인한 것 · 못 한 것 (10/13 오후)

- **Mac 디스크 이미지 둘**: 열어서 내용 셋(앱 · ‘How to open Gadak.txt’ · ‘Gadak install guide.pdf’), 서명이 온전한 것, 종류(arm64 · x86_64), 앱이 `en`으로 도는 것을 봤어요. 꺼낸 앱을 시험용 기록 폴더로 켜서 영어 화면과 백엔드의 답을 봤고(Intel용은 Rosetta로), Apple Silicon용은 떠 있는 버튼의 스스로 확인까지 돌렸어요(버튼이 화면 밖 · 겹침 0, 누르기 · 끌기 · 목록 창 · 역 누르기 · Esc).
- **Windows 묶음**: Wine(가짜 홈)으로만 — zip의 내용, 조용히 설치 · 바로 가기 둘 · 켜서 영어 화면 받기 · 끄기 · 제거, 테스트 388개 통과(32개 건너뜀).
- **사이트**: `main`에서 테스트 통과, 크롬으로 쪽 여섯 · 데모 여섯을 열어 오류 0, 영어 쪽에 남은 한글은 로고와 ‘한국어’ · ‘한국어판’뿐.
- **못 한 것**: 깨끗한 다른 Mac에서 내려받아 여는 것, 진짜 Intel Mac, **진짜 Windows PC**(한 번도 못 켜 봤어요). 영어 프롬프트로 정확도(README 3-5)를 다시 재는 것. 2단(놓친 일 확인) · 앞길 살피기 · 이어 가기 요약을 영어 프롬프트로 실제 불러 보는 것(1단 정리만 불러 봤어요).

## 6. `main`의 `english/` 폴더 — 이 브랜치의 사본 (10/13 저녁)

구현 담당이 “main 브랜치 하나에 모든 파일이 들어 있게” 해 달라고 해서 넣었어요.

- **무엇**: 이 브랜치의 파일 전부가 같은 경로로 `main`의 `english/` 아래에 있어요. 폴더의 나무가 브랜치의 나무와 같아서, 아래 두 값이 같으면 사본이 지금 브랜치와 똑같은 거예요.

  ```sh
  git rev-parse origin/main:english          # 폴더
  git rev-parse 'origin/english^{tree}'      # 브랜치
  ```

- **고치는 곳은 이 브랜치예요.** `main`의 `english/` 안에서는 고치지 않아요(두 군데에서 고치면 갈라져요). 이 브랜치에 올린 뒤 `main`에서 폴더를 다시 가져와요:

  ```sh
  git switch -c chore/sync-english origin/main
  git rm -r -q english && git read-tree --prefix=english/ -u origin/english     # 폴더를 브랜치의 지금 모습으로
  [ "$(git write-tree --prefix=english/)" = "$(git rev-parse 'origin/english^{tree}')" ] && echo 같음
  git commit -m "chore: english/ 폴더를 english 브랜치의 지금 모습으로" && git push -u origin chore/sync-english     # PR → main
  ```

- 영어 설치 안내가 바뀌었으면 `main` 뿌리의 `docs/gadak-install-guide.pdf`도 폴더의 것으로 같이 바꿔요(둘이 같은 파일인지 `main`의 테스트가 봐요).
- **폴더에서 영어판을 돌리고 만들 수 있어요**: `main`에서 `cd english` 뒤 `../.venv/bin/python -m backend.launch` · `-m unittest discover -s tests` · `-m backend.macapp --dmg`. Mac에서는 `english/Install Gadak.command`를 더블클릭하면 가지를 바꾸지 않고도 `Gadak.app`이 깔려요(그 앱은 `english/` 폴더의 코드를 돌려요).
- **폴더 안의 `homepage/` · `docs/` · `README.md` · `CHANGES.md`는 딸려 온 사본**이에요. 사이트와 문서의 원본은 `main` 뿌리의 것이에요.
- 한국어판 고친 것을 영어판에 옮길 때는 전과 같아요(3장): `main`을 이 브랜치에 머지 → 충돌은 영어 쪽을 남김. 다만 **`main`의 `english/` 폴더는 이 브랜치에 들어오면 안 돼요**(영어판 안에 영어판이 또 생겨요). 머지한 뒤 `git rm -r -q english`로 빼고 커밋해요.
- **봐 주실 것**: 영어판을 두 군데(브랜치 · 폴더)에 두는 것이 괜찮은지. 폴더만 원본으로 삼고 브랜치를 없애는 길도 있어요(정해 주시면 바꿔요).
