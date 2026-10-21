# PyInstaller spec for AutoSWF: a one-folder Windows build (dist/AutoSWF/AutoSWF.exe).
# Build with: python packaging/build.py   (nothing from cache/ is ever packaged; the build script checks it)
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files

ROOT = Path(SPECPATH).parent
EXCLUDES = ["tkinter", "cv2", "pytest", "_pytest", "IPython",
            "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtWebEngineQuick",
            "PySide6.QtWebChannel", "PySide6.QtQuick", "PySide6.QtQuickWidgets", "PySide6.QtQml",
            "PySide6.Qt3DCore", "PySide6.Qt3DRender", "PySide6.QtMultimedia", "PySide6.QtPdf",
            "PySide6.QtPdfWidgets", "PySide6.QtCharts", "PySide6.QtDataVisualization", "PySide6.QtNetwork",
            "PySide6.QtSql", "PySide6.QtTest", "PySide6.QtOpenGL", "PySide6.QtOpenGLWidgets"]
DROP = ("Qt6WebEngine", "Qt6Quick", "Qt6Qml", "Qt6Pdf", "Qt63D", "Qt6Multimedia", "Qt6Charts",
        "Qt6DataVisualization", "Qt6WebChannel", "qtwebengine", "QtWebEngine")

a = Analysis([str(ROOT / "src" / "autoswf" / "app" / "main.py")],
             pathex=[str(ROOT / "src")],
             datas=collect_data_files("clipparse") + collect_data_files("psd_tools"),
             hiddenimports=["keyring.backends.Windows", "pyclipper"],
             excludes=EXCLUDES,
             noarchive=False)
a.binaries = [b for b in a.binaries if not any(k in b[0] for k in DROP)]
a.datas = [d for d in a.datas if not any(k in d[0] for k in DROP)]
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="AutoSWF", console=False, debug=False, strip=False,
          upx=False)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="AutoSWF")
