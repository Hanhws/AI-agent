"""가닥 백엔드. 내 PC(127.0.0.1)에서만 떠요.

실행: python -m backend.launch   (프로그램처럼: 대화 기록 읽기 · 정리 · 화면까지)
      python -m backend.app      (서버만. 기록 읽기와 정리는 돌지 않아요)
"""
from flask import Flask, abort, g, jsonify, request, send_from_directory

from . import assemble, config, sources, store, usage
from .agent import trace
from .engines import describe_engine
from .runtime import Runtime
from .sources import exports

LOCAL_HOSTS = {"127.0.0.1", "localhost"}
UPLOAD_TYPES = {"application/zip", "application/json", "application/octet-stream"}
WEB_DIR = config.ROOT / "backend" / "web"
UI_DIR = config.ROOT / "shared" / "ui"
DEMO_FILE = "demo_conversations.json"


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
    def bad_event(exc):
        return jsonify(error=str(exc)), 400

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
        return jsonify(ok=True, app="gadak", engine=describe_engine())

    @app.get("/status")
    def status():
        return jsonify(rt.status())

    @app.get("/sources")
    def source_list():
        return jsonify(sources=sources.detect(store.site_counts(db())))

    @app.post("/sources/cursor/connect")
    def cursor_connect():
        result = sources.connect_cursor()
        usage.record(db(), "connect", cursor=bool(result["ok"]))
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
        return jsonify(projects=store.projects(db()))

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

    # ----- 사용 기록 (backend/usage.py) -----
    @app.get("/usage/state")
    def usage_state():
        return jsonify(usage.state(db()))

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
