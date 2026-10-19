"""The Properties panel (spec §6 right panel): what can be set for the current stage and selection — the drawing's
alignment (Import), the detail (Vectorize), the export summary (Export); later tasks add parts, presets, pivots,
colors and keyframes. Every edit is one undo step through the controller."""
import math

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QCheckBox, QDoubleSpinBox, QFormLayout, QGroupBox, QHBoxLayout, QLabel, QPushButton,
                               QScrollArea, QSlider, QVBoxLayout, QWidget)

from autoswf.aqw.template import Alignment
from autoswf.parts.assemble import colorable_summary

STAGE_GROUPS = {"Import": ("Alignment",), "Vectorize": ("Vectorize",), "Parts": ("Fixes",), "Animate": (),
                "Colors": (), "Export": ("Export",)}


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
        self._make_fixes()
        self._layout.addStretch(1)
        self._last_report = ""
        controller.built.connect(lambda build: self.refresh())
        controller.settings_changed.connect(self.refresh)
        controller.exported.connect(self._on_exported)
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

    def refresh(self) -> None:
        wanted = STAGE_GROUPS.get(self.stage, ())
        for name, box in self.groups.items():
            box.setHidden(name not in wanted)
        build, settings = self._build(), self.controller.settings
        if settings is None:
            return
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
