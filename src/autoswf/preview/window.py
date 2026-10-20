"""PySide6 preview window: the helm on the AQW male and female bodies, the game's labels at 24 fps, player colors,
morph check, and the user-initiated download of the AQW reference files."""
import threading
from pathlib import Path

from PySide6.QtCore import QElapsedTimer, QObject, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (QApplication, QCheckBox, QColorDialog, QComboBox, QFileDialog, QGroupBox, QHBoxLayout,
                               QMainWindow, QMessageBox, QPushButton, QSlider, QVBoxLayout, QWidget)

from autoswf.aqw.assets import DEFAULT_ARMOR, AqwCache, DownloadError, default_cache_dir, download_reference_files
from autoswf.preview.scene import GENDERS, MORPH_TOLERANCE_PX, MissingReferenceFiles, PreviewScene, find_helm_link
from autoswf.render.colors import PlayerColors
from autoswf.swf.decode import MovieData

LOCATION_ORDER = ("Hair", "Skin", "Eye", "Base", "Trim", "Accessory")
FPS = 24
MAX_TICKS_PER_EVENT = 3
MORPH_CHECK_EVERY = 12          # ticks between morph-check recounts (half a second)
GENDER_NAMES = {"M": "Male", "F": "Female"}


def download_question(cache: AqwCache) -> str:
    return ("AutoSWF needs the AQW game client and one armor to show the body. Download them now from AQW's public "
            "server (game.aq.com)? They are saved only on this computer, in %s, and are never shared." % Path(cache.root))


MOTION_PREFIX = "Armor: "          # an animated armor's own animation in the label box, played by name

class _Canvas(QWidget):
    def __init__(self, window: "PreviewWindow"):
        super().__init__()
        self._window = window
        self.setMinimumSize(480, 360)

    def paintEvent(self, event) -> None:
        w = self._window
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        if w.scene is None:
            p.fillRect(self.rect(), QColor(*w.background))
            p.setPen(QColor(220, 220, 220))
            p.drawText(self.rect().adjusted(24, 24, -24, -24), Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap,
                       w.empty_message)
        else:
            w.scene.paint(p, self.width(), self.height(), **w.paint_options(self.height()))
        p.end()


class Downloader(QObject):
    progress = Signal(str)
    finished = Signal(str)      # error message, empty on success

    def __init__(self, cache: AqwCache, armor: str):
        super().__init__()
        self._cache, self._armor = cache, armor

    def run(self) -> None:
        """Runs on a daemon thread; always reports back, whatever happens."""
        try:
            download_reference_files(self._cache, armor=self._armor, progress=self.progress.emit)
        except DownloadError as e:
            self.finished.emit(str(e))
            return
        except Exception as e:
            self.finished.emit("Unexpected error while downloading: %s" % e)
            return
        self.finished.emit("")


