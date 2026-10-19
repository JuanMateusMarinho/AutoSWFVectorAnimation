"""The Properties panel (spec §6 right panel): what can be set for the current stage and selection — the drawing's
alignment (Import), the detail (Vectorize), the export summary (Export); later tasks add parts, presets, pivots,
colors and keyframes. Every edit is one undo step through the controller."""
import math

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QCheckBox, QColorDialog, QComboBox, QDoubleSpinBox, QFormLayout, QGroupBox, QHBoxLayout,
                               QLabel, QMessageBox, QPushButton, QScrollArea, QSlider, QSpinBox, QVBoxLayout, QWidget)

from autoswf.aqw.template import Alignment
from dataclasses import fields as dataclass_fields

from autoswf.anim.presets import MOVES, PRESETS, RANGES
from autoswf.anim.settings import FIELD_RANGES
from autoswf.anim.timeline import POSE_FIELDS, ManualEditsError
from autoswf.parts.assemble import colorable_summary
from autoswf.project.settings import Adjust
from autoswf.render.colors import PlayerColors

STAGE_GROUPS = {"Import": ("Alignment",), "Vectorize": ("Vectorize",), "Parts": ("Part", "Fixes", "Adjust"),
                "Animate": ("Part", "Animation", "Pivot", "Adjust"), "Colors": ("Player colors", "Part", "Adjust"),
                "Export": ("Export", "Adjust")}
PART_GROUPS = ("Part", "Animation", "Pivot")          # shown only with a part selected
SLOT_CHOICES = ("Automatic", "Skin", "Hair", "Eye", "Base", "Trim", "Accessory", "None")
COLOR_ORDER = ("Hair", "Skin", "Eye", "Base", "Trim", "Accessory")
TONES_NOTE = ("In colorable areas the game draws shadows and lights with its own fixed tones (Dark, Darker, Light), "
              "not the colors you painted.")


class ParamWidget(QWidget):
    """One preset setting: a slider and a spin box with the preset's range (spec §11 sliders)."""

    def __init__(self, low: float, high: float, whole: bool, on_commit):
        super().__init__()
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        self.whole, self.low, self.high = whole, low, high
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(0, 1000)
        self.spin = QSpinBox() if whole else QDoubleSpinBox()
        self.spin.setRange(int(low) if whole else low, int(high) if whole else high)
        if not whole:
            self.spin.setDecimals(2)
            self.spin.setSingleStep((high - low) / 100)
        self.spin.setKeyboardTracking(False)
        row.addWidget(self.slider, 1)
        row.addWidget(self.spin)
        self.slider.valueChanged.connect(self._slid)
        self.slider.sliderReleased.connect(lambda: on_commit(self.value()))
        self.spin.editingFinished.connect(lambda: on_commit(self.value()))

    def value(self):
        return int(self.spin.value()) if self.whole else float(self.spin.value())

    def set_value(self, value) -> None:
        for w in (self.spin, self.slider):
            w.blockSignals(True)
        self.spin.setValue(value)
        self.slider.setValue(round((value - self.low) / (self.high - self.low) * 1000) if self.high > self.low else 0)
        for w in (self.spin, self.slider):
            w.blockSignals(False)

    def _slid(self, position: int) -> None:
        value = self.low + (self.high - self.low) * position / 1000
        self.spin.blockSignals(True)
        self.spin.setValue(round(value) if self.whole else value)
        self.spin.blockSignals(False)


class FixRow(QWidget):
    """One part fix in the list, with its remove button."""

    def __init__(self, text: str, on_remove):
        super().__init__()
        self.text = text
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        label = QLabel(text)
        label.setWordWrap(True)
        self.remove_button = QPushButton("Remove")
        self.remove_button.clicked.connect(on_remove)
        row.addWidget(label, 1)
        row.addWidget(self.remove_button)


def _spin(low: float, high: float, decimals: int, step: float) -> QDoubleSpinBox:
    box = QDoubleSpinBox()
    box.setRange(low, high)
    box.setDecimals(decimals)
    box.setSingleStep(step)
    box.setKeyboardTracking(False)
    return box


