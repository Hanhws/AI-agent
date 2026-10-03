# 가닥 사용 가이드 — 내 LLM 이용 형태에 맞게 쓰기

가닥을 쓰려면 두 가지만 정하면 돼요.

- **입구**: 가닥이 내 대화를 읽는 곳 (Cursor, VS Code의 Claude Code, 웹, 데스크톱 앱)
- **엔진**: 가닥이 대화를 분류할 때 쓰는 LLM (내가 가진 구독이나 키에 따라 달라요)

> 2026-10-03 기준이에요. **지금 되는 것은 Cursor · Claude Code 대화를 기록하는 것과 엔진 연결 확인까지**예요. 분류와 노선도 화면은 아직 없어요. ‘예정’ 옆 날짜는 README 10장 일정이에요. macOS에서만 확인했어요.

## 1. 한눈에 고르기

| 내가 쓰는 것 | 입구 | 엔진 | 추가 비용 | 상태 |
|---|---|---|---|---|
| Claude 구독(Pro · Max) + VS Code의 Claude Code | Claude Code hook (4-1) | Claude 구독 엔진 (3-1) | 없음 | 기록까지 됨 |
| Claude 구독 + Cursor | Cursor hook (4-2) | Claude 구독 엔진 (3-1) | 없음 | 설치까지 됨 (실제 Cursor 대화는 확인 중) |
| Claude 구독 + Claude 웹 · 데스크톱 앱 | 크롬 확장 · 데스크톱 MCP · 불러오기 | Claude 구독 엔진 (3-1) | 없음 | 예정 (10/7~10/10) |
| ChatGPT 구독만 | 크롬 확장 · 불러오기 | 따로 필요 (3-3) | 엔진에 따라 | 예정 (10/7~10/9) |
| Anthropic API 키가 있음 | 위 입구 아무거나 | API 키 엔진 (3-2) | 쓴 만큼 | 예정 |
| 유료 LLM이 없음 | 배포 웹 데모에서 예시 대화 보기 | 필요 없음 | 없음 | 예정 (10/7) |

## 2. 준비 (공통)

저장소를 받은 폴더에서 한 번만 해요.

```bash
python3 -m venv .venv
./.venv/bin/python -m pip install -r requirements.txt
```

가닥을 쓸 때는 백엔드를 켜 둬요. 내 PC 안(`http://127.0.0.1:7311`)에서만 떠요.

```bash
./.venv/bin/python -m backend.app
```

## 3. 엔진 고르기

엔진은 `backend/.env`에서 정해요. `backend/.env.example`을 `backend/.env`로 복사해서 고치면 돼요. 기본값 `auto`는 Claude Code가 깔려 있으면 Claude 구독 엔진을, 없으면 ‘엔진 없이’를 골라요.

### 3-1. Claude 구독 엔진 (`claude_cli`) — Pro · Max 구독만 있을 때

내 PC에 로그인돼 있는 Claude Code를 가닥이 대신 불러요. **API 키가 필요 없고 추가 결제도 없어요.**

1. Claude Code를 설치하고 로그인해요. `claude auth status`에 `"subscriptionType": "pro"`처럼 나오면 준비된 거예요.
2. `backend/.env`에 `GADAK_ENGINE=claude_cli`를 적어요. (`auto` 그대로 둬도 돼요.)
3. 확인해요. 실제로 한 번 불러 봐요.

```bash
./.venv/bin/python -m backend.engines --ping
# {"ok": true, "authMethod": "claude.ai", "subscriptionType": "pro"}
# 응답 {"ok": true} · 2.6초
```

알아 둘 점

- **구독 사용 한도를 같이 써요.** 가닥이 분류할 때마다 내 한도가 조금씩 줄어요. 한도에 걸려도 대화 기록은 계속돼요.
- **한 번 부르는 데 몇 초 걸려요** (10/3 측정: 3~8초). 그래서 분류 결과는 답이 온 뒤 조금 있다가 나와요.
- 환경 변수에 `ANTHROPIC_API_KEY`가 있어도 이 엔진은 구독 로그인으로 불러요.
- 가닥이 부른 Claude Code는 내 설정(hook · MCP · CLAUDE.md)을 싣지 않고, 내 대화 목록에도 남지 않아요.
- **서버에 배포한 가닥에서는 쓸 수 없어요.** 구독 로그인은 내 PC에만 있어요.
- Claude Code 2.1.267에서 확인했어요. 버전이 바뀌면 동작이 달라질 수 있어요.
- 모델은 `GADAK_ENGINE_MODEL`로 바꿔요 (`haiku` · `sonnet` · `opus`, 기본 `haiku`).

### 3-2. API 키 엔진 — 예정

Anthropic API 키로 직접 불러요. 쓴 만큼 과금되고, 배포한 가닥에서도 쓸 수 있어요. 아직 만들지 않았어요.

### 3-3. 엔진 없이 (`none`) — ChatGPT 구독만 있을 때

`GADAK_ENGINE=none`이면 대화를 기록만 해요. 곁길 · 정함 분류와 한마디는 나오지 않아요.

