"""Photoshop-style layers (Plan 7, spec §7, §8.1): one row per element with the AQW color it takes and a note when it
changes over time, an eye that hides it in the editor only, and the layer actions — + New layer, Trace PNG…,
Color ▾ and Delete layer — plus the part picker for armors."""
from dataclasses import dataclass

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (QComboBox, QHBoxLayout, QMenu, QPushButton, QToolButton, QTreeWidget, QTreeWidgetItem,
                               QVBoxLayout, QWidget)

LOCATIONS = ("Hair", "Skin", "Eye", "Base", "Trim", "Accessory")
BLINK_FRAMES = 87
KEY_ROLE = Qt.ItemDataRole.UserRole


@dataclass
class LayerRow:
    key: str
    name: str
    level: int
    color_tag: str | None
    note: str | None
    visible: bool
    deletable: bool


def color_tag(location: str | None) -> str | None:
    return "%s Color" % location if location else None


def piece_note(movie, piece) -> str | None:
    """"N frames" when a clip shows several drawings over its own timeline, "blink" for AQW's 87-frame eye clip."""
    from autoswf.swf.decode import PlaceCommand, SpriteDef
    sprite = movie.character(piece.char_id) if piece.kind == "clip" else None
    if not isinstance(sprite, SpriteDef) or sprite.frame_count < 2:
        return None
    if sprite.frame_count == BLINK_FRAMES:
        return "blink"
    drawings = {c.char_id for frame in sprite.frames for c in frame if isinstance(c, PlaceCommand) and c.char_id}
    return "%d frames" % sprite.frame_count if len(drawings) > 1 else None


def swf_layer_rows(movie, structure, part_key: str, hidden: set[str] = frozenset()) -> list[LayerRow]:
    part = next(p for p in structure.parts if p.key == part_key)
    rows = []

    def visit(pieces, level):
        for piece in pieces:
            name = piece.instance_name or (piece.class_name.rpartition(".")[2] if piece.class_name else piece.label)
            rows.append(LayerRow(piece.path, name, level, color_tag(piece.color[0] if piece.color else None),
                                 piece_note(movie, piece), piece.path not in hidden, True))
            visit(piece.children, level + 1)
    visit(part.pieces, 0)
    return rows


def helm_layer_rows(build, hidden: set[str] = frozenset()) -> list[LayerRow]:
    """One row per part of the helm (eyes as one element) and per extra layer."""
    if build is None or build.helm is None:
        return []
    locations = {}
    for name, location, _ in build.helm.colorable:
        locations.setdefault(name, location)
    rigs = getattr(build, "rigs", {}) or {}
    rows, seen = [], set()
    for layer in build.layers:
        name = layer.parent or layer.name
        if name in seen:
            continue
        seen.add(name)
        location = locations.get(name) or next((locations[l.name] for l in build.layers
                                                if l.parent == name and l.name in locations), None)
        note = "blink" if name.startswith("Eye") and name in rigs else None
        rows.append(LayerRow(name, name, 0, color_tag(location), note, name not in hidden, False))
    for extra in build.settings.edits.extras:
        location = next((loc for _, loc, _ in extra.tones if loc), None)
        rows.append(LayerRow(extra.name, extra.name, 0, color_tag(location), None, extra.name not in hidden, True))
    return rows


class EditLayersPanel(QWidget):
    layer_selected = Signal(str)
    visibility_changed = Signal(str, bool)
    new_layer_requested = Signal()
    trace_requested = Signal()
    color_requested = Signal(str, str)          # layer key, location or "None"
    delete_requested = Signal(str)
    part_selected = Signal(str)

    def __init__(self, parent=None, with_rows: bool = True):
        super().__init__(parent)
        self.parts = QComboBox()
        self.parts.setToolTip("The part of the item to edit")
        self.parts.activated.connect(lambda i: self.part_selected.emit(self.parts.itemData(i)))
        self.tree = QTreeWidget()
        self.tree.setColumnCount(3)
        self.tree.setHeaderLabels(["Layer", "Color", "Note"])
        self.tree.setRootIsDecorated(False)
        self.tree.currentItemChanged.connect(self._on_current)
        self.tree.itemChanged.connect(self._on_changed)
        self.tree.setVisible(with_rows)
        self.new_button = QPushButton("+ New layer")
        self.trace_button = QPushButton("Trace PNG…")
        self.color_button = QToolButton()
        self.color_button.setText("Color ▾")
        self.color_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        menu = QMenu(self.color_button)
        for location in LOCATIONS + ("None",):
            action = QAction(location if location != "None" else "None (fixed colors)", menu)
            action.triggered.connect(lambda checked=False, loc=location: self._color(loc))
            menu.addAction(action)
        self.color_button.setMenu(menu)
        self.delete_button = QPushButton("Delete layer")
        self.new_button.clicked.connect(self.new_layer_requested.emit)
        self.trace_button.clicked.connect(self.trace_requested.emit)
        self.delete_button.clicked.connect(lambda: self.current and self.delete_requested.emit(self.current))
        buttons = QHBoxLayout()
        for b in (self.new_button, self.trace_button, self.color_button, self.delete_button):
            buttons.addWidget(b)
        column = QVBoxLayout(self)
        column.setContentsMargins(0, 0, 0, 0)
        column.addWidget(self.parts)
        column.addWidget(self.tree, 1)
        column.addLayout(buttons)
        self.current: str | None = None
        self._filling = False

    def set_parts(self, parts: list[tuple[str, str]], current: str) -> None:
        self.parts.blockSignals(True)
        self.parts.clear()
        for key, label in parts:
            self.parts.addItem(label, key)
        index = self.parts.findData(current)
        if index >= 0:
            self.parts.setCurrentIndex(index)
        self.parts.setVisible(len(parts) > 1)
        self.parts.blockSignals(False)

    def set_rows(self, rows: list[LayerRow], current: str | None) -> None:
        self._filling = True
        self.tree.clear()
        for row in rows:
            item = QTreeWidgetItem(self.tree, ["   " * row.level + row.name, row.color_tag or "", row.note or ""])
            item.setData(0, KEY_ROLE, row.key)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(0, Qt.CheckState.Checked if row.visible else Qt.CheckState.Unchecked)
            item.setToolTip(0, "Uncheck to hide it while you edit (the item keeps it)")
            if row.key == current:
                self.tree.setCurrentItem(item)
        self.current = current
        self._filling = False

    def rows(self) -> list[tuple[str, str, str]]:
        return [(self.tree.topLevelItem(i).data(0, KEY_ROLE), self.tree.topLevelItem(i).text(1),
                 self.tree.topLevelItem(i).text(2)) for i in range(self.tree.topLevelItemCount())]

    def _on_current(self, item, previous) -> None:
        if item is not None and not self._filling:
            self.current = item.data(0, KEY_ROLE)
            self.layer_selected.emit(self.current)

    def _on_changed(self, item, column) -> None:
        if not self._filling and column == 0:
            self.visibility_changed.emit(item.data(0, KEY_ROLE), item.checkState(0) == Qt.CheckState.Checked)

    def _color(self, location: str) -> None:
        if self.current:
            self.color_requested.emit(self.current, location)
