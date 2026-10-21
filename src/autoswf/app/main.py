"""Start the AutoSWF app (`AutoSWF.exe`, `python -m autoswf app`): `[FILE]` opens a drawing, a project or a SWF;
`--smoke-test OUT.json` imports a built-in mini drawing, builds and exports it, opens the window and writes the result
(used to check the packaged app)."""
import argparse
import json
import os
import sys
import tempfile
import threading
import time
import traceback
from pathlib import Path
from typing import Callable


def smoke_drawing(path: Path) -> None:
    """A small layered helm drawing (flats, shadow, line art) written as a PSD."""
    import numpy as np
    from autoswf.drawing.writers import LayerSpec, write_psd
    size = 400
    yy, xx = np.mgrid[0:size, 0:size].astype(np.float32) + 0.5

    def disc(color, cx, cy, r):
        out = np.zeros((size, size, 4), np.uint8)
        inside = (xx - cx) ** 2 + (yy - cy) ** 2 <= r * r
        out[inside] = color
        return out

    flats = disc((242, 201, 160, 255), 200, 215, 120)
    hair = disc((110, 60, 160, 255), 200, 150, 125)
    hair[230:] = 0
    flats[hair[..., 3] > 0] = hair[hair[..., 3] > 0]
    shadow = disc((0, 0, 0, 90), 230, 260, 70)
    shadow[flats[..., 3] == 0] = 0
    line = disc((20, 20, 20, 255), 200, 215, 124)
    line[disc((0, 0, 0, 255), 200, 215, 119)[..., 3] > 0] = 0
    write_psd(path, size, size, [LayerSpec("Flats", flats), LayerSpec("Shadow", shadow, blend="multiply", clipping=True),
                                 LayerSpec("Line", line)])


def run_smoke_test(out: Path) -> int:
    from PySide6.QtCore import QSettings
    from PySide6.QtWidgets import QApplication
    from autoswf import __version__
    from autoswf.app.controller import ProjectController
    from autoswf.app.theme import apply_dark_theme
    from autoswf.app.window import MainWindow
    from autoswf.aqw.assets import AqwCache
    from autoswf.aqw.validate import validate_helm_swf
    app = QApplication.instance() or QApplication(["AutoSWF"])
    result = {"ok": False, "version": __version__, "link": None, "size": 0, "problems": []}
    try:
        folder = Path(tempfile.mkdtemp(prefix="autoswf-smoke-"))
        drawing = folder / "Smoke Helm.psd"
        smoke_drawing(drawing)
        cache = AqwCache(folder / "cache")
        controller = ProjectController(cache, threaded=False)
        controller.import_drawing(drawing)
        build = controller.build
        if build.error:
            result["problems"].append(build.error)
        else:
            (folder / ("%s.swf" % build.link)).write_bytes(build.swf)
            result["problems"] += validate_helm_swf(build.swf, build.link)
            result.update(link=build.link, size=len(build.swf))
        apply_dark_theme(app)
        window = MainWindow(controller, cache, settings_store=QSettings(str(folder / "ui.ini"), QSettings.Format.IniFormat))
        window.show()
        app.processEvents()
        window.close()
        result["ok"] = not result["problems"]
    except Exception as e:                          # everything goes into the report: the packaged app has no console
        result["problems"].append("%s: %s" % (type(e).__name__, e))
        result["traceback"] = traceback.format_exc()
    Path(out).write_text(json.dumps(result, indent=2), encoding="utf-8")
    return 0 if result["ok"] else 1


def log_folder() -> Path:
    return Path(os.environ.get("LOCALAPPDATA") or tempfile.gettempdir()) / "AutoSWF" / "logs"


def install_error_report(folder: Path, show: Callable[[str], None] | None = None) -> None:
    """An unexpected error never passes silently (the packaged app has no console): it is written to
    FOLDER/autoswf.log and, on the GUI thread, shown in a message."""
    log = Path(folder) / "autoswf.log"

    def show_box(text: str) -> None:
        from PySide6.QtWidgets import QMessageBox
        QMessageBox.critical(None, "Unexpected error", text)

    def report(kind, value, tb) -> None:
        details = "".join(traceback.format_exception(kind, value, tb))
        try:
            log.parent.mkdir(parents=True, exist_ok=True)
            with open(log, "a", encoding="utf-8") as f:
                f.write("%s AutoSWF\n%s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), details))
        except OSError:
            pass
        if sys.stderr is not None:
            sys.stderr.write(details)
        if threading.current_thread() is threading.main_thread():
            (show or show_box)("AutoSWF hit an unexpected error and the last action may not have finished:\n\n"
                               "%s: %s\n\nThe details were written to %s" % (kind.__name__, value, log))

    sys.excepthook = report
    threading.excepthook = lambda args: report(args.exc_type, args.exc_value, args.exc_traceback)


def run_app(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="AutoSWF", description="AutoSWF: turn drawings into AQW items")
    parser.add_argument("file", nargs="?", help="a drawing, an AutoSWF project (.aswf) or a SWF to open")
    parser.add_argument("--smoke-test", metavar="OUT.json", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.smoke_test:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        return run_smoke_test(Path(args.smoke_test))
    from PySide6.QtWidgets import QApplication, QMessageBox
    from autoswf.app.controller import ProjectController
    from autoswf.app.theme import apply_dark_theme
    from autoswf.app.window import MainWindow
    from autoswf.aqw.assets import AqwCache, default_cache_dir
    from autoswf.qt_gc import GuiThreadCollector
    app = QApplication.instance() or QApplication(["AutoSWF"])
    app.setApplicationName("AutoSWF")
    app.setOrganizationName("AutoSWF")
    collector = GuiThreadCollector(app)             # Qt objects in cycles are never freed on the build thread
    collector.start()
    install_error_report(log_folder())
    apply_dark_theme(app)
    cache = AqwCache(default_cache_dir())
    window = MainWindow(ProjectController(cache), cache)
    window.show()
    window.first_run()
    if args.file:
        error = window.open_path(args.file)
        if error:
            QMessageBox.warning(window, "Open", error)
    return app.exec()


def main() -> None:
    sys.exit(run_app(sys.argv[1:]))


if __name__ == "__main__":
    main()