class PreviewWindow(QMainWindow):
    def __init__(self, scene: PreviewScene | None, *, cache: AqwCache, helm_path: Path | None = None,
                 link: str | None = None, armor: str = DEFAULT_ARMOR):
        super().__init__()
        self.scene, self.cache, self.helm_path, self.link, self.armor = None, cache, helm_path, link, armor
        self.background = (51, 51, 51, 255)
        self.empty_message = "AQW reference files are not downloaded yet."
        self._morph_text, self._ticks_since_check = "", MORPH_CHECK_EVERY
        self._worker = None
        self._helm_size = 0
        self._update_title()

        self.canvas = _Canvas(self)
        self.label_box = QComboBox()
        self.play_button = QPushButton("Pause")
        self.fit_box = QCheckBox("Fit")
        self.fit_box.setChecked(True)
        self.zoom_slider = QSlider(Qt.Orientation.Horizontal)
        self.zoom_slider.setRange(25, 800)
        self.zoom_slider.setValue(100)
        self.zoom_slider.setEnabled(False)
        self.zoom_slider.setToolTip("Zoom, in % of the fitted size")
        self.mirror_box = QCheckBox("Mirror")
        self.morph_box = QCheckBox("Morph check")
        self.morph_box.setToolTip("Show in red the parts of the base head the helm does not cover")
        self.background_button = QPushButton("Background…")
        self.color_buttons = {loc: QPushButton(loc) for loc in LOCATION_ORDER}
        self.reset_colors_button = QPushButton("Reset colors")
        self.open_button = QPushButton("Open helm…")
        self.save_button = QPushButton("Save PNG…")
        self.download_button = QPushButton("Download AQW files…")
        self._layout()
        self._connect()

        self._timer = QTimer(self)
        self._timer.setInterval(10)
        self._timer.timeout.connect(self._on_timer)
        self._clock = QElapsedTimer()
        self._ticks_done, self._playing = 0, True
        self._set_scene(scene)

    # ------------------------------------------------------------ layout

    def _layout(self) -> None:
        def group(title: str, widgets) -> QGroupBox:
            box, layout = QGroupBox(title), QVBoxLayout()
            for widget in widgets:
                layout.addWidget(widget)
            box.setLayout(layout)
            return box
        panel = QVBoxLayout()
        panel.addWidget(group("Animation", [self.label_box, self.play_button]))
        panel.addWidget(group("View", [self.fit_box, self.zoom_slider, self.mirror_box, self.morph_box,
                                       self.background_button]))
        panel.addWidget(group("Player colors", [*self.color_buttons.values(), self.reset_colors_button]))
        panel.addWidget(group("File", [self.open_button, self.save_button, self.download_button]))
        panel.addStretch(1)
        side = QWidget()
        side.setLayout(panel)
        side.setFixedWidth(220)
        root = QHBoxLayout()
        root.addWidget(self.canvas, 1)
        root.addWidget(side)
        central = QWidget()
        central.setLayout(root)
        self.setCentralWidget(central)

    def _connect(self) -> None:
        self.label_box.currentTextChanged.connect(self._on_label)
        self.play_button.clicked.connect(self._on_play)
        self.fit_box.toggled.connect(lambda on: (self.zoom_slider.setEnabled(not on), self.canvas.update()))
        self.zoom_slider.valueChanged.connect(lambda _: self.canvas.update())
        self.mirror_box.toggled.connect(lambda _: self.canvas.update())
        self.morph_box.toggled.connect(self._on_morph)
        self.background_button.clicked.connect(self._on_background)
        for location, button in self.color_buttons.items():
            button.clicked.connect(lambda _=False, loc=location: self._pick_color(loc))
        self.reset_colors_button.clicked.connect(self._on_reset_colors)
        self.open_button.clicked.connect(self._on_open)
        self.save_button.clicked.connect(self._on_save)
        self.download_button.clicked.connect(self._on_download)

    def _update_title(self) -> None:
        name = Path(self.helm_path).name if self.helm_path else (self.link or "no helm")
        self.setWindowTitle("AutoSWF Preview — %s" % name)

    def paint_options(self, height: int) -> dict:
        zoom = None
        if not self.fit_box.isChecked() and self.scene is not None:
            zoom = self.zoom_slider.value() / 100 * self.scene.default_zoom(height)
        return {"zoom": zoom, "mirror": self.mirror_box.isChecked(), "morph_check": self.morph_box.isChecked(),
                "background": self.background}

    # ------------------------------------------------------------ scene

    def _set_scene(self, scene: PreviewScene | None) -> None:
        self.scene = scene
        for widget in (self.label_box, self.play_button, self.mirror_box, self.morph_box, self.save_button,
                       self.reset_colors_button, *self.color_buttons.values()):
            widget.setEnabled(scene is not None)
        self.download_button.setHidden(scene is not None)
        if scene is None:
            self._timer.stop()
            self.canvas.update()
            return
        self.label_box.blockSignals(True)
        self.label_box.clear()
        self.label_box.addItems(scene.labels)
        self.label_box.addItems([MOTION_PREFIX + m for m in scene.motions])
        self.label_box.setCurrentText(scene.label)
        self.label_box.blockSignals(False)
        self._refresh_swatches()
        self._restart_clock()
        self._timer.start()
        self._update_status()
        self.canvas.update()

    def set_player_color(self, location: str, rgb: int) -> None:
        if self.scene is None:
            return
        self.scene.set_color(location, rgb)
        self._refresh_swatches()
        self.canvas.update()

    def _refresh_swatches(self) -> None:
        colors = self.scene.colors if self.scene is not None else PlayerColors()
        for location, button in self.color_buttons.items():
            rgb = colors.get(location)
            light = ((rgb >> 16) & 255) * 0.3 + ((rgb >> 8) & 255) * 0.59 + (rgb & 255) * 0.11 > 140
            button.setStyleSheet("background-color: #%06x; color: %s;" % (rgb, "black" if light else "white"))

    def _restart_clock(self) -> None:
        self._clock.start()
        self._ticks_done = 0

    def _on_timer(self) -> None:
        if self.scene is None or not self._playing:
            return
        due = int(self._clock.elapsed() * FPS / 1000) - self._ticks_done
        if due <= 0:
            return
        for _ in range(min(due, MAX_TICKS_PER_EVENT)):
            self.scene.tick()
        self._ticks_done += due
        self._ticks_since_check += due
        self._update_status()
        self.canvas.update()

    def _update_status(self) -> None:
        if self.scene is None:
            return
        parts = []
        if self.helm_path and Path(self.helm_path).exists():
            parts.append("%s (%d KB)" % (self.scene.helm_link or Path(self.helm_path).name,
                                         max(1, Path(self.helm_path).stat().st_size // 1024)))
        elif self._helm_size:
            parts.append("%s (%d KB)" % (self.scene.helm_link, max(1, self._helm_size // 1024)))
        parts.append("Frame %d" % self.scene.rigs[self.scene.genders[0]].skel.frame)
        if self.morph_box.isChecked():
            if self._ticks_since_check >= MORPH_CHECK_EVERY:
                self._ticks_since_check = 0
                counts = self.scene.morph_check()
                if any(n > MORPH_TOLERANCE_PX for n in counts.values()):
                    self._morph_text = "Morph check: base head visible around the helm — %s" % ", ".join(
                        "%s: %d px" % (GENDER_NAMES[g], counts[g]) for g in counts if counts[g] > MORPH_TOLERANCE_PX)
                else:
                    self._morph_text = "Morph check: the helm covers the base head (male and female)"
            parts.append(self._morph_text)
        if self.scene.renderer.notes:
            parts.append("Approximated: " + "; ".join(sorted(self.scene.renderer.notes)))
        self.statusBar().showMessage("  |  ".join(parts))

    # ------------------------------------------------------------ actions

    def _on_label(self, label: str) -> None:
        if self.scene is not None and label.startswith(MOTION_PREFIX):
            self.scene.play_motion(label[len(MOTION_PREFIX):])
            self._restart_clock()
            self.canvas.update()
        elif self.scene is not None and label:
            self.scene.set_label(label)
            self._restart_clock()
            self.canvas.update()

    def _on_play(self) -> None:
        self._playing = not self._playing
        self.play_button.setText("Pause" if self._playing else "Play")
        if self._playing:
            self._restart_clock()

    def _on_morph(self, on: bool) -> None:
        self._ticks_since_check = MORPH_CHECK_EVERY
        self._update_status()
        self.canvas.update()

    def _on_background(self) -> None:
        color = QColorDialog.getColor(QColor(*self.background), self, "Background color")
        if color.isValid():
            self.background = (color.red(), color.green(), color.blue(), 255)
            self.canvas.update()

    def _pick_color(self, location: str) -> None:
        if self.scene is None:
            return
        color = QColorDialog.getColor(QColor(self.scene.colors.get(location) | 0xFF000000), self, "%s color" % location)
        if color.isValid():
            self.set_player_color(location, color.rgb() & 0xFFFFFF)

    def _on_reset_colors(self) -> None:
        defaults = PlayerColors()
        for location in LOCATION_ORDER:
            self.scene.set_color(location, defaults.get(location))
        self._refresh_swatches()
        self.canvas.update()

    def open_helm(self, path: str | Path) -> str | None:
        """Show another helm; returns an error message (and keeps the current helm) when the file cannot be used."""
        try:
            helm = MovieData(path)
            link = find_helm_link(helm, Path(path).name)
            if self.scene is not None:
                self.scene.set_helm(helm, link)
        except (ValueError, OSError) as e:
            return str(e)
        self.helm_path, self.link = Path(path), link
        self._update_title()
        if self.scene is not None:
            self._set_scene(self.scene)
        return None

    def set_helm_data(self, data: bytes, link: str) -> str | None:
        """Show a helm held in memory (the app's current helm); returns an error message and keeps the current helm
        when the data cannot be used."""
        try:
            helm = MovieData(data)
            if self.scene is not None:
                self.scene.set_helm(helm, link)
        except (ValueError, OSError) as e:
            return str(e)
        self.helm_path, self.link, self._helm_size = None, link, len(data)
        self._update_title()
        if self.scene is not None:
            self._set_scene(self.scene)
        return None

    def set_armor_data(self, data: bytes) -> str | None:
        """Wear an armor held in memory (Open SWF's edited file): only the genders it has are shown. Returns an
        error message and keeps the current armor when the data cannot be used."""
        from autoswf.items.structure import find_armor_link
        if self.scene is None:
            return "AQW reference files are not downloaded yet."
        try:
            movie = MovieData(data)
            link, genders = find_armor_link(movie, "the armor")
            scene = PreviewScene(self.scene.client, {g: movie for g in genders}, link, helm=self.scene.helm,
                                 helm_link=self.scene.helm_link, colors=self.scene.colors, genders=genders)
            scene.set_label(self.scene.label) if self.scene.label in scene.labels else None
        except (ValueError, OSError) as e:
            return str(e)
        self.armor = link
        self._set_scene(scene)
        return None

    def _on_open(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Open helm", "", "SWF files (*.swf)")
        if path:
            error = self.open_helm(path)
            if error:
                QMessageBox.warning(self, "Cannot open helm", error)

    def _on_save(self) -> None:
        if self.scene is None:
            return
        path, _ = QFileDialog.getSaveFileName(self, "Save PNG", "preview.png", "PNG images (*.png)")
        if path:
            self.scene.snapshot(self.canvas.width(), self.canvas.height(), **self.paint_options(self.canvas.height())).save(path)

    def _on_download(self) -> None:
        answer = QMessageBox.question(self, "Download AQW files", download_question(self.cache))
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.download_button.setEnabled(False)
        # A daemon thread: closing the window never waits for (or kills) a download in progress.
        self._worker = Downloader(self.cache, self.armor)
        self._worker.progress.connect(self.statusBar().showMessage)
        self._worker.finished.connect(self._on_downloaded)
        threading.Thread(target=self._worker.run, name="aqw-download", daemon=True).start()

    def _on_downloaded(self, error: str) -> None:
        self.download_button.setEnabled(True)
        if error:
            QMessageBox.warning(self, "Download failed", error)
            return
        try:
            scene = PreviewScene.from_cache(self.cache, self.helm_path, link=self.link, armor=self.armor)
        except (MissingReferenceFiles, ValueError, OSError) as e:
            QMessageBox.warning(self, "Cannot show the preview", str(e))
            return
        self._set_scene(scene)

    def closeEvent(self, event) -> None:
        self._timer.stop()
        super().closeEvent(event)


def run_preview(helm_path: Path | None, *, link: str | None = None, label: str = "Idle",
                armor: str = DEFAULT_ARMOR, colors: dict[str, int] | None = None, armor_data: Path | None = None) -> int:
    app = QApplication.instance() or QApplication([])
    from autoswf.qt_gc import GuiThreadCollector
    GuiThreadCollector(app).start()                 # Qt objects in cycles are never freed on the download thread
    cache = AqwCache(default_cache_dir())
    scene, problem = None, None
    try:
        scene = PreviewScene.from_cache(cache, helm_path, link=link, armor=armor, armor_data=armor_data)
        scene.set_label(label)
        for location, rgb in (colors or {}).items():
            scene.set_color(location, rgb)
    except MissingReferenceFiles as e:
        problem = str(e)
    except (ValueError, OSError) as e:
        print(e)
        return 1
    window = PreviewWindow(scene, cache=cache, helm_path=helm_path, link=link, armor=armor)
    if problem:
        window.empty_message = problem
    window.resize(1100, 720)
    window.show()
    return app.exec()
