"""The AI suggestions panel (spec §6 right panel): one card per suggestion — "Eyes found. Make them blink?" — with
Accept, Fix and Skip. Nothing is applied until the user decides."""
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QScrollArea, QVBoxLayout, QWidget

from autoswf.project.suggest import Suggestion, suggestions

EMPTY_TEXT = "No suggestions. Everything found has been decided."


class SuggestionCard(QFrame):
    def __init__(self, suggestion: Suggestion, controller):
        super().__init__()
        self.suggestion = suggestion
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setStyleSheet("SuggestionCard { background: #33333a; border-radius: 4px; }")
        column = QVBoxLayout(self)
        text = QLabel(suggestion.text)
        text.setWordWrap(True)
        column.addWidget(text)
        row = QHBoxLayout()
        self.accept_button = QPushButton("Accept")
        self.fix_button = QPushButton("Fix")
        self.skip_button = QPushButton("Skip")
        self.accept_button.setHidden(suggestion.preset is None)
        self.accept_button.setToolTip("Animate %s with %s" % (", ".join(suggestion.parts), suggestion.preset)
                                      if suggestion.preset else "")
        self.fix_button.setToolTip("Go to the %s stage to correct this by hand" % suggestion.stage)
        self.skip_button.setToolTip("Leave it as it is")
        for b in (self.accept_button, self.fix_button, self.skip_button):
            row.addWidget(b)
        row.addStretch(1)
        column.addLayout(row)
        # deferred: the card is rebuilt by the change it makes
        self.accept_button.clicked.connect(lambda: QTimer.singleShot(0, lambda: controller.accept(suggestion)))
        self.fix_button.clicked.connect(lambda: QTimer.singleShot(0, lambda: controller.fix(suggestion)))
        self.skip_button.clicked.connect(lambda: QTimer.singleShot(0, lambda: controller.skip(suggestion)))


class SuggestionsPanel(QScrollArea):
    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self.controller = controller
        self.setWidgetResizable(True)
        body = QWidget()
        self._layout = QVBoxLayout(body)
        self._layout.setContentsMargins(4, 4, 4, 4)
        title = QLabel("AI suggestions")
        title.setStyleSheet("font-weight: bold;")
        self._layout.addWidget(title)
        self.empty_label = QLabel(EMPTY_TEXT)
        self.empty_label.setWordWrap(True)
        self._layout.addWidget(self.empty_label)
        self._cards_box = QVBoxLayout()
        self._layout.addLayout(self._cards_box)
        self._layout.addStretch(1)
        self.setWidget(body)
        self.cards: list[SuggestionCard] = []
        self.extra: list[Suggestion] = []          # suggestions from outside the build (a changed drawing)
        self._pending = False
        controller.built.connect(lambda build: self.schedule_refresh())
        controller.settings_changed.connect(self.schedule_refresh)
        self.refresh()

    def schedule_refresh(self) -> None:
        if not self._pending:
            self._pending = True
            QTimer.singleShot(0, self.refresh)

    def current(self) -> list[Suggestion]:
        c = self.controller
        return list(self.extra) + suggestions(c.helm_build or c.build, c.settings)

    def refresh(self) -> None:
        self._pending = False
        for card in self.cards:
            self._cards_box.removeWidget(card)
            card.deleteLater()
        self.cards = [SuggestionCard(s, self.controller) for s in self.current()]
        for card in self.cards:
            self._cards_box.addWidget(card)
        self.empty_label.setHidden(bool(self.cards) or self.controller.settings is None)
