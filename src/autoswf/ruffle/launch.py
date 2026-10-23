"""Finding and starting the user's Ruffle for Open in Ruffle (spec §5.7): the Ruffle they chose, else the official Artix
Games Launcher 2.x (itself a Ruffle desktop build that plays a SWF given on its command line), else the older Artix Game
Launcher's ruffle.exe. Ruffle's log is piped: it is where Ruffle reports errors the armor's code throws (the test stage
never hears of them), and AutoSWF shows them."""
import os
import re
import subprocess
import threading
from pathlib import Path
from typing import Iterable

from PySide6.QtCore import QObject, Signal

ARTIX_LAUNCHER = Path("Artix Games Launcher", "Artix Games Launcher.exe")
ARTIX_RUFFLE = Path("Artix Game Launcher", "resources", "ruffle", "ruffle.exe")
SETTINGS_KEY = "ruffle/path"
LOG_FILTER = "error,avm_trace=info"           # Ruffle's errors, and the traces where the stage reports armor errors
_ANSI = re.compile(r"\x1b\[[0-9;]*m")
_AVM2_ERROR = re.compile(r"\bERROR\s+ruffle_core::avm2\S*:\s*(.*)$")
_FRAME_SCRIPT = re.compile(r"\bERROR\s+ruffle_core::\S*:\s*Error occurred when running AVM2 frame script:\s*(.*)$")
_STAGE_REPORT = re.compile(r"AUTOSWF ARMOR ERROR (.*)$")
_HANDLER = re.compile(r'name: "([^"]+)" \}\) : (.+)$')


def program_dirs() -> list[Path]:
    """Where launchers get installed: the user's local app data (and its Programs), then Program Files."""
    out = []
    local = os.environ.get("LOCALAPPDATA")
    if local:
        out += [Path(local), Path(local) / "Programs"]
    for key in ("ProgramFiles", "ProgramFiles(x86)"):
        if os.environ.get(key):
            out.append(Path(os.environ[key]))
    return out


def find_ruffle(saved: str | None, dirs: list[Path] | None = None) -> Path | None:
    """The Ruffle to use; a saved path that no longer exists is ignored."""
    if saved and Path(saved).is_file():
        return Path(saved)
    for name in (ARTIX_LAUNCHER, ARTIX_RUFFLE):
        for folder in program_dirs() if dirs is None else dirs:
            if (Path(folder) / name).is_file():
                return Path(folder) / name
    return None


def launch_ruffle(ruffle: Path, swf: Path, *, width: int = 1000, height: int = 680) -> subprocess.Popen:
    """Start Ruffle on `swf` without waiting; its log comes out on the process's stdout."""
    env = dict(os.environ, RUST_LOG=LOG_FILTER)
    return subprocess.Popen([str(ruffle), "--width", str(width), "--height", str(height), str(swf)],
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=env, text=True, encoding="utf-8",
                            errors="replace")


def armor_errors(lines: Iterable[str]) -> list[str]:
    """The errors in Ruffle's log: AVM2 errors ("<Class/handler()>: <error>" when an event handler threw), errors in
    frame scripts ("frame script: <error>") and the ones the stage caught itself."""
    out = []
    for line in lines:
        text = _ANSI.sub("", line).strip()
        frame = _FRAME_SCRIPT.search(text)
        stage = _STAGE_REPORT.search(text)
        found = _AVM2_ERROR.search(text)
        if frame is not None:
            out.append("frame script: %s" % frame.group(1))
        elif stage is not None:
            out.append(stage.group(1))
        elif found is not None:
            handler = _HANDLER.search(found.group(1))
            out.append("%s: %s" % handler.groups() if handler else found.group(1))
    return out


class RuffleWatcher(QObject):
    """Reads a Ruffle process's log on a thread and reports each armor error (on the GUI thread, through the
    signal)."""
    error = Signal(str)

    def __init__(self, process):
        super().__init__()
        self._process = process

    def start(self) -> None:
        threading.Thread(target=self._read, name="ruffle-log", daemon=True).start()

    def _read(self) -> None:
        try:
            for line in self._process.stdout:
                for message in armor_errors([line]):
                    self.error.emit(message)
        except (OSError, ValueError):
            pass