class PropertiesPanel(QScrollArea):
    export_requested = Signal()

    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self.controller = controller
        self.stage = "Import"
        self.setWidgetResizable(True)
        body = QWidget()
        self._layout = QVBoxLayout(body)
        self._layout.setContentsMargins(4, 4, 4, 4)
        self.setWidget(body)
        self.groups: dict[str, QGroupBox] = {}
        self._make_alignment()
        self._make_vectorize()
        self._make_export()
        self.key = None
        self._make_part()
        self._make_animation()
        self._make_pivot()
        self._make_adjust()
        self._make_colors()
        self._make_fixes()
        self._make_keyframe()
        self._layout.addStretch(1)
        self.gender = "M"
        self._last_report = ""
        controller.built.connect(lambda build: self.refresh())
        controller.settings_changed.connect(self.refresh)
        controller.exported.connect(self._on_exported)
        controller.selection_changed.connect(lambda name: self.refresh())
        self.refresh()

    def _group(self, name: str, title: str) -> QFormLayout:
        box = QGroupBox(title)
        form = QFormLayout(box)
        self.groups[name] = box
        self._layout.addWidget(box)
        return form

    # ------------------------------------------------------------ groups

    def _make_alignment(self) -> None:
        form = self._group("Alignment", "Alignment on the head")
        self.scale_spin = _spin(0.01, 1000, 4, 0.1)
        self.scale_spin.setToolTip("Drawing pixels per head unit")
        self.x_spin, self.y_spin = _spin(-100000, 100000, 2, 1), _spin(-100000, 100000, 2, 1)
        self.rotation_spin = _spin(-360, 360, 2, 1)
        self.rotation_spin.setToolTip("Degrees the drawing turns clockwise onto the head")
        form.addRow("Scale (px per unit)", self.scale_spin)
        form.addRow("Head origin x (px)", self.x_spin)
        form.addRow("Head origin y (px)", self.y_spin)
        form.addRow("Rotation (°)", self.rotation_spin)
        for box in (self.scale_spin, self.x_spin, self.y_spin, self.rotation_spin):
            box.editingFinished.connect(self._alignment_edited)
        self.fit_button = QPushButton("Fit to head")
        self.fit_button.setToolTip("Align automatically again (the template, or the drawing fitted to the head)")
        self.fit_button.clicked.connect(lambda: self.controller.set_alignment(None))
        form.addRow(self.fit_button)
        self.alignment_note = QLabel()
        self.alignment_note.setWordWrap(True)
        form.addRow(self.alignment_note)
        hint = QLabel("On the canvas: drag to move the drawing, Alt+drag to scale it, Shift+drag to turn it.")
        hint.setWordWrap(True)
        form.addRow(hint)
        self._shown_alignment: Alignment | None = None

    def _make_vectorize(self) -> None:
        form = self._group("Vectorize", "Vectorize")
        row = QHBoxLayout()
        self.detail_slider = QSlider(Qt.Orientation.Horizontal)
        self.detail_slider.setRange(0, 100)
        self.detail_label = QLabel()
        row.addWidget(self.detail_slider, 1)
        row.addWidget(self.detail_label)
        form.addRow("Detail", row)
        self.detail_slider.sliderReleased.connect(lambda: self.controller.set_detail(self.detail_slider.value()))
        self.detail_slider.valueChanged.connect(self._detail_moved)
        self.separate_box = QCheckBox("Separate tones (shadows and lights as their own shapes)")
        self.separate_box.toggled.connect(lambda on: self.controller.set_separate_tones(on))
        form.addRow(self.separate_box)
        self.art_notes = QLabel()
        self.art_notes.setWordWrap(True)
        form.addRow(self.art_notes)

    def _make_export(self) -> None:
        form = self._group("Export", "Export")
        self.export_summary = QLabel()
        self.export_summary.setWordWrap(True)
        self.export_report = QLabel()
        self.export_report.setWordWrap(True)
        button = QPushButton("Export SWF…")
        button.clicked.connect(self.export_requested.emit)
        form.addRow(self.export_summary)
        form.addRow(button)
        form.addRow(self.export_report)

    def _make_part(self) -> None:
        form = self._group("Part", "Part")
        self.part_label = QLabel()
        form.addRow(self.part_label)
        self.color_box = QComboBox()
        self.color_box.addItems(SLOT_CHOICES)
        self.color_box.setToolTip("The AQW color this part follows; None keeps the colors you painted")
        self.color_box.currentTextChanged.connect(self._slot_picked)
        form.addRow("Color slot", self.color_box)

    def _make_animation(self) -> None:
        form = self._group("Animation", "Animation")
        self.preset_box = QComboBox()
        self.preset_box.currentTextChanged.connect(self._preset_picked)
        form.addRow("Preset", self.preset_box)
        self._params_box = QFormLayout()
        form.addRow(self._params_box)
        self.param_widgets: dict[str, QWidget] = {}
        self.apply_all_button = QPushButton("Use for every part with this preset")
        self.apply_all_button.clicked.connect(lambda: self._part() and self.controller.apply_to_all(self._part()))
        form.addRow(self.apply_all_button)
        self._shown_params = None

    def _make_pivot(self) -> None:
        form = self._group("Pivot", "Pivot (registration point)")
        self.pivot_x, self.pivot_y = _spin(-500, 500, 2, 0.5), _spin(-500, 500, 2, 0.5)
        form.addRow("x (head units)", self.pivot_x)
        form.addRow("y (head units)", self.pivot_y)
        for box in (self.pivot_x, self.pivot_y):
            box.editingFinished.connect(self._pivot_edited)
        reset = QPushButton("Reset pivot")
        reset.clicked.connect(lambda: self._part() and self.controller.set_pivot(self._part(), None))
        form.addRow(reset)
        hint = QLabel("You can also drag the pivot circle on the canvas.")
        hint.setWordWrap(True)
        form.addRow(hint)

    def _make_adjust(self) -> None:
        form = self._group("Adjust", "Adjust for male/female")
        self.adjust_title = QLabel()
        self.adjust_title.setWordWrap(True)
        form.addRow(self.adjust_title)
        self.adjust_x, self.adjust_y = _spin(-500, 500, 2, 0.5), _spin(-500, 500, 2, 0.5)
        self.adjust_scale = _spin(0.1, 10, 3, 0.01)
        form.addRow("Move x", self.adjust_x)
        form.addRow("Move y", self.adjust_y)
        form.addRow("Scale", self.adjust_scale)
        for box in (self.adjust_x, self.adjust_y, self.adjust_scale):
            box.editingFinished.connect(self._adjust_edited)

    def _make_colors(self) -> None:
        form = self._group("Player colors", "Player colors")
        self.color_buttons: dict[str, QPushButton] = {}
        for location in COLOR_ORDER:
            button = QPushButton(location)
            button.clicked.connect(lambda _=False, loc=location: self._pick_color(loc))
            form.addRow(button)
            self.color_buttons[location] = button
        reset = QPushButton("Reset colors")
        reset.clicked.connect(lambda: self.controller.reset_player_colors())
        form.addRow(reset)
        note = QLabel(TONES_NOTE)
        note.setWordWrap(True)
        form.addRow(note)
        self.slots_label = QLabel()
        self.slots_label.setWordWrap(True)
        form.addRow(self.slots_label)

    def _make_keyframe(self) -> None:
        form = self._group("Keyframe", "Keyframe")
        self.key_label = QLabel()
        form.addRow(self.key_label)
        self.key_widgets: dict[str, QDoubleSpinBox] = {}
        for name in POSE_FIELDS:
            low, high = FIELD_RANGES[name]
            box = _spin(low, high, 3, 0.1 if high - low <= 4 else 1)
            box.editingFinished.connect(lambda n=name: self._key_edited(n))
            form.addRow(name.replace("_", " ").capitalize(), box)
            self.key_widgets[name] = box
        self.tween_box = QCheckBox("Tween to the next keyframe")
        self.tween_box.toggled.connect(lambda on: self._key_edited(None))
        form.addRow(self.tween_box)
        delete = QPushButton("Delete keyframe")
        delete.clicked.connect(lambda: self.key and self.controller.delete_key(*self.key))
        form.addRow(delete)
        self.key = None

    def show_key(self, key) -> None:
        """The hand-made keyframe (part, target, 0-based frame) to edit, or None."""
        self.key = key
        self.refresh()

    def _refresh_key(self, settings) -> None:
        if self.key is None:
            return
        part, target, frame = self.key
        self.key_label.setText("%s, frame %d" % (target, frame + 1))
        manual = next((k for k in settings.animation.keys if (k.part, k.target, k.frame) == (part, target, frame + 1)),
                      None)
        build = self.controller.helm_build
        clip = build.timeline.clips.get(part) if build is not None and build.timeline is not None else None
        pose = clip.pose(target, frame) if clip is not None and target in clip.tracks else None
        bends = clip is not None and target in clip.bends
        for name, box in self.key_widgets.items():
            value = manual.fields.get(name) if manual is not None and name in manual.fields else (
                getattr(pose, name) if pose is not None else None)
            box.blockSignals(True)
            box.setValue(float(value) if value is not None else 0.0)
            box.blockSignals(False)
        self.key_widgets["bend"].setEnabled(bends)
        self.tween_box.blockSignals(True)
        self.tween_box.setChecked(bool(manual.tween) if manual is not None else False)
        self.tween_box.blockSignals(False)

    def _key_edited(self, name: str | None) -> None:
        if self.key is None:
            return
        part, target, frame = self.key
        fields = {name: self.key_widgets[name].value()} if name is not None else {}
        try:
            self.controller.set_key(part, target, frame, fields, self.tween_box.isChecked())
        except ValueError as e:
            QMessageBox.warning(self, "Keyframe", str(e))

    def _make_fixes(self) -> None:
        form = self._group("Fixes", "Part fixes")
        hint = QLabel("Click a region on the canvas and pick its part. Press C (or the Cut button) and drag a line to "
                      "split a region.")
        hint.setWordWrap(True)
        form.addRow(hint)
        self._fix_box = QVBoxLayout()
        form.addRow(self._fix_box)
        self.fix_rows: list[FixRow] = []

    def _refresh_fixes(self, settings) -> None:
        for row in self.fix_rows:
            self._fix_box.removeWidget(row)
            row.deleteLater()
        self.fix_rows = []
        c = settings.corrections
        entries = [("assign", k, "%s%s at %d, %d" % (a.part, " " + a.piece if a.piece else "", a.at[0], a.at[1]))
                   for k, a in enumerate(c.assign)]
        entries += [("cut", k, "Cut, %d points" % len(cut)) for k, cut in enumerate(c.cuts)]
        for kind, index, text in entries:
            row = FixRow(text, lambda _=False, kind=kind, index=index: self.controller.remove_fix(kind, index))
            self._fix_box.addWidget(row)
            self.fix_rows.append(row)

    # ------------------------------------------------------------ state

    def show_stage(self, stage: str, build=None, settings=None) -> None:
        self.stage = stage
        self.refresh()

    def _build(self):
        c = self.controller
        return c.build if c.build is not None and c.build.drawing is not None else c.helm_build

    def _part(self) -> str | None:
        return self.controller.selected_part

    def refresh(self) -> None:
        wanted = set(STAGE_GROUPS.get(self.stage, ()))
        settings = self.controller.settings
        if self._part() is None:
            wanted -= set(PART_GROUPS)
        if settings is None or not settings.export.variants:
            wanted.discard("Adjust")
        if self.key is not None:
            wanted.add("Keyframe")
        for name, box in self.groups.items():
            box.setHidden(name not in wanted)
        build = self._build()
        if settings is None:
            return
        self._refresh_part(settings)
        self._refresh_key(settings)
        self._refresh_adjust(settings)
        self._refresh_colors(settings)
        if build is not None and build.alignment is not None:
            a = build.alignment
            self._shown_alignment = a
            for box, value in ((self.scale_spin, a.scale), (self.x_spin, a.origin[0]), (self.y_spin, a.origin[1]),
                               (self.rotation_spin, a.rotation)):
                box.blockSignals(True)
                box.setValue(value)
                box.blockSignals(False)
            self.alignment_note.setText({"AutoSWF template": "Drawn on the AutoSWF template: aligned automatically."}
                                        .get(build.alignment_reason, "Alignment: %s." % build.alignment_reason))
        self.detail_slider.blockSignals(True)
        self.detail_slider.setValue(settings.detail)
        self.detail_slider.blockSignals(False)
        self.detail_label.setText(str(settings.detail))
        self.separate_box.blockSignals(True)
        self.separate_box.setChecked(settings.separate_tones)
        self.separate_box.blockSignals(False)
        self.art_notes.setText("\n".join(build.art.notes) if build is not None and build.art is not None else "")
        helm = self.controller.helm_build
        self.export_summary.setText(colorable_summary(helm.helm) if helm is not None and helm.helm is not None
                                    else "The helm is not built yet.")
        self.export_report.setText(self._last_report)
        self._refresh_fixes(settings)

    # ------------------------------------------------------------ edits

    def _refresh_part(self, settings) -> None:
        part = self._part()
        if part is None:
            return
        kind = self.controller._part_kind(part)
        self.part_label.setText("%s (%s)" % (part, kind.replace("_", " ")))
        slot = settings.corrections.colors.get(part)
        self.color_box.blockSignals(True)
        self.color_box.setCurrentText("Automatic" if slot is None else "None" if slot == "none" else slot)
        self.color_box.blockSignals(False)
        allowed = ["None"] + [name for name in PRESETS if kind in MOVES[name]]
        preset, values = settings.animation.parts.get(part, (None, {}))
        self.preset_box.blockSignals(True)
        self.preset_box.clear()
        self.preset_box.addItems(allowed)
        self.preset_box.setCurrentText(preset or "None")
        self.preset_box.blockSignals(False)
        self._refresh_params(preset, {**settings.animation.presets.get(preset, {}), **values} if preset else {})
        build = self.controller.helm_build or self.controller.build
        rig = build.rigs.get(part) if build is not None and build.rigs else None
        self.groups["Pivot"].setHidden(self.groups["Pivot"].isHidden() or rig is None)
        if rig is not None:
            for box, value in ((self.pivot_x, rig.pivot.x), (self.pivot_y, rig.pivot.y)):
                box.blockSignals(True)
                box.setValue(value)
                box.blockSignals(False)

    def _refresh_params(self, preset: str | None, values: dict) -> None:
        if self._shown_params != preset:
            while self._params_box.rowCount():
                self._params_box.removeRow(0)
            self.param_widgets = {}
            if preset is not None:
                for f in dataclass_fields(PRESETS[preset]):
                    if f.type in ("bool", bool):
                        box = QCheckBox()
                        box.toggled.connect(lambda on, key=f.name: self._param_committed(key, on))
                        self.param_widgets[f.name] = box
                    else:
                        low, high = RANGES[(preset, f.name)]
                        widget = ParamWidget(low, high, f.type in ("int", int),
                                             lambda value, key=f.name: self._param_committed(key, value))
                        self.param_widgets[f.name] = widget
                    self._params_box.addRow(f.name.replace("_", " ").capitalize(), self.param_widgets[f.name])
            self._shown_params = preset
        if preset is None:
            return
        defaults = {f.name: f.default for f in dataclass_fields(PRESETS[preset])}
        for key, widget in self.param_widgets.items():
            value = values.get(key, defaults[key])
            if isinstance(widget, QCheckBox):
                widget.blockSignals(True)
                widget.setChecked(bool(value) if not isinstance(value, str) else value.lower() in ("on", "true", "yes", "1"))
                widget.blockSignals(False)
            else:
                widget.set_value(float(value))
        self.apply_all_button.setEnabled(bool(values))

    def _refresh_adjust(self, settings) -> None:
        if not settings.export.variants:
            return
        part = self._part()
        variant = settings.export.genders.get(self.gender)
        adjust = (variant.parts.get(part) if part else variant.helm) if variant is not None else None
        adjust = adjust or Adjust()
        who = {"M": "male", "F": "female"}[self.gender]
        self.adjust_title.setText("%s in the %s version (pick the version with the Male/Female button)"
                                  % (part or "The whole helm", who))
        for box, value in ((self.adjust_x, adjust.x), (self.adjust_y, adjust.y), (self.adjust_scale, adjust.scale)):
            box.blockSignals(True)
            box.setValue(value)
            box.blockSignals(False)

    def _refresh_colors(self, settings) -> None:
        colors = PlayerColors()
        for location, rgb in settings.colors.items():
            colors = colors.replace(location, rgb)
        for location, button in self.color_buttons.items():
            rgb = colors.get(location)
            light = ((rgb >> 16) & 255) * 0.3 + ((rgb >> 8) & 255) * 0.59 + (rgb & 255) * 0.11 > 140
            button.setStyleSheet("background-color: #%06x; color: %s;" % (rgb, "black" if light else "white"))
        slots = settings.corrections.colors
        self.slots_label.setText("Color slots set by hand: " + (", ".join("%s → %s" % kv for kv in slots.items())
                                                                 if slots else "none (automatic)"))

    # ------------------------------------------------------------ part edits

    def ask_edits(self, error: ManualEditsError) -> str | None:
        """Re-running a preset over hand-made keyframes (spec §11): "replace", "keep" or None (cancel)."""
        box = QMessageBox(QMessageBox.Icon.Question, "Hand-made keyframes", str(error) + ".", parent=self)
        replace = box.addButton("Replace them", QMessageBox.ButtonRole.DestructiveRole)
        keep = box.addButton("Keep them", QMessageBox.ButtonRole.AcceptRole)
        box.addButton(QMessageBox.StandardButton.Cancel)
        box.exec()
        return "replace" if box.clickedButton() is replace else "keep" if box.clickedButton() is keep else None

    def _with_edits(self, action) -> None:
        try:
            action("ask")
        except ManualEditsError as e:
            choice = self.ask_edits(e)
            if choice is not None:
                action(choice)
        except ValueError as e:
            QMessageBox.warning(self, "Animation", str(e))
        self.refresh()

    def _preset_picked(self, text: str) -> None:
        part = self._part()
        if part is None:
            return
        preset = None if text == "None" else text
        self._with_edits(lambda edits: self.controller.set_animation(part, preset, {}, edits=edits))

    def _param_committed(self, key: str, value) -> None:
        part = self._part()
        if part is None:
            return
        self._with_edits(lambda edits: self.controller.set_preset_value(part, key, value, edits=edits))

    def _slot_picked(self, text: str) -> None:
        part = self._part()
        if part is not None:
            self.controller.set_color_slot(part, None if text == "Automatic" else "none" if text == "None" else text)

    def _pivot_edited(self) -> None:
        part = self._part()
        if part is not None:
            self.controller.set_pivot(part, (self.pivot_x.value(), self.pivot_y.value()))

    def _adjust_edited(self) -> None:
        self.controller.set_adjust(self.gender, self._part(), Adjust(self.adjust_x.value(), self.adjust_y.value(),
                                                                     self.adjust_scale.value()))

    def set_player_color(self, location: str, rgb: int) -> None:
        self.controller.set_player_color(location, rgb)

    def _pick_color(self, location: str) -> None:
        settings = self.controller.settings
        current = settings.colors.get(location, PlayerColors().get(location)) if settings is not None else 0
        color = QColorDialog.getColor(QColor(current | 0xFF000000), self, "%s color" % location)
        if color.isValid():
            self.set_player_color(location, color.rgb() & 0xFFFFFF)

    def _alignment_edited(self) -> None:
        shown = self._shown_alignment
        if shown is None:
            return

        def value(box, exact):           # keep full precision for the fields the user did not change
            return exact if math.isclose(box.value(), round(exact, box.decimals()), abs_tol=1e-9) else box.value()
        new = Alignment(value(self.scale_spin, shown.scale),
                        (value(self.x_spin, shown.origin[0]), value(self.y_spin, shown.origin[1])),
                        value(self.rotation_spin, shown.rotation))
        if new != shown:
            self.controller.set_alignment(new)

    def _detail_moved(self, value: int) -> None:
        self.detail_label.setText(str(value))
        if not self.detail_slider.isSliderDown() and self.controller.settings is not None \
                and value != self.controller.settings.detail:
            self.controller.set_detail(value)

    def _on_exported(self, results) -> None:
        lines = []
        for r in results:
            lines.append(r.summary())
            lines += r.notes
        self._last_report = "\n".join(lines)
        self.export_report.setText(self._last_report)
