"""The stage bar (spec §6): Import › Vectorize › Parts › Animate › Colors › Export. It shows where the user is and what
is missing; any stage can be clicked at any time."""
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QToolButton, QWidget

from autoswf.drawing.passes import NO_ROLES_NOTE

STAGES = ("Import", "Vectorize", "Parts", "Animate", "Colors", "Export")
BUSY_STAGE = {"Reading the drawing": "Import", "Sorting the layers": "Import", "Finding the parts": "Parts",
              "Filling behind moving parts": "Parts", "Vectorizing": "Vectorize", "Building the helm": "Colors",
              "Animating": "Animate", "Writing the SWF": "Animate"}
MARKS = {"todo": "", "done": "✓ ", "attention": "! ", "busy": "… "}
COLORS = {"todo": "#9a9aa0", "done": "#7fcf8a", "attention": "#f0b03c", "busy": "#6aa8f0"}


def stage_states(settings, build, suggestions, exported: bool, busy_stage: str | None) -> dict[str, tuple[str, str]]:
    """Each stage's state ("todo", "done", "attention" or "busy") and tooltip. `suggestions` are pending AI suggestions
    (objects with `preset` and `stage`): an undecided animation flags Animate, any other flags its own stage."""
    states = {name: ("todo", "") for name in STAGES}
    if settings is None:
        return {name: ("todo", "Import a drawing first") for name in STAGES}
    failed = build.failed_stage if build is not None else None
    error = build.error if build is not None else None
    if failed in ("read", "passes"):
        states["Import"] = ("attention", error)
    elif build is not None and build.passes is not None and NO_ROLES_NOTE in build.passes.notes:
        states["Import"] = ("attention", "No layer name matches a painting pass: check the layer roles")
    elif build is not None and build.drawing is not None:
        states["Import"] = ("done", "Drawing imported")
    if failed == "art":
        states["Vectorize"] = ("attention", error)
    elif build is not None and build.art is not None:
        states["Vectorize"] = ("done", "Vector art ready")
    if failed in ("parts", "split"):
        states["Parts"] = ("attention", error)
    elif build is not None and build.art is not None:
        states["Parts"] = ("done", "%d parts" % len(build.parts.parts) if build.parts is not None else "One still shape set")
    if failed in ("helm", "animation", "swf"):
        states["Animate"] = ("attention", error)
    elif build is not None and build.swf is not None:
        states["Animate"] = ("done", "%d animated part%s" % (len(build.timeline.clips), "" if len(build.timeline.clips) == 1 else "s")
                             if build.timeline is not None else "Still helm")
    if build is not None and build.helm is not None:
        states["Colors"] = ("done", "Color custom ready")
    for s in suggestions:
        stage = "Animate" if s.preset is not None else s.stage
        states[stage] = ("attention", getattr(s, "text", "") or "AI suggestions are waiting")
    if exported:
        states["Export"] = ("done", "Exported")
    if busy_stage is not None and busy_stage in states:
        states[busy_stage] = ("busy", "Working…")
    return states


class StageBar(QWidget):
    stage_clicked = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 2, 4, 2)
        layout.setSpacing(2)
        self.buttons: dict[str, QToolButton] = {}
        for k, name in enumerate(STAGES):
            if k:
                arrow = QLabel("›")
                arrow.setStyleSheet("color: #77777c; font-size: 16px;")
                layout.addWidget(arrow)
            button = QToolButton()
            button.setCheckable(True)
            button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
            button.clicked.connect(lambda _=False, n=name: self._clicked(n))
            layout.addWidget(button)
            self.buttons[name] = button
        self.states = {name: ("todo", "") for name in STAGES}
        self.current = "Import"
        self._refresh()

    def _clicked(self, name: str) -> None:
        self.set_current(name)
        self.stage_clicked.emit(name)

    def set_current(self, name: str) -> None:
        self.current = name
        self._refresh()

    def set_states(self, states: dict[str, tuple[str, str]]) -> None:
        self.states = dict(states)
        self._refresh()

    def _refresh(self) -> None:
        for name, button in self.buttons.items():
            state, tip = self.states.get(name, ("todo", ""))
            button.setText(MARKS[state] + name)
            button.setToolTip(tip or name)
            button.setChecked(name == self.current)
            weight = "bold" if name == self.current else "normal"
            button.setStyleSheet("QToolButton { color: %s; font-weight: %s; padding: 3px 10px; }"
                                 "QToolButton:checked { background: #3a3a40; border-radius: 3px; }"
                                 % (COLORS[state], weight))
