# 가닥 배포 사이트

소개 · OS별 받기 · 바로 써 보는 데모를 한국어와 영어로 담은 정적 사이트예요. 서버 코드가 없어서 GitHub Pages 같은 곳에 파일만 올리면 돼요.

**말마다 그 말의 가닥을 줘요 (10/13).** 한국어 쪽(뿌리)은 한국어판을, 영어 쪽(`en/`)은 영어판을 받게 하고, 데모 · 화면 그림 · 설치 안내 PDF도 그 판의 것이에요.

| | 한국어 쪽 | 영어 쪽 (`en/`) |
|---|---|---|
| 받는 파일 | 릴리스 `v0.1.0` | 릴리스 `v0.1.0-en` |
| 데모 (`app/` · `en/app/`) | 이 브랜치의 `backend/web` · `shared/ui` | `homepage/english/`의 `backend/web` · `shared/ui` |
| 화면 그림 | `static/shots/` · `docs/install-guide/img/` | `static/shots/en/` · `homepage/english/docs/install-guide/img/` |
| 설치 안내 PDF | `docs/가닥-설치-안내.pdf` | `docs/gadak-install-guide.pdf` |
| 쓰는 법 (발치의 링크) | `docs/usage-guide.md` | `docs/usage-guide.en.md` |

영어판은 `english` 브랜치에 있어요(같은 자리의 파일을 영어로 바꾼 것이라 이 브랜치에 같이 둘 수 없어요). 그래서 **사이트가 쓰는 영어판 파일만** `homepage/english/`에 같은 경로로 가져와 두고, 사이트는 `main`에서 만들어요. `homepage/english/`의 파일은 여기서 고치지 않아요.

## 만들기와 미리 보기

```bash
./.venv/bin/python -m homepage.build            # dist/site/ 에 만들어요
./.venv/bin/python -m homepage.build --serve    # 만들고 http://127.0.0.1:7398 에서 보여 줘요
./.venv/bin/python -m unittest tests.test_homepage
```

`dist/`는 깃에 올라가지 않아요. 사이트의 원본은 이 폴더(`homepage/`)예요.

## 어디를 고치나

| 고칠 것 | 파일 |
|---|---|
| 글 (한국어 · 영어) | `strings/ko.json` · `strings/en.json` — 두 파일의 열쇠는 늘 같아야 해요(테스트가 봐요). 영어 글에 적는 버튼 이름은 영어판 화면에 보이는 그대로 |
| 쪽의 뼈대 | `pages/base.html`(머리띠 · 발치) · `index.html` · `download.html` · `demo.html` |
| 모양 | `static/site.css` — 색 · 글꼴 · 자간은 가닥 창(`shared/ui/tokens.css`)과 같은 값이에요 |
| 움직이는 노선도 | `static/routes.js` — 첫 화면의 지도 · ‘채팅과 노선도’ · ‘앞길’ 그림 |
| 받기 버튼 · 낮 밤 · 왼쪽 세로 노선 | `static/site.js` |
| 화면 그림 | `static/shots/`(기능 그림 · 영어는 `en/`) · `docs/install-guide/img/`(설치 안내와 같이 쓰는 그림) |

화면 그림과 데모는 만든 예시 대화만 써요. 실제 대화를 찍은 그림은 넣지 않아요.

## 바로 써 보는 데모

`app/`(영어는 `en/app/`)은 가닥 창(`backend/web` · `shared/ui`)을 그대로 복사한 것이에요. 백엔드를 부르지 않고 `data/demo_conversations.json`만 보여 주게 몇 줄을 바꿔요. 바꾸는 줄은 `build.py`의 `PATCHES`(두 판에서 같은 줄)와 `TITLES`(판마다 다른 제목)에 다 있고, 가닥 창의 코드가 바뀌어 그 줄을 못 찾으면 만들기가 멈춰요(그때 맞춰요).

## 영어판의 화면이 바뀌면

`english` 브랜치를 받아 둔 폴더가 있어야 해요 (예: `git worktree add ../gadak-english english`).

```bash
./.venv/bin/python -m homepage.build --pull-english ../gadak-english    # 가닥 창 · shared/ui · 예시 · 그림 셋 · 설치 안내 PDF
```

- 가져오는 것: `backend/web`의 다섯 파일 · `shared/ui` 전부 · `data/demo_conversations.json` · 설치 안내 그림 셋(`window` · `map` · `float-fan`) → `homepage/english/`, 영어 설치 안내 → `docs/gadak-install-guide.pdf`.
- `static/shots/en/`의 기능 그림 둘(`feature-route` · `feature-todo`)은 영어판 가닥 창을 `?demo`로 열어 찍은 것이에요(밝은 화면 · 1320×860 · 배율 2 · 노선도 카드와 오른쪽 목록). 화면이 바뀌면 다시 찍어요.
- `english` 브랜치에도 이 폴더가 똑같이 있어요. 거기서는 사이트를 만들지 않고(만들기가 멈춰요), 테스트가 `homepage/english/`가 그 브랜치의 지금 파일과 같은지 봐요. 다르면 그 브랜치에서 `python -m homepage.build --pull-english .`을 돌리고, 같은 바뀜을 `main`에도 올려요.

## 설치 파일과 받기 버튼

설치 파일은 사이트에 넣지 않고 GitHub Releases에 올려요. 받기 버튼의 주소 · 크기 · 확인 값(SHA-256)은 `downloads.json`에서 와요(판마다 한 칸: `ko` · `en`).

```bash
# 한국어판: 이 폴더의 dist/ 에서. 올릴 이름(로마자)으로 복사하고 downloads.json 을 다시 적어요
./.venv/bin/python -m homepage.build --stamp --stage <빈 폴더>
# 영어판: english 브랜치를 받아 둔 폴더의 dist/ 에서 (거기서 backend.macapp · backend.winapp 으로 만든 뒤)
./.venv/bin/python -m homepage.build --stamp-english ../gadak-english --stage <빈 폴더>
```

- 한국어판은 GitHub가 한글 파일 이름을 지워 버려서 `Gadak-0.1.0-mac-arm64.dmg`처럼 로마자로 올려요.
- 영어판은 만든 이름 그대로 올려요(`Gadak-0.1.0-arm64.dmg` …). 영어 설치 안내와 ‘How to open Gadak.txt’에 적힌 이름과 같아요. Windows용 둘은 한국어판과 이름이 같아서 **릴리스로만 구분돼요**(받기 쪽에 판을 적어 뒀어요).
- `--stage` 폴더에는 설치 파일 넷 · 크롬 확장 zip(그 판의 `extension/`) · `SHA256SUMS.txt`가 모여요. 그대로 릴리스에 올려요.
- 버전을 올릴 때는 `downloads.json`의 그 판 칸에서 `version` · `tag` · `date`를 먼저 고쳐요.

## 올리기

사이트는 GitHub Pages에 있어요: https://hanhws.github.io/AI-agent/ (영어는 `/en/`). `dist/site/`의 내용을 `gh-pages` 가지의 뿌리에 그대로 올리면 1~2분 뒤에 바뀌어요. 그 가지에는 만들어진 파일만 둬요. 모든 길이 상대 경로라 `…/AI-agent/` 아래에서도 그대로 돌고, `.nojekyll`이 같이 만들어져요.
