"""The source layers (spec §5, §6 left panel): every layer of the drawing with the painting pass it is used as, why,
and a menu to set the role by hand; soft shadow/occlusion/light layers can be drawn as SWF gradients."""
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QCheckBox, QComboBox, QTreeWidget, QTreeWidgetItem

from autoswf.drawing.roles import IGNORE, TONE_ROLES, assign_roles, role_reason

ROLE_LABELS = {"line": "Line", "flat": "Flat colors", "shadow": "Shadow", "occlusion": "Occlusion shadow",
               "light": "Light", "details": "Details", IGNORE: "Not used"}
LABEL_ROLES = {label: role for role, label in ROLE_LABELS.items()}


class LayerList(QTreeWidget):
    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self.controller = controller
        self.setColumnCount(4)
        self.setHeaderLabels(["Layer", "Role", "Why", "Gradient"])
        self.setRootIsDecorated(True)
        self._drawing, self._detected = None, {}
        self._rows: dict[str, tuple[QComboBox, QTreeWidgetItem]] = {}
        self._pending = False
        controller.built.connect(lambda build: self.schedule_refresh())
        controller.settings_changed.connect(self.schedule_refresh)

    def schedule_refresh(self) -> None:
        """Rebuild the rows after the current event (a combo must not be deleted inside its own signal)."""
        if not self._pending:
            self._pending = True
            QTimer.singleShot(0, self.refresh)

    def _build(self):
        for build in (self.controller.build, self.controller.helm_build):
            if build is not None and build.drawing is not None:
                return build
        return None

    def refresh(self) -> None:
        self._pending = False
        build, settings = self._build(), self.controller.settings
        self.clear()
        self._rows = {}
        if build is None or settings is None:
            return
        drawing = build.drawing
        if drawing is not self._drawing:
            self._drawing = drawing
            self._detected = {n: r.role for n, r in assign_roles(drawing, {}).items()}
        try:
            roles = assign_roles(drawing, dict(settings.roles))
        except ValueError:
            roles = assign_roles(drawing, {})
        items: dict[int, QTreeWidgetItem] = {}
        for node, ancestors in drawing.walk():
            parent = items.get(id(ancestors[-1])) if ancestors else None
            item = QTreeWidgetItem(parent) if parent is not None else QTreeWidgetItem(self)
            item.setText(0, node.name)
            items[id(node)] = item
            if node.kind == "group":
                item.setExpanded(True)
                continue
            path = "/".join([a.name for a in ancestors] + [node.name])
            role = roles[node]
            siblings = ancestors[-1].children if ancestors else drawing.layers
            detected = self._detected.get(node)
            auto = "Auto (%s)" % (detected if detected not in (None, IGNORE) else "not used")
            combo = QComboBox()
            combo.addItems([auto] + list(ROLE_LABELS.values()))
            override = settings.roles.get(path, settings.roles.get(node.name))
            combo.setCurrentText(ROLE_LABELS[override] if override in ROLE_LABELS else auto)
            combo.activated.connect(lambda _=0, p=path, c=combo: self.set_role(p, c.currentText()))
            self.setItemWidget(item, 1, combo)
            item.setText(2, role_reason(node, ancestors, role, siblings))
            if role.role in TONE_ROLES:
                box = QCheckBox()
                box.setChecked(node.name in settings.gradient)
                box.setToolTip("Draw this soft layer as an SWF gradient instead of flat steps")
                box.toggled.connect(lambda on, n=node.name: self.set_gradient(n, on))
                self.setItemWidget(item, 3, box)
            self._rows[path] = (combo, item)
        self.resizeColumnToContents(0)

    def rows(self) -> dict[str, tuple[str, str]]:
        """Layer path -> (the role shown, why)."""
        if self._pending:
            self.refresh()
        return {path: (combo.currentText(), item.text(2)) for path, (combo, item) in self._rows.items()}

    def set_role(self, layer: str, text: str) -> None:
        """What picking an entry of a layer's role menu does."""
        if self._pending:
            self.refresh()
        if layer in self._rows:
            self._rows[layer][0].setCurrentText(text)
        self.controller.set_role(layer, None if text.startswith("Auto") else LABEL_ROLES[text])

    def set_gradient(self, layer: str, on: bool) -> None:
        self.controller.set_gradient(layer, on)
