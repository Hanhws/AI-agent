# 가닥 배포 사이트

소개 · OS별 받기 · 바로 써 보는 데모를 한국어와 영어로 담은 정적 사이트예요. 서버 코드가 없어서 GitHub Pages 같은 곳에 파일만 올리면 돼요.

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
| 글 (한국어 · 영어) | `strings/ko.json` · `strings/en.json` — 두 파일의 열쇠는 늘 같아야 해요(테스트가 봐요) |
| 쪽의 뼈대 | `pages/base.html`(머리띠 · 발치) · `index.html` · `download.html` · `demo.html` |
| 모양 | `static/site.css` — 색 · 글꼴 · 자간은 가닥 창(`shared/ui/tokens.css`)과 같은 값이에요 |
| 움직이는 노선도 | `static/routes.js` — 첫 화면의 지도 · ‘채팅과 노선도’ · ‘앞길’ 그림 |
| 받기 버튼 · 낮 밤 · 왼쪽 세로 노선 | `static/site.js` |
| 화면 그림 | `static/shots/`(기능 그림) · `docs/install-guide/img/`(설치 안내와 같이 쓰는 그림) |

화면 그림과 데모는 만든 예시 대화만 써요. 실제 대화를 찍은 그림은 넣지 않아요.

## 바로 써 보는 데모

`app/`은 가닥 창(`backend/web` · `shared/ui`)을 그대로 복사한 것이에요. 백엔드를 부르지 않고 `data/demo_conversations.json`만 보여 주게 몇 줄을 바꿔요. 바꾸는 줄은 `build.py`의 `PATCHES`에 다 있고, 가닥 창의 코드가 바뀌어 그 줄을 못 찾으면 만들기가 멈춰요(그때 `PATCHES`를 맞춰요).

## 설치 파일과 받기 버튼

설치 파일은 사이트에 넣지 않고 GitHub Releases에 올려요. 받기 버튼의 주소 · 크기 · 확인 값(SHA-256)은 `downloads.json`에서 와요.

```bash
# 설치 파일을 다시 만든 뒤: 올릴 이름(로마자)으로 복사하고 downloads.json 을 다시 적어요
./.venv/bin/python -m homepage.build --stamp --stage <빈 폴더>
```

GitHub는 한글 파일 이름을 지워 버려서 `Gadak-0.1.0-mac-arm64.dmg`처럼 로마자로 올려요. 버전을 올릴 때는 `downloads.json`의 `version` · `tag` · `date`를 먼저 고쳐요.

## 올리기

사이트는 GitHub Pages에 있어요: https://hanhws.github.io/AI-agent/ (10/13). `dist/site/`의 내용을 `gh-pages` 가지의 뿌리에 그대로 올리면 1~2분 뒤에 바뀌어요. 그 가지에는 만들어진 파일만 둬요. 모든 길이 상대 경로라 `…/AI-agent/` 아래에서도 그대로 돌고, `.nojekyll`이 같이 만들어져요.
