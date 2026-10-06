# 가닥 데이터 계약 (schema)

입구(크롬 확장 · MCP · VS Code · Cursor)와 백엔드가 주고받는 형식이에요. **필드 이름은 프로토타입(`prototype/index.html`의 `SCEN`)과 똑같이** 맞췄어요. 그래서 `data/example_conversations.json`이 그대로 이 형식의 예시예요. 이 문서를 먼저 합의하면 화면 쪽과 백엔드 쪽을 따로 만들어도 맞물려요.

> 9/30 전달 문서의 초안(`decision`, `parts[].text`)은 폐기하고 아래 이름을 써요.

## 1. 객체

### Project
| 필드 | 타입 | 설명 |
|---|---|---|
| `id` | string | |
| `name` | string | 예: `빅데이터핀테크응용ai`. 프로젝트 · 폴더 기능이 없는 대화는 `null` 프로젝트에 묶음 |
| `chats` | Chat[] | 오래된 순 |

### Chat
| 필드 | 타입 | 설명 |
|---|---|---|
| `id` | string | 사이트의 대화 id (예: claude.ai `/chat/<id>`, Cursor `conversation_id`) |
| `title` | string | 사이트에 보이는 제목 |
| `date` | string | 화면 표시용 (`9/30`, `오늘`) |
| `site` | `claude` \| `chatgpt` \| `gemini` \| `claude-code` \| `codex` \| `cursor` | 어느 입구에서 읽었는지 |
| `active` | bool | 지금 열린 대화 |
| `turns` | Turn[] | |

### Turn (역 하나 = 사용자 메시지 하나 + 그 답)
| 필드 | 타입 | 필수 | 설명 |
|---|---|---|---|
| `id` | string | ✓ | |
| `title` | string | ✓ | 역 라벨. 12자 안팎 명사구 (에이전트가 만듦) |
| `user` | string | ✓ | 사용자 메시지 원문 |
| `ai` | string | ✓ | 답변 원문 (화면에는 처음 몇 줄만) |
| `depth` | 0 \| 1 \| 2 | ✓ | 0 본류, 1 · 2 곁길 층. 3 이상은 2로 접음 |
| `seg` | string | | 이 턴부터 새 구간(섹션)이 시작되면 구간 이름 |
| `topic` | string | | 주제 전환 감지 결과 (한 창 몰아쓰기). 승인 뒤에만 구간이 됨 |
| `dec` | string | | 이 턴에서 정한 것 한 줄 → 빨간 테두리 역 |
| `dec_note` | string | | 정한 것을 대화 밖에서도 읽히게 풀어 쓴 한 문장. 이어 가기 요약에 씀 (저장소에만, 화면에는 안 실음) |
| `ret` | bool | | 곁길에서 본류로 돌아온 첫 턴 |
| `ref` | string | | 다시 이야기한 이전 턴 id (다른 대화도 가능) |
| `files` | (string \| {n, u})[] | | 이 턴에서 나온 · 바뀐 산출물. `n` 이름, `u` 링크 |
| `parts` | Part[] | | 메시지 하나에 요청이 여러 개면 나눈 결과 → 캡슐 역 |
| `alts` | {user, ai, dec?}[] | | 고쳐 쓰기 · 재생성으로 숨은 이전 가지들 (마지막 판은 `user`/`ai`) |
| `todo` | Item[] | | 이 턴을 보고 에이전트가 만든 할 일 · 제안 |
| `messageRef` | string | | 원본 위치. 웹은 DOM 식별자, VS Code는 JSONL 줄 번호, Cursor는 transcript 오프셋 |

### Part (요청 하나)
| 필드 | 타입 | 설명 |
|---|---|---|
| `t` | string | 요청 한 줄 요약 |
| `type` | `q` \| `task` \| `rev` | 질문 · 작업 · 수정 요청 |
| `open` | bool | 답에서 빠졌으면 true → 캡슐 안 빈 칸 + ‘빠진 요청’ 할 일 자동 생성 |
| `target` | string | `rev`일 때 고칠 대상 턴 id → 수정 대기열로 감 |
| `follow` | {user, ai, files?} | 프로토타입 전용: 다시 물었을 때 나올 예시 대화 |

### Item (할 일 장부의 한 줄 · 한마디)
| 필드 | 타입 | 설명 |
|---|---|---|
| `id` | string | `<turnId>:<n>` 또는 `<turnId>:p<partIndex>` |
| `kind` | 아래 표 | |
| `text` | string | 한마디 본문 (한 줄, 해요체) |
| `why` | string | 왜 말을 거는지 (근거 한두 문장) |
| `btn` | string | 실행 버튼 문구 (동사 2~5자: ‘다시 묻기’, ‘요약 붙이기’) |
| `prompt` | string | 실행하면 입력창에 넣을 글 |
| `effect` | `split` \| `scopeAll` | 글을 넣는 대신 화면을 바꾸는 실행 |
| `pop` | {title, text?, diff?, note?, btn?, prompt?} | 실행 전에 보여 줄 창 (요약 · 바뀐 곳) |
| `at` | string | 근거가 된 다른 턴 id (지난 대화 포함) |
| `state` | `open` \| `later` \| `done` | 저장소가 관리 |

**kind 목록과 우선순위** (작을수록 먼저, 한 턴에 한마디는 하나)

