# 가닥 설치 안내 (받아서 쓰는 사람이 보는 설명서)

- 읽는 사람: 가닥을 처음 받아 Mac이나 Windows에 넣는 사람. 개발을 모르는 사람도 따라 할 수 있게 썼어요.
- 결과물: [`docs/가닥-설치-안내.pdf`](../가닥-설치-안내.pdf) (A4 아홉 쪽). Mac의 디스크 이미지(`python -m backend.macapp --dmg`)와 Windows의 설치 파일 · zip(`python -m backend.winapp`)에 같이 들어가요.
- 글과 모양: [`guide.html`](guide.html). 고친 뒤에는 PDF를 다시 찍어요.

```sh
sh docs/install-guide/make-pdf.sh      # 크롬과 인터넷(글꼴)이 필요해요
```

## 쪽

| 쪽 | 무엇 |
|---|---|
| 1 | 표지 · 내 컴퓨터에 맞는 파일(Apple 칩 Mac · Intel Mac · Windows) · 차례 |
| 2 | Mac에 설치하기 · 처음 열기 |
| 3 | Windows에 설치하기 · 처음 열기 · Windows에서 다른 점 |
| 4 | AI 연결 |
| 5 | 대화 읽어 오기 |
| 6 | 가닥 창 보는 법 |
| 7 | 노선도 읽기 · 전체 지도 |
| 8 | 떠 있는 버튼 (Mac) |
| 9 | 바꿀 수 있는 것 · 막힐 때 · 지우기 |

모양은 가닥 창의 표기를 따라요(`shared/ui/tokens.css`): 글꼴 Helvetica Neue + Pretendard, 흰 종이와 중립 회색, 빨강은 ‘지금 · 꼭 볼 것’에만. Mac이나 Windows 한쪽에만 맞는 말에는 `Mac` · `Windows` 표가 붙어 있어요.

## 그림 (`img/`)

실제 대화가 들어가지 않게, **지어낸 예시 대화**로 띄운 시험용 가닥에서 찍었어요(`data/demo_conversations.json`, 손으로 넣은 대화 둘 ‘발표 준비’ · ‘데이터 분석’, 지어낸 Claude Code 세션 파일 하나). 밝은 화면 · 배율 2예요.

| 파일 | 무엇 | 찍은 곳 |
|---|---|---|
| `ai-first.png` · `ai-done.png` | ‘AI 연결’ 창 (연결 전 · 연결된 뒤) | 시험용 가닥. 연결된 모습은 로그인된 척하는 가짜 `claude` 명령과 `POST /engine/choose`로 만들었어요 |
| `sources.png` | ‘찾은 곳’ 창 | 시험용 가닥. `GADAK_CLAUDE_PROJECTS`에 지어낸 세션 파일을 둬서 ‘알아서 읽는 중’으로 보이게 했어요 |
| `window.png` | 가닥 창 | 가닥 창을 `?demo`로 연 것 (1320×860) |
| `map.png` | 전체 지도 | `/map?demo` (지도에 들어 있는 만든 예시) |
| `float-peek.png` · `float-fan.png` · `float-six.png` | 떠 있는 버튼 (걸친 모양 · 펼친 모양 · 바꾼 모양) | 가닥 앱의 스스로 확인(`GADAK_FLOAT_SNAPSHOT`, mac/FloatCheck.swift)이 남긴 그림에서 잘라 냈어요 |
| `strip.png` | 떠 있는 노선도 창 | `/strip?list=0&app=2&project=…` |
| `float-edit.png` | 버튼 편집 창 | `/float/edit` |

- 창을 찍을 때는 가운데 대화와 왼쪽 목록을 가리고(`visibility: hidden`) 왼쪽 아래의 창과 발치만 잘랐어요.
- 2쪽의 ‘열 수 없습니다’ 창과 시스템 설정, 3쪽의 ‘Windows의 PC 보호’ 창과 설치 창은 **실제 화면이 아니라 본떠 그린 그림**이에요. 3쪽은 진짜 Windows에서 본 적이 없어서(상세 28-6), 글은 Windows와 NSIS의 한국어 문구를 따라 적었어요.
- 6 · 7쪽의 번호 표시와 노선도의 작은 표시들은 `guide.html` 안에 그려 넣은 것이에요.

화면이 바뀌면 그림도 다시 찍어요. 시험용 가닥을 띄우는 법은 `docs/usage-guide.md` 7장 아래의 환경 변수(`GADAK_PORT` · `GADAK_HOME`)를 봐 주세요.
