"""예시 대화를 가닥에 흘려보내고(backend/replay.py), 가닥이 붙인 값을 받아 와요.

임시 저장소에서 돌아서 내 가닥(~/.gadak)과 켜져 있는 가닥은 건드리지 않아요. 1단(분류)과 2단(확인)은
가닥이 평소에 도는 그 일꾼(Classifier)을 그대로 써요. 엔진 호출만 세고 시간을 재요.
"""
import json
import tempfile
import time
from pathlib import Path

from backend import config, replay, store
from backend.agent import classify, trace
from backend.runtime import Runtime


class Meter:
    """엔진을 감싸 호출 수 · 걸린 시간 · (엔진이 알려 주면) 토큰과 값을 모아요."""

    def __init__(self, engine):
        self.engine = engine
        self.name = getattr(engine, "name", "engine")
        self.model = getattr(engine, "model", None)
        self.calls = {"classify": 0, "check": 0}
        self.seconds = {"classify": 0.0, "check": 0.0}
        self.tokens = {"in": 0, "out": 0}
        self.cost = 0.0
        self.priced = 0          # 값을 알려 준 호출 수

    def complete_json(self, system, prompt, schema):
        try:
            stage = "check" if "trigger" in json.loads(prompt) else "classify"     # 2단의 입력에는 확인하는 까닭이 있어요
        except ValueError:
            stage = "classify"
        began = time.time()
        try:
            return self.engine.complete_json(system, prompt, schema)
        finally:
            self.calls[stage] += 1
            self.seconds[stage] += time.time() - began
            last = getattr(self.engine, "last", None) or {}
            self.tokens["in"] += int(last.get("input_tokens") or 0)
            self.tokens["out"] += int(last.get("output_tokens") or 0)
            if last.get("cost") is not None:
                self.cost += float(last["cost"])
                self.priced += 1
            if hasattr(self.engine, "last"):
                self.engine.last = None

    def stats(self) -> dict:
        out = {"engine": self.name, "model": self.model, "calls": dict(self.calls),
               "seconds": {k: round(v, 1) for k, v in self.seconds.items()}}
        if self.tokens["in"] or self.tokens["out"]:
            out["tokens"] = dict(self.tokens)
        if self.priced:
            out["cost_usd"] = round(self.cost, 4)
        return out


def run(scenario, engine, check=True, max_calls=120, say=None) -> dict:
    """시나리오 하나를 처음부터 끝까지. 돌려주는 것: view(화면이 받는 모양) · stats(호출 · 시간) · runs(2단이 돈 수) · error."""
    meter = Meter(engine)
    kept = config.CHECK_MODEL
    config.CHECK_MODEL = meter.model      # 2단도 같은 엔진 · 같은 모델로 (재는 동안만)
    try:
        with tempfile.TemporaryDirectory() as tmp:
            rt = Runtime(Path(tmp) / "gadak.db", engine=meter)
            clf = classify.Classifier(rt, meter, max_calls=max_calls)
            rt.classifier = clf
            conn = rt.connect()
            try:
                fed = replay.feed(conn, scenario)
                for chat_id in fed["chats"]:              # 오래된 대화부터: 뒤 대화의 ‘이어 가기’는 앞 대화의 정함을 봐요
                    clf.request(chat_id)
                while clf.queue and not clf.status["paused"]:
                    clf.step(conn)                        # 1단: 대화 하나를 분류하고, 2단이 볼 턴을 줄 세워요
                    if say:
                        say(f"1단 {clf.status['turns']}턴 · 호출 {meter.calls['classify']}번")
                if not check:
                    clf.checker.queue.clear()
                while clf.checker.queue and not clf.status["paused"]:
                    if not clf.step(conn):                # 2단: 걸린 턴을 하나씩 확인해요
                        break
                    if say:
                        say(f"2단 {clf.status['checks']}턴 확인 · 호출 {meter.calls['check']}번")
                project = store.chat_row(conn, fed["chats"][0])["project_id"]
                view = store.view(conn, project, scope="all")
                runs = trace.runs(conn, limit=300)
                unlabeled = [r["message_ref"] for r in conn.execute(
                    "SELECT message_ref FROM turns WHERE classified != 1 ORDER BY chat_id, seq")]
                refs = {r["id"]: r["message_ref"] for r in conn.execute("SELECT id, message_ref FROM turns")}
                # 2단이 턴마다 한 일 (어느 도구를 썼고 무엇을 만들고 버렸는지). 한마디의 글이 들어 있어서 내 PC에만 남겨요
                traces = [{"turn": refs.get(r["turn"]["id"]), "trigger": r["trigger"], "tools": [s["tool"] for s in r["steps"]],
                           "calls": r["calls"], "ended": r["ended"], "items": [{"kind": i["kind"], "text": i["text"]} for i in r["items"]],
                           "missing": [m["t"] for m in r["missing"]], "dropped": r["dropped"]} for r in reversed(runs)]
                waiting = sum(len(store.waiting_checks(conn, chat_id)) for chat_id in fed["chats"]) if check else 0
            finally:
                conn.close()
    finally:
        config.CHECK_MODEL = kept
    return {
        "view": view, "stats": meter.stats(), "error": clf.status["error"],
        "unlabeled": unlabeled,           # 가닥이 분류하지 못한 턴 (정답 파일의 턴 id). 화면에는 임시 제목의 본류 역으로 보여요
        "traces": traces,
        "checks": {"ran": len(runs), "waiting": waiting, "made": sum(len(r["items"]) for r in runs),
                   "missing": sum(len(r["missing"]) for r in runs), "dropped": sum(len(r["dropped"]) for r in runs),
                   "triggers": sorted({t for r in runs for t in r["trigger"]})},
    }


def load(path, key) -> dict:
    data = replay.scenario(path, key)
    data.setdefault("key", key)
    return data


def read_json(path, default=None):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default
