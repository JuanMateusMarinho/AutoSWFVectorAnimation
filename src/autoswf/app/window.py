"""The main window (spec §6, layout "C hybrid"): stage bar on top, the canvas in the middle with the part tree and
source layers on the left, AI suggestions and Properties on the right and the timeline at the bottom; menus and
Animate-like shortcuts; the welcome page; the first-run download of the AQW reference files."""
import threading
from pathlib import Path

from PySide6.QtCore import QSettings, Qt
from PySide6.QtGui import QAction, QKeySequence, QUndoGroup
from PySide6.QtWidgets import (QDockWidget, QFileDialog, QGroupBox, QHBoxLayout, QLabel, QMainWindow, QMessageBox,
                               QPushButton, QSizePolicy, QSlider, QSplitter, QStackedWidget, QTabWidget, QToolBar, QVBoxLayout,
                               QWidget)

from autoswf import __version__
from autoswf.app.canvas import HelmCanvas
from autoswf.app.layers_panel import LayerList
from autoswf.app.parts_panel import PartTree
from autoswf.app.properties import PropertiesPanel
from autoswf.app.suggestions_panel import SuggestionsPanel
from autoswf.app.swf_editor import SwfEditor
from autoswf.app.timeline_view import TimelineView
from autoswf.app.stagebar import BUSY_STAGE, STAGES, StageBar, stage_states
from autoswf.aqw.assets import DEFAULT_ARMOR, AqwCache
from autoswf.preview.window import Downloader, PreviewWindow, download_question

DRAWING_SUFFIXES = (".clip", ".psd", ".psb", ".png")
RECENT_MAX = 8
OPEN_HINT = "AutoSWF opens drawings (.clip, .psd, .png), AutoSWF projects (.aswf) and SWF files"

SHORTCUTS = {
    "import": ("&Import drawing…", "Ctrl+R"), "open": ("&Open…", "Ctrl+O"), "open_swf": ("Open &SWF…", "Ctrl+Shift+O"),
    "save": ("&Save", "Ctrl+S"), "save_as": ("Save &As…", "Ctrl+Shift+S"), "reimport": ("&Re-import drawing", None), "export": ("&Export SWF…", "Ctrl+Alt+Shift+S"),
    "quit": ("&Quit", "Ctrl+Q"), "play": ("&Play / Pause", "Return"), "preview": ("Preview on AQW &body", "Ctrl+Return"),
    "insert_frame": ("Insert &frame", "F5"), "remove_frame": ("&Remove frame", "Shift+F5"),
    "insert_keyframe": ("Insert &keyframe", "F6"), "clear_keyframe": ("&Clear keyframe", "Shift+F6"),
    "timeline": ("&Timeline", "Ctrl+Alt+T"), "zoom_in": ("Zoom &in", "Ctrl+="), "zoom_out": ("Zoom &out", "Ctrl+-"),
    "fit": ("&Fit", "Ctrl+2"), "toggle_gender": ("Male / &female head", "Ctrl+M"),
    "download": ("&Download AQW files…", None), "about": ("&About AutoSWF", None),
}


