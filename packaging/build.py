"""Build the Windows app: PyInstaller one-folder build (dist/AutoSWF), a check that nothing from AQW or the user's
art got in, the packaged app's own smoke test, then the installer (Inno Setup) unless --skip-installer.

    python packaging/build.py [--skip-installer]
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import zipfile
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


def app_version() -> str:
    text = (ROOT / "src" / "autoswf" / "__init__.py").read_text(encoding="utf-8")
    return re.search(r'__version__ = "([^"]+)"', text).group(1)


def find_iscc() -> Path | None:
    """Inno Setup's compiler: on PATH, or where its installer puts it (for all users or for this user)."""
    found = shutil.which("ISCC")
    if found:
        return Path(found)
    bases = [os.environ.get("ProgramFiles(x86)"), os.environ.get("ProgramFiles")]
    if os.environ.get("LOCALAPPDATA"):
        bases.append(str(Path(os.environ["LOCALAPPDATA"]) / "Programs"))
    for base in filter(None, bases):
        path = Path(base) / "Inno Setup 6" / "ISCC.exe"
        if path.is_file():
            return path
    return None


def package(dist: Path, version: str) -> tuple[Path | None, str]:
    """dist/AutoSWF-Setup-<version>.exe, or a zip of dist/AutoSWF when Inno Setup is not installed."""
    iscc = find_iscc()
    if iscc is None:
        path = dist / ("AutoSWF-%s-win64.zip" % version)
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
            for p in sorted((dist / "AutoSWF").rglob("*")):
                if p.is_file():
                    z.write(p, p.relative_to(dist).as_posix())
        return path, "Inno Setup was not found: wrote a zip instead. Install Inno Setup 6 to build the installer."
    command = [str(iscc), "/Q", "/DAppVersion=" + version, "/DDistDir=" + str(Path(dist).resolve()),
               str(ROOT / "packaging" / "autoswf.iss")]
    if subprocess.run(command, cwd=ROOT).returncode != 0:
        return None, "Inno Setup failed"
    path = dist / ("AutoSWF-Setup-%s.exe" % version)
    return path, "Built the installer %s (%.0f MB)" % (path, path.stat().st_size / 2 ** 20)


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
    if args.skip_installer:
        return 0
    path, message = package(dist, app_version())
    print(message)
    return 0 if path is not None else 1


if __name__ == "__main__":
    sys.exit(main())
