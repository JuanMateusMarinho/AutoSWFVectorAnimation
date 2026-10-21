"""The timeline (spec §6 bottom, §11): one row per animated layer, frames at 24 fps, keyframes made by the presets
(hollow) and by hand (filled), every-frame keys as a band, the playhead, play/loop and onion skin. Frames are shown
1-based, as in Animate."""
from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QCheckBox, QHBoxLayout, QLabel, QPushButton, QScrollArea, QVBoxLayout, QWidget

from autoswf.project.timeline_rows import TimelineRow, timeline_rows

FPS = 24
FRAME_W, ROW_H, NAME_W, RULER_H = 10, 20, 170, 20
BACKGROUND, ROW_A, ROW_B, OUTSIDE = QColor(34, 34, 37), QColor(44, 44, 48), QColor(40, 40, 44), QColor(28, 28, 30)
GENERATED, MANUAL, PLAYHEAD = QColor(150, 150, 160), QColor(240, 190, 80), QColor(230, 60, 60)


class _Area(QWidget):
    def __init__(self, view: "TimelineView"):
        super().__init__()
        self.view = view
        self.setMouseTracking(False)

    def sizeHint(self):
        from PySide6.QtCore import QSize
        return QSize(NAME_W + FRAME_W * (self.view.length() + 2), RULER_H + ROW_H * max(1, len(self.view.rows)))

    def paintEvent(self, event) -> None:
        v = self.view
        p = QPainter(self)
        p.fillRect(self.rect(), BACKGROUND)
        length = v.length()
        font = QFont(p.font())
        font.setPointSizeF(8)
        p.setFont(font)
        p.setPen(QColor(170, 170, 175))
        for f in range(0, length + 1, 5):
            x = NAME_W + f * FRAME_W
            p.drawLine(x, RULER_H - 5, x, RULER_H)
            p.drawText(QRectF(x + 2, 0, 30, RULER_H - 4), Qt.AlignmentFlag.AlignLeft, str(f + 1))
        for i, row in enumerate(v.rows):
            y = RULER_H + i * ROW_H
            p.fillRect(0, y, NAME_W + length * FRAME_W, ROW_H, ROW_A if i % 2 == 0 else ROW_B)
            p.fillRect(NAME_W + row.length * FRAME_W, y, max(0, (length - row.length) * FRAME_W), ROW_H, OUTSIDE)
            selected = v.selected == (row.part, row.target or row.part)
            p.setPen(QColor(255, 255, 255) if selected else QColor(200, 200, 205))
            weight = QFont(font)
            weight.setBold(row.target is None)
            p.setFont(weight)
            label = "%s  (%s, %d frames)" % (row.part, row.preset, row.length) if row.target is None else "   " + row.target
            p.drawText(QRectF(4, y, NAME_W - 6, ROW_H), Qt.AlignmentFlag.AlignVCenter, label)
            for f in v.marks.get(row.part, []) if row.target is None else []:
                p.fillRect(NAME_W + f * FRAME_W + 2, y + ROW_H - 4, FRAME_W - 4, 3, QColor(110, 160, 255))
            every = len(row.keys) >= row.length > 1
            if every:
                p.fillRect(NAME_W, y + 7, row.length * FRAME_W, ROW_H - 14, QColor(90, 90, 110))
            for f, kind in row.keys.items():
                cx, cy = NAME_W + f * FRAME_W + FRAME_W / 2, y + ROW_H / 2
                if kind == "manual":
                    p.setPen(Qt.PenStyle.NoPen)
                    p.setBrush(MANUAL)
                    p.drawEllipse(QPointF(cx, cy), 3.5, 3.5)
                elif not every:
                    p.setPen(QPen(GENERATED, 1.2))
                    p.setBrush(Qt.BrushStyle.NoBrush)
                    p.drawEllipse(QPointF(cx, cy), 3, 3)
        x = NAME_W + v.playhead * FRAME_W + FRAME_W / 2
        p.setPen(QPen(PLAYHEAD, 1.5))
        p.drawLine(QPointF(x, 0), QPointF(x, RULER_H + ROW_H * max(1, len(v.rows))))
        p.end()

    def mousePressEvent(self, event) -> None:
        v = self.view
        pos = event.position()
        frame = int((pos.x() - NAME_W) // FRAME_W)
        if frame < 0:
            frame = v.playhead
        frame = max(0, min(v.length() - 1, frame))
        index = int((pos.y() - RULER_H) // ROW_H)
        if pos.y() < RULER_H or not 0 <= index < len(v.rows):
            v.set_playhead(frame)
            return
        row = v.rows[index]
        v.select_cell(row.part, row.target or row.part, frame)


class TimelineView(QWidget):
    frame_changed = Signal(int)
    key_selected = Signal(object)        # (part, target, frame) of a hand-made key, or None
    track_selected = Signal(object)      # (part, target) or None

    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self.controller = controller
        self.rows: list[TimelineRow] = []
        self.marks: dict[str, list[int]] = {}       # part -> frames showing the drawing being edited
        self.playhead, self.selected, self.selected_key = 0, None, None
        self.playing, self.loop, self.onion = False, True, False
        self.play_button = QPushButton("Play")
        self.play_button.setToolTip("Play / pause (Enter)")
        self.loop_box = QCheckBox("Loop")
        self.loop_box.setChecked(True)
        self.onion_box = QCheckBox("Onion skin")
        self.frame_label = QLabel()
        bar = QHBoxLayout()
        bar.setContentsMargins(4, 2, 4, 2)
        for w in (self.play_button, self.loop_box, self.onion_box, self.frame_label):
            bar.addWidget(w)
        bar.addStretch(1)
        fps = QLabel("%d fps" % FPS)
        bar.addWidget(fps)
        self.area = _Area(self)
        scroll = QScrollArea()
        scroll.setWidget(self.area)
        scroll.setWidgetResizable(False)
        column = QVBoxLayout(self)
        column.setContentsMargins(0, 0, 0, 0)
        column.addLayout(bar)
        column.addWidget(scroll, 1)
        self.timer = QTimer(self)
        self.timer.setInterval(round(1000 / FPS))
        self.timer.timeout.connect(self.advance)
        self.play_button.clicked.connect(self.toggle_play)
        self.loop_box.toggled.connect(lambda on: setattr(self, "loop", on))
        self.onion_box.toggled.connect(self._onion_toggled)
        controller.built.connect(lambda build: self.refresh())
        controller.selection_changed.connect(self._on_part_selected)
        self.refresh()

    def set_marks(self, part: str, frames: list[int]) -> None:
        self.marks[part] = list(frames)
        self.area.update()

    def length(self) -> int:
        return max((r.length for r in self.rows), default=1)

    def refresh(self) -> None:
        self.rows = timeline_rows(self.controller.helm_build)
        if self.playhead >= self.length():
            self.playhead = 0
        if self.selected_key is not None and not self._is_manual(*self.selected_key):
            self.selected_key = None
            self.key_selected.emit(None)
        self.area.resize(self.area.sizeHint())
        self._update_label()
        self.area.update()

    def _is_manual(self, part: str, target: str, frame: int) -> bool:
        return any(r.part == part and r.target == target and r.keys.get(frame) == "manual" for r in self.rows)

    def _update_label(self) -> None:
        self.frame_label.setText("Frame %d / %d" % (self.playhead + 1, self.length()))

    def set_playhead(self, frame: int) -> None:
        self.playhead = max(0, frame)
        self._update_label()
        self.area.update()
        self.frame_changed.emit(self.playhead)

    def select_cell(self, part: str, target: str, frame: int) -> None:
        self.selected = (part, target)
        self.track_selected.emit(self.selected)
        if self.controller.selected_part != part:
            self.controller.select_part(part)
        self.set_playhead(frame)
        self.select_key((part, target, frame) if self._is_manual(part, target, frame) else None)

    def select_key(self, key) -> None:
        self.selected_key = key
        self.key_selected.emit(key)
        self.area.update()

    def _on_part_selected(self, name) -> None:
        if name is not None and (self.selected is None or self.selected[0] != name):
            self.selected = (name, name)
            self.area.update()

    def toggle_play(self) -> None:
        self.playing = not self.playing
        self.play_button.setText("Pause" if self.playing else "Play")
        if self.playing:
            self.timer.start()
        else:
            self.timer.stop()

    def advance(self) -> None:
        """One timer tick: the next frame, looping at the longest loop (or stopping there)."""
        nxt = self.playhead + 1
        if nxt >= self.length():
            if self.loop:
                nxt = 0
            else:
                nxt = self.length() - 1
                if self.playing:
                    self.toggle_play()
        self.set_playhead(nxt)

    def _onion_toggled(self, on: bool) -> None:
        self.onion = on
        self.frame_changed.emit(self.playhead)
