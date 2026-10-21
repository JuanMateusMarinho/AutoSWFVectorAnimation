"""The editor's tools (Plan 7, spec §6, §8.2-8.4), shared by the helm and the SWF canvases: Move (V), Brush (B), Magic
Wand (W), Eraser (E) and Eyedropper (I), with Photoshop's habits — Alt+click picks a color, Shift/Alt+click add to or
take from the selection, Delete clears it, Ctrl+D deselects, Ctrl+T transforms, [ and ] change the brush size.
Everything here works in layer px; the canvas converts its events. An edit comes out as `edit_ready(LayerEdit,
label)`; a selection change is an undo step of its own, pushed on `undo_stack`."""
import math

from PySide6.QtCore import QEvent, QObject, QPointF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen, QUndoCommand

from autoswf.edit.brush import Sample, stroke_area, stroke_width
from autoswf.edit.layer import EditLayer, Selection, ToneRef
from autoswf.edit.regions import TWIPS, Area, bounds_px, transform_area, union
from autoswf.model.geometry import Matrix, Point

TOOLS = ("move", "brush", "wand", "eraser", "eyedropper")
TOOL_KEYS = {"move": "V", "brush": "B", "wand": "W", "eraser": "E", "eyedropper": "I"}
TOOL_NAMES = {"move": "Move", "brush": "Brush", "wand": "Magic Wand", "eraser": "Eraser", "eyedropper": "Eyedropper"}
SIZE_RANGE = (1.0, 200.0)
SIZE_STEP = 1.1                    # [ and ] change the size by 10%
HANDLE_PX = 8.0                    # transform handles, widget px


class _SelectionCommand(QUndoCommand):
    def __init__(self, tools: "EditTools", label: str, before, after):
        super().__init__(label)
        self.tools, self.before, self.after = tools, before, after

    def redo(self) -> None:
        self.tools._set_selection(self.after)

    def undo(self) -> None:
        self.tools._set_selection(self.before)


class EditableCanvas:
    """Mixin for a canvas the tools work on. The canvas provides `edit_tools`, `layer_matrix()` (layer px -> widget),
    `pan_by(dx, dy)`, `fit()` and `zoom_100()`; this turns its mouse, tablet and key events into tool calls."""

    def _tools_init(self) -> None:
        self.edit_tools: EditTools | None = None
        self._space = False
        self._pan_drag = None
        self._tablet_down = False

    def _tools_on(self) -> bool:
        return self.edit_tools is not None and self.edit_tools.active

    def _layer_point(self, pos) -> Point:
        return self.layer_matrix().inverse().apply(Point(pos.x(), pos.y()))

    def _sync_handles(self) -> None:
        m = self.layer_matrix()
        scale = math.hypot(m.a, m.b) or 1.0
        self.edit_tools.handle_radius = HANDLE_PX / scale

    def tool_mouse(self, event, kind: str) -> bool:
        """Mouse press/move/release for the tools or for a Space+drag pan; True when used."""
        if self._pan_drag is not None or (kind == "press" and self._space):
            if kind == "press":
                self._pan_drag = event.position()
            elif kind == "move":
                delta = event.position() - self._pan_drag
                self._pan_drag = event.position()
                self.pan_by(delta.x(), delta.y())
            else:
                self._pan_drag = None
            return True
        if not self._tools_on() or self._tablet_down:
            return self._tablet_down
        if kind == "move" and not (event.buttons() & Qt.MouseButton.LeftButton):
            return False
        if kind == "press" and event.button() != Qt.MouseButton.LeftButton:
            return False
        p = self._layer_point(event.position())
        self._sync_handles()
        if kind == "press":
            self.edit_tools.press(p.x, p.y, 1.0, event.modifiers())
        elif kind == "move":
            self.edit_tools.move(p.x, p.y, 1.0)
        else:
            self.edit_tools.release(p.x, p.y, 1.0)
        self.update()
        return True

    def tabletEvent(self, event) -> None:
        if not self._tools_on():
            event.ignore()
            return
        p = self._layer_point(event.position())
        kind = event.type()
        self._sync_handles()
        if kind == QEvent.Type.TabletPress:
            self._tablet_down = True
            self.edit_tools.press(p.x, p.y, event.pressure(), event.modifiers())
        elif kind == QEvent.Type.TabletMove and self._tablet_down:
            self.edit_tools.move(p.x, p.y, event.pressure())
        elif kind == QEvent.Type.TabletRelease and self._tablet_down:
            self._tablet_down = False
            self.edit_tools.release(p.x, p.y, event.pressure())
        event.accept()
        self.update()

    def tool_shortcut_override(self, event) -> bool:
        """Keys the canvas takes before window shortcuts (Enter/Esc while transforming)."""
        if self._tools_on() and self.edit_tools.transforming and event.key() in (
                Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Escape):
            event.accept()
            return True
        return False

    def tool_key(self, event) -> bool:
        k, mods = event.key(), event.modifiers()
        ctrl = bool(mods & Qt.KeyboardModifier.ControlModifier)
        if k == Qt.Key.Key_Space and not event.isAutoRepeat():
            self._space = True
            return True
        if ctrl and k == Qt.Key.Key_0:
            self.fit()
            return True
        if ctrl and k == Qt.Key.Key_1:
            self.zoom_100()
            return True
        if not self._tools_on():
            return False
        t = self.edit_tools
        if t.transforming and k in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            t.commit_transform()
        elif t.transforming and k == Qt.Key.Key_Escape:
            t.cancel_transform()
        elif k in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            t.delete_selection()
        elif ctrl and k == Qt.Key.Key_D:
            t.deselect()
        elif ctrl and k == Qt.Key.Key_T:
            t.begin_transform()
        elif k == Qt.Key.Key_BracketRight:
            t.bigger()
        elif k == Qt.Key.Key_BracketLeft:
            t.smaller()
        else:
            return False
        self.update()
        return True

    def tool_key_release(self, event) -> bool:
        if event.key() == Qt.Key.Key_Space and not event.isAutoRepeat():
            self._space = False
            return True
        return False


