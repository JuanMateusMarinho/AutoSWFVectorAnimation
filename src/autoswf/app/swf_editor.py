"""The Open SWF workspace (added 2026-10-18 by the user): any AQW item SWF shown the way AQW splits it — parts, and
under each part its sub-pieces with thumbnails; unchecking a sub-piece removes it (a surgical edit: everything else
stays byte for byte); the result previews on the AQW body (armors, helms) and exports as a validated SWF."""
import math
import os
from pathlib import Path

from PySide6.QtCore import QEvent, QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QImage, QPainter, QPen, QPixmap, QUndoCommand, QUndoStack
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QFileDialog, QFormLayout, QHBoxLayout, QHeaderView, QLabel,
                               QMessageBox,
                               QLineEdit, QPushButton, QSplitter, QTextEdit, QTreeWidget, QTreeWidgetItem,
                               QVBoxLayout, QWidget)

from autoswf.app.edit_layers import EditLayersPanel, swf_layer_rows
from autoswf.app.edit_tools import EditableCanvas, EditTools
from autoswf.app.frame_strip import FrameStrip
from autoswf.aqw.assets import AqwCache
from autoswf.aqw.contract import check_link, client_class_names
from autoswf.aqw.validate import validate_item_swf
from autoswf.edit.swf_source import UneditableDrawing, drawing_uses, shape_def_of, swf_layer
from autoswf.items.edit import edit_swf
from autoswf.items.item_edits import ItemEdits
from autoswf.items.layers import NewLayer
from autoswf.items.structure import ItemStructure, PieceRef, read_structure
from autoswf.items.thumbs import piece_image
from autoswf.model.geometry import Matrix, Point
from autoswf.render.colors import PlayerColors
from autoswf.render.display import ClipInstance, ScriptContext, instantiate, run_pending_actions
from autoswf.render.painter import Renderer, object_bounds
from autoswf.swf.decode import MovieData

THUMB = 40
BACKGROUND = QColor(58, 58, 62)
PATH_ROLE = Qt.ItemDataRole.UserRole
KINDS_ON_HEAD = ("Helm", "Weapon", "Cape", "Pet")
OVERWRITE = "The output would overwrite the file being edited; choose another name"


class _EditCommand(QUndoCommand):
    """One change of the item: its ItemEdits before and after."""

    def __init__(self, editor: "SwfEditor", label: str, before: ItemEdits, after: ItemEdits):
        super().__init__(label)
        self.editor, self.before, self.after = editor, before, after

    def redo(self) -> None:
        self.editor.apply_edits(self.after.copy())

    def undo(self) -> None:
        self.editor.apply_edits(self.before.copy())