class MainWindow(QMainWindow):
    def __init__(self, controller, cache: AqwCache, *, settings_store: QSettings | None = None):
        super().__init__()
        self.controller, self.cache = controller, cache
        self.settings_store = settings_store or QSettings("AutoSWF", "AutoSWF")
        self._preview: PreviewWindow | None = None
        self._busy_stage: str | None = None
        self._download_worker = None
        self.undo_group = QUndoGroup(self)
        self.undo_group.addStack(controller.undo_stack)
        self.undo_group.setActiveStack(controller.undo_stack)
        self.setAcceptDrops(True)
        self.resize(1400, 900)
        self._make_actions()
        self._make_menus()
        self._make_layout()
        controller.built.connect(self._on_built)
        controller.progress.connect(self._on_progress)
        controller.settings_changed.connect(self._refresh)
        controller.exported.connect(lambda results: self._refresh())
        self._refresh()
        self._refresh_recent()

    # ------------------------------------------------------------ actions and menus

    def _make_actions(self) -> None:
        self.actions: dict[str, QAction] = {}
        for name, (text, keys) in SHORTCUTS.items():
            if name in ("undo", "redo"):
                continue
            action = QAction(text, self)
            if keys:
                action.setShortcut(QKeySequence(keys))
            self.actions[name] = action
        undo = self.undo_group.createUndoAction(self, "&Undo")
        undo.setShortcuts([QKeySequence("Ctrl+Z")])
        redo = self.undo_group.createRedoAction(self, "&Redo")
        redo.setShortcuts([QKeySequence("Ctrl+Y"), QKeySequence("Ctrl+Shift+Z")])
        self.actions["undo"], self.actions["redo"] = undo, redo
        self.actions["timeline"].setCheckable(True)
        handlers = {"import": self._on_import, "open": self._on_open, "open_swf": self._on_open_swf,
                    "save": self._on_save, "save_as": self._on_save_as, "reimport": self._on_reimport, "export": self._on_export, "quit": self.close,
                    "play": self._on_play, "preview": self.preview_window, "insert_frame": self._on_insert_frame,
                    "remove_frame": self._on_remove_frame, "insert_keyframe": self._on_insert_keyframe,
                    "clear_keyframe": self._on_clear_keyframe, "timeline": self._on_timeline,
                    "zoom_in": lambda: self.canvas.set_zoom(self.canvas.current_zoom() * 1.25),
                    "zoom_out": lambda: self.canvas.set_zoom(self.canvas.current_zoom() / 1.25),
                    "fit": lambda: self.canvas.fit(), "toggle_gender": self._on_toggle_gender,
                    "download": self.download_reference_files, "about": self._on_about}
        for name, handler in handlers.items():
            self.actions[name].triggered.connect(lambda _=False, h=handler: h())
        for name, action in self.actions.items():
            if name != "play":
                self.addAction(action)
        # Enter plays only where it cannot mean "commit this field": the canvas and the timeline
        self.actions["play"].setShortcutContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)

    def _make_menus(self) -> None:
        bar = self.menuBar()
        a = self.actions
        for title, names in (("&File", ("import", "open", "open_swf", None, "save", "save_as", "reimport", None, "export", None,
                                       "quit")),
                             ("&Edit", ("undo", "redo")),
                             ("&View", ("zoom_in", "zoom_out", "fit", None, "toggle_gender", "timeline")),
                             ("&Control", ("play", "preview")),
                             ("&Insert", ("insert_frame", "remove_frame", "insert_keyframe", "clear_keyframe")),
                             ("&Help", ("download", "about"))):
            menu = bar.addMenu(title)
            for name in names:
                if name is None:
                    menu.addSeparator()
                else:
                    menu.addAction(a[name])

    def _make_layout(self) -> None:
        self.stage_bar = StageBar()
        self.stage_bar.stage_clicked.connect(self.set_stage)
        top = QToolBar("Stages")
        top.setMovable(False)
        self._stage_action = top.addWidget(self.stage_bar)        # a toolbar widget hides through its action
        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        top.addWidget(spacer)
        self.preview_button = QPushButton("Preview on AQW body")
        self.preview_button.clicked.connect(self.preview_window)
        self.export_button = QPushButton("Export SWF…")
        self.export_button.clicked.connect(self._on_export)
        top.addWidget(self.preview_button)
        top.addWidget(self.export_button)
        self.addToolBar(top)

        self.stack = QStackedWidget()
        self.welcome = self._make_welcome()
        self.stack.addWidget(self.welcome)
        self.canvas = HelmCanvas(self.controller, self.cache)
        self.canvas.download_requested.connect(self.download_reference_files)
        self.layers = LayerList(self.controller)
        self.parts_tree = PartTree(self.controller)
        self.left_tabs = QTabWidget()
        self.left_tabs.addTab(self.parts_tree, "Parts")
        self.left_tabs.addTab(self.layers, "Layers")
        self.suggestions_panel = SuggestionsPanel(self.controller)
        self.controller.stage_requested.connect(self.set_stage)
        self.properties = PropertiesPanel(self.controller)
        self.properties.export_requested.connect(self._on_export)
        self.right_panel = QSplitter(Qt.Orientation.Vertical)
        self.right_panel.addWidget(self.suggestions_panel)
        self.right_panel.addWidget(self.properties)
        self.right_panel.setSizes([240, 620])
        center = QWidget()
        column = QVBoxLayout(center)
        column.setContentsMargins(0, 0, 0, 0)
        column.addWidget(self._make_canvas_bar())
        column.addWidget(self.canvas, 1)
        self.workspace = QSplitter(Qt.Orientation.Horizontal)
        self.workspace.addWidget(self.left_tabs)
        self.workspace.addWidget(center)
        self.workspace.addWidget(self.right_panel)
        self.workspace.setStretchFactor(1, 1)
        self.workspace.setSizes([260, 840, 300])
        self.stack.addWidget(self.workspace)
        self.swf_editor = SwfEditor(self.cache)
        self.undo_group.addStack(self.swf_editor.undo_stack)
        self.stack.addWidget(self.swf_editor)
        self.setCentralWidget(self.stack)
        self.timeline = TimelineView(self.controller)
        self.timeline.frame_changed.connect(self._on_frame)
        self.timeline.key_selected.connect(self.properties.show_key)
        self.timeline_dock = QDockWidget("Timeline", self)
        self.timeline_dock.setObjectName("timeline")
        self.timeline_dock.setWidget(self.timeline)
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, self.timeline_dock)
        self.canvas.addAction(self.actions["play"])
        self.timeline.addAction(self.actions["play"])
        self.timeline_dock.hide()
        self.timeline_dock.visibilityChanged.connect(self.actions["timeline"].setChecked)

    def _make_canvas_bar(self) -> QWidget:
        bar = QWidget()
        row = QHBoxLayout(bar)
        row.setContentsMargins(6, 2, 6, 2)
        self.gender_button = QPushButton("Head: Male")
        self.gender_button.setToolTip("Show the male or the female AQW head under the helm (Ctrl+M)")
        self.gender_button.clicked.connect(self._on_toggle_gender)
        fit = QPushButton("Fit")
        fit.clicked.connect(self.canvas.fit)
        self.cut_button = QPushButton("Cut")
        self.cut_button.setCheckable(True)
        self.cut_button.setToolTip("Drag a line on the canvas to split a region (C)")
        self.cut_button.toggled.connect(lambda on: self.canvas.set_tool("cut" if on else "select"))
        row.addWidget(self.gender_button)
        row.addWidget(fit)
        row.addWidget(self.cut_button)
        for label, attr, value in (("Drawing", "drawing_opacity", 0), ("Guide", "guide_opacity", 100)):
            row.addWidget(QLabel(label))
            slider = QSlider(Qt.Orientation.Horizontal)
            slider.setRange(0, 100)
            slider.setValue(value)
            slider.setFixedWidth(110)
            slider.setToolTip("%s opacity" % label)
            slider.valueChanged.connect(lambda v, a=attr: (setattr(self.canvas, a, v / 100), self.canvas.update()))
            row.addWidget(slider)
        row.addStretch(1)
        return bar

    def _make_welcome(self) -> QWidget:
        page = QWidget()
        column = QVBoxLayout(page)
        column.addStretch(1)
        title = QLabel("AutoSWF")
        title.setStyleSheet("font-size: 32px; font-weight: bold;")
        subtitle = QLabel("Turn your drawings into AdventureQuest Worlds items.")
        for widget in (title, subtitle):
            widget.setAlignment(Qt.AlignmentFlag.AlignCenter)
            column.addWidget(widget)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        for text, handler in (("Import drawing…", self._on_import), ("Open project…", self._on_open),
                              ("Open SWF…", self._on_open_swf)):
            b = QPushButton(text)
            b.setMinimumWidth(150)
            b.clicked.connect(handler)
            buttons.addWidget(b)
        buttons.addStretch(1)
        column.addLayout(buttons)
        self.recent_box = QVBoxLayout()
        column.addLayout(self.recent_box)
        self._recent_ready = True
        self.aqw_status = QLabel()
        self.aqw_status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        column.addWidget(self.aqw_status)
        self.welcome_download = QPushButton("Download AQW files…")
        self.welcome_download.clicked.connect(self.download_reference_files)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(self.welcome_download)
        row.addStretch(1)
        column.addLayout(row)
        column.addStretch(2)
        return page

    # ------------------------------------------------------------ state

    def pending_suggestions(self) -> list:
        return self.suggestions_panel.current()

    def _refresh(self) -> None:
        c = self.controller
        missing = self.cache.missing(DEFAULT_ARMOR)
        self.aqw_status.setText("AQW reference files: downloaded" if not missing
                                else "AQW reference files are not downloaded yet (needed for the head guide and the "
                                     "body preview).")
        self.welcome_download.setHidden(not missing)
        exported = c.settings is not None and c.exported_settings == c.settings.to_dict()
        self.stage_bar.set_states(stage_states(c.settings, c.build, self.pending_suggestions(), exported,
                                               self._busy_stage if c.busy else None))
        self.setWindowTitle(self.title())

    def title(self) -> str:
        if self.in_swf_editor() and self.swf_editor.path is not None:
            return "AutoSWF — %s" % self.swf_editor.path.name
        c = self.controller
        if c.settings is None:
            return "AutoSWF"
        name = c.project_path.name if c.project_path is not None else Path(c.settings.source).name
        return "AutoSWF — %s%s" % (name, " *" if c.dirty else "")

    def _on_built(self, build) -> None:
        self._busy_stage = None
        self._refresh()
        if build.error:
            self.statusBar().showMessage(build.error)
        elif build.complete:
            self.statusBar().showMessage("Helm ready: %s (%.1f KB)" % (build.link, len(build.swf) / 1024))
        if self._preview is not None and self._preview.isVisible() and self.controller.helm_build is not None:
            self._preview.set_helm_data(self.controller.helm_build.swf, self.controller.helm_build.link)

    def _on_progress(self, text: str) -> None:
        self._busy_stage = BUSY_STAGE.get(text)
        self.statusBar().showMessage(text + "…")
        self._refresh()

    def set_stage(self, stage: str) -> None:
        if stage not in STAGES:
            return
        self.stage_bar.set_current(stage)
        self.canvas.set_stage(stage)
        self.properties.show_stage(stage)
        self.left_tabs.setCurrentWidget(self.layers if stage in ("Import", "Vectorize") else self.parts_tree)
        if stage == "Animate" and not self.timeline_dock.isVisible():
            self.timeline_dock.show()
            self.resizeDocks([self.timeline_dock], [240], Qt.Orientation.Vertical)

    # ------------------------------------------------------------ opening

    def open_path(self, path) -> str | None:
        """Open a drawing (new project) or a project (.aswf); returns an error message when it cannot be opened."""
        path = Path(path)
        if path.suffix.lower() == ".swf":
            error = self.swf_editor.open(path)
            if error:
                return error
            self._add_recent(path)
            self.stack.setCurrentWidget(self.swf_editor)
            self._stage_action.setVisible(False)
            self.undo_group.setActiveStack(self.swf_editor.undo_stack)
            self.setWindowTitle("AutoSWF — %s" % path.name)
            return None
        if path.suffix.lower() in DRAWING_SUFFIXES + (".aswf",) and not self._may_leave():
            return None                      # the user kept the current project
        if path.suffix.lower() == ".aswf":
            return self.open_project(path)
        if path.suffix.lower() in DRAWING_SUFFIXES:
            if not path.exists():
                return "%s was not found" % path
            self.controller.import_drawing(path)
            self._add_recent(path)
            self._show_helm_workspace()
            self.set_stage("Import")
            return None
        return OPEN_HINT

    def _ask_open(self, title: str, filters: str) -> None:
        path, _ = QFileDialog.getOpenFileName(self, title, "", filters)
        if path:
            error = self.open_path(path)
            if error:
                QMessageBox.warning(self, title, error)

    def _on_import(self) -> None:
        self._ask_open("Import drawing", "Drawings (*.clip *.psd *.psb *.png)")

    def _on_open(self) -> None:
        self._ask_open("Open", "AutoSWF projects and SWF files (*.aswf *.swf)")

    def _on_open_swf(self) -> None:
        self._ask_open("Open SWF", "SWF files (*.swf)")

    def dragEnterEvent(self, event) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:
        for url in event.mimeData().urls():
            if url.isLocalFile():
                error = self.open_path(url.toLocalFile())
                if error:
                    QMessageBox.warning(self, "Open", error)
                return

    # ------------------------------------------------------------ actions (later tasks fill the empty ones)

    def _show_helm_workspace(self) -> None:
        self.stack.setCurrentWidget(self.workspace)
        self._stage_action.setVisible(True)
        self.undo_group.setActiveStack(self.controller.undo_stack)
        self.set_stage("Import")

    def in_swf_editor(self) -> bool:
        return self.stack.currentWidget() is self.swf_editor

    def open_project(self, path: Path) -> str | None:
        try:
            loaded = self.controller.open_project(path)
        except ValueError as e:
            return str(e)
        self._add_recent(path)
        self._show_helm_workspace()
        for note in loaded.notes:
            self.statusBar().showMessage(note)
        if loaded.source_changed:
            if self.ask_reimport():
                self.controller.reimport_drawing(self._on_reimported)
            else:
                self.controller.use_saved_copy()
        self._refresh()
        return None

    def ask_reimport(self) -> bool:
        box = QMessageBox(QMessageBox.Icon.Question, "The drawing changed",
                          "The drawing changed since this project was saved. Re-import it? Animation and hand-made "
                          "keyframes stay on the parts that still match.", parent=self)
        yes = box.addButton("Re-import", QMessageBox.ButtonRole.AcceptRole)
        box.addButton("Use the saved copy", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        return box.clickedButton() is yes

    def show_report(self, text: str) -> None:
        QMessageBox.information(self, "Re-import", text)

    def _on_reimported(self, report) -> None:
        self.show_report(report.text() if report is not None else
                         "The drawing could not be read again; the project keeps its parts as they were.")
        self._refresh()

    def _on_reimport(self) -> None:
        if self.controller.settings is not None:
            self.controller.reimport_drawing(self._on_reimported)

    def _add_recent(self, path: Path) -> None:
        recent = [str(Path(path))] + [p for p in self.recent_files() if Path(p) != Path(path)]
        self.settings_store.setValue("recent", recent[:RECENT_MAX])
        self._refresh_recent()

    def recent_files(self) -> list[str]:
        value = self.settings_store.value("recent", [])
        return [value] if isinstance(value, str) else list(value or [])

    def _refresh_recent(self) -> None:
        while self.recent_box.count():
            item = self.recent_box.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        for path in self.recent_files():
            button = QPushButton(Path(path).name)
            button.setFlat(True)
            button.setToolTip(path)
            button.clicked.connect(lambda _=False, p=path: self._open_recent(p))
            self.recent_box.addWidget(button)

    def _open_recent(self, path: str) -> None:
        error = self.open_path(path)
        if error:
            QMessageBox.warning(self, "Open", error)

    def _on_save(self) -> bool:
        if self.controller.settings is None:
            return False
        if self.controller.project_path is None:
            return self._on_save_as()
        return self._save(self.controller.project_path)

    def _on_save_as(self) -> bool:
        if self.controller.settings is None:
            return False
        default = str(Path(self.controller.settings.source).with_suffix(".aswf"))
        path, _ = QFileDialog.getSaveFileName(self, "Save project", default, "AutoSWF projects (*.aswf)")
        return self._save(Path(path)) if path else False

    def _save(self, path: Path) -> bool:
        try:
            self.controller.save(path)
        except ValueError as e:
            QMessageBox.warning(self, "Save project", str(e))
            return False
        self._add_recent(path)
        self.statusBar().showMessage("Saved %s" % path.name)
        self._refresh()
        return True

    def ask_save(self) -> str:
        """"save", "discard" or "cancel" for unsaved changes."""
        answer = QMessageBox.question(self, "Unsaved changes", "Save the changes to this project first?",
                                      QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard
                                      | QMessageBox.StandardButton.Cancel)
        return {QMessageBox.StandardButton.Save: "save",
                QMessageBox.StandardButton.Discard: "discard"}.get(answer, "cancel")

    def _may_leave(self) -> bool:
        """True when the current project may be closed (saved, discarded or clean)."""
        if not self.controller.dirty:
            return True
        choice = self.ask_save()
        if choice == "save":
            return self._on_save()
        return choice == "discard"

    def _on_play(self) -> None:
        self.timeline.toggle_play()

    def _on_frame(self, frame: int) -> None:
        self.canvas.onion = self.timeline.onion and not self.timeline.playing
        self.canvas.set_frame(frame)

    def _track(self) -> tuple[str, str] | None:
        """The timeline row picked (part, target), else the selected part's own layer."""
        if self.timeline.selected is not None:
            return self.timeline.selected
        part = self.controller.selected_part
        return (part, part) if part else None

    def _timeline_action(self, action) -> None:
        track = self._track()
        if track is None:
            self.statusBar().showMessage("Pick a row of the timeline (or a part) first")
            return
        try:
            action(*track)
        except (ValueError, KeyError) as e:
            QMessageBox.warning(self, "Timeline", str(e).strip("'\""))

    def _on_insert_frame(self) -> None:
        self._timeline_action(lambda part, target: self.controller.change_loop(part, 1))

    def _on_remove_frame(self) -> None:
        self._timeline_action(lambda part, target: self.controller.change_loop(part, -1))

    def _on_insert_keyframe(self) -> None:
        def insert(part, target):
            frame = self.timeline.playhead
            self.controller.add_key(part, target, frame)
            self.set_stage("Animate")
            self.timeline.refresh()
            self.timeline.select_key((part, target, frame))
        self._timeline_action(insert)

    def _on_clear_keyframe(self) -> None:
        self._timeline_action(lambda part, target: self.controller.delete_key(part, target, self.timeline.playhead))

    def _on_timeline(self) -> None:
        self.timeline_dock.setVisible(not self.timeline_dock.isVisible())

    def _on_toggle_gender(self) -> None:
        self.canvas.set_gender("F" if self.canvas.gender == "M" else "M")
        self.properties.gender = self.canvas.gender
        self.properties.refresh()
        self.gender_button.setText("Head: %s" % ("Male" if self.canvas.gender == "M" else "Female"))

    def _on_export(self) -> None:
        if self.in_swf_editor():
            self.swf_editor.export_dialog().exec()
            return
        if self.controller.settings is None:
            QMessageBox.information(self, "Export SWF", "Import a drawing first.")
            return
        from autoswf.app.export_dialog import ExportDialog
        ExportDialog(self.controller, self).exec()
        self._refresh()

    def _on_about(self) -> None:
        QMessageBox.about(self, "About AutoSWF",
                          "AutoSWF %s\n\nTurns your drawings into AdventureQuest Worlds items.\n\nAutoSWF is an "
                          "independent fan-made tool, not affiliated with Artix Entertainment. AQW files are only "
                          "downloaded to this computer for the preview and are never shared." % __version__)

    def preview_window(self) -> PreviewWindow | None:
        """Show the helm on the AQW male and female bodies (Ctrl+Enter); in Open SWF, the edited item."""
        if self.in_swf_editor():
            return self.swf_editor.preview()
        from autoswf.preview.scene import MissingReferenceFiles, PreviewScene
        build = self.controller.helm_build
        if build is None:
            QMessageBox.information(self, "Preview on AQW body", "Import a drawing first.")
            return None
        if self._preview is None or self._preview.scene is None:
            try:
                scene = PreviewScene.from_cache(self.cache, build.swf, link=build.link)
            except (MissingReferenceFiles, ValueError) as e:
                scene, problem = None, str(e)
            else:
                problem = None
            self._preview = PreviewWindow(scene, cache=self.cache, link=build.link)
            if problem:
                self._preview.empty_message = problem
        else:
            self._preview.set_helm_data(build.swf, build.link)
        settings = self.controller.settings
        for location, rgb in (settings.colors.items() if settings is not None else ()):
            self._preview.set_player_color(location, rgb)
        self._preview.resize(1100, 720)
        self._preview.show()
        self._preview.raise_()
        return self._preview

    # ------------------------------------------------------------ AQW files

    def first_run(self) -> None:
        """Ask once to download the AQW reference files when they are missing."""
        if not self.cache.missing(DEFAULT_ARMOR) or self.settings_store.value("firstRunAsked", False, type=bool):
            return
        self.settings_store.setValue("firstRunAsked", True)
        self.settings_store.sync()
        answer = QMessageBox.question(self, "Download AQW files", download_question(self.cache))
        if answer == QMessageBox.StandardButton.Yes:
            self._start_download()

    def download_reference_files(self) -> None:
        answer = QMessageBox.question(self, "Download AQW files", download_question(self.cache))
        if answer == QMessageBox.StandardButton.Yes:
            self._start_download()

    def _start_download(self) -> None:
        self._download_worker = Downloader(self.cache, DEFAULT_ARMOR)
        self._download_worker.progress.connect(self.statusBar().showMessage)
        self._download_worker.finished.connect(self._on_downloaded)
        threading.Thread(target=self._download_worker.run, name="aqw-download", daemon=True).start()

    def _on_downloaded(self, error: str) -> None:
        if error:
            QMessageBox.warning(self, "Download failed", error + "\n\nAutoSWF still works without these files; only the "
                                "head guide and the body preview need them.")
            return
        self.statusBar().showMessage("AQW reference files downloaded")
        self.canvas.reload_client()
        self._refresh()

    def closeEvent(self, event) -> None:
        if not self._may_leave():
            event.ignore()
            return
        if self._preview is not None:
            self._preview.close()
        self.controller.close()
        super().closeEvent(event)