| kind | 묶음 | 라벨 | 우선 | 언제 만드나 |
|---|---|---|---|---|
| `missing` | 놓친 일 | 빠진 요청 | 1 | `parts[].open` = true |
| `unasked` | 놓친 일 | 요청 외 변경 | 1 | 요청 범위 밖 파일 · 문단이 바뀜 (diff) |
| `yours` | 놓친 일 | 내가 할 일 | 2 | 답변이 사용자에게 행동을 요청했는데 다음 턴에서 안 함 |
| `branch` | 놓친 일 | 숨은 가지 | 2 | 고쳐 쓴 이전 가지에만 있는 요청 · 결정이 현재 가지에 없음 |
| `open` | 놓친 일 | 끝나지 않은 곁길 | 3 | 곁길이 결론(dec) 없이 닫힘, 또는 “다음에 하자”로 끝남 |
| `check` | 제안 | 이해 확인 | 4 | 개념 설명(곁길 질문) 뒤 확인 질문 없이 넘어감 |
| `topic` | 제안 | 주제 전환 | 4 | 한 창에서 주제가 바뀜. 승인하면 이후 자동 분할 |
| `repeat` | 제안 | 반복 질문 | 4 | 지난 대화에 비슷한 질문이 있음 (임베딩 유사도) |
| `handoff` | 제안 | 이어 가기 | 5 | 같은 프로젝트에 새 대화가 열림 / 한 창에 주제가 3개 이상 |
| `next` | 제안 | 다음 할 일 | 6 | 결정이 났는데 정리 문서가 없음 등 |

## 2. 계산되는 값 (저장하지 않음)

- **구간(segment)**: 프로젝트 전체 보기에서는 `대화 날짜 · seg`, 대화 보기에서는 `seg`(승인 뒤엔 `topic`)로 연속 구간을 만들어요.
- **곁길 묶음(chain)**: 본류 턴 뒤에 이어지는 depth ≥ 1 턴들. 지금 위치가 그 안에 있으면 ‘진행 중’, 아니면 ‘끝남(회색)’.
- **산출물 판(version)**: 파일 이름에서 ` v2`, ` (…)` 꼬리를 뗀 기본 이름이 같으면 같은 파일. 나온 순서대로 v1, v2… 마지막이 ‘최신’.
- **수정 대기열**: 모든 `parts[type=rev]`.
- **지금(cur)**: 열린 대화에서 마지막으로 보인 턴. 화면 전체에 하나.

## 3. API (Python 백엔드, 로컬 `http://127.0.0.1:7311`)

| 메서드 | 경로 | 하는 일 |
|---|---|---|
| `POST` | `/turns` | 입구가 새 턴을 보냄 → 에이전트가 분류해 Turn과 새 Item을 돌려줌 |
| `GET` | `/projects/:id/view?scope=chat\|all&chat=:chatId` | 노선도를 그릴 턴 목록 (구간 계산 포함) |
| `GET` | `/projects/:id/search?q=` | 지난 대화 찾기. 정한 것이 먼저 |
| `GET` | `/projects/:id/files` | 산출물 판 목록 |
| `PATCH` | `/items/:id` | `{state: "later" \| "done"}` |
| `POST` | `/import` | 대화 내보내기 파일(ChatGPT · Claude conversations.json) 한꺼번에 불러오기 |

`POST /turns` 요청
```json
{
  "project": "빅데이터핀테크응용ai",
  "chat": { "id": "c2", "title": "가닥 고도화", "site": "claude" },
  "turn": { "user": "…", "ai": "…", "messageRef": "msg-41", "edited_files": ["prototype/index.html"], "alts": [] }
}
```

응답
```json
{
  "turn": { "id": "g7", "title": "간결하게 · 확률 표시", "depth": 0, "dec": "D안 통일 · 패턴 카드 없앰",
            "files": ["index.html"],
            "parts": [{ "t": "세 입구 D안으로", "type": "task" }, { "t": "볼륨 줄이기", "type": "task" }, { "t": "“n% 확률로 U1” 필요할까", "type": "q" }] },
  "items": [{ "id": "g7:0", "kind": "next", "text": "판단 기록을 발표 슬라이드 한 장으로 옮길까요?", "why": "…", "btn": "슬라이드 초안", "prompt": "…" }],
  "nudge": "g7:0"
}
```

## 4. 저장소 (SQLite, 로컬)

```
projects(id, name)
chats(id, project_id, title, site, created_at)
turns(id, chat_id, seq, depth, title, seg, topic, dec, dec_note, ret, ref, user, ai, message_ref, created_at)
parts(turn_id, idx, t, type, open, target)
files(turn_id, name, url, base_name)
alts(turn_id, idx, user, ai, dec)
items(id, turn_id, kind, text, why, btn, prompt, effect, pop_json, at, state, created_at)
```

## 5. 입구별로 받는 원천 데이터

| 입구 | 질문 | 답변 | 파일 변경 | 대화 id |
|---|---|---|---|---|
| 크롬 확장 (claude.ai · chatgpt.com) | DOM의 사용자 메시지 노드 | DOM의 답변 노드 (스트리밍이 끝난 뒤) | 첨부 · 생성 파일 칩 | URL 경로 |
| Claude 데스크톱 (MCP) | Claude가 `record_turn` 도구 호출 때 넘김 | 같음 | 같음 | 도구 인자 |
| VS Code · Claude Code | `~/.claude/projects/<proj>/<session>.jsonl`의 user 줄 | assistant 줄 | `Edit`/`Write` tool_use 줄 | 세션 파일 이름 |
| Cursor | hook `beforeSubmitPrompt.prompt` | hook `afterAgentResponse.text` | hook `afterFileEdit` | hook의 `conversation_id`, `transcript_path` |