class _ItemCanvas(EditableCanvas, QWidget):
    """The selected part of the edited file, fitted (or zoomed and panned), with the selected piece outlined; the
    editor's tools work on it."""

    def __init__(self, editor: "SwfEditor"):
        super().__init__()
        self.editor = editor
        self.setMinimumSize(320, 280)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.renderer = Renderer()
        self.colors = PlayerColors()
        self.zoom: float | None = None           # None = fitted
        self._pan = QPointF(0, 0)
        self._box = None                         # the part's bounds the view is fitted to
        self._view: Matrix | None = None
        self._tools_init()

    # ------------------------------------------------------------ view

    def fit(self) -> None:
        self.zoom, self._pan, self._box = None, QPointF(0, 0), None
        self.update()

    def zoom_100(self) -> None:
        self.zoom = 1.0
        self.update()

    def pan_by(self, dx: float, dy: float) -> None:
        self._pan += QPointF(dx, dy)
        self.update()

    def view_for(self, width: int, height: int, bounds) -> Matrix:
        if self._box is None:
            self._box = bounds
        x0, x1, y0, y1 = self._box
        fitted = min((width - 40) / max(x1 - x0, 1e-3), (height - 40) / max(y1 - y0, 1e-3))
        z = self.zoom if self.zoom is not None else fitted
        return (Matrix.translate(width / 2 + self._pan.x(), height / 2 + self._pan.y()) @ Matrix.scale(z, z)
                @ Matrix.translate(-(x0 + x1) / 2, -(y0 + y1) / 2))

    def layer_matrix(self) -> Matrix:
        if self._view is None:
            self.render_image(max(self.width(), 1), max(self.height(), 1))
        return self._view or Matrix()

    # ------------------------------------------------------------ events

    def mousePressEvent(self, event) -> None:
        self.setFocus()
        if event.button() == Qt.MouseButton.MiddleButton:
            self._pan_drag = event.position()
            return
        self.tool_mouse(event, "press")

    def mouseMoveEvent(self, event) -> None:
        self.tool_mouse(event, "move")

    def mouseReleaseEvent(self, event) -> None:
        self.tool_mouse(event, "release")

    def wheelEvent(self, event) -> None:
        steps = (event.angleDelta().y() or event.angleDelta().x()) / 120
        current = self.zoom if self.zoom is not None else math.hypot(self.layer_matrix().a, self.layer_matrix().b)
        self.zoom = max(0.05, min(64.0, current * math.pow(1.15, steps)))
        self.update()

    def keyPressEvent(self, event) -> None:
        if not self.tool_key(event):
            super().keyPressEvent(event)

    def keyReleaseEvent(self, event) -> None:
        if not self.tool_key_release(event):
            super().keyReleaseEvent(event)

    def event(self, event) -> bool:
        if event.type() == QEvent.Type.ShortcutOverride and self.tool_shortcut_override(event):
            return True
        return super().event(event)

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.paint(p, self.width(), self.height())
        p.end()

    def render_image(self, width: int, height: int) -> QImage:
        image = QImage(width, height, QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(0)
        p = QPainter(image)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.paint(p, width, height)
        p.end()
        return image

    def paint(self, p: QPainter, width: int, height: int) -> None:
        p.fillRect(0, 0, width, height, BACKGROUND)
        e = self.editor
        part = e.current_part()
        if part is None or e.edited_movie is None:
            return
        obj = instantiate(e.edited_movie, part.char_id) if part.char_id else None
        if part.char_id == 0:
            obj = ClipInstance(e.edited_movie, 0, sprite=e.edited_movie.root)
            obj._reconcile(0)
        if obj is None:
            return
        ctx = ScriptContext(self.colors)
        if e.frame and isinstance(obj, ClipInstance):
            obj.driven = True                       # shown on that frame: its own frame scripts do not move it
            obj.goto(e.frame)
        run_pending_actions(obj, ctx)
        e.prepare_display(obj, ctx)
        bounds = object_bounds(obj, Matrix())
        if bounds is None and self._box is None:
            p.setPen(QColor(200, 200, 200))
            p.drawText(QRectF(0, 0, width, height), Qt.AlignmentFlag.AlignCenter,
                       e.canvas_message() or "This part is empty")
            return
        view = self.view_for(width, height, bounds)
        self._view = view
        scale = math.hypot(view.a, view.b)
        self.renderer.draw(p, obj, view, self.colors, filter_scale=scale)
        if self.edit_tools is not None:
            self.edit_tools.paint_overlay(p, view)
        selected = e.selected_path
        if selected is None or "/" not in selected:
            return
        target, parent = obj, view
        for depth in [int(d.split(".")[0]) for d in selected.split("/")[1:]]:
            child = target.child_at_depth(depth) if hasattr(target, "child_at_depth") else None
            if child is None:
                return
            parent, target = parent @ target.matrix, child
        box = object_bounds(target, parent)
        if box is not None:
            p.setPen(QPen(QColor(255, 210, 60), 2, Qt.PenStyle.DashLine))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRect(QRectF(QPointF(box[0] - 2, box[2] - 2), QPointF(box[1] + 2, box[3] + 2)))


class SwfEditor(QWidget):
    def __init__(self, cache: AqwCache, parent=None):
        super().__init__(parent)
        self.cache = cache
        self.path: Path | None = None
        self.original = b""
        self.edited = b""
        self.edited_movie: MovieData | None = None
        self.movie: MovieData | None = None
        self.structure: ItemStructure | None = None
        self.edits = ItemEdits()
        self._exported = ItemEdits()                    # the edits of the last export
        self._structure_key = self.edits.structure_key()
        self._stale = False                             # the edited bytes lag behind drawings shown by override
        self._shared_ok: set[int] = set()               # shared drawings the user agreed to edit everywhere
        self.layer_frame = 0                            # the frame of the selected piece's own timeline
        self.hidden: set[str] = set()                   # pieces hidden in the editor only (the eye)
        self._new_layer_part = None                     # "+ New layer" waits for its first stroke here
        self.selected_path: str | None = None
        self.frame = 0
        self.undo_stack = QUndoStack(self)
        self.edit_tools = EditTools(self)
        self.edit_tools.undo_stack = self.undo_stack
        self.edit_tools.edit_ready.connect(self._on_layer_edit)
        self.edit_tools.message.connect(lambda text: self.message.setText(text))
        self.edit_tools.changed.connect(lambda: self.canvas.update())
        self._items: dict[str, QTreeWidgetItem] = {}
        self._preview = None
        self._thumbs: dict[int, QIcon] = {}

        self.tree = QTreeWidget()
        self.tree.setColumnCount(5)
        self.tree.setHeaderLabels(["Piece", "Kind", "Color", "Note", "Shown"])
        self.tree.setIconSize(QPixmap(THUMB, THUMB).size())
        self.tree.itemChanged.connect(self._on_item_changed)
        self.tree.currentItemChanged.connect(self._on_current)
        self.tree.itemExpanded.connect(self._load_thumbs)
        self.tree.header().setStretchLastSection(False)
        self.tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.tree.header().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.canvas = _ItemCanvas(self)
        self.canvas.edit_tools = self.edit_tools
        self.frame_strip = FrameStrip()
        self.frame_strip.frame_changed.connect(self._on_frame)
        self.layers_panel = EditLayersPanel(with_rows=False)
        self.layers_panel.part_selected.connect(self.select)
        self.layers_panel.new_layer_requested.connect(self.new_layer)
        self.layers_panel.trace_requested.connect(self.trace_png)
        self.layers_panel.color_requested.connect(self.set_layer_color)
        self.layers_panel.delete_requested.connect(self.delete_layer)
        self.title = QLabel()
        self.title.setStyleSheet("font-weight: bold;")
        self.kind_box = QComboBox()
        self.kind_box.addItems(KINDS_ON_HEAD)
        self.kind_box.setToolTip("What this one-class item is (it changes only how the preview shows it)")
        self.preview_button = QPushButton("Preview on AQW body")
        self.preview_button.clicked.connect(self.preview)
        self.export_button = QPushButton("Export SWF…")
        self.export_button.clicked.connect(lambda: self.export_dialog().exec())
        self.info = QLabel()
        self.info.setWordWrap(True)
        self.info.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.message = QLabel()
        self.message.setWordWrap(True)

        bar = QHBoxLayout()
        bar.addWidget(self.title, 1)
        self.kind_label = QLabel("This item is a:")
        bar.addWidget(self.kind_label)
        bar.addWidget(self.kind_box)
        bar.addWidget(self.preview_button)
        bar.addWidget(self.export_button)
        center = QWidget()
        column = QVBoxLayout(center)
        column.setContentsMargins(0, 0, 0, 0)
        column.addLayout(bar)
        column.addWidget(self.canvas, 1)
        column.addWidget(self.frame_strip)
        column.addWidget(self.message)
        self.right = QWidget()
        right = QVBoxLayout(self.right)
        title = QLabel("Piece")
        title.setStyleSheet("font-weight: bold;")
        right.addWidget(title)
        right.addWidget(self.info, 1)
        self.animations_view = QTreeWidget()
        self.animations_view.setColumnCount(3)
        self.animations_view.setHeaderLabels(["Game label", "Armor animation", "Blocks the body"])
        self.animations_view.setToolTip("This armor plays its own animations: each game label (skills, walk, emotes…) "
                                        "starts one of them; the preview plays them as the game does")
        self.animations_view.hide()
        right.addWidget(self.animations_view, 2)
        self._right_layout = right
        self.animated = None
        split = QSplitter(Qt.Orientation.Horizontal)
        left = QWidget()
        left_column = QVBoxLayout(left)
        left_column.setContentsMargins(0, 0, 0, 0)
        left_column.addWidget(self.layers_panel)
        left_column.addWidget(self.tree, 1)
        self.layers_panel.layout().removeWidget(self.layers_panel.tree)
        split.addWidget(left)
        split.addWidget(center)
        split.addWidget(self.right)
        split.setSizes([380, 660, 260])
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(split)

    # ------------------------------------------------------------ opening

    def open(self, path) -> str | None:
        path = Path(path)
        try:
            data = path.read_bytes()
            movie = MovieData(data)
            structure = read_structure(movie, path.name)
        except OSError as e:
            return "Could not read %s: %s" % (path, e.strerror or e)
        except ValueError as e:
            return str(e)
        self.path, self.original, self.movie, self.structure = path, data, movie, structure
        self.edits, self._exported, self.selected_path, self.frame = ItemEdits(), ItemEdits(), None, 0
        self.hidden, self._new_layer_part = set(), None
        self._structure_key, self._stale, self._shared_ok, self.layer_frame = self.edits.structure_key(), False, set(), 0
        self.undo_stack.clear()
        self._thumbs = {}
        self._set_edited(data)
        self.kind_box.setVisible(structure.kind == "item")
        self.kind_label.setVisible(structure.kind == "item")
        self._fill_animations()
        self.title.setText("%s — %s%s" % (path.name, structure.kind, " %s" % structure.link if structure.link else ""))
        self._fill_tree()
        if structure.parts:
            self.select(structure.parts[0].key)
        if structure.notes:
            self.message.setText(" ".join(structure.notes))
        return None

    def _fill_tree(self) -> None:
        self.tree.blockSignals(True)
        self.tree.clear()
        self._items = {}
        for part in self.structure.parts:
            top = QTreeWidgetItem(self.tree, [part.label, part.class_name or ""])
            top.setData(0, PATH_ROLE, part.key)
            self._items[part.key] = top
            self._add_pieces(top, part.pieces)
        self.tree.blockSignals(False)

    def _add_pieces(self, parent: QTreeWidgetItem, pieces) -> None:
        for piece in pieces:
            from autoswf.app.edit_layers import color_tag, piece_note
            item = QTreeWidgetItem(parent, [piece.label, piece.kind + (" (changes)" if piece.changes else ""),
                                            color_tag(piece.color[0] if piece.color else None) or "",
                                            piece_note(self.movie, piece) or "", ""])
            item.setData(0, PATH_ROLE, piece.path)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(0, Qt.CheckState.Unchecked if piece.ref in self.removed else Qt.CheckState.Checked)
            item.setCheckState(4, Qt.CheckState.Unchecked if piece.path in self.hidden else Qt.CheckState.Checked)
            self._items[piece.path] = item
            self._add_pieces(item, piece.children)

    def _fill_animations(self) -> None:
        from autoswf.items.animated import read_animated_armor
        self.animated = read_animated_armor(self.movie) if self.structure.kind == "armor" else None
        self.animations_view.clear()
        self.animations_view.setHidden(self.animated is None)
        if self.animated is None:
            return
        own = QTreeWidgetItem(self.animations_view, ["Armor's own animations", "", ""])
        starts = sorted(self.animated.labels.items(), key=lambda kv: kv[1])
        sprite = self.movie.character(self.animated.char_id)
        for k, (label, frame) in enumerate(starts):
            end = starts[k + 1][1] if k + 1 < len(starts) else sprite.frame_count
            QTreeWidgetItem(own, [label, "frames %d-%d" % (frame + 1, end), ""])
        table = QTreeWidgetItem(self.animations_view, ["Game label → armor animation", "", ""])
        for game, armor, block in self.animated.table():
            QTreeWidgetItem(table, [game, armor or "?", "yes" if block else ""])
        self.animations_view.expandAll()
        for note in self.animated.notes:
            QTreeWidgetItem(self.animations_view, [note, "", ""])

    def animation_rows(self) -> list[tuple[str, str, str]]:
        """(game label, armor animation, "yes" when it blocks the body) as the Animations panel lists them."""
        if self.animated is None:
            return []
        return [(game, armor or "?", "yes" if block else "") for game, armor, block in self.animated.table()]

    def _load_thumbs(self, item: QTreeWidgetItem) -> None:
        for k in range(item.childCount()):
            child = item.child(k)
            path = child.data(0, PATH_ROLE)
            if path is None or not child.icon(0).isNull():
                continue
            char_id = self.structure.piece(path).char_id
            if char_id not in self._thumbs:
                self._thumbs[char_id] = QIcon(QPixmap.fromImage(piece_image(self.movie, char_id, THUMB)))
            child.setIcon(0, self._thumbs[char_id])

    def tree_item(self, path: str) -> QTreeWidgetItem:
        return self._items[path]

    # ------------------------------------------------------------ selection and info

    def current_part(self):
        if self.structure is None:
            return None
        key = (self.selected_path or self.structure.parts[0].key).split("/")[0]
        return next((p for p in self.structure.parts if p.key == key), None)

    def canvas_message(self) -> str:
        """What the canvas says instead of drawing the current part ("" when there is something to draw)."""
        part = self.current_part()
        if part is None or part.pieces:
            return ""
        if self.animated is not None:
            return "This part is empty: the armor draws its whole character in its Head"
        return "This part is empty"

    @property
    def removed(self) -> set[PieceRef]:
        return set(self.edits.removed)

    def select(self, path: str) -> None:
        old_part = self.current_part()
        self.selected_path = path
        top = "/".join(path.split("/")[:2]) if path and "/" in path else None
        self.frame = self.structure.piece(top).frame if top else 0
        item = self._items.get(path)
        if item is not None and self.tree.currentItem() is not item:
            self.tree.blockSignals(True)
            self.tree.setCurrentItem(item)
            self.tree.blockSignals(False)
        self._refresh_info()
        if self.current_part() is not old_part:
            self.canvas.fit()
        self.layer_frame = 0
        self.layers_panel.current = path
        part = self.current_part()
        if part is not None:
            self.layers_panel.set_parts([(p.key, p.label) for p in self.structure.parts], part.key)
        self.refresh_layer()
        self.update_strip()
        self.canvas.update()

    # ------------------------------------------------------------ layers (Plan 7)

    def layer_rows(self):
        part = self.current_part()
        return swf_layer_rows(self.movie, self.structure, part.key, self.hidden) if part is not None else []

    def _strip_target(self):
        """("layer", sprite) when the selected piece is a clip with its own frames, else ("part", sprite)."""
        from autoswf.swf.decode import SpriteDef
        path = self.selected_path
        if path and "/" in path:
            piece = self.structure.piece(path)
            sprite = self.movie.character(piece.char_id) if piece.kind == "clip" else None
            if isinstance(sprite, SpriteDef) and sprite.frame_count > 1:
                return "layer", sprite
        part = self.current_part()
        sprite = self.movie.character(part.char_id) if part is not None and part.char_id else None
        return "part", sprite if isinstance(sprite, SpriteDef) else None

    def update_strip(self) -> None:
        from autoswf.edit.swf_source import drawing_frames
        mode, sprite = self._strip_target()
        if sprite is None:
            self.frame_strip.set_frames(1, 0)
            return
        current = self.layer_frame if mode == "layer" else self.frame
        self.frame_strip.set_frames(sprite.frame_count, current, sprite.labels)
        marks = []
        layer = self.edit_tools.layer
        if mode == "layer" and layer is not None and layer.drawings:
            try:
                marks = drawing_frames(self.edited_movie, self.structure, self.selected_path,
                                       int(layer.drawings[0].key.split("#")[0]))
            except (ValueError, KeyError):
                marks = []
        self.frame_strip.set_marks(marks)

    def _on_frame(self, frame: int) -> None:
        mode, _ = self._strip_target()
        if mode == "layer":
            self.layer_frame = frame
        else:
            self.frame = frame
        self.refresh_layer()
        self.update_strip()
        self.canvas.update()

    def _child(self, obj, path: str):
        for comp in path.split("/")[1:]:
            if not hasattr(obj, "child_at_depth"):
                return None
            obj = obj.child_at_depth(int(comp.split(".")[0]))
            if obj is None:
                return None
        return obj

    def prepare_display(self, obj, ctx) -> None:
        """The canvas's part as the editor shows it: the selected clip at its own frame, hidden pieces hidden."""
        path = self.selected_path
        if self.layer_frame and path and "/" in path:
            target = self._child(obj, path)
            if isinstance(target, ClipInstance):
                target.driven = True
                target.goto(self.layer_frame)
                run_pending_actions(obj, ctx)
        part = self.current_part()
        for hidden in self.hidden:
            if part is not None and hidden.split("/")[0] == part.key:
                target = self._child(obj, hidden)
                if target is not None:
                    target.visible = False

    def set_hidden(self, path: str, hidden: bool) -> None:
        (self.hidden.add if hidden else self.hidden.discard)(path)
        item = self._items.get(path)
        if item is not None:
            self.tree.blockSignals(True)
            item.setCheckState(4, Qt.CheckState.Unchecked if hidden else Qt.CheckState.Checked)
            self.tree.blockSignals(False)
        self.canvas.update()

    def delete_layer(self, path: str) -> None:
        if path and "/" in path:
            self.set_removed(self.structure.piece(path).ref, True)

    def set_layer_color(self, path: str, location: str) -> None:
        """The AQW color of every colorable clip in the layer (their shades kept)."""
        if location == "None":
            self.message.setText("An AQW color cannot be taken off a clip yet; pick another color")
            return
        targets = [p for p in self.structure.walk() if (p.path == path or p.path.startswith(path + "/"))
                   and p.color and p.class_name]
        if not targets:
            self.message.setText("This layer has no AQW-colored clip")
            return
        after = self.edits.copy()
        for p in targets:
            after.rebinds[p.class_name] = (location, p.color[1])
        self.push_edit("Color", after)

    def new_layer(self) -> None:
        from autoswf.edit.layer import Drawing, EditLayer
        from autoswf.model.shape import Shape
        part = self.current_part()
        if part is None:
            return
        self._new_layer_part = part
        self.edit_tools.set_layer(EditLayer("New layer", [Drawing("new", Shape([], []), Matrix(), False)], [], None, 1.0))
        self.message.setText("New layer: paint on it (pick a color first with New color… or Alt+click)")

    def ask_png_path(self):
        path, _ = QFileDialog.getOpenFileName(self, "Trace PNG", "", "PNG images (*.png)")
        return path or None

    def ask_trace_target(self, layer_name: str) -> str | None:
        box = QMessageBox(QMessageBox.Icon.Question, "Trace PNG", "Use the PNG to replace this layer, or as a new one?",
                          parent=self)
        replace = box.addButton('Replace "%s"' % layer_name, QMessageBox.ButtonRole.AcceptRole)
        new = box.addButton("New layer", QMessageBox.ButtonRole.ActionRole)
        box.addButton(QMessageBox.StandardButton.Cancel)
        box.exec()
        return {id(replace): "replace", id(new): "new"}.get(id(box.clickedButton()))

    def place_png(self, size, layer_bounds):
        from autoswf.edit.trace_png import placement
        return placement(size, target_bounds=layer_bounds)

    def trace_png(self) -> None:
        from autoswf.edit.regions import bounds_px, union
        from autoswf.edit.trace_png import new_layer_tones, read_png, replace_layer, trace_png
        path = self.ask_png_path()
        if not path:
            return
        try:
            traced = trace_png(read_png(path))
        except (OSError, ValueError) as e:
            self.message.setText(str(e))
            return
        layer = self.edit_tools.layer
        name = layer.name.rpartition("/")[2] if layer is not None else "this part"
        target = self.ask_trace_target(name)
        if target is None:
            return
        everything = []
        for area in (layer.visible_areas().values() if layer is not None else []):
            everything = union(everything, area)
        matrix = self.place_png(traced.size, bounds_px(everything))
        if target == "replace" and layer is not None:
            edit = replace_layer(layer, traced, matrix)
            for note in edit.notes:
                self.message.setText(note)
            if not edit.empty:
                self._on_layer_edit(edit, "Trace PNG")
            return
        bound = [t for t in (layer.tones if layer is not None else []) if t.binding]
        after = self.edits.copy()
        after.layers.append(NewLayer(self.current_part().char_id, "Traced layer",
                                     new_layer_tones(traced, matrix, bound)))
        self.push_edit("Trace PNG", after)

    def refresh_layer(self, keep_selection: bool = False) -> None:
        """The selected piece (or part) as the tools' layer, from the file as edited."""
        path = self.selected_path or (self.structure.parts[0].key if self.structure and self.structure.parts else None)
        layer = None
        if path is not None and self.edited_movie is not None:
            try:
                layer = swf_layer(self.edited_movie, self.structure, path, self.layer_frame, self.canvas.colors)
            except UneditableDrawing as e:
                self.message.setText(str(e))
            except (ValueError, KeyError):
                layer = None
        self.edit_tools.set_layer(layer, keep_selection=keep_selection)

    def _on_current(self, current, previous) -> None:
        if current is not None:
            self.select(current.data(0, PATH_ROLE))

    def _refresh_info(self) -> None:
        path = self.selected_path
        if path is None or "/" not in path:
            part = self.current_part()
            self.info.setText("%s\nClass: %s\n%d sub-pieces" % (part.label, part.class_name or "(root timeline)",
                                                               len(part.pieces)) if part else "")
            return
        piece = self.structure.piece(path)
        lines = ["%s" % piece.label, "Kind: %s" % piece.kind, "Character: %d" % piece.char_id,
                 "Placed on character %d at depth %d" % (piece.ref.sprite, piece.ref.depth)]
        if piece.class_name:
            lines.append("Class: %s" % piece.class_name)
        if piece.color:
            lines.append("Follows the player's %s color (%s)" % piece.color)
        if piece.changes:
            lines.append("Other characters take this place later in the timeline; removing it removes them too.")
        siblings = piece.path.rpartition("/")[0]
        instances = [p for p in self.structure.instances(piece.ref)
                     if p == piece.path or p.rpartition("/")[0] != siblings]
        if len(instances) > 1:
            labels = list(dict.fromkeys(self.structure.part_of(p).label for p in instances))
            lines.append("Also used in: %s — this piece sits inside a symbol used in %d places; removing it removes it "
                         "from all of them." % (", ".join(labels), len(instances)))
        if piece.instance_name:
            lines.append("This piece is named '%s'; the game may look for it by that name. Removing it may break the "
                         "item in the game." % piece.instance_name)
        self.info.setText("\n".join(lines))

    # ------------------------------------------------------------ removing

    def _on_item_changed(self, item: QTreeWidgetItem, column: int) -> None:
        path = item.data(0, PATH_ROLE)
        if path is None or "/" not in path:
            return
        if column == 4:
            self.set_hidden(path, item.checkState(4) == Qt.CheckState.Unchecked)
            return
        ref = self.structure.piece(path).ref
        removed = item.checkState(0) == Qt.CheckState.Unchecked
        if removed != (ref in self.removed):
            self.set_removed(ref, removed)

    def set_removed(self, ref: PieceRef, removed: bool) -> None:
        """Remove (or restore) a placement: one undo step; every instance of it in the tree follows."""
        if removed == (ref in self.removed):
            return
        after = self.edits.copy()
        after.removed = [r for r in after.removed if r != ref] + ([ref] if removed else [])
        self.push_edit("Remove piece" if removed else "Restore piece", after)

    def push_edit(self, label: str, after: ItemEdits) -> None:
        self.undo_stack.push(_EditCommand(self, label, self.edits.copy(), after))

    def apply_edits(self, edits: ItemEdits) -> None:
        """Show these edits: drawings at once through the movie's overrides, structure changes by rewriting the file."""
        previous, self.edits = self.edits, edits
        if edits.structure_key() != self._structure_key:
            grew = (edits.layers, edits.rebinds) != (previous.layers, previous.rebinds)
            self._structure_key = edits.structure_key()
            self._set_edited(self.edits.apply(self.original))
            self._stale = False
            if grew:
                shown = ItemEdits([], dict(edits.shapes), list(edits.layers), dict(edits.rebinds))
                self.structure = read_structure(MovieData(shown.apply(self.original)), self.path.name if self.path else "")
                selected = self.selected_path
                self._fill_tree()
                if selected and (selected in self._items):
                    item = self._items[selected]
                    self.tree.blockSignals(True)
                    self.tree.setCurrentItem(item)
                    self.tree.blockSignals(False)
        else:
            for cid in set(previous.shapes) | set(edits.shapes):
                shape = edits.shapes.get(cid)
                if shape is previous.shapes.get(cid):
                    continue
                original = self.movie.character(cid)
                self.edited_movie.override(cid, shape_def_of(shape, cid) if shape is not None else original)
                self._stale = True
        self.tree.blockSignals(True)
        for path, item in self._items.items():
            if "/" in path:
                ref = self.structure.piece(path).ref
                item.setCheckState(0, Qt.CheckState.Unchecked if ref in self.removed else Qt.CheckState.Checked)
        self.tree.blockSignals(False)
        n = len(self.edits.removed)
        self.message.setText("%d piece%s removed" % (n, "" if n == 1 else "s") if n else "")
        self.refresh_layer(keep_selection=True)
        self.canvas.update()
        if self._preview is not None and self._preview.isVisible():
            self.preview()

    def current_data(self) -> bytes:
        """The file with every edit, written out (drawings shown by override are written here)."""
        if self._stale:
            self._set_edited(self.edits.apply(self.original))
            self._stale = False
            self.refresh_layer(keep_selection=True)
        return self.edited

    def ask_shared_edit(self, places: list[str]) -> bool:
        labels = list(dict.fromkeys(self.structure.part_of(p).label + " (" + p + ")" for p in places))
        answer = QMessageBox.question(self, "Shared drawing", "This drawing also shows in:\n%s\n\nEdit it everywhere?"
                                      % "\n".join(labels[:8]))
        return answer == QMessageBox.StandardButton.Yes

    def _on_layer_edit(self, edit, label: str) -> None:
        path = self.selected_path or self.structure.parts[0].key
        if "new" in edit.shapes and self._new_layer_part is not None:
            part, self._new_layer_part = self._new_layer_part, None
            after = self.edits.copy()
            after.layers.append(NewLayer(part.char_id, "New layer", [(edit.shapes["new"], None)]))
            self.push_edit("New layer", after)
            newest = part_pieces = next(p for p in self.structure.parts if p.key == part.key).pieces
            if part_pieces:
                self.select(newest[-1].path)
            return
        shapes = {}
        for key, shape in edit.shapes.items():
            cid = int(key.split("#")[0])
            if cid not in self._shared_ok:
                places = drawing_uses(self.edited_movie, self.structure, path, cid)
                if places and not self.ask_shared_edit(places):
                    return
                self._shared_ok.add(cid)
            shapes[cid] = shape
        after = self.edits.copy()
        after.shapes.update(shapes)
        self.push_edit(label, after)

    def _set_edited(self, data: bytes) -> None:
        self.edited = data
        self.edited_movie = MovieData(data)

    # ------------------------------------------------------------ preview and export

    def preview(self):
        """Armors (and helms) on the AQW body; other items play on their own in the canvas."""
        from autoswf.preview.scene import MissingReferenceFiles, PreviewScene
        from autoswf.preview.window import PreviewWindow
        kind = self.structure.kind if self.structure.kind != "item" else self.kind_box.currentText().lower()
        if kind not in ("armor", "helm"):
            self.message.setText("The body preview shows armors and helms; this %s plays here on its own." % kind)
            return None
        helm_link = self.structure.link if kind == "helm" else None
        if helm_link is None and kind == "helm":
            helm_link = self.structure.parts[0].class_name
        if self._preview is None or self._preview.scene is None:
            try:
                if kind == "armor":
                    scene = PreviewScene.from_cache(self.cache, None, armor_data=self.current_data())
                else:
                    scene = PreviewScene.from_cache(self.cache, self.current_data(), link=helm_link)
                problem = None
            except (MissingReferenceFiles, ValueError) as e:
                scene, problem = None, str(e)
            self._preview = PreviewWindow(scene, cache=self.cache)
            if problem:
                self._preview.empty_message = problem
        elif kind == "armor":
            self._preview.set_armor_data(self.current_data())
        else:
            self._preview.set_helm_data(self.current_data(), helm_link)
        self._preview.resize(1000, 700)
        self._preview.show()
        return self._preview

    @property
    def dirty(self) -> bool:
        """Edits that were not exported that way yet."""
        e, x = self.edits, self._exported
        same = (set(e.removed) == set(x.removed) and e.shapes == x.shapes and e.layers == x.layers
                and e.rebinds == x.rebinds)
        return not e.empty and not same

    def export_dialog(self) -> "ItemExportDialog":
        return ItemExportDialog(self, self)


class ItemExportDialog(QDialog):
    def __init__(self, editor: SwfEditor, parent=None):
        super().__init__(parent)
        self.editor = editor
        self.setWindowTitle("Export SWF")
        self.setMinimumWidth(560)
        source = editor.path
        self.file_edit = QLineEdit(str(source.with_name(source.stem + "_edited.swf")))
        self.file_message = QLabel()
        browse = QPushButton("Browse…")
        browse.clicked.connect(self._browse)
        self.rename_box = QCheckBox("New link (a new item)")
        self.rename_box.setEnabled(editor.structure.link is not None)
        self.link_edit = QLineEdit(editor.structure.link or "")
        self.link_edit.setEnabled(False)
        self.link_message = QLabel()
        self.link_message.setWordWrap(True)
        self.keep_unused_box = QCheckBox("Keep shapes nothing uses any more")
        self.export_button = QPushButton("Export")
        close = QPushButton("Close")
        self.report = QTextEdit()
        self.report.setReadOnly(True)
        row = QHBoxLayout()
        row.addWidget(self.file_edit, 1)
        row.addWidget(browse)
        form = QFormLayout()
        form.addRow("File", row)
        form.addRow("", self.file_message)
        form.addRow("", self.rename_box)
        form.addRow("Link", self.link_edit)
        form.addRow("", self.link_message)
        form.addRow("", self.keep_unused_box)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(self.export_button)
        buttons.addWidget(close)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(self.report, 1)
        layout.addLayout(buttons)
        self._client = self._client_names()
        self.file_edit.textChanged.connect(self._check)
        self.link_edit.textChanged.connect(self._check)
        self.rename_box.toggled.connect(lambda on: (self.link_edit.setEnabled(on), self._check()))
        self.export_button.clicked.connect(self.export)
        close.clicked.connect(self.reject)
        self._check()

    def _client_names(self):
        client = self.editor.cache.client_path()
        if client is None:
            return ()
        try:
            return client_class_names(MovieData(client))
        except ValueError:
            return ()

    def _check(self) -> None:
        path = Path(self.file_edit.text().strip() or ".")
        file_problem = ""
        try:
            if path.resolve() == self.editor.path.resolve():
                file_problem = OVERWRITE
        except OSError:
            pass
        if not file_problem and path.suffix.lower() != ".swf":
            file_problem = "The output must be a .swf file"
        self.file_message.setText(file_problem)
        link_problem = ""
        if self.rename_box.isChecked():
            check = check_link(self.link_edit.text(), self._client)
            if check.error:
                link_problem = check.error
            elif check.link == self.editor.structure.link:
                link_problem = "The new link is the same as the old one"
            elif check.warning:
                link_problem = check.warning
        self.link_message.setText(link_problem)
        changes = not self.editor.edits.empty or self.rename_box.isChecked()
        self.export_button.setEnabled(not file_problem and not link_problem and changes)
        if not changes:
            self.file_message.setText(file_problem or "Uncheck a piece (or give a new link) to export.")

    def _browse(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Export SWF", self.file_edit.text(), "SWF files (*.swf)")
        if path:
            self.file_edit.setText(path)

    def export(self) -> None:
        e = self.editor
        out = Path(self.file_edit.text().strip())
        rename = self.link_edit.text().strip() if self.rename_box.isChecked() else None
        try:
            result = edit_swf(e.original, sorted(e.removed, key=lambda r: (r.sprite, r.depth)),
                              prune=not self.keep_unused_box.isChecked(), rename=rename,
                              replace_shapes=e.edits.shapes, add_layers=e.edits.layers, rebind=e.edits.rebinds)
        except ValueError as error:
            self.report.setPlainText(str(error))
            return
        except Exception as error:                  # a damaged file: say so, never lose the window
            self.report.setPlainText("Could not edit this file (%s: %s)" % (type(error).__name__, error))
            return
        tmp = out.with_name(out.name + ".part")
        try:
            out.parent.mkdir(parents=True, exist_ok=True)
            tmp.write_bytes(result.data)
            os.replace(tmp, out)
        except OSError as error:
            if tmp.exists():
                tmp.unlink()
            self.report.setPlainText("Could not write %s: %s" % (out, error.strerror or error))
            return
        e._exported = e.edits.copy()
        expected = [result.renamed.get(c, c) for c in e.structure.public_classes()]
        try:
            report = validate_item_swf(result.data, expected, e.original)
        except Exception as error:
            self.report.setPlainText("Wrote %s, but it could not be checked (%s: %s)"
                                     % (out.name, type(error).__name__, error))
            return
        n, k = result.removed_placements, len(result.removed_characters)
        lines = ["Wrote %s (%.1f KB, %d placement%s removed, %d unused shape%s dropped)%s"
                 % (out.name, len(result.data) / 1024, n, "" if n == 1 else "s", k, "" if k == 1 else "s",
                    " — valid" if report.ok else "")]
        lines += ["Problem: " + p for p in report.problems] + result.notes + report.notes
        self.report.setPlainText("\n".join(lines))
