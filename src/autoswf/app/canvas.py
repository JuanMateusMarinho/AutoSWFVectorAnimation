"""The canvas (spec §6): the helm in head-local space over the AQW head guide (male or female), the drawing as the user
aligns it, and the overlays of the current stage. Coordinates: head units (helm space) → widget pixels by `view`."""
import math

from PySide6.QtCore import QPointF, Qt, Signal
import numpy as np
from PySide6.QtGui import QAction, QColor, QImage, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QHBoxLayout, QLabel, QMenu, QPushButton, QWidget

from autoswf.aqw.assets import DEFAULT_ARMOR, AqwCache
from autoswf.model.geometry import Matrix, Point
from autoswf.parts.assemble import head_to_backhair
from autoswf.parts.overview import part_tint
from autoswf.project.fixes import part_choices, region_mask
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
PART_ALPHA, SELECTED_ALPHA, PENDING_ALPHA = 0.35, 0.6, 0.7
CLICK_SLOP = 4                           # px a click may move and stay a click
MIN_CUT = 3.0                            # drawing px a cut line must span
ONION_OPACITY = 0.3
PIVOT_RADIUS = 7                         # px: the pivot circle (and how near a press grabs it)
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
        self.tool = "select"
        self.pending = None                      # (mask, rgb) of a fix not built yet
        self._cut: list[tuple[float, float]] = []
        self._overlay_key, self._overlay_image = None, None
        self._pivot_preview: Point | None = None
        self.onion = False
        self._onion_players: list[HelmPlayer] = []
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
        controller.selection_changed.connect(self._on_selection)
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

    @staticmethod
    def onion_frames(frame: int, length: int) -> tuple[int, int]:
        """The frames onion skin shows around `frame` (the loop wraps)."""
        return (frame - 1) % length, (frame + 1) % length

    def set_onion(self, on: bool) -> None:
        self.onion = on
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

    def set_tool(self, tool: str) -> None:
        """"select" (click a region to fix its part) or "cut" (drag a line to split regions)."""
        self.tool = tool
        self.setCursor(Qt.CursorShape.CrossCursor if tool == "cut" else Qt.CursorShape.ArrowCursor)
        self.update()

    def _on_selection(self, name) -> None:
        self.selected = name
        self.update()

    def _on_built(self, build) -> None:
        self.pending = None
        helm = self.controller.helm_build
        if helm is not None and helm is not self._player_build:
            self._player_build = helm
            self.player = HelmPlayer(helm.swf, helm.link, self.colors)
            self._onion_players = []
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
        whole = self.whole_adjust()
        if self.player is not None and self.stage != "Import":
            back = self.player.back_at(self.frame)
            if back is not None:
                self.renderer.draw(p, back, view @ whole @ head_to_backhair().inverse(), self.colors, filter_scale=zoom)
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
            if self.onion and self.player.length > 1:
                if not self._onion_players:
                    build = self._player_build
                    self._onion_players = [HelmPlayer(build.swf, build.link, self.colors) for _ in range(2)]
                p.setOpacity(ONION_OPACITY)
                for player, frame in zip(self._onion_players, self.onion_frames(self.frame, self.player.length)):
                    self.renderer.draw(p, player.at(frame), view @ whole, self.colors, filter_scale=zoom)
                p.setOpacity(1.0)
            self.renderer.draw(p, self.helm_at(self.frame), view @ whole, self.colors, filter_scale=zoom)
        self.paint_overlays(p, view)

    def _variant(self):
        settings = self.controller.settings
        if settings is None or not settings.export.variants:
            return None
        return settings.export.genders.get(self.gender)

    def whole_adjust(self) -> Matrix:
        """The male or female version's adjustment of the whole helm, as the canvas shows that gender."""
        from autoswf.project.export import adjust_matrix
        variant = self._variant()
        return adjust_matrix(variant.helm, Point(0, 0)) if variant is not None else Matrix()

    def helm_at(self, frame: int):
        """The helm at a frame, with the shown version's part adjustments on its top-level clips."""
        from autoswf.project.export import adjust_matrix, adjust_targets
        obj = self.player.at(frame)
        build = self._player_build
        if build is None or build.helm is None:
            return obj
        variant = self._variant()
        back = self.player.back_at(frame)
        inner = back.children[0] if back is not None and back.children else None
        for part, placements in adjust_targets(build.helm, build.layers).items():
            adjust = variant.parts.get(part) if variant is not None else None
            rig = build.rigs.get(part)
            for placement in placements:
                child = obj.child_by_name(placement.name) or (inner.child_by_name(placement.name)
                                                              if inner is not None else None)
                if child is None:
                    continue
                if adjust is None:
                    child.matrix = placement.matrix
                else:
                    pivot = rig.pivot if rig is not None else Point(placement.matrix.tx, placement.matrix.ty)
                    child.matrix = adjust_matrix(adjust, pivot) @ placement.matrix
        return obj

    def paint_overlays(self, p: QPainter, view: Matrix) -> None:
        """Stage overlays: the parts, a fix not built yet and the cut being drawn (Parts)."""
        if self.stage == "Animate":
            pivot = self.pivot_point()
            if pivot is not None:
                q = (view @ self.whole_adjust()).apply(pivot)
                p.setPen(QPen(QColor(20, 20, 20), 3))
                p.drawEllipse(QPointF(q.x, q.y), PIVOT_RADIUS, PIVOT_RADIUS)
                p.setPen(QPen(QColor(255, 255, 255), 1.5))
                p.drawEllipse(QPointF(q.x, q.y), PIVOT_RADIUS, PIVOT_RADIUS)
                p.drawPoint(QPointF(q.x, q.y))
        matrix = self.drawing_matrix()
        if self.stage != "Parts" or matrix is None:
            return
        transform = qt_transform(view @ matrix)
        overlay = self.parts_overlay()
        if overlay is not None:
            p.save()
            p.setTransform(transform)
            p.drawImage(0, 0, overlay)
            p.restore()
        if self.pending is not None:
            mask, rgb = self.pending
            image = np.zeros(mask.shape + (4,), np.float32)
            image[mask] = (rgb[0] / 255 * PENDING_ALPHA, rgb[1] / 255 * PENDING_ALPHA, rgb[2] / 255 * PENDING_ALPHA,
                           PENDING_ALPHA)
            p.save()
            p.setTransform(transform)
            p.drawImage(0, 0, array_to_qimage(image))
            p.restore()
        if len(self._cut) >= 2:
            path = QPainterPath()
            for k, (x, y) in enumerate(self._cut):
                q = (view @ matrix).apply(Point(x, y))
                (path.moveTo if k == 0 else path.lineTo)(q.x, q.y)
            p.setPen(QPen(QColor(255, 80, 80), 2, Qt.PenStyle.DashLine))
            p.drawPath(path)

    def pivot_point(self) -> Point | None:
        """The selected part's pivot (head units), or the one being dragged."""
        if self._pivot_preview is not None:
            return self._pivot_preview
        build = self.controller.helm_build
        rig = build.rigs.get(self.selected) if build is not None and build.rigs and self.selected else None
        return rig.pivot if rig is not None else None

    def _parts(self):
        for build in (self.controller.build, self.controller.helm_build):
            if build is not None and build.parts is not None:
                return build.parts
        return None

    def part_color(self, name: str) -> tuple[int, int, int]:
        parts = self._parts()
        names = list(parts.parts) if parts is not None else []
        return part_tint(names.index(name) if name in names else len(names))

    def parts_overlay(self) -> QImage | None:
        """Every part tinted at PART_ALPHA, the selected one at SELECTED_ALPHA (drawing pixels)."""
        parts = self._parts()
        if parts is None:
            return None
        key = (id(parts), self.selected)
        if self._overlay_key != key:
            image = np.zeros((parts.graph.height, parts.graph.width, 4), np.float32)
            for k, name in enumerate(parts.parts):
                mask = parts.part_mask(name)
                a = SELECTED_ALPHA if name == self.selected else PART_ALPHA
                r, g, b = part_tint(k)
                image[mask] = (r / 255 * a, g / 255 * a, b / 255 * a, a)
            self._overlay_key, self._overlay_image = key, array_to_qimage(image)
        return self._overlay_image

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
        elif self.stage == "Parts" and self.tool == "cut":
            point = self.drawing_point(event.position())
            if point is not None:
                self._drag, self._cut = ("cut", event.position()), [point]
        elif self.stage == "Parts":
            self._drag = ("click", event.position())
        elif self.stage == "Animate" and self.pivot_point() is not None:
            q = self.widget_point(self.whole_adjust().apply(self.pivot_point()))
            if abs(q.x() - event.position().x()) <= PIVOT_RADIUS + 3 and abs(q.y() - event.position().y()) <= PIVOT_RADIUS + 3:
                self._drag = ("pivot", event.position(), self.pivot_point())

    def _dragged_pivot(self, pos: QPointF) -> Point:
        _, start, pivot = self._drag
        a, b = self.head_point(start), self.head_point(pos)
        return Point(pivot.x + b.x - a.x, pivot.y + b.y - a.y)

    def left_move(self, event) -> None:
        if self._drag[0] == "pivot":
            self._pivot_preview = self._dragged_pivot(event.position())
            self.update()
            return
        if self._drag[0] == "cut":
            point = self.drawing_point(event.position())
            if point is not None:
                self._cut.append(point)
                self.update()

    def left_release(self, event) -> None:
        kind, start = self._drag[0], self._drag[1]
        if kind == "pivot":
            point = self._dragged_pivot(event.position())
            self._drag, self._pivot_preview = None, None
            if self.selected is not None:
                self.controller.set_pivot(self.selected, (point.x, point.y))
            self.update()
            return
        self._drag = None
        if kind == "cut":
            point = self.drawing_point(event.position())
            if point is not None and point != self._cut[-1]:
                self._cut.append(point)
            cut, self._cut = self._cut, []
            span = max((np.hypot(x - cut[0][0], y - cut[0][1]) for x, y in cut), default=0.0)
            if len(cut) >= 2 and span >= MIN_CUT:
                self.controller.add_cut(cut)
            self.update()
        elif kind == "click":
            moved = event.position() - start
            if abs(moved.x()) + abs(moved.y()) <= CLICK_SLOP:
                self.click_part(event.position())

    def click_part(self, pos: QPointF) -> None:
        """Click a region, then pick its part from the menu: one fix in two actions (spec §9.2)."""
        parts, point = self._parts(), self.drawing_point(pos)
        if parts is None or point is None:
            return
        found = region_mask(parts, *point)
        if found is None:
            self.controller.select_part(None)
            return
        rid, mask = found
        current = parts.part_of.get(rid)
        current_piece = parts.piece_of.get(rid)
        menu = QMenu(self)
        title = menu.addAction("This is: %s" % (current or "nothing") + (" (%s)" % current_piece if current_piece else ""))
        title.setEnabled(False)
        menu.addSeparator()
        groups: dict[str, QMenu] = {}
        actions: dict[QAction, object] = {}
        for choice in part_choices(parts):
            target = menu
            if choice.group is not None:
                if choice.group not in groups:
                    groups[choice.group] = menu.addMenu(choice.group)
                target = groups[choice.group]
            action = target.addAction(choice.label)
            action.setCheckable(True)
            action.setChecked(choice.part == current and choice.piece in (None, current_piece))
            actions[action] = choice
        picked = self.exec_menu(menu, pos)
        choice = actions.get(picked)
        if choice is None:
            self.controller.select_part(current)
            return
        self.pending = (mask, self.part_color(choice.part))
        self.update()
        self.controller.assign_region(point, choice.part, choice.piece)
        self.controller.select_part(choice.part)

    def exec_menu(self, menu: QMenu, pos: QPointF) -> QAction | None:
        """Show a menu at a canvas point and return the action picked (tests replace this)."""
        return menu.exec(self.mapToGlobal(pos.toPoint()))

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_C and self.stage == "Parts":
            self.set_tool("select" if self.tool == "cut" else "cut")
        elif event.key() == Qt.Key.Key_Escape:
            self.set_tool("select")
        else:
            super().keyPressEvent(event)

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