def area_path(area: Area, view: Matrix) -> QPainterPath:
    path = QPainterPath()
    path.setFillRule(Qt.FillRule.WindingFill)
    for ring in area:
        pts = [view.apply(Point(x / TWIPS, y / TWIPS)) for x, y in ring]
        if len(pts) < 3:
            continue
        path.moveTo(pts[0].x, pts[0].y)
        for p in pts[1:]:
            path.lineTo(p.x, p.y)
        path.closeSubpath()
    return path


class EditTools(QObject):
    edit_ready = Signal(object, str)        # LayerEdit, undo label
    selection_changed = Signal()
    tone_changed = Signal()
    message = Signal(str)
    changed = Signal()                      # anything the overlay or the options bar shows

    def __init__(self, parent=None):
        super().__init__(parent)
        self.tool = "brush"
        self.active = False                 # the canvas gives its left button to the tools
        self.size = 10.0
        self.use_pressure = True
        self.color: ToneRef | tuple | None = None
        self.close_gap = 3.0
        self.selection: Selection | None = None
        self.layer: EditLayer | None = None
        self.undo_stack = None
        self.handle_radius = 2.0            # layer px, set by the canvas from its zoom
        self._size_by_hand = False
        self._stroke: list[Sample] | None = None
        self._drag = None                   # ("move", start) or a transform drag
        self._offset = (0.0, 0.0)
        self.transforming = False
        self._transform = Matrix()
        self._box = None

    # ------------------------------------------------------------ state

    def set_tool(self, tool: str) -> None:
        if tool not in TOOLS:
            raise ValueError("Unknown tool '%s'" % tool)
        self.cancel_transform()
        self.tool, self.active = tool, True
        self.changed.emit()

    def set_size(self, size: float, by_hand: bool = True) -> None:
        self.size = max(SIZE_RANGE[0], min(SIZE_RANGE[1], float(size)))
        self._size_by_hand = self._size_by_hand or by_hand
        self.changed.emit()

    def bigger(self) -> None:
        self.set_size(round(self.size * SIZE_STEP, 2))

    def smaller(self) -> None:
        self.set_size(round(self.size / SIZE_STEP, 2))

    def set_layer(self, layer: EditLayer | None, keep_selection: bool = False) -> None:
        self.layer = layer
        self.cancel_transform()
        if not keep_selection:
            self.selection = None
        if layer is not None:
            if not self._size_by_hand:
                self.size = float(max(1, round(layer.line_width)))
            known = {t.ref for t in layer.tones}
            if not (isinstance(self.color, ToneRef) and self.color in known) and not isinstance(self.color, tuple):
                self.color = layer.line_tone or (layer.tones[0].ref if layer.tones else None)
        self.changed.emit()

    def set_color(self, color) -> None:
        self.color = color
        self.tone_changed.emit()
        self.changed.emit()

    def _set_selection(self, selection: Selection | None) -> None:
        self.selection = selection
        self.selection_changed.emit()
        self.changed.emit()

    def _commit_selection(self, label: str, selection: Selection | None) -> None:
        if selection == self.selection:
            return
        if self.undo_stack is None:
            self._set_selection(selection)
        else:
            self.undo_stack.push(_SelectionCommand(self, label, self.selection, selection))

    # ------------------------------------------------------------ pointer (layer px)

    def press(self, x: float, y: float, pressure: float = 1.0, modifiers=Qt.KeyboardModifier.NoModifier) -> None:
        if self.layer is None:
            self.message.emit("Pick a layer to edit first")
            return
        alt = bool(modifiers & Qt.KeyboardModifier.AltModifier)
        shift = bool(modifiers & Qt.KeyboardModifier.ShiftModifier)
        if self.transforming:
            self._press_transform(x, y)
            return
        if self.tool == "eyedropper" or (alt and self.tool != "wand"):
            ref = self.layer.tone_at(x, y)
            if ref is not None:
                self.set_color(ref)
            return
        if self.tool in ("brush", "eraser"):
            self._stroke = [Sample(x, y, pressure)]
        elif self.tool == "wand":
            found = self.layer.wand(x, y, close_gap=self.close_gap)
            if shift and self.selection is not None:
                new = self.selection.combined(found) if found is not None else self.selection
            elif alt and self.selection is not None:
                new = self.selection.combined(found, subtract=True) if found is not None else self.selection
            else:
                new = found
            self._commit_selection("Magic Wand", new)
        elif self.tool == "move":
            self._drag = ("move", (x, y))
            self._offset = (0.0, 0.0)
        self.changed.emit()

    def move(self, x: float, y: float, pressure: float = 1.0) -> None:
        if self.transforming and self._drag is not None:
            self._move_transform(x, y)
        elif self._stroke is not None:
            self._stroke.append(Sample(x, y, pressure))
        elif self._drag is not None and self._drag[0] == "move":
            self._offset = (x - self._drag[1][0], y - self._drag[1][1])
        else:
            return
        self.changed.emit()

    def release(self, x: float, y: float, pressure: float = 1.0) -> None:
        if self.transforming:
            self._drag = None
            self.changed.emit()
            return
        if self._stroke is not None:
            self._stroke.append(Sample(x, y, pressure))
            samples, self._stroke = self._stroke, None
            area = stroke_area(samples, self.size, use_pressure=self.use_pressure)
            if self.tool == "brush":
                if self.color is None:
                    self.message.emit("Pick a color first (Alt+click a color of the layer)")
                else:
                    self._emit(self.layer.paint(area, self.color), "Brush")
            else:
                self._emit(self.layer.erase(area), "Eraser")
        elif self._drag is not None and self._drag[0] == "move":
            dx, dy = x - self._drag[1][0], y - self._drag[1][1]
            self._drag, self._offset = None, (0.0, 0.0)
            if math.hypot(dx, dy) > 1e-6:
                self._apply_matrix(Matrix.translate(dx, dy), "Move")
        self.changed.emit()

    def _emit(self, edit, label: str) -> None:
        for note in edit.notes:
            self.message.emit(note)
        if not edit.empty:
            self.edit_ready.emit(edit, label)

    def _apply_matrix(self, m: Matrix, label: str) -> None:
        edit = self.layer.transform(self.selection, m)
        moved = None if self.selection is None else Selection(transform_area(self.selection.area, m),
                                                              transform_area(self.selection.lines, m))
        self._emit(edit, label)
        if self.selection is not None and not edit.empty:
            self._set_selection(moved)

    # ------------------------------------------------------------ keys

    def delete_selection(self) -> None:
        if self.layer is not None and self.selection is not None:
            self._emit(self.layer.delete(self.selection), "Delete")

    def deselect(self) -> None:
        self._commit_selection("Deselect", None)

    # ------------------------------------------------------------ Ctrl+T

    def _target_area(self) -> Area:
        if self.selection is not None:
            return union(self.selection.area, self.selection.lines)
        out = []
        for area in (self.layer.visible_areas().values() if self.layer is not None else []):
            out = union(out, area)
        return out

    def begin_transform(self) -> None:
        if self.layer is None:
            return
        box = bounds_px(self._target_area())
        if box is None:
            return
        self.transforming, self._transform, self._box, self._drag = True, Matrix(), box, None
        self.changed.emit()

    def _corners(self):
        x0, x1, y0, y1 = self._box
        return [self._transform.apply(Point(x, y)) for x, y in ((x0, y0), (x1, y0), (x1, y1), (x0, y1))]

    def _press_transform(self, x: float, y: float) -> None:
        x0, x1, y0, y1 = self._box
        center = self._transform.apply(Point((x0 + x1) / 2, (y0 + y1) / 2))
        near = [c for c in self._corners() if math.hypot(c.x - x, c.y - y) <= self.handle_radius]
        inverse = self._transform.inverse().apply(Point(x, y))
        if near:
            mode = "scale"
        elif x0 <= inverse.x <= x1 and y0 <= inverse.y <= y1:
            mode = "move"
        else:
            mode = "rotate"
        self._drag = (mode, (x, y), self._transform, center)

    def _move_transform(self, x: float, y: float) -> None:
        mode, (sx, sy), start, c = self._drag
        if mode == "move":
            self._transform = Matrix.translate(x - sx, y - sy) @ start
        elif mode == "scale":
            d0 = math.hypot(sx - c.x, sy - c.y)
            k = math.hypot(x - c.x, y - c.y) / d0 if d0 > 1e-9 else 1.0
            self._transform = Matrix.translate(c.x, c.y) @ Matrix.scale(k, k) @ Matrix.translate(-c.x, -c.y) @ start
        else:
            a = math.atan2(y - c.y, x - c.x) - math.atan2(sy - c.y, sx - c.x)
            rot = Matrix(math.cos(a), math.sin(a), -math.sin(a), math.cos(a), 0, 0)
            self._transform = Matrix.translate(c.x, c.y) @ rot @ Matrix.translate(-c.x, -c.y) @ start

    def commit_transform(self) -> None:
        if not self.transforming:
            return
        m = self._transform
        self.transforming, self._drag, self._box = False, None, None
        if m != Matrix():
            self._apply_matrix(m, "Free Transform")
        self.changed.emit()

    def cancel_transform(self) -> None:
        if self.transforming:
            self.transforming, self._drag, self._box = False, None, None
            self.changed.emit()

    # ------------------------------------------------------------ overlay

    def paint_overlay(self, p: QPainter, view: Matrix) -> None:
        p.save()
        if self._stroke:
            pts = [view.apply(Point(s.x, s.y)) for s in self._stroke]
            scale = math.hypot(view.a, view.b)
            for a, b, s in zip(pts, pts[1:], self._stroke[1:]):
                width = stroke_width(self.size, s.pressure, self.use_pressure) * scale
                p.setPen(QPen(QColor(90, 160, 255, 200), max(1.0, width), Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
                p.drawLine(QPointF(a.x, a.y), QPointF(b.x, b.y))
        if self.selection is not None:
            shift = Matrix.translate(*self._offset) if self._drag and self._drag[0] == "move" else Matrix()
            path = area_path(union(self.selection.area, self.selection.lines), view @ shift)
            p.setBrush(QColor(60, 140, 255, 70))
            p.setPen(QPen(QColor(255, 255, 255), 1, Qt.PenStyle.DashLine))
            p.drawPath(path)
        if self.transforming and self._box is not None:
            corners = [view.apply(c) for c in self._corners()]
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(QColor(255, 255, 255), 1))
            for a, b in zip(corners, corners[1:] + corners[:1]):
                p.drawLine(QPointF(a.x, a.y), QPointF(b.x, b.y))
            p.setBrush(QColor(255, 255, 255))
            for c in corners:
                p.drawRect(int(c.x - HANDLE_PX / 2), int(c.y - HANDLE_PX / 2), int(HANDLE_PX), int(HANDLE_PX))
        p.restore()
