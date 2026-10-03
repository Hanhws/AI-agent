"""가닥 백엔드. 내 PC(127.0.0.1)에서만 떠요.

실행: python -m backend.app
"""
from flask import Flask, abort, g, jsonify, request

from . import assemble, config, store
from .engines import describe_engine

LOCAL_HOSTS = {"127.0.0.1", "localhost"}


def create_app(db_path=None) -> Flask:
    app = Flask(__name__)
    app.config["DB_PATH"] = db_path or config.DB_PATH
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
        # 열어 둔 다른 웹 페이지가 이 서버를 부르지 못하게 해요: Host는 로컬만, 쓰기는 JSON만
        if request.host.split(":")[0] not in LOCAL_HOSTS:
            abort(403)
        if request.method == "POST" and not request.is_json:
            abort(415)

    @app.errorhandler(assemble.BadEvent)
    def bad_event(exc):
        return jsonify(error=str(exc)), 400

    @app.get("/health")
    def health():
        return jsonify(ok=True, engine=describe_engine())

    @app.post("/events")
    def events():
        body = request.get_json()
        batch = body["events"] if isinstance(body, dict) and "events" in body else [body]
        turns = [assemble.ingest_event(db(), event) for event in batch]
        return jsonify(turns=[t for t in turns if t])

    @app.post("/turns")
    def turns():
        turn = assemble.ingest_turn(db(), request.get_json())
        return jsonify(turn=turn, items=[], nudge=None)

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

    return app


def main():
    create_app().run(host=config.HOST, port=config.PORT)


if __name__ == "__main__":
    main()