가닥은 아직 ChatGPT 구독을 엔진으로 쓰지 못해요. ChatGPT를 주로 쓰더라도 Claude 구독이나 API 키가 있으면 그걸 엔진으로 고르면 되고(입구와 엔진은 달라도 돼요), 둘 다 없으면 기록만 하거나 배포 웹 데모로 먼저 써 봐요.

## 4. 입구 붙이기

### 4-1. Claude Code (VS Code · 터미널) — 지금 됨

1. 백엔드를 켜 둬요 (2장).
2. 내 PC의 경로를 채운 설정을 뽑아요. 이 명령은 화면에 보여 주기만 하고 파일을 고치지 않아요.

```bash
python3 cursor-hooks/install.py claude
```

3. 나온 내용의 `hooks`를 설정 파일에 넣어요. 이미 `hooks`가 있으면 항목을 합쳐요.
   - 한 프로젝트에서만: 그 프로젝트의 `.claude/settings.json`
   - 모든 프로젝트에서: `~/.claude/settings.json`
4. Claude Code를 다시 시작하고 질문을 하나 보내요.
5. 들어왔는지 확인해요.

```bash
curl http://127.0.0.1:7311/projects
```

읽는 것은 내 질문, 마지막 답변, Edit · Write로 바뀐 파일의 전 · 후예요. 끄려면 넣었던 `hooks` 항목을 지워요.

### 4-2. Cursor — 설치는 명령 한 번

1. 백엔드를 켜 둬요 (2장).
2. 가닥을 쓸 프로젝트 폴더에 hook을 붙여요. 그 프로젝트의 `.cursor/hooks.json`과 `.cursor/hooks/gadak.sh`가 생겨요.

```bash
python3 cursor-hooks/install.py cursor --project /내/프로젝트/폴더
```

3. Cursor에서 그 폴더를 열고 Agent에 질문을 하나 보내요. Cursor는 `hooks.json`이 저장되면 바로 다시 읽어요.
4. 들어왔는지 확인해요.

```bash
curl http://127.0.0.1:7311/projects
```

- 모든 프로젝트에 붙이려면 `--project 폴더` 대신 `--user`를 써요 (`~/.cursor/`에 생겨요).
- 이미 `hooks.json`이 있으면 덮어쓰지 않고, 합칠 내용을 화면에 보여 줘요.
- 안 들어오면 Cursor의 Customize → Hooks 탭과 Hooks 출력 채널에서 hook이 돌았는지 봐요.
- 끄려면 `.cursor/hooks.json`에서 가닥 항목을 지워요.
- Cursor Cloud Agent에서는 일부 hook이 돌지 않으니 로컬 Agent에서 써요.

Cursor 3.22에서 설치하고, Cursor가 부르는 방식 그대로 실행기를 돌려 보는 데까지 확인했어요. 실제 Agent 대화가 들어오는지는 확인 중이에요. `--debug`를 붙여 설치하면 Cursor가 넘긴 원본 입력이 `~/.gadak/raw.jsonl`에도 남아서, 안 맞는 곳을 찾을 때 써요.

### 4-3. ChatGPT · Claude 웹 (크롬 확장) — 예정 10/8~10/9

### 4-4. Claude 데스크톱 앱 (MCP) — 예정 10/10

Claude가 답할 때마다 직접 기록을 넘기는 방식이라 엔진이 따로 필요 없어요. 대신 Claude가 기록을 빼먹는 턴이 있을 수 있어요.

### 4-5. 대화 내보내기 파일 불러오기 — 예정 10/7

ChatGPT와 Claude 모두 설정의 데이터 내보내기에서 신청하면 메일로 파일이 와요. 오는 데 시간이 걸리니 미리 신청해 둬요.

## 5. 내 대화가 어디로 가나

| 무엇 | 어디에 |
|---|---|
| 대화 원문, 바뀐 파일의 전 · 후 | 내 PC의 `~/.gadak/gadak.db` (저장소 밖) |
| 백엔드가 꺼져 있을 때 온 대화 | `~/.gadak/spool.jsonl`에 쌓였다가 `./.venv/bin/python -m backend.replay`로 들어감 |
| 분류할 때 그 턴 (분류가 붙은 뒤) | 고른 엔진으로 전송. Claude 구독 엔진이면 내 Claude 계정으로 Anthropic에 |
| 옮기지 않는 것 | Cursor가 hook에 넘기는 계정 이메일 |

- 백엔드는 내 PC(127.0.0.1)에서 온 요청만 받아요.
- 기록을 모두 지우려면 `~/.gadak` 폴더를 지워요.

## 6. 안 될 때

| 증상 | 볼 곳 |
|---|---|
| `curl .../projects`가 비어 있음 | 백엔드가 켜져 있는지, hook 설정의 경로가 지금 폴더와 맞는지(`install.py`를 다시 돌려 비교), `~/.gadak/spool.jsonl`에 쌓이고 있는지 |
| `--ping`이 실패 | `claude auth status`로 로그인 확인, 구독 사용 한도 |
| hook을 붙인 뒤 에디터가 느림 | hook은 백엔드를 1.5초까지만 기다려요. 그래도 느리면 hook 항목을 지우고 알려 주세요 |
