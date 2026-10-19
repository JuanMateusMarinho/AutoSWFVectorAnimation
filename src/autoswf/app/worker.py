"""The background build thread: one job at a time; a new build cancels the running one between stages and replaces any
build still waiting, so the latest settings always win. Other jobs (exports) are never dropped."""
import threading
from collections import deque
from typing import Callable

from PySide6.QtCore import QObject, Signal

from autoswf.project.build import BuildCancelled

Job = Callable[[Callable[[str], None], Callable[[], bool]], object]


class BuildWorker(QObject):
    progress = Signal(int, str)
    finished = Signal(int, object)      # request number, the job's result or the exception it raised

    def __init__(self):
        super().__init__()
        self._lock = threading.Condition()
        self._queue: deque[tuple[int, str, Job]] = deque()
        self._count = 0
        self._latest_build = 0
        self._stopped = False
        self._thread = threading.Thread(target=self._loop, name="autoswf-build", daemon=True)
        self._thread.start()

    def request(self, job: Job, kind: str = "build") -> int:
        with self._lock:
            self._count += 1
            n = self._count
            if kind == "build":
                self._latest_build = n
                self._queue = deque(item for item in self._queue if item[1] != "build")
            self._queue.append((n, kind, job))
            self._lock.notify()
        return n

    def _loop(self) -> None:
        while True:
            with self._lock:
                while not self._queue and not self._stopped:
                    self._lock.wait()
                if self._stopped:
                    return
                n, kind, job = self._queue.popleft()

            def cancelled(n=n, kind=kind) -> bool:
                return self._stopped or (kind == "build" and n != self._latest_build)
            try:
                result = job(lambda text, n=n: self.progress.emit(n, text), cancelled)
            except BuildCancelled:
                continue
            except Exception as e:          # reported to the window, never lost on this thread
                result = e
            if not self._stopped:
                self.finished.emit(n, result)

    def stop(self) -> None:
        with self._lock:
            self._stopped = True
            self._lock.notify()
