"""Run the Ruffle test stage's self-test in the user's Ruffle: the stage (flashvar selftest=1) traces
"AUTOSWF CHECK <name> | <PASS|FAIL detail|SKIP why>" lines and "AUTOSWF DONE"; Ruffle desktop prints traces on stdout
when RUST_LOG enables avm_trace (found in Plan 8 Task 1)."""
import os
import queue
import subprocess
import threading
from pathlib import Path

from autoswf.swf.decode import MovieData

ARTIX_RUFFLE = Path("Artix Game Launcher", "resources", "ruffle", "ruffle.exe")
MAIN_CACHE = Path(__file__).resolve().parents[1] / "cache"


def installed_ruffle() -> Path | None:
    """AUTOSWF_RUFFLE (e.g. the Artix Games Launcher 2.x exe, a Ruffle desktop build), else the Artix Game Launcher's."""
    if os.environ.get("AUTOSWF_RUFFLE") and Path(os.environ["AUTOSWF_RUFFLE"]).exists():
        return Path(os.environ["AUTOSWF_RUFFLE"])
    for base in (os.environ.get("ProgramFiles"), os.environ.get("ProgramFiles(x86)")):
        if base and (Path(base) / ARTIX_RUFFLE).exists():
            return Path(base) / ARTIX_RUFFLE
    return None


def make_test_swf(folder: Path, armor: bytes, client: str = "mini") -> Path:
    """A test SWF for `armor` on the mini client's skeleton, or on the cached AQW client (client="aqw")."""
    from aqw_fakes import mini_client
    from autoswf.aqw.assets import AqwCache, default_cache_dir
    from autoswf.ruffle.settings import stage_settings
    from autoswf.ruffle.testswf import build_test_swf
    if client == "aqw":
        cache = AqwCache(os.environ.get("AUTOSWF_CACHE") or default_cache_dir())
        client_movie = MovieData(cache.client_path())
    else:
        client_movie = MovieData(mini_client())
    path = Path(folder) / "test.swf"
    path.write_bytes(build_test_swf(armor, stage_settings(client_movie, MovieData(armor))))
    return path


def run_selftest(ruffle: Path, swf: Path, timeout: float = 60) -> dict[str, str]:
    """check name -> its result ("PASS", "FAIL detail" or "SKIP why")."""
    env = dict(os.environ, RUST_LOG="avm_trace=info,warn")
    process = subprocess.Popen([str(ruffle), "--width", "960", "--height", "600", "-Pselftest=1", str(swf)],
                               stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=env, text=True,
                               encoding="utf-8", errors="replace")
    lines: queue.Queue = queue.Queue()
    threading.Thread(target=lambda: [lines.put(line) for line in process.stdout], daemon=True).start()
    checks, log = {}, []
    try:
        while True:
            try:
                line = lines.get(timeout=timeout)
            except queue.Empty:
                checks["finished"] = "FAIL no AUTOSWF DONE within %s s; log tail: %s" % (timeout, log[-5:])
                break
            log.append(line.rstrip())
            if "AUTOSWF CHECK " in line:
                name, _, result = line.split("AUTOSWF CHECK ", 1)[1].partition(" | ")
                checks[name.strip()] = result.strip()
            elif "AUTOSWF DONE" in line:
                break
    finally:
        process.kill()
        process.wait(10)
    return checks
