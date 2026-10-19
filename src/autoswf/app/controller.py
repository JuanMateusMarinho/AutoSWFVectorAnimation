"""The app's controller: the project's settings, undo/redo as settings snapshots (one step per edit), and builds on a
background thread where the latest settings always win. Every widget edits the project through `change`."""
import time
from pathlib import Path
from typing import Callable

from PySide6.QtCore import QCoreApplication, QEventLoop, QObject, Signal
from PySide6.QtGui import QUndoCommand, QUndoStack

from autoswf.aqw.assets import AqwCache
from autoswf.project.build import Build, HelmBuilder
from autoswf.project.settings import HelmSettings


class SettingsCommand(QUndoCommand):
    """One edit: the settings before and after it."""

    def __init__(self, controller: "ProjectController", label: str, before: HelmSettings, after: HelmSettings):
        super().__init__(label)
        self.controller, self.before, self.after = controller, before, after
        self._done = True                   # pushed after the edit was applied: the first redo does nothing

    def redo(self) -> None:
        if self._done:
            self._done = False
            return
        self.controller.set_settings(self.after.copy())

    def undo(self) -> None:
        self.controller.set_settings(self.before.copy())


class ProjectController(QObject):
    built = Signal(object)              # every finished Build (complete or not)
    progress = Signal(str)              # the stage being built
    settings_changed = Signal()
    exported = Signal(object)           # list of ExportResult

    def __init__(self, cache: AqwCache, *, threaded: bool = True, builder: HelmBuilder | None = None):
        super().__init__()
        self.cache, self.threaded = cache, threaded
        self.builder = builder or HelmBuilder()
        self.settings: HelmSettings | None = None
        self.build: Build | None = None
        self.helm_build: Build | None = None
        self.undo_stack = QUndoStack(self)
        self.busy = False
        self.exported_settings: dict | None = None     # the settings of the last successful export
        self._latest = 0
        self._jobs: dict[int, Callable[[object], None]] = {}
        self._count = 0
        self.worker = None
        if threaded:
            from autoswf.app.worker import BuildWorker
            self.worker = BuildWorker()
            self.worker.progress.connect(self._on_progress)
            self.worker.finished.connect(self._on_finished)

    # ------------------------------------------------------------ editing

    def import_drawing(self, path, *, align: str | None = None) -> None:
        """A new project from a drawing (clears undo)."""
        self.undo_stack.clear()
        self.settings = HelmSettings(source=str(Path(path)), align=align)
        self.build = self.helm_build = None
        self.exported_settings = None
        self.settings_changed.emit()
        self._request_build()

    def change(self, label: str, edit: Callable[[HelmSettings], None]) -> None:
        """Apply `edit` to the settings as one undo step and rebuild (an edit that changes nothing leaves no step)."""
        if self.settings is None:
            return
        before, after = self.settings.copy(), self.settings.copy()
        edit(after)
        if after.to_dict() == before.to_dict():
            return
        self.settings = after
        self.undo_stack.push(SettingsCommand(self, label, before, after.copy()))
        self.settings_changed.emit()
        self._request_build()

    def set_settings(self, settings: HelmSettings) -> None:
        self.settings = settings
        self.settings_changed.emit()
        self._request_build()

    # ------------------------------------------------------------ builds and jobs

    def _request_build(self) -> None:
        snapshot, builder = self.settings.copy(), self.builder

        def job(progress, cancelled):
            return builder.build(snapshot, progress=progress, cancelled=cancelled)
        self.busy = True
        self._latest = self._submit(job, "build")

    def run_job(self, job, on_done: Callable[[object], None]) -> None:
        """Run `job(progress, cancelled)` on the build thread after the current build; `on_done(result)` back here."""
        self._submit(job, "job", on_done)

    def export(self, on_done: Callable[[list], None] | None = None) -> None:
        """Export with the settings of this moment, after the build of those settings (on the build thread)."""
        from autoswf.project.export import ExportResult, export_files, outputs
        snapshot, builder, cache = self.settings.copy(), self.builder, self.cache

        def job(progress, cancelled):
            return export_files(builder, builder.build(snapshot, progress=progress), snapshot, cache)

        def done(results) -> None:
            if isinstance(results, Exception):
                results = [ExportResult(path, link, g, problems=["Unexpected error while exporting: %s" % results])
                           for g, path, link in outputs(snapshot)]
            if results and all(r.ok for r in results):
                self.exported_settings = snapshot.to_dict()
            self.exported.emit(results)
            if on_done is not None:
                on_done(results)
        self.run_job(job, done)

    def _submit(self, job, kind: str, on_done=None) -> int:
        if self.worker is not None:
            n = self.worker.request(job, kind)
            if on_done is not None:
                self._jobs[n] = on_done
            return n
        self._count += 1
        n = self._count
        if on_done is not None:
            self._jobs[n] = on_done
        if kind == "build":
            self._latest = n
        try:
            result = job(self.progress.emit, lambda: False)
        except Exception as e:
            result = e
        self._on_finished(n, result)
        return n

    def _on_progress(self, n: int, text: str) -> None:
        if n == self._latest:
            self.progress.emit(text)

    def _on_finished(self, n: int, result) -> None:
        if n in self._jobs:
            self._jobs.pop(n)(result)
            return
        if n != self._latest:
            return                          # a build of settings that changed since
        self.busy = False
        if isinstance(result, Exception):
            result = Build(self.settings.copy(), error="Unexpected error while building: %s" % result,
                           failed_stage="read")
        self.build = result
        if result.complete:
            self.helm_build = result
        self.built.emit(result)

    def wait(self, timeout: float = 180.0) -> Build | None:
        """Process events until no build or job is running (tests and the smoke test)."""
        deadline = time.monotonic() + timeout
        while (self.busy or self._jobs) and time.monotonic() < deadline:
            QCoreApplication.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 50)
            time.sleep(0.005)
        return self.build

    def close(self) -> None:
        if self.worker is not None:
            self.worker.stop()
