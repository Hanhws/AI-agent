"""가닥 백엔드. 내 PC(127.0.0.1)에서만 떠요.

실행: python -m backend.launch   (프로그램처럼: 대화 기록 읽기 · 정리 · 화면까지)
      python -m backend.app      (서버만. 기록 읽기와 정리는 돌지 않아요)
"""
import time

from flask import Flask, abort, g, jsonify, request, send_from_directory

from . import assemble, auto, config, sources, store, usage
from .agent import trace
from .engines import describe_engine
from .runtime import Runtime
from .sources import exports, pages

LOCAL_HOSTS = {"127.0.0.1", "localhost"}
UPLOAD_TYPES = {"application/zip", "application/json", "application/octet-stream"}
WEB_DIR = config.ROOT / "backend" / "web"
UI_DIR = config.ROOT / "shared" / "ui"
DEMO_FILE = "demo_conversations.json"
EXTENSION_HEADER = "X-Gadak-Extension"   # 크롬 확장이 요청마다 붙이는 자기 버전 (extension/background.js)
EXTENSION_NOTE_EVERY = 60                # 초. 확장이 다녀간 때는 이 간격으로만 적어요


def create_app(db_path=None, engine="auto") -> Flask:
    app = Flask(__name__, static_folder=None)
    rt = Runtime(db_path, engine=engine)
    app.config["DB_PATH"] = rt.db_path
    app.config["GADAK"] = rt
    app.json.ensure_ascii = False

    def db():
        if "db" not in g:
            g.db = store.connect(app.config["DB_PATH"])
        return g.db

    @app.teardown_appcontext
    def close_db(_exc):
        conn = g.pop("db", None)
        if conn is not None:
            conn.close()

    @app.before_request
    def local_only():
        # 열어 둔 다른 웹 페이지가 이 서버를 부르지 못하게 해요: Host는 로컬만, 쓰기는 JSON만.
        # 파일 올리기(/import)의 zip도 브라우저가 다른 사이트에서는 먼저 허락을 구하는 형식이라 같아요
        if request.host.split(":")[0] not in LOCAL_HOSTS:
            abort(403)
        if request.method in ("POST", "PATCH") and not request.is_json:
            if not (request.path == "/import" and request.mimetype in UPLOAD_TYPES):
                abort(415)

    @app.errorhandler(assemble.BadEvent)
    @app.errorhandler(pages.BadPage)
    def bad_event(exc):
        return jsonify(error=str(exc)), 400

    @app.errorhandler(pages.Elsewhere)
    def page_elsewhere(exc):
        return jsonify(error=str(exc)), 409

    def extension_here():
        """크롬 확장이 다녀갔어요. 찾은 곳에 ‘연결됨’으로 보이게 마지막 때를 적어 둬요."""
        version = request.headers.get(EXTENSION_HEADER)
        if version and time.time() - rt.extension_noted > EXTENSION_NOTE_EVERY:
            rt.extension_noted = time.time()
            conn = db()
            with conn:
                pages.note_seen(conn, version)

    # ----- 화면 (로컬 웹 페이지) -----
    @app.get("/")
    def index():
        return send_from_directory(WEB_DIR, "index.html", max_age=0)

    @app.get("/trace")
    def trace_page():
        """판단 기록: 2단이 어떤 도구를 어떤 순서로 썼고 무엇을 보고 결론 냈는지 (README 3-1)."""
        return send_from_directory(WEB_DIR, "trace.html", max_age=0)

    @app.get("/web/<path:name>")
    def web_file(name):
        return send_from_directory(WEB_DIR, name, max_age=0)

    @app.get("/ui/<path:name>")
    def ui_file(name):
        return send_from_directory(UI_DIR, name, max_age=0)

    @app.get("/data/<name>")
    def data_file(name):
        # 만든 예시(demo)와, 있으면 각자 PC에만 있는 실제 예시(example · 공개 저장소에 없음)
        if name not in (DEMO_FILE, "example_conversations.json"):
            abort(404)
        return send_from_directory(config.ROOT / "data", name, max_age=0)

    # ----- 상태 -----
    @app.get("/health")
    def health():
        extension_here()
        return jsonify(ok=True, app="gadak", engine=describe_engine(), code=config.CODE)

    @app.get("/status")
    def status():
        return jsonify(rt.status())

    @app.get("/sources")
    def source_list():
        return jsonify(sources=sources.detect(store.site_counts(db()), pages.status(db())))

    @app.post("/sources/cursor/connect")
    def cursor_connect():
        result = sources.connect_cursor()
        usage.record(db(), "connect", cursor=bool(result["ok"]))
        rt.bump()
        return jsonify(result), (200 if result["ok"] else 409)

    @app.post("/sources/claude-code/connect")
    def claude_connect():
        """자동 실행에 쓸 hook 둘(Stop · SessionStart)을 Claude Code 설정에 더해요. 사용자가 눌렀을 때만."""
        result = sources.connect_claude()
        rt.bump()
        return jsonify(result), (200 if result["ok"] else 409)

    @app.post("/sources/claude-code/disconnect")
    def claude_disconnect():
        result = sources.disconnect_claude()
        rt.bump()
        return jsonify(result), (200 if result["ok"] else 409)

    @app.post("/quit")
    def quit_app():
        rt.quit()
        return jsonify(ok=True)

    # ----- 입구가 보내는 것 -----
    @app.post("/events")
    def events():
        body = request.get_json()
        batch = body["events"] if isinstance(body, dict) and "events" in body else [body]
        turns = [assemble.ingest_event(db(), event) for event in batch]
        for event in batch:
            if event.get("kind") in ("answer", "stop"):
                rt.classifier.request(event.get("chat_id"))
        rt.bump()
        return jsonify(turns=[t for t in turns if t])

    @app.post("/turns")
    def turns():
        body = request.get_json()
        turn = assemble.ingest_turn(db(), body)
        rt.classifier.request(body["chat"]["id"])
        rt.bump()
        return jsonify(turn=turn, items=[], nudge=None)

    @app.post("/pages")
    def page_in():
        """크롬 확장이 지금 열린 대화 화면을 통째로 보내요. 저장소의 역과 맞추는 건 backend/sources/pages.py."""
        extension_here()
        result = pages.ingest(db(), request.get_json())
        if result["live"]:
            rt.classifier.request(result["chat"])     # 방금 끝난 턴만 바로 정리해요. 열어 본 지난 대화는 볼 때
        if result["new"] or result["changed"]:
            rt.bump()
        return jsonify(result)

    @app.post("/import")
    def import_file():
        try:
            chats = exports.read(request.get_data())
        except exports.BadExport as exc:
            usage.record(db(), "import", ok=False)
            return jsonify(error=str(exc)), 400
        result = exports.ingest(db(), chats)
        usage.record(db(), "import", ok=True, turns=result["turns"],
                     **{site: sum(1 for c in chats if c["site"] == site) for site in ("claude", "chatgpt")})
        rt.bump()
        return jsonify(chats=result["chats"], turns=result["turns"])

    # ----- 화면이 읽는 것 -----
    @app.get("/projects")
    def projects():
        return jsonify(projects=store.projects(db()), hidden=store.hidden_count(db()))

    # ----- 목록에서 빼기 · 되돌리기: 읽어 둔 글은 지우지 않고, 화면 · 찾기 · 정리에서만 빠져요 -----
    @app.get("/chats/hidden")
    def hidden_list():
        return jsonify(chats=store.hidden_chats(db()))

    @app.post("/chats/hidden")
    def hidden_set():
        body = request.get_json() or {}
        ids, hidden = body.get("ids"), body.get("hidden")
        if not isinstance(ids, list) or not all(isinstance(i, str) for i in ids) or not isinstance(hidden, bool):
            abort(400)
        conn = db()
        with conn:
            changed = store.set_hidden(conn, ids[:1000], hidden)
        if changed:
            rt.bump()
        return jsonify(ids=changed, hidden=store.hidden_count(conn))

    @app.post("/projects/<project_id>/hide")
    def project_hide(project_id):
        """그 프로젝트에서 지금 보이는 대화를 모두 빼요. 뺀 대화의 id를 돌려줘서 바로 되돌릴 수 있어요."""
        conn = db()
        with conn:
            changed = store.set_hidden(conn, store.visible_chat_ids(conn, project_id), True)
        if changed:
            rt.bump()
        return jsonify(ids=changed, hidden=store.hidden_count(conn))

    @app.get("/projects/<project_id>/view")
    def view(project_id):
        scope = request.args.get("scope", "all")
        data = store.view(db(), project_id, scope=scope, chat_id=request.args.get("chat"))
        if data is None:
            abort(404)
        return jsonify(data)

    @app.get("/projects/<project_id>/search")
    def search(project_id):
        return jsonify(hits=store.search(db(), project_id, request.args.get("q", "")))

    @app.get("/chats/search")
    def find_chats():
        """모든 프로젝트의 대화에서 찾기 (가닥 창 왼쪽의 ‘대화 찾기’)."""
        return jsonify(chats=store.find_chats(db(), request.args.get("q", "")))

    @app.get("/turns/<turn_id>")
    def turn(turn_id):
        data = store.turn_full(db(), turn_id)
        if data is None:
            abort(404)
        return jsonify(turn=data)

    @app.get("/turns/<turn_id>/trace")
    def turn_trace(turn_id):
        return jsonify(runs=trace.runs(db(), turn_id=turn_id))

    @app.get("/runs")
    def runs():
        """판단 기록 목록. 최근 것부터, project를 주면 그 프로젝트만."""
        limit = min(max(request.args.get("limit", 60, type=int), 1), 300)
        return jsonify(runs=trace.runs(db(), project_id=request.args.get("project") or None, limit=limit))

    @app.patch("/items/<path:item_id>")
    def item(item_id):
        conn = db()
        with conn:
            if not store.set_item_state(conn, item_id, (request.get_json() or {}).get("state")):
                abort(400)
        rt.bump()
        return jsonify(ok=True)

    # ----- 승인한 종류의 자동 실행 (backend/auto.py) -----
    @app.get("/auto")
    def auto_state():
        return jsonify(auto=auto.state(db()), ways=sources.auto_ways())

    @app.post("/auto")
    def auto_set():
        """종류별 ‘앞으로는 알아서’를 켜고 꺼요. 화면에서 사용자가 눌렀을 때만 불러요."""
        body = request.get_json() or {}
        if body.get("kind") not in auto.KINDS or not isinstance(body.get("on"), bool):
            abort(400)
        state = auto.set_enabled(db(), body["kind"], body["on"])
        rt.bump()
        return jsonify(auto=state, ways=sources.auto_ways())

    @app.post("/auto/stop")
    def auto_stop():
        """턴이 끝났을 때 hook이 물어요: 이어서 보낼 글이 있나요? (확인이 끝날 때까지 기다릴 수 있어요)"""
        return jsonify(auto.on_stop(rt, db(), request.get_json() or {}))

    @app.post("/auto/start")
    def auto_start():
        """새 대화가 시작될 때 hook이 물어요: 넣을 요약이 있나요?"""
        result = auto.on_start(db(), request.get_json() or {})
        if result["context"]:
            rt.bump()
        return jsonify(result)

    # ----- 사용 기록 (backend/usage.py) -----
    @app.get("/usage/state")
    def usage_state():
        # error: 보내려다 실패했으면 그 까닭의 이름. 다음 차례에 다시 보내요
        return jsonify(dict(usage.state(db()), error=rt.sender.status["error"]))

    @app.get("/usage/recent")
    def usage_recent():
        """보내는 것 보기: 서버로 가는 모양 그대로."""
        return jsonify(events=usage.recent(db()))

    @app.post("/usage/consent")
    def usage_consent():
        body = request.get_json() or {}
        if body.get("forget") is True:
            return jsonify(usage.forget(db()))
        if not isinstance(body.get("share"), bool):
            abort(400)
        state = usage.consent(db(), body["share"])
        rt.sender.poke()
        return jsonify(state)

    @app.post("/usage")
    def usage_record():
        """화면에서 누른 것. 화면이 적을 수 있는 종류는 둘뿐이에요."""
        body = request.get_json() or {}
        if body.get("name") not in ("ui", "item"):
            abort(400)
        fields = body.get("fields") if isinstance(body.get("fields"), dict) else {}
        return jsonify(ok=usage.record(db(), body["name"], fields))

    @app.post("/classify")
    def classify():
        """화면에 보이는 대화를 정리해 달라는 요청. 엔진은 뒤에서 차례로 돌아요."""
        body = request.get_json() or {}
        if "pause" in body:
            rt.classifier.pause() if body["pause"] else rt.classifier.resume()
        for chat_id in body.get("chats") or []:
            rt.classifier.request(chat_id, front=True)
        return jsonify(rt.status()["classify"])

    return app


def main():
    create_app().run(host=config.HOST, port=config.PORT)


if __name__ == "__main__":
    main()
