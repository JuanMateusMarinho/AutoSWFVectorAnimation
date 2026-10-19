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
    selection_changed = Signal(object)  # the selected part's name or None
    stage_requested = Signal(str)       # a suggestion's Fix asks the window to show a stage

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
        self.selected_part: str | None = None
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

    # ------------------------------------------------------------ Import and Vectorize

    def set_role(self, layer: str, role: str | None) -> None:
        """A layer's role by hand ("line" … "details", "ignore"), or None for the detected one."""
        def edit(s):
            if role is None:
                s.roles.pop(layer, None)
            else:
                s.roles[layer] = role
        self.change("Layer role", edit)

    def set_gradient(self, layer: str, on: bool) -> None:
        def edit(s):
            s.gradient = [g for g in s.gradient if g != layer] + ([layer] if on else [])
        self.change("Gradient", edit)

    def set_alignment(self, alignment) -> None:
        """An Alignment, or None to align automatically (template or fitted to the head)."""
        from autoswf.aqw.template import alignment_text
        text = alignment_text(alignment) if alignment is not None else None
        self.change("Alignment", lambda s: setattr(s, "align", text))

    def set_detail(self, value: int) -> None:
        self.change("Detail", lambda s: setattr(s, "detail", int(value)))

    def set_separate_tones(self, on: bool) -> None:
        self.change("Separate tones", lambda s: setattr(s, "separate_tones", bool(on)))

    # ------------------------------------------------------------ Parts

    def select_part(self, name: str | None) -> None:
        if name != self.selected_part:
            self.selected_part = name
            self.selection_changed.emit(name)

    def assign_region(self, at: tuple[float, float], part: str, piece: str | None = None) -> None:
        """The region under a drawing pixel belongs to `part` (and `piece` for eyes): one click-to-fix."""
        from autoswf.parts.model import Assign
        self.change("Fix part", lambda s: s.corrections.assign.append(Assign((float(at[0]), float(at[1])), part, piece)))

    def add_cut(self, points: list[tuple[float, float]]) -> None:
        """Split regions along a line of drawing pixels."""
        self.change("Cut region", lambda s: s.corrections.cuts.append([(float(x), float(y)) for x, y in points]))

    def remove_fix(self, kind: str, index: int) -> None:
        """Remove one part fix: kind "assign" or "cut"."""
        self.change("Remove fix", lambda s: (s.corrections.assign if kind == "assign" else s.corrections.cuts).pop(index))

    # ------------------------------------------------------------ suggestions, animation, colors, adjustments

    def accept(self, suggestion) -> None:
        if suggestion.preset is None or not suggestion.parts:
            return

        def edit(s):
            for part in suggestion.parts:
                s.animation.parts[part] = (suggestion.preset, {})
        self.change("Accept suggestion", edit)

    def skip(self, suggestion) -> None:
        def edit(s):
            if suggestion.parts:
                for part in suggestion.parts:
                    s.animation.parts[part] = (None, {})
            elif suggestion.key not in s.dismissed:
                s.dismissed.append(suggestion.key)
        self.change("Skip suggestion", edit)

    def fix(self, suggestion) -> None:
        """Go where the suggestion can be fixed by hand, its first part selected."""
        self.stage_requested.emit(suggestion.stage)
        if suggestion.parts:
            self.select_part(suggestion.parts[0])

    def _part_kind(self, part: str) -> str | None:
        build = self.helm_build or self.build
        if build is not None and build.parts is not None and part in build.parts.parts:
            return build.parts.parts[part].kind
        from autoswf.parts.model import PartName
        return PartName.parse(part).kind

    def set_animation(self, part: str, preset: str | None, values: dict | None = None, *, edits: str = "ask") -> None:
        """A part's preset (None = not animated) and its own settings. With hand-made keyframes on the part, "ask"
        raises ManualEditsError; "replace" drops them, "keep" keeps them on top of the new motion."""
        from autoswf.anim.presets import check_preset, parse_params
        from autoswf.anim.timeline import ManualEditsError
        values = dict(values or {})
        if preset is not None:
            check_preset(preset, part, self._part_kind(part))
            parse_params(preset, {**self.settings.animation.presets.get(preset, {}), **values})
        keys = [k for k in self.settings.animation.keys if k.part == part]
        if keys and edits == "ask" and self.settings.animation.parts.get(part) != (preset, values):
            raise ManualEditsError(part, [(k.target, k.frame - 1) for k in keys])

        def edit(s):
            s.animation.parts[part] = (preset, values)
            if edits == "replace":
                s.animation.keys = [k for k in s.animation.keys if k.part != part]
        self.change("Animation", edit)

    def set_preset_value(self, part: str, key: str, value, *, edits: str = "ask") -> None:
        preset, values = self.settings.animation.parts.get(part, (None, {}))
        if preset is None:
            raise ValueError("'%s' has no animation; pick a preset first" % part)
        self.set_animation(part, preset, {**values, key: value}, edits=edits)

    def apply_to_all(self, part: str) -> None:
        """The part's own preset settings become the settings of every part with that preset."""
        preset, values = self.settings.animation.parts.get(part, (None, {}))
        if preset is None:
            return

        def edit(s):
            s.animation.presets[preset] = {**s.animation.presets.get(preset, {}), **values}
            for name, (p, _) in list(s.animation.parts.items()):
                if p == preset:
                    s.animation.parts[name] = (p, {})
        self.change("Use for every part", edit)

    def set_pivot(self, part: str, point: tuple[float, float] | None) -> None:
        def edit(s):
            if point is None:
                s.pivots.pop(part, None)
            else:
                s.pivots[part] = (float(point[0]), float(point[1]))
        self.change("Pivot", edit)

    def set_color_slot(self, part: str, location: str | None) -> None:
        """The AQW color a part follows: Skin … Accessory, "none" (its drawn colors), or None (automatic)."""
        def edit(s):
            if location is None:
                s.corrections.colors.pop(part, None)
            else:
                s.corrections.colors[part] = location
        self.change("Color slot", edit)

    def set_player_color(self, location: str, rgb: int) -> None:
        self.change("Player color", lambda s: s.colors.__setitem__(location, int(rgb)))

    def reset_player_colors(self) -> None:
        self.change("Player colors", lambda s: s.colors.clear())

    def set_adjust(self, gender: str, part: str | None, adjust) -> None:
        """A male or female version's adjustment of the whole helm (part None) or of a part; turns versions on."""
        from autoswf.project.export import default_variant

        def edit(s):
            s.export.variants = True
            for g in ("M", "F"):
                if g not in s.export.genders:
                    s.export.genders[g] = default_variant(s, g)
            variant = s.export.genders[gender]
            if part is None:
                variant.helm = adjust
            else:
                variant.parts[part] = adjust
        self.change("Adjust", edit)

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
