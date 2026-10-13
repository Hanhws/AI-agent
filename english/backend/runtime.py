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
WINDOW_GRACE = 6.0    # 초. 창을 띄운 브라우저가 끝난 뒤 이만큼 더 봐요: 화면이 계속 물으면 창은 살아 있는 거예요
WINDOW_QUIET = 150.0  # 초. 그 뒤로는 화면이 이만큼 묻지 않으면 닫힌 것으로 봐요 (가려 둔 창은 1분에 한 번만 물어요)
WINDOW_STEP = 15.0    # 초. 묻는지 보는 간격. 잠든 동안은 세지 않아요 (깨어나자마자 꺼지지 않게)


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

    def watch_window(self, process, grace=WINDOW_GRACE, quiet=WINDOW_QUIET, step=WINDOW_STEP) -> None:
        """창 하나로 도는 가닥(launch.py --app · Windows 앱)은 그 창이 닫히면 따라 꺼져요. process는 창을 띄운 브라우저예요.
        브라우저가 먼저 떠 있던 자기 창에 일을 넘기고 바로 끝나기도 해요. 그래서 끝난 뒤에도 화면이 계속 물으면(/status)
        창이 살아 있다고 보고, 그때는 화면이 한동안 묻지 않을 때 꺼요."""
        def watch():
            process.wait()
            ended, alive = time.time(), False
            while not alive and time.time() - ended < grace:
                if self._stop.wait(min(0.5, grace / 4)):
                    return
                alive = (self.last_seen or 0) > ended + grace / 3
            misses = 0
            while alive and misses * step < quiet:
                seen = self.last_seen
                if self._stop.wait(step):
                    return
                misses = 0 if self.last_seen != seen else misses + 1
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
