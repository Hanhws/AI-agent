"""가닥 팀 서버: 동의한 사용자의 사용 기록을 받아 모으고, 통계로 보여 줘요 (README 5장).

대화 내용은 받지 않아요. 받는 것은 backend/usage_schema.py의 표에 있는 숫자 · 참거짓 · 정해 둔 낱말뿐이고,
표에 없는 것은 저장하지 않아요. 누가 보냈는지는 무작위 설치 번호로만 알고, IP 주소는 저장하지 않아요.

실행  python -m server.app                 (내 PC에서 시험: http://127.0.0.1:7321)
환경  GADAK_SERVER_DB      저장 파일 (기본 server-data/usage.db)
      GADAK_SERVER_TOKEN   통계를 볼 때 넣는 암호. 정하지 않으면 통계를 볼 수 없어요
      GADAK_SERVER_HOST · PORT   받을 주소와 포트 (배포한 곳에서 정해 줘요)

POST /v1/events   {v, install, app, events: [{seq, day, name, fields}]}  → {stored, dropped}
POST /v1/forget   {install}                                              → {deleted}
GET  /v1/stats    Authorization: Bearer <암호>, ?days=7                   → 통계
GET  /            통계 화면 (암호를 물어요)
"""
import hmac
import json
import os
import re
import sqlite3
from datetime import date, timedelta
from pathlib import Path

from flask import Flask, abort, jsonify, request, send_from_directory

from backend import usage_schema

from . import stats

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "server" / "web"
MAX_BODY = 512 * 1024
MAX_EVENTS = 500
APP_VERSION = re.compile(r"\d{1,3}\.\d{1,3}\.\d{1,3}")

SCHEMA = """
CREATE TABLE IF NOT EXISTS events(
  install TEXT NOT NULL,
  seq INTEGER NOT NULL,
  day TEXT NOT NULL,
  name TEXT NOT NULL,
  fields_json TEXT NOT NULL,
  app TEXT,
  PRIMARY KEY(install, seq)
);
CREATE INDEX IF NOT EXISTS events_day ON events(day);
"""


def create_app(db_path=None, token=None) -> Flask:
    app = Flask(__name__, static_folder=None)
    app.config["MAX_CONTENT_LENGTH"] = MAX_BODY
    app.json.ensure_ascii = False
    db_path = Path(db_path or os.environ.get("GADAK_SERVER_DB") or ROOT / "server-data" / "usage.db")
    token = token if token is not None else os.environ.get("GADAK_SERVER_TOKEN", "")

    def connect():
        db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(db_path, timeout=15)
        conn.executescript(SCHEMA)
        return conn

    def body():
        data = request.get_json(silent=True)
        if not isinstance(data, dict) or not usage_schema.valid_install(data.get("install")):
            abort(400)
        return data

    @app.post("/v1/events")
    def events():
        data = body()
        batch = data.get("events")
        if not isinstance(batch, list) or len(batch) > MAX_EVENTS:
            abort(400)
        version = data.get("app") if isinstance(data.get("app"), str) and APP_VERSION.fullmatch(data["app"]) else None
        keep, dropped = [], 0
        for event in batch:
            # 표에 없는 이름 · 칸 · 값은 여기서 떨어져요. 저장되는 것은 걸러진 것뿐이에요
            fields = usage_schema.clean(event.get("name"), event.get("fields")) if isinstance(event, dict) else None
            seq = event.get("seq") if isinstance(event, dict) else None
            if not fields or isinstance(seq, bool) or not isinstance(seq, int) or seq < 0 \
                    or not usage_schema.valid_day(event.get("day")):
                dropped += 1
                continue
            keep.append((data["install"], seq, event["day"], event["name"], json.dumps(fields), version))
        conn = connect()
        with conn:
            conn.executemany("INSERT OR IGNORE INTO events VALUES(?, ?, ?, ?, ?, ?)", keep)
        conn.close()
        return jsonify(stored=len(keep), dropped=dropped)

    @app.post("/v1/forget")
    def forget():
        """그 PC가 보낸 기록을 모두 지워요. 설치 번호는 그 PC만 알아요."""
        data = body()
        conn = connect()
        with conn:
            deleted = conn.execute("DELETE FROM events WHERE install = ?", (data["install"],)).rowcount
        conn.close()
        return jsonify(deleted=deleted)

    @app.get("/v1/stats")
    def summary():
        given = request.headers.get("Authorization", "")
        if not token or not hmac.compare_digest(given.encode(), ("Bearer " + token).encode()):
            abort(403)
        days = request.args.get("days", type=int)
        where, values = "", []
        if days and days > 0:
            where, values = " WHERE day >= ?", [(date.today() - timedelta(days=days - 1)).isoformat()]
        conn = connect()
        rows = conn.execute(
            "SELECT install, seq, day, name, fields_json FROM events" + where + " ORDER BY install, seq", values
        ).fetchall()
        conn.close()
        return jsonify(stats.summarize((i, s, d, n, json.loads(f)) for i, s, d, n, f in rows))

    @app.get("/")
    def page():
        return send_from_directory(WEB, "stats.html", max_age=0)

    @app.get("/tokens.css")
    def tokens():
        return send_from_directory(ROOT / "shared" / "ui", "tokens.css", max_age=0)

    @app.get("/health")
    def health():
        return jsonify(ok=True, app="gadak-server", schema=usage_schema.VERSION)

    return app


def main():
    host = os.environ.get("GADAK_SERVER_HOST", "127.0.0.1")
    port = int(os.environ.get("PORT") or os.environ.get("GADAK_SERVER_PORT") or 7321)
    create_app().run(host=host, port=port)


if __name__ == "__main__":
    main()
