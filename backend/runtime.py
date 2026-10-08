"""켜져 있는 동안 도는 것들: 대화 기록 읽기(sources) · 정리(agent) · 화면에 알릴 변경 번호.

화면은 /status의 rev가 바뀔 때만 노선도를 다시 불러와요.
"""
import os
import threading
import time
from pathlib import Path

from . import config, store, usage
from .engines import resolve_name
from .agent.classify import Classifier
from .sources.sync import Syncer

PARENT_CHECK = 1.5  # 초. 가닥 앱이 살아 있는지 보는 간격


class Runtime:
    def __init__(self, db_path=None, engine="auto", home=None):
        self.db_path = Path(db_path or config.DB_PATH)
        self.home = Path(home) if home else (config.HOME if db_path is None else self.db_path.parent)
        self.rev = 0
        self.started = time.time()
        self.last_seen = None        # 화면이 마지막으로 물어본 때
        self.on_quit = None
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self.connect().close()       # 스레드들이 돌기 전에 저장소를 한 번 만들어 둬요
        self.syncer = Syncer(self)
        self.classifier = Classifier(self, engine)
        self.sender = usage.Sender(self)   # 동의한 사용 기록을 가닥 팀 서버로 (서버 주소가 없으면 쉬어요)
        self.via = "browser"               # 가닥 앱이 켰으면 "app" (launch.py)
        self.extension_noted = 0.0         # 크롬 확장이 다녀간 것을 저장소에 마지막으로 적은 때

    def connect(self):
        return store.connect(self.db_path)

    def bump(self) -> None:
        with self._lock:
            self.rev += 1

    def start(self) -> None:
        """읽기 · 정리를 뒤에서 돌려요."""
        for target in (self.syncer.run_forever, self.classifier.run_forever, self.sender.run_forever):
            threading.Thread(target=target, args=(self._stop,), daemon=True).start()

    def opened(self, conn) -> None:
        """켜고 처음 한 번 다 읽은 뒤: 어떤 입구의 대화가 얼마나 있는지 사용 기록에 적어요."""
        usage.note_open(conn, self.via, self.classifier.status["engine"] or resolve_name())

    def watch_parent(self, pid) -> None:
        """가닥 앱이 켠 백엔드는 앱이 사라지면(강제 종료 포함) 따라 꺼져요. 혼자 남아 돌지 않게요."""
        def watch():
            while not self._stop.wait(PARENT_CHECK):
                if os.getppid() != pid:
                    self.quit()
        threading.Thread(target=watch, daemon=True).start()

    def quit(self) -> None:
        self._stop.set()
        if self.on_quit:
            # 끄라는 요청에 답을 보낸 다음에 서버를 내려요
            threading.Timer(0.3, self.on_quit).start()

    def status(self) -> dict:
        self.last_seen = time.time()
        try:
            self.classifier.engine()
        except Exception as exc:
            self.classifier.status["error"] = str(exc)[:200]
        sync, classify = self.syncer.status, dict(self.classifier.status)
        classify["queued"] = len(self.classifier.queue)
        classify["checkQueued"] = len(self.classifier.checker.queue)   # 2단을 기다리는 대화
        classify["aheadQueued"] = len(self.classifier.checker.wanted)  # 사용자가 ‘앞길 보기’를 눌러 기다리는 대화
        return {
            "rev": self.rev,
            "sync": {k: sync.get(k) for k in ("phase", "done", "total", "scans", "error")},
            "classify": classify,
            # 앞길 살피기(backend/agent/ahead.py)가 켜져 있는지. 화면이 ‘앞길 보기’를 보일지 정해요
            "ahead": {"on": config.AHEAD, "web": config.AHEAD and config.AHEAD_WEB, "files": config.AHEAD and config.AHEAD_FILES},
        }
