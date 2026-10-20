"""Python's cycle collector runs on whichever thread happens to allocate, so a Qt object caught in a reference cycle
could be destroyed on the build or download thread. Qt objects must be destroyed on the thread they live in (a
QFileSystemWatcher or a widget destroyed elsewhere crashes the app later), so the app turns automatic collection off and
collects on the GUI thread instead, as often as Python would."""
import gc

from PySide6.QtCore import QObject, QTimer

INTERVAL_MS = 250


def collect_step() -> None:
    """One collection on this thread: the youngest generation, and the older ones as often as Python would."""
    _, t1, t2 = gc.get_threshold()
    _, c1, c2 = gc.get_count()
    gc.collect(2 if c2 > t2 else 1 if c1 > t1 else 0)


class GuiThreadCollector(QObject):
    """Create and start it on the GUI thread; stop() gives collection back to Python as it was."""

    def __init__(self, parent: QObject | None = None, interval_ms: int = INTERVAL_MS):
        super().__init__(parent)
        self._timer = QTimer(self)
        self._timer.setInterval(interval_ms)
        self._timer.timeout.connect(self.collect)
        self._was_enabled = gc.isenabled()

    def start(self) -> None:
        self._was_enabled = gc.isenabled()
        gc.disable()
        self._timer.start()

    def stop(self) -> None:
        self._timer.stop()
        if self._was_enabled:
            gc.enable()

    def collect(self) -> None:
        collect_step()
