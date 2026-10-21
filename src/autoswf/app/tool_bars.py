"""The editor's tool column (left) and tool options bar (top), Photoshop-style (Plan 7, spec §7)."""
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QAction, QActionGroup, QColor, QKeySequence
from PySide6.QtWidgets import (QCheckBox, QColorDialog, QDoubleSpinBox, QHBoxLayout, QLabel, QPushButton, QSlider,
                               QToolBar, QWidget)

from autoswf.app.edit_tools import TOOL_KEYS, TOOL_NAMES, TOOLS, EditTools
from autoswf.edit.layer import ToneRef


class ToolsColumn(QToolBar):
    tool_picked = Signal(str)

    def __init__(self, parent=None):
        super().__init__("Tools", parent)
        self.setOrientation(Qt.Orientation.Vertical)
        self.group = QActionGroup(self)
        self.group.setExclusive(True)
        self.actions_by_tool: dict[str, QAction] = {}
        for tool in TOOLS:
            action = QAction("%s (%s)" % (TOOL_NAMES[tool], TOOL_KEYS[tool]), self)
            action.setCheckable(True)
            action.setShortcut(QKeySequence(TOOL_KEYS[tool]))
            action.setShortcutContext(Qt.ShortcutContext.WindowShortcut)
            action.triggered.connect(lambda checked=False, t=tool: self.tool_picked.emit(t))
            self.group.addAction(action)
            self.addAction(action)
            self.actions_by_tool[tool] = action

    def show_tool(self, tool: str) -> None:
        self.actions_by_tool[tool].setChecked(True)


class ToolOptionsBar(QWidget):
    """Brush size and pressure, the layer's colors as swatches (and "New color…"), the Magic Wand's close gap."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.tools: EditTools | None = None
        row = QHBoxLayout(self)
        row.setContentsMargins(6, 2, 6, 2)
        self.tool_label = QLabel()
        self.size_slider = QSlider(Qt.Orientation.Horizontal)
        self.size_slider.setRange(1, 200)
        self.size_slider.setFixedWidth(160)
        self.size_label = QLabel()
        self.pressure_box = QCheckBox("Pressure → width")
        self.gap_label = QLabel("Close gap")
        self.gap_box = QDoubleSpinBox()
        self.gap_box.setRange(0, 20)
        self.gap_box.setSuffix(" px")
        self.swatches = QHBoxLayout()
        self.new_color = QPushButton("New color…")
        for w in (self.tool_label, QLabel("Size"), self.size_slider, self.size_label, self.pressure_box,
                  self.gap_label, self.gap_box):
            row.addWidget(w)
        row.addLayout(self.swatches)
        row.addWidget(self.new_color)
        row.addStretch(1)
        self.size_slider.valueChanged.connect(lambda v: self.tools and self.tools.set_size(v))
        self.pressure_box.toggled.connect(lambda on: self.tools and setattr(self.tools, "use_pressure", on))
        self.gap_box.valueChanged.connect(lambda v: self.tools and setattr(self.tools, "close_gap", v))
        self.new_color.clicked.connect(self._pick_new_color)

    def attach(self, tools: EditTools | None) -> None:
        if self.tools is not None:
            try:
                self.tools.changed.disconnect(self.refresh)
            except (RuntimeError, TypeError):
                pass
        self.tools = tools
        if tools is not None:
            tools.changed.connect(self.refresh)
        self.refresh()

    def refresh(self) -> None:
        t = self.tools
        self.setEnabled(t is not None)
        if t is None:
            return
        from autoswf.app.edit_tools import TOOL_NAMES
        self.tool_label.setText(TOOL_NAMES[t.tool] if t.active else "")
        for w in (self.size_slider, self.pressure_box, self.gap_box):
            w.blockSignals(True)
        self.size_slider.setValue(int(round(t.size)))
        self.size_label.setText("%g px" % t.size)
        self.pressure_box.setChecked(t.use_pressure)
        self.gap_box.setValue(t.close_gap)
        for w in (self.size_slider, self.pressure_box, self.gap_box):
            w.blockSignals(False)
        self.gap_label.setVisible(t.tool == "wand")
        self.gap_box.setVisible(t.tool == "wand")
        while self.swatches.count():
            item = self.swatches.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        for tone in (t.layer.tones if t.layer is not None else []):
            button = QPushButton()
            button.setFixedSize(20, 20)
            border = "2px solid white" if tone.ref == t.color else "1px solid #333"
            button.setStyleSheet("background: rgb(%d,%d,%d); border: %s;" % (tone.color[:3] + (border,)))
            button.setToolTip("%s %s" % tone.binding if tone.binding else "Fixed color")
            button.clicked.connect(lambda checked=False, ref=tone.ref: t.set_color(ref))
            self.swatches.addWidget(button)

    def _pick_new_color(self) -> None:
        if self.tools is None:
            return
        color = QColorDialog.getColor(QColor(0, 0, 0), self, "New color")
        if color.isValid():
            self.tools.set_color((color.red(), color.green(), color.blue(), 255))
