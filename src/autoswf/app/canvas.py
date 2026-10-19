"""The canvas (spec §6): the helm in head-local space over the AQW head guide (male or female), the drawing as the user
aligns it, and the overlays of the current stage. Coordinates: head units (helm space) → widget pixels by `view`."""
import math

from PySide6.QtCore import QPointF, Qt, Signal
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QWidget

from autoswf.aqw.assets import DEFAULT_ARMOR, AqwCache
from autoswf.model.geometry import Matrix, Point
from autoswf.parts.assemble import head_to_backhair
from autoswf.project.player import HelmPlayer
from autoswf.render.colors import PlayerColors
from autoswf.render.display import ScriptContext, instantiate, run_pending_actions
from autoswf.render.effects import array_to_qimage
from autoswf.render.painter import Renderer, qt_transform
from autoswf.swf.decode import MovieData

BACKGROUND = QColor(58, 58, 62)
HEAD_CENTER = Point(-8.75, -1.45)        # middle of the male and female base heads (head units)
FIT_SIZE = (130.0, 140.0)                # head units shown when fitted
MIN_ZOOM, MAX_ZOOM = 0.5, 80.0
MISSING_TEXT = "AQW reference files are not downloaded: the head guide and the body preview need them."


class HelmCanvas(QWidget):
    download_requested = Signal()
    view_changed = Signal()

    def __init__(self, controller, cache: AqwCache, parent=None):
        super().__init__(parent)
        self.controller, self.cache = controller, cache
        self.setMinimumSize(360, 300)
        self.setMouseTracking(True)
        self.gender, self.frame, self.stage = "M", 0, "Import"
        self.zoom: float | None = None           # None = fitted to the widget
        self._pan = QPointF(0, 0)
        self.guide_opacity, self.drawing_opacity = 1.0, 0.0
        self.colors = PlayerColors()
        self.selected: str | None = None
        self.renderer = Renderer()
        self.player: HelmPlayer | None = None
        self._player_build = None
        self._client: MovieData | None = None
        self._guides: dict[str, object] = {}
        self._drawing_key, self._drawing_image = None, None
        self._drag = None
        self._align_preview: Matrix | None = None
        self._banner = QWidget(self)
        row = QHBoxLayout(self._banner)
        row.setContentsMargins(8, 4, 8, 4)
        self._banner_label = QLabel(MISSING_TEXT)
        self._banner_label.setWordWrap(True)
        button = QPushButton("Download AQW files…")
        button.clicked.connect(self.download_requested.emit)
        row.addWidget(self._banner_label, 1)
        row.addWidget(button)
        self._banner.setStyleSheet("background: #4a3a1c; color: #f3d9a4;")
        controller.built.connect(self._on_built)
        controller.settings_changed.connect(self._on_settings)
        self.reload_client()

    # ------------------------------------------------------------ state

    @property
    def banner_text(self) -> str:
        return "" if self._banner.isHidden() else self._banner_label.text()

    @property
    def guide_class(self) -> str | None:
        return "mcHead" + self.gender if self._client is not None else None

    def reload_client(self) -> None:
        """Load the head guides from the cached AQW client (after a download too)."""
        path = self.cache.client_path()
        self._client, self._guides = None, {}
        if path is not None:
            try:
                self._client = MovieData(path)
            except ValueError:
                self._client = None
        if self._client is not None:
            for g in "MF":
                cid = self._client.classes.get("mcHead" + g)
                if cid is not None:
                    obj = instantiate(self._client, cid)
                    run_pending_actions(obj, ScriptContext(self.colors))
                    self._guides[g] = obj
        self._banner.setHidden(not self.cache.missing(DEFAULT_ARMOR))
        self.update()

    def set_gender(self, gender: str) -> None:
        self.gender = gender
        self.update()

    def set_frame(self, frame: int) -> None:
        self.frame = max(0, frame)
        self.update()

    def set_stage(self, stage: str) -> None:
        self.stage = stage
        self.update()

    def fit(self) -> None:
        self.zoom, self._pan = None, QPointF(0, 0)
        self.view_changed.emit()
        self.update()

    def set_zoom(self, zoom: float, anchor: QPointF | None = None) -> None:
        old = self.current_zoom()
        zoom = min(MAX_ZOOM, max(MIN_ZOOM, zoom))
        if anchor is not None:
            head = self.head_point(anchor)
            self.zoom = zoom
            moved = self.widget_point(head)
            self._pan += anchor - moved
        else:
            self.zoom = zoom
        if old != zoom:
            self.view_changed.emit()
        self.update()

    def _on_built(self, build) -> None:
        helm = self.controller.helm_build
        if helm is not None and helm is not self._player_build:
            self._player_build = helm
            self.player = HelmPlayer(helm.swf, helm.link, self.colors)
        self.update()

    def _on_settings(self) -> None:
        settings = self.controller.settings
        colors = PlayerColors()
        for location, rgb in (settings.colors.items() if settings is not None else ()):
            colors = colors.replace(location, rgb)
        self.colors = colors
        if self.player is not None:
            self.player.set_colors(colors)
        self.update()

    # ------------------------------------------------------------ coordinates

    def current_zoom(self, width: int | None = None, height: int | None = None) -> float:
        if self.zoom is not None:
            return self.zoom
        w, h = width or self.width(), height or self.height()
        return max(MIN_ZOOM, min(w / FIT_SIZE[0], h / FIT_SIZE[1]))

    def view(self, width: int | None = None, height: int | None = None) -> Matrix:
        """Head units -> widget pixels."""
        w, h = width or self.width(), height or self.height()
        z = self.current_zoom(w, h)
        return (Matrix.translate(w / 2 + self._pan.x(), h / 2 + self._pan.y()) @ Matrix.scale(z, z)
                @ Matrix.translate(-HEAD_CENTER.x, -HEAD_CENTER.y))

    def _alignment(self):
        build = self._drawing_build()
        return build.alignment if build is not None else None

    def head_point(self, pos: QPointF) -> Point:
        return self.view().inverse().apply(Point(pos.x(), pos.y()))

    def widget_point(self, p: Point) -> QPointF:
        q = self.view().apply(p)
        return QPointF(q.x, q.y)

    def drawing_point(self, pos: QPointF) -> tuple[float, float] | None:
        alignment = self._alignment()
        if alignment is None:
            return None
        p = alignment.matrix().inverse().apply(self.head_point(pos))
        return p.x, p.y

    def widget_point_of_drawing(self, x: float, y: float) -> QPointF:
        return self.widget_point(self._alignment().matrix().apply(Point(x, y)))

    # ------------------------------------------------------------ drawing

    def _drawing_build(self):
        for build in (self.controller.build, self.controller.helm_build):
            if build is not None and build.passes is not None and build.alignment is not None:
                return build
        return None

    def drawing_image(self) -> QImage | None:
        build = self._drawing_build()
        if build is None:
            return None
        if self._drawing_key is not build.passes:
            self._drawing_key, self._drawing_image = build.passes, array_to_qimage(build.passes.full)
        return self._drawing_image

    def drawing_matrix(self) -> Matrix | None:
        """Drawing pixels -> head units (the alignment, or the one being dragged)."""
        if self._align_preview is not None:
            return self._align_preview
        alignment = self._alignment()
        return alignment.matrix() if alignment is not None else None

    def render_image(self, width: int, height: int) -> QImage:
        image = QImage(width, height, QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(0)
        p = QPainter(image)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        self._paint(p, width, height)
        p.end()
        return image

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        self._paint(p, self.width(), self.height())
        p.end()

    def _paint(self, p: QPainter, width: int, height: int) -> None:
        p.fillRect(0, 0, width, height, BACKGROUND)
        view = self.view(width, height)
        zoom = self.current_zoom(width, height)
        if self.player is not None and self.stage != "Import":
            back = self.player.back_at(self.frame)
            if back is not None:
                self.renderer.draw(p, back, view @ head_to_backhair().inverse(), self.colors, filter_scale=zoom)
        guide = self._guides.get(self.gender)
        if guide is not None and self.guide_opacity > 0:
            p.setOpacity(self.guide_opacity)
            self.renderer.draw(p, guide, view, self.colors, filter_scale=zoom)
            p.setOpacity(1.0)
        opacity = 1.0 if self.stage == "Import" else self.drawing_opacity
        image, matrix = self.drawing_image(), self.drawing_matrix()
        if image is not None and matrix is not None and opacity > 0:
            p.save()
            p.setOpacity(opacity)
            p.setTransform(qt_transform(view @ matrix))
            p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
            p.drawImage(0, 0, image)
            p.restore()
        if self.player is not None and self.stage != "Import":
            self.renderer.draw(p, self.helm_at(self.frame), view, self.colors, filter_scale=zoom)
        self.paint_overlays(p, view)

    def helm_at(self, frame: int):
        return self.player.at(frame)

    def paint_overlays(self, p: QPainter, view: Matrix) -> None:
        """Stage overlays (parts, pending fixes, cut line, pivot); later stages add theirs."""

    # ------------------------------------------------------------ mouse

    def resizeEvent(self, event) -> None:
        self._banner.setGeometry(0, 0, self.width(), 40)
        super().resizeEvent(event)

    def wheelEvent(self, event) -> None:
        steps = event.angleDelta().y() / 120
        self.set_zoom(self.current_zoom() * math.pow(1.15, steps), event.position())

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.MiddleButton:
            self._drag = ("pan", event.position(), QPointF(self._pan))
        elif event.button() == Qt.MouseButton.LeftButton:
            self.left_press(event)

    def mouseMoveEvent(self, event) -> None:
        if self._drag is None:
            return
        if self._drag[0] == "pan":
            self._pan = self._drag[2] + (event.position() - self._drag[1])
            self.update()
        elif self._drag[0] == "align":
            self._align_preview = self._align_transform(event.position()) @ self._drag[3]
            self.update()
        else:
            self.left_move(event)

    def mouseReleaseEvent(self, event) -> None:
        if self._drag is None:
            return
        kind = self._drag[0]
        if kind == "align":
            from autoswf.aqw.template import alignment_from_matrix
            matrix = self._align_transform(event.position()) @ self._drag[3]
            self._drag, self._align_preview = None, None
            if matrix != self.drawing_matrix():
                self.controller.set_alignment(alignment_from_matrix(matrix))
            self.update()
        elif kind == "pan":
            self._drag = None
        else:
            self.left_release(event)

    # ------------------------------------------------------------ stage tools (left button)

    def left_press(self, event) -> None:
        if self.stage == "Import" and self.drawing_matrix() is not None:
            self._drag = ("align", event.position(), event.modifiers(), self.drawing_matrix())

    def left_move(self, event) -> None:
        pass

    def left_release(self, event) -> None:
        self._drag = None

    def _align_transform(self, pos: QPointF) -> Matrix:
        """The head-space transform a drag gives the drawing: move; Alt = scale about the head origin (down =
        bigger); Shift = turn about the head origin."""
        _, start, modifiers, _ = self._drag
        if modifiers & Qt.KeyboardModifier.AltModifier:
            k = math.exp((pos.y() - start.y()) / 200)
            return Matrix.scale(k, k)
        if modifiers & Qt.KeyboardModifier.ShiftModifier:
            origin = self.widget_point(Point(0, 0))
            a0 = math.atan2(start.y() - origin.y(), start.x() - origin.x())
            a1 = math.atan2(pos.y() - origin.y(), pos.x() - origin.x())
            return Matrix.rotate(a1 - a0)
        p0, p1 = self.head_point(start), self.head_point(pos)
        return Matrix.translate(p1.x - p0.x, p1.y - p0.y)
