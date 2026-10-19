"""Build the Windows app: PyInstaller one-folder build (dist/AutoSWF), a check that nothing from AQW or the user's
art got in, the packaged app's own smoke test, then the installer (Inno Setup) unless --skip-installer.

    python packaging/build.py [--skip-installer]
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN = (".swf", ".clip", ".psd", ".psb")


def check_dist(dist: Path) -> list[str]:
    """Files that must never be packaged: AQW files and the user's drawings (relative paths)."""
    return sorted(p.relative_to(dist).as_posix() for p in Path(dist).rglob("*")
                  if p.is_file() and p.suffix.lower() in FORBIDDEN)


def folder_size(folder: Path) -> int:
    return sum(p.stat().st_size for p in Path(folder).rglob("*") if p.is_file())


def build_exe(dist: Path) -> int:
    command = [sys.executable, "-m", "PyInstaller", str(ROOT / "packaging" / "autoswf.spec"), "--noconfirm", "--clean",
               "--distpath", str(dist), "--workpath", str(ROOT / "build" / "pyinstaller")]
    return subprocess.run(command, cwd=ROOT).returncode


def smoke_test(exe: Path, out: Path) -> dict:
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.exists():
        out.unlink()
    subprocess.run([str(exe), "--smoke-test", str(out)], timeout=600)
    if not out.exists():
        return {"ok": False, "problems": ["the app wrote no smoke-test report"]}
    return json.loads(out.read_text(encoding="utf-8"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--skip-installer", action="store_true", help="build the app folder only")
    args = parser.parse_args(argv)
    dist = ROOT / "dist"
    if build_exe(dist) != 0:
        print("PyInstaller failed")
        return 1
    app = dist / "AutoSWF"
    bad = check_dist(app)
    if bad:
        print("These files must never be packaged:\n  " + "\n  ".join(bad))
        return 1
    report = smoke_test(app / "AutoSWF.exe", ROOT / "build" / "smoke.json")
    if not report.get("ok"):
        print("Smoke test failed: %s" % "; ".join(report.get("problems", [])))
        if report.get("traceback"):
            print(report["traceback"])
        return 1
    print("Smoke test passed (helm %s, %d bytes)" % (report.get("link"), report.get("size", 0)))
    print("Built %s (%.0f MB)" % (app, folder_size(app) / 2 ** 20))
    return 0


if __name__ == "__main__":
    sys.exit(main())
