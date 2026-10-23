"""Compile the Ruffle test stage (src/autoswf/ruffle/stage/*.as) into src/autoswf/ruffle/stage.abc with FFDec's
compiler, on the developer's machine (users never need Java or FFDec). Run it after changing the .as files:

    python tools/build_ruffle_stage.py [--ffdec DIR] [--java EXE]

FFDec (its folder in AUTOSWF_FFDEC, as for the fidelity checks) compiles the sources into a stub SWF whose classes have
the same names; its single ABC is kept. Java: AUTOSWF_JAVA, else java on PATH, else Android Studio's."""
import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from autoswf.abc.movieclip_classes import ClassSpec, build_abc  # noqa: E402
from autoswf.model.document import Frame, Symbol  # noqa: E402
from autoswf.ruffle.stagecode import ABC_FILE, RECORD_FILE, STAGE_DIR, sources_digest  # noqa: E402
from autoswf.swf.decode import MovieData  # noqa: E402
from autoswf.swf.movie import build_swf  # noqa: E402

ANDROID_STUDIO_JAVA = Path(os.environ.get("ProgramFiles", r"C:\Program Files"), "Android", "Android Studio", "jbr", "bin",
                           "java.exe")


def default_java() -> str | None:
    if os.environ.get("AUTOSWF_JAVA"):
        return os.environ["AUTOSWF_JAVA"]
    return shutil.which("java") or (str(ANDROID_STUDIO_JAVA) if ANDROID_STUDIO_JAVA.exists() else None)


def compile_stage(ffdec_dir: Path, java: str) -> bytes:
    """Compile the stage, write stage.abc and its record, and return the ABC."""
    names = sorted(p.stem for p in STAGE_DIR.glob("*.as"))
    with tempfile.TemporaryDirectory() as tmp:
        stub, out = Path(tmp) / "stub.swf", Path(tmp) / "stage.swf"
        symbols = [Symbol(name, [Frame()]) for name in names]
        stub.write_bytes(build_swf(symbols, {id(s): n for s, n in zip(symbols, names)},
                                   build_abc([ClassSpec(n) for n in names])))
        command = [java, "-jar", str(Path(ffdec_dir) / "ffdec-cli.jar"), "-onerror", "abort", "-importScript",
                   str(stub), str(out), str(STAGE_DIR)]
        result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace")
        if result.returncode != 0 or not out.exists():
            raise RuntimeError("FFDec could not compile the stage:\n%s\n%s" % (result.stdout, result.stderr))
        abcs = MovieData(out).abcs
    if len(abcs) != 1 or abcs[0].major != 46:
        raise RuntimeError("Expected one Flash ABC (46.x), got %s" % [(a.major, a.minor) for a in abcs])
    compiled = {abcs[0].mname(i["name"]) for i in abcs[0].instances}
    if compiled != set(names):
        raise RuntimeError("Compiled classes %s differ from the sources %s" % (sorted(compiled), names))
    abc = bytes(abcs[0].d)
    ABC_FILE.write_bytes(abc)
    RECORD_FILE.write_text(json.dumps({"sources": sources_digest()}, indent=1) + "\n", encoding="utf-8")
    return abc


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--ffdec", default=os.environ.get("AUTOSWF_FFDEC"), help="FFDec's folder (has ffdec-cli.jar)")
    parser.add_argument("--java", default=default_java())
    args = parser.parse_args()
    if not args.ffdec or not args.java:
        parser.error("set AUTOSWF_FFDEC to FFDec's folder (or pass --ffdec) and make Java available (AUTOSWF_JAVA, "
                     "PATH or Android Studio)")
    abc = compile_stage(Path(args.ffdec), args.java)
    print("Built %s (%d bytes)" % (ABC_FILE, len(abc)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
