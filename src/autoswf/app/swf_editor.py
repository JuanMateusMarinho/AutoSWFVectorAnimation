"""The Open SWF workspace (added 2026-10-18 by the user): any AQW item SWF shown the way AQW splits it — parts, and
under each part its sub-pieces with thumbnails; unchecking a sub-piece removes it (a surgical edit: everything else
stays byte for byte); the result previews on the AQW body (armors, helms) and exports as a validated SWF."""
import os
from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QImage, QPainter, QPen, QPixmap, QUndoCommand, QUndoStack
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QFileDialog, QFormLayout, QHBoxLayout, QHeaderView, QLabel,
                               QLineEdit, QPushButton, QSplitter, QTextEdit, QTreeWidget, QTreeWidgetItem,
                               QVBoxLayout, QWidget)

from autoswf.aqw.assets import AqwCache
from autoswf.aqw.contract import check_link, client_class_names
from autoswf.aqw.validate import validate_item_swf
from autoswf.items.edit import edit_swf
from autoswf.items.structure import ItemStructure, PieceRef, read_structure
from autoswf.items.thumbs import piece_image
from autoswf.model.geometry import Matrix
from autoswf.render.colors import PlayerColors
from autoswf.render.display import ClipInstance, ScriptContext, instantiate, run_pending_actions
from autoswf.render.painter import Renderer, object_bounds
from autoswf.swf.decode import MovieData

THUMB = 40
BACKGROUND = QColor(58, 58, 62)
PATH_ROLE = Qt.ItemDataRole.UserRole
KINDS_ON_HEAD = ("Helm", "Weapon", "Cape", "Pet")
OVERWRITE = "The output would overwrite the file being edited; choose another name"


class _RemoveCommand(QUndoCommand):
    def __init__(self, editor: "SwfEditor", ref: PieceRef, removed: bool):
        super().__init__("Remove piece" if removed else "Restore piece")
        self.editor, self.ref, self.removed = editor, ref, removed

    def redo(self) -> None:
        self.editor._apply(self.ref, self.removed)

    def undo(self) -> None:
        self.editor._apply(self.ref, not self.removed)


class _ItemCanvas(QWidget):
    """The selected part of the edited file, fitted, with the selected piece outlined."""

    def __init__(self, editor: "SwfEditor"):
        super().__init__()
        self.editor = editor
        self.setMinimumSize(320, 280)
        self.renderer = Renderer()
        self.colors = PlayerColors()

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
        bounds = object_bounds(obj, Matrix())
        if bounds is None:
            p.setPen(QColor(200, 200, 200))
            p.drawText(QRectF(0, 0, width, height), Qt.AlignmentFlag.AlignCenter,
                       e.canvas_message() or "This part is empty")
            return
        x0, x1, y0, y1 = bounds
        scale = min((width - 40) / max(x1 - x0, 1e-3), (height - 40) / max(y1 - y0, 1e-3))
        view = Matrix.translate(width / 2, height / 2) @ Matrix.scale(scale, scale) @ Matrix.translate(
            -(x0 + x1) / 2, -(y0 + y1) / 2)
        self.renderer.draw(p, obj, view, self.colors, filter_scale=scale)
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
        self.removed: set[PieceRef] = set()
        self.selected_path: str | None = None
        self.frame = 0
        self.undo_stack = QUndoStack(self)
        self._items: dict[str, QTreeWidgetItem] = {}
        self._preview = None
        self._thumbs: dict[int, QIcon] = {}

        self.tree = QTreeWidget()
        self.tree.setColumnCount(2)
        self.tree.setHeaderLabels(["Piece", "Kind"])
        self.tree.setIconSize(QPixmap(THUMB, THUMB).size())
        self.tree.itemChanged.connect(self._on_item_changed)
        self.tree.currentItemChanged.connect(self._on_current)
        self.tree.itemExpanded.connect(self._load_thumbs)
        self.tree.header().setStretchLastSection(False)
        self.tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.tree.header().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.canvas = _ItemCanvas(self)
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
        split.addWidget(self.tree)
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
        self.removed, self.selected_path, self.frame = set(), None, 0
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
            item = QTreeWidgetItem(parent, [piece.label, piece.kind + (" (changes)" if piece.changes else "")])
            item.setData(0, PATH_ROLE, piece.path)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(0, Qt.CheckState.Unchecked if piece.ref in self.removed else Qt.CheckState.Checked)
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

    def select(self, path: str) -> None:
        self.selected_path = path
        top = "/".join(path.split("/")[:2]) if path and "/" in path else None
        self.frame = self.structure.piece(top).frame if top else 0
        item = self._items.get(path)
        if item is not None and self.tree.currentItem() is not item:
            self.tree.blockSignals(True)
            self.tree.setCurrentItem(item)
            self.tree.blockSignals(False)
        self._refresh_info()
        self.canvas.update()

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
        ref = self.structure.piece(path).ref
        removed = item.checkState(0) == Qt.CheckState.Unchecked
        if removed != (ref in self.removed):
            self.set_removed(ref, removed)

    def set_removed(self, ref: PieceRef, removed: bool) -> None:
        """Remove (or restore) a placement: one undo step; every instance of it in the tree follows."""
        if removed == (ref in self.removed):
            return
        self.undo_stack.push(_RemoveCommand(self, ref, removed))

    def _apply(self, ref: PieceRef, removed: bool) -> None:
        (self.removed.add if removed else self.removed.discard)(ref)
        self._set_edited(edit_swf(self.original, sorted(self.removed, key=lambda r: (r.sprite, r.depth)),
                                  prune=False).data if self.removed else self.original)
        self.tree.blockSignals(True)
        for path in self.structure.instances(ref):
            item = self._items.get(path)
            if item is not None:
                item.setCheckState(0, Qt.CheckState.Unchecked if removed else Qt.CheckState.Checked)
        self.tree.blockSignals(False)
        self.message.setText("%d piece%s removed" % (len(self.removed), "" if len(self.removed) == 1 else "s")
                             if self.removed else "")
        self.canvas.update()
        if self._preview is not None and self._preview.isVisible():
            self.preview()

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
                    scene = PreviewScene.from_cache(self.cache, None, armor_data=self.edited)
                else:
                    scene = PreviewScene.from_cache(self.cache, self.edited, link=helm_link)
                problem = None
            except (MissingReferenceFiles, ValueError) as e:
                scene, problem = None, str(e)
            self._preview = PreviewWindow(scene, cache=self.cache)
            if problem:
                self._preview.empty_message = problem
        elif kind == "armor":
            self._preview.set_armor_data(self.edited)
        else:
            self._preview.set_helm_data(self.edited, helm_link)
        self._preview.resize(1000, 700)
        self._preview.show()
        return self._preview

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
        changes = bool(self.editor.removed) or self.rename_box.isChecked()
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
                              prune=not self.keep_unused_box.isChecked(), rename=rename)
        except ValueError as error:
            self.report.setPlainText(str(error))
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
        expected = [result.renamed.get(c, c) for c in e.structure.public_classes()]
        report = validate_item_swf(result.data, expected, e.original)
        n, k = result.removed_placements, len(result.removed_characters)
        lines = ["Wrote %s (%.1f KB, %d placement%s removed, %d unused shape%s dropped)%s"
                 % (out.name, len(result.data) / 1024, n, "" if n == 1 else "s", k, "" if k == 1 else "s",
                    " — valid" if report.ok else "")]
        lines += ["Problem: " + p for p in report.problems] + result.notes + report.notes
        self.report.setPlainText("\n".join(lines))
