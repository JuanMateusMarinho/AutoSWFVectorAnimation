"""The part tree (spec §6 left panel): Face, Ears, Eyes (with their pieces), Brows, Nose, Mouth, Hair and its locks,
Back hair, Horns, Helm, Accessories — each with its color slot and animation; selection is shared with the canvas."""
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QTreeWidget, QTreeWidgetItem

GROUPS = (("Face", ("face",)), ("Ears", ("ear",)), ("Eyes", ("eye",)), ("Brows", ("brow",)), ("Nose", ("nose",)),
          ("Mouth", ("mouth",)), ("Hair", ("hair", "lock")), ("Back hair", ("back_hair",)), ("Horns", ("horn",)),
          ("Helm", ("shell",)), ("Accessories", ("accessory",)))
SINGLE = {"face", "nose", "mouth", "back_hair", "shell"}       # shown as one row, not a group


class PartTree(QTreeWidget):
    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self.controller = controller
        self.setColumnCount(3)
        self.setHeaderLabels(["Part", "Color", "Animation"])
        self._items: dict[str, QTreeWidgetItem] = {}
        self._pending = False
        self.currentItemChanged.connect(self._on_current)
        controller.built.connect(lambda build: self.schedule_refresh())
        controller.settings_changed.connect(self.schedule_refresh)
        controller.selection_changed.connect(self._on_selection)

    def schedule_refresh(self) -> None:
        if not self._pending:
            self._pending = True
            QTimer.singleShot(0, self.refresh)

    def _parts(self):
        for build in (self.controller.build, self.controller.helm_build):
            if build is not None and build.parts is not None:
                return build.parts
        return None

    def refresh(self) -> None:
        self._pending = False
        parts, settings = self._parts(), self.controller.settings
        self.blockSignals(True)
        self.clear()
        self._items = {}
        if parts is not None and settings is not None:
            for title, kinds in GROUPS:
                members = [p for p in parts.parts.values() if p.kind in kinds]
                if not members:
                    continue
                single = len(members) == 1 and members[0].kind in SINGLE
                parent = None if single else QTreeWidgetItem(self, [title])
                if parent is not None:
                    parent.setFlags(parent.flags() & ~Qt.ItemFlag.ItemIsSelectable)
                    parent.setExpanded(True)
                for part in sorted(members, key=lambda p: (kinds.index(p.kind), p.side or "", p.index or 0)):
                    item = QTreeWidgetItem(parent) if parent is not None else QTreeWidgetItem(self)
                    item.setText(0, part.name)
                    item.setData(0, Qt.ItemDataRole.UserRole, part.name)
                    item.setText(1, settings.corrections.colors.get(part.name, "auto"))
                    preset = settings.animation.parts.get(part.name)
                    item.setText(2, "none" if preset is not None and preset[0] is None else preset[0] if preset else "")
                    if part.kind == "eye":
                        pieces = sorted({parts.piece_of[r] for r in part.regions if r in parts.piece_of})
                        for piece in pieces:
                            child = QTreeWidgetItem(item, [piece])
                            child.setData(0, Qt.ItemDataRole.UserRole, part.name)
                    self._items[part.name] = item
        selected = self._items.get(self.controller.selected_part)
        if selected is not None:
            self.setCurrentItem(selected)
        self.blockSignals(False)
        self.resizeColumnToContents(0)

    def select(self, name: str) -> None:
        if self._pending:
            self.refresh()
        item = self._items.get(name)
        if item is not None:
            self.setCurrentItem(item)
        self.controller.select_part(name)

    def _on_current(self, current, previous) -> None:
        name = current.data(0, Qt.ItemDataRole.UserRole) if current is not None else None
        if name is not None:
            self.controller.select_part(name)

    def _on_selection(self, name) -> None:
        if self._pending:
            self.refresh()
        item = self._items.get(name)
        if item is not None and item is not self.currentItem():
            self.blockSignals(True)
            self.setCurrentItem(item)
            self.blockSignals(False)
