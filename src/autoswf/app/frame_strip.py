"""A strip of the selected layer's frames (Plan 7, spec §7, §8.5): the current frame, frame labels to jump to (an
animated armor's own animations), and marks on the frames that show the drawing being edited."""
from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter
from PySide6.QtWidgets import QWidget

CELL, HEIGHT = 9, 34


class FrameStrip(QWidget):
    frame_changed = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.count, self.current, self.labels, self.marks = 1, 0, {}, []
        self.setFixedHeight(HEIGHT)
        self.setToolTip("Frames of the selected layer; marked frames show the drawing you are editing")

    def set_frames(self, count: int, current: int, labels: dict[str, int] | None = None) -> None:
        self.count, self.current, self.labels = max(1, count), max(0, min(current, max(1, count) - 1)), dict(labels or {})
        self.setVisible(self.count > 1)
        self.update()

    def set_marks(self, frames: list[int]) -> None:
        self.marks = list(frames)
        self.update()

    def frame_at(self, x: float) -> int:
        return max(0, min(self.count - 1, int(x // CELL)))

    def mousePressEvent(self, event) -> None:
        pos = event.position()
        frame = self.frame_at(pos.x())
        if pos.y() < 12:
            starts = sorted(self.labels.values())
            frame = max([s for s in starts if s <= frame], default=frame)
        self.current = frame
        self.update()
        self.frame_changed.emit(frame)

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(34, 34, 37))
        font = QFont(p.font())
        font.setPointSizeF(7)
        p.setFont(font)
        for label, frame in self.labels.items():
            p.setPen(QColor(240, 190, 80))
            p.drawText(QRectF(frame * CELL + 1, 0, 120, 12), Qt.AlignmentFlag.AlignLeft, label)
        for f in range(self.count):
            x = f * CELL
            color = QColor(230, 60, 60) if f == self.current else (
                QColor(110, 160, 255) if f in self.marks else QColor(70, 70, 76))
            p.fillRect(int(x), 14, CELL - 1, HEIGHT - 16, color)
        p.end()
