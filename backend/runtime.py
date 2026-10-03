"""켜져 있는 동안 도는 것들: 대화 기록 읽기(sources) · 정리(agent) · 화면에 알릴 변경 번호.

화면은 /status의 rev가 바뀔 때만 노선도를 다시 불러와요.
"""
import threading
import time
from pathlib import Path

from . import config, store
from .agent.classify import Classifier
from .sources.sync import Syncer

IDLE_EXIT = 180  # 초. 프로그램처럼 켰을 때, 창이 닫히고 이만큼 지나면 스스로 꺼져요


class Runtime:
    def __init__(self, db_path=None, engine="auto", home=None):
        self.db_path = Path(db_path or config.DB_PATH)
        self.home = Path(home) if home else (config.HOME if db_path is None else self.db_path.parent)
        self.rev = 0
        self.started = time.time()
        self.last_seen = None        # 화면이 마지막으로 물어본 때
        self.exit_when_idle = False
        self.on_quit = None
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self.connect().close()       # 스레드들이 돌기 전에 저장소를 한 번 만들어 둬요
        self.syncer = Syncer(self)
        self.classifier = Classifier(self, engine)

    def connect(self):
        return store.connect(self.db_path)

    def bump(self) -> None:
        with self._lock:
            self.rev += 1

    def start(self) -> None:
        """읽기 · 정리 · (프로그램 모드면) 창이 닫혔는지 보는 일을 뒤에서 돌려요."""
        for target in (self.syncer.run_forever, self.classifier.run_forever, self._watch_idle):
            threading.Thread(target=target, args=(self._stop,), daemon=True).start()

    def quit(self) -> None:
        self._stop.set()
        if self.on_quit:
            # 끄라는 요청에 답을 보낸 다음에 서버를 내려요
            threading.Timer(0.3, self.on_quit).start()

    def _watch_idle(self, stop) -> None:
        while not stop.wait(15):
            seen = self.last_seen or self.started
            if self.exit_when_idle and time.time() - seen > IDLE_EXIT:
                self.quit()

    def status(self) -> dict:
        self.last_seen = time.time()
        try:
            self.classifier.engine()
        except Exception as exc:
            self.classifier.status["error"] = str(exc)[:200]
        sync, classify = self.syncer.status, dict(self.classifier.status)
        classify["queued"] = len(self.classifier.queue)
        return {
            "rev": self.rev,
            "sync": {k: sync.get(k) for k in ("phase", "done", "total", "scans", "error")},
            "classify": classify,
        }
