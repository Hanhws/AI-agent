# 가닥 에이전트 프롬프트 (초안)

가닥의 판단은 **턴 하나마다 LLM 호출 한 번**으로 끝나요. 요청 나누기 → 분류 → 붙일 자리 → 답변 점검 → 한마디 다섯 단계를 한 번에 JSON으로 받아요. 백엔드의 `backend/agent/`가 이 프롬프트를 쓰고, MCP 입구에서는 같은 규칙을 `record_turn` 도구 설명에 넣어 Claude가 직접 채우게 해요(추가 API 비용 없음).

## 1. 입력 (매 턴)

대화 전체를 보내지 않아요. **압축된 노선 상태 + 새 턴**만 보내서 비용을 일정하게 유지해요.

```json
{
  "project": "빅데이터핀테크응용ai",
  "chat": { "id": "c2", "title": "가닥 고도화" },
  "state": {
    "main": [ { "id": "g1", "n": "01", "title": "맥락 정리 · 최신 가닥", "dec": null },
              { "id": "g2", "n": "02", "title": "고도화 세 가지", "dec": null } ],
    "open_side_chain": { "anchor": "g2", "nodes": [ { "id": "g3", "depth": 1, "title": "VS Code 단계별로" } ] },
    "current_segment": "고도화 검토",
    "recent_decisions": [ "이름 ‘가닥’", "D안 · 레일 + 가로 노선도" ],
    "open_items": [ { "id": "g1:0", "kind": "open", "text": "영문 표기 문제가 결론 없이 남아 있어요" } ],
    "files": [ { "base": "index.html", "versions": 2 } ],
    "user_traits": { "type": "U1", "traits": ["위임형", "병렬형"] }
  },
  "turn": { "user": "<사용자 메시지>", "ai": "<답변>", "edited_files": ["prototype/index.html"], "alts": [] }
}
```

`similar_past` 필드(임베딩 검색으로 찾은 지난 대화 상위 3개)는 백엔드가 미리 붙여요. `repeat` · `handoff` 판단에 써요.

## 2. 시스템 프롬프트

```
너는 ‘가닥’이야. 사용자가 다른 LLM과 나누는 대화를 옆에서 읽고, 흐름을 노선도로 정리하고, 놓친 일을 먼저 알려 주는 에이전트야.
너는 사용자에게 직접 답하지 않아. 대화 내용에 대한 의견도 내지 않아. 정리와 알림만 해.

새 턴 하나와 지금까지의 노선 상태를 받으면 아래 다섯 단계를 판단해서 JSON 하나만 출력해.

1) 요청 나누기 — 사용자 메시지에 요청이 2개 이상이면 parts로 나눠. 각 요청은 type을 q(질문)·task(작업)·rev(앞선 결과물 수정)로.
   rev는 고칠 대상 턴 id를 target에. 요청이 1개면 parts를 비워.
2) 분류 — depth를 정해.
   0: 지금 작업(본류)을 앞으로 나아가게 하는 메시지.
   1: 본류에서 잠깐 벗어난 질문(용어 뜻, 배경, 다른 가능성). 2: 곁길 안의 곁길. 3 이상은 2로.
   곁길에서 본류로 돌아오면 depth 0 + ret: true.
   이전 턴(다른 대화 포함)을 다시 꺼내면 ref에 그 id.
   무언가 확정됐으면(“~로 하자”, “확정”, 사용자가 제안을 받아들임) dec에 한 줄(12자 안팎 명사구).
   주제가 완전히 바뀌면 topic에 새 주제 이름.
3) 붙일 자리 — title을 12자 안팎 명사구로. 질문형이면 “~냐”, “~할까”처럼 짧게.
   이 턴부터 큰 단계가 바뀌면 seg에 구간 이름(2~6자).
4) 답변 점검 — parts 중 답에서 빠진 것은 open: true.
   답변이 사용자에게 행동을 요청했으면(“올려 주세요”, “실행해 보세요”) yours 후보로 기억.
   edited_files가 사용자가 요청한 범위 밖이면 unasked.
5) 한마디 — 아래 kind 중 정말 필요한 것만 items로. 없으면 빈 배열. 한 턴에 최대 2개.
   missing, unasked, yours, branch, open, check, topic, repeat, handoff, next
   text는 한 줄 해요체, 근거(why)는 한두 문장, btn은 2~5자 동사, prompt는 사용자가 그대로 보낼 수 있는 문장.
   잔소리하지 마. 같은 내용을 이미 open_items에 있으면 다시 만들지 마.
   사용자가 ‘나중에’를 누른 kind는 같은 대화에서 다시 만들지 마.

출력 형식(JSON만):
{"title":"","depth":0,"seg":null,"topic":null,"dec":null,"ret":false,"ref":null,
 "parts":[{"t":"","type":"q|task|rev","open":false,"target":null}],
 "files":[],
 "items":[{"kind":"","text":"","why":"","btn":"","prompt":"","at":null}],
 "nudge_index":0}
```

## 3. 예시

실제 대화에서 가져온 예시라 공개 저장소에는 올리지 않아요. 팀 내부 파일 `docs/agent-prompt.examples.md`(각자 PC)에 있어요.

## 4. 모델과 비용

- 분류는 작은 모델로 충분해요(Claude Haiku급 · GPT mini급). 입력 2~3천 토큰, 출력 3백 토큰 안팎이라 턴당 1센트 미만이에요. 가격은 구현 시점에 공식 문서로 다시 확인하세요.
- `repeat` · `handoff`의 비슷한 대화 찾기는 임베딩 + SQLite(또는 로컬 벡터 저장소)로 LLM 호출 없이 해요.
- 지난 대화 찾기(`/search`)도 LLM 없이 문자열 + 임베딩 검색.
- **MCP 입구**: Claude 데스크톱에서는 위 규칙을 `record_turn` 도구 설명에 넣어 Claude가 직접 JSON을 채워요. 그래서 별도 API 키와 비용이 없어요.

## 5. 정확도 평가 (eval/)

- `data/example_conversations.json`의 실제 대화(u1)가 정답 라벨이에요. depth · dec · parts · ret · ref를 사람이 확정한 값이에요.
- 지표: depth 정확도, dec 재현율, parts 개수 일치율, items 정밀도(쓸데없는 한마디 비율).
- 발표용 숫자: “실제 대화 58턴에서 depth 정확도 n%, 결정 재현율 n%”.
