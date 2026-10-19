"""The main window (spec §6, layout "C hybrid"): stage bar on top, the canvas in the middle with the part tree and
source layers on the left, AI suggestions and Properties on the right and the timeline at the bottom; menus and
Animate-like shortcuts; the welcome page; the first-run download of the AQW reference files."""
import threading
from pathlib import Path
from types import SimpleNamespace

from PySide6.QtCore import QSettings, Qt
from PySide6.QtGui import QAction, QKeySequence, QUndoGroup
from PySide6.QtWidgets import (QDockWidget, QFileDialog, QGroupBox, QHBoxLayout, QLabel, QMainWindow, QMessageBox,
                               QPushButton, QSizePolicy, QSlider, QSplitter, QStackedWidget, QTabWidget, QToolBar, QVBoxLayout,
                               QWidget)

from autoswf import __version__
from autoswf.anim.settings import suggest_presets
from autoswf.app.canvas import HelmCanvas
from autoswf.app.layers_panel import LayerList
from autoswf.app.parts_panel import PartTree
from autoswf.app.properties import PropertiesPanel
from autoswf.app.stagebar import BUSY_STAGE, STAGES, StageBar, stage_states
from autoswf.aqw.assets import DEFAULT_ARMOR, AqwCache
from autoswf.preview.window import Downloader, PreviewWindow, download_question

DRAWING_SUFFIXES = (".clip", ".psd", ".psb", ".png")
OPEN_HINT = "AutoSWF opens drawings (.clip, .psd, .png), AutoSWF projects (.aswf) and SWF files"

SHORTCUTS = {
    "import": ("&Import drawing…", "Ctrl+R"), "open": ("&Open…", "Ctrl+O"), "open_swf": ("Open &SWF…", "Ctrl+Shift+O"),
    "save": ("&Save", "Ctrl+S"), "save_as": ("Save &As…", "Ctrl+Shift+S"), "export": ("&Export SWF…", "Ctrl+Alt+Shift+S"),
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
                    "save": self._on_save, "save_as": self._on_save_as, "export": self._on_export, "quit": self.close,
                    "play": self._on_play, "preview": self.preview_window, "insert_frame": self._on_insert_frame,
                    "remove_frame": self._on_remove_frame, "insert_keyframe": self._on_insert_keyframe,
                    "clear_keyframe": self._on_clear_keyframe, "timeline": self._on_timeline,
                    "zoom_in": lambda: self.canvas.set_zoom(self.canvas.current_zoom() * 1.25),
                    "zoom_out": lambda: self.canvas.set_zoom(self.canvas.current_zoom() / 1.25),
                    "fit": lambda: self.canvas.fit(), "toggle_gender": self._on_toggle_gender,
                    "download": self.download_reference_files, "about": self._on_about}
        for name, handler in handlers.items():
            self.actions[name].triggered.connect(lambda _=False, h=handler: h())
        for action in self.actions.values():
            self.addAction(action)

    def _make_menus(self) -> None:
        bar = self.menuBar()
        a = self.actions
        for title, names in (("&File", ("import", "open", "open_swf", None, "save", "save_as", None, "export", None, "quit")),
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
        top.addWidget(self.stage_bar)
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
        self.suggestions_panel = QGroupBox("AI suggestions")
        self.suggestions_panel.setLayout(QVBoxLayout())
        self.properties = PropertiesPanel(self.controller)
        self.properties.export_requested.connect(self._on_export)
        self.right_panel = QSplitter(Qt.Orientation.Vertical)
        self.right_panel.addWidget(self.suggestions_panel)
        self.right_panel.addWidget(self.properties)
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
        self.swf_editor = QWidget()
        self.stack.addWidget(self.swf_editor)
        self.setCentralWidget(self.stack)
        self.timeline = QWidget()
        self.timeline_dock = QDockWidget("Timeline", self)
        self.timeline_dock.setObjectName("timeline")
        self.timeline_dock.setWidget(self.timeline)
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, self.timeline_dock)
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
        """Undecided animation suggestions (Task 6 replaces this with the full suggestion engine)."""
        build, settings = self.controller.helm_build, self.controller.settings
        if build is None or settings is None or not build.rigs:
            return []
        parts = [p for p in suggest_presets(build.rigs) if p not in settings.animation.parts]
        return [SimpleNamespace(preset="suggested", stage="Animate", parts=parts, text="Animations are suggested")] \
            if parts else []

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
        settings = self.controller.settings
        if settings is None:
            return "AutoSWF"
        return "AutoSWF — %s" % Path(settings.source).name

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
        if stage == "Animate":
            self.timeline_dock.show()

    # ------------------------------------------------------------ opening

    def open_path(self, path) -> str | None:
        """Open a drawing (new project); returns an error message when the file cannot be opened."""
        path = Path(path)
        if path.suffix.lower() in DRAWING_SUFFIXES:
            if not path.exists():
                return "%s was not found" % path
            self.controller.import_drawing(path)
            self.stack.setCurrentWidget(self.workspace)
            self.stage_bar.show()
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

    def _on_save(self) -> None:
        pass

    def _on_save_as(self) -> None:
        pass

    def _on_play(self) -> None:
        pass

    def _on_insert_frame(self) -> None:
        pass

    def _on_remove_frame(self) -> None:
        pass

    def _on_insert_keyframe(self) -> None:
        pass

    def _on_clear_keyframe(self) -> None:
        pass

    def _on_timeline(self) -> None:
        self.timeline_dock.setVisible(not self.timeline_dock.isVisible())

    def _on_toggle_gender(self) -> None:
        self.canvas.set_gender("F" if self.canvas.gender == "M" else "M")
        self.gender_button.setText("Head: %s" % ("Male" if self.canvas.gender == "M" else "Female"))

    def _on_export(self) -> None:
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
        """Show the helm on the AQW male and female bodies (Ctrl+Enter)."""
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
        if self._preview is not None:
            self._preview.close()
        self.controller.close()
        super().closeEvent(event)
