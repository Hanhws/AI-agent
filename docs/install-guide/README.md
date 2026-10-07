# 가닥 설치 안내 (받아서 쓰는 사람이 보는 설명서)

- 읽는 사람: 가닥을 처음 받아 Mac에 넣는 사람. 개발을 모르는 사람도 따라 할 수 있게 썼어요.
- 결과물: [`docs/가닥-설치-안내.pdf`](../가닥-설치-안내.pdf) (A4 일곱 쪽). 디스크 이미지를 만들 때(`python -m backend.macapp --dmg`) 같이 들어가요.
- 글과 모양: [`guide.html`](guide.html). 고친 뒤에는 PDF를 다시 찍어요.

```sh
sh docs/install-guide/make-pdf.sh      # 크롬과 인터넷(글꼴)이 필요해요
```

## 그림 (`img/`)

실제 대화가 들어가지 않게, **지어낸 예시 대화**(`data/demo_conversations.json`과 손으로 넣은 두 대화)로 띄운 시험용 가닥에서 찍었어요.

| 파일 | 무엇 | 찍은 곳 |
|---|---|---|
| `ai-first.png` · `ai-done.png` | ‘AI 연결’ 창 (연결 전 · 연결된 뒤) | 시험용 가닥. 연결된 모습은 로그인된 척하는 가짜 `claude` 명령으로 만들었어요 |
| `sources.png` | ‘찾은 곳’ 창 | 시험용 가닥 |
| `window.png` | 가닥 창 | 가닥 창을 `?demo`로 연 것 |
| `float-peek.png` · `float-fan.png` · `float-six.png` | 떠 있는 버튼 (걸친 모양 · 펼친 모양 · 바꾼 모양) | 가닥 앱의 스스로 확인(`GADAK_FLOAT_SNAPSHOT`, mac/FloatCheck.swift)이 남긴 그림에서 잘라 냈어요 |
| `strip.png` | 떠 있는 노선도 창 | `/strip?list=0&app=2&project=…` |
| `float-edit.png` | 버튼 편집 창 | `/float/edit` |

2쪽의 ‘열 수 없습니다’ 창과 시스템 설정은 실제 화면이 아니라 본떠 그린 그림이에요. 글은 macOS 버전에 따라 조금 달라요.

화면이 바뀌면 그림도 다시 찍어요. 시험용 가닥을 띄우는 법은 `docs/usage-guide.md` 7장 아래의 환경 변수(`GADAK_PORT` · `GADAK_HOME`)를 봐 주세요.
