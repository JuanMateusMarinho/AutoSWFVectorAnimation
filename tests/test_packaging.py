# tests/test_packaging.py
import importlib.util
import json
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def build_module():
    spec = importlib.util.spec_from_file_location("build_exe", ROOT / "packaging" / "build.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_dist_check_refuses_aqw_and_user_files(tmp_path):
    dist = tmp_path / "AutoSWF"
    (dist / "_internal").mkdir(parents=True)
    (dist / "AutoSWF.exe").write_bytes(b"MZ")
    assert build_module().check_dist(dist) == []
    (dist / "_internal" / "KindOfBrave.swf").write_bytes(b"CWS")
    assert build_module().check_dist(dist) == ["_internal/KindOfBrave.swf"]


def test_spec_leaves_out_what_the_app_does_not_use():
    text = (ROOT / "packaging" / "autoswf.spec").read_text(encoding="utf-8")
    for name in ("PySide6.QtWebEngineCore", "PySide6.QtQuick", "cv2", "tkinter", "clipparse"):
        assert name in text


@pytest.mark.exe
def test_the_built_exe_passes_its_smoke_test(tmp_path):
    exe = ROOT / "dist" / "AutoSWF" / "AutoSWF.exe"
    if not exe.exists():
        pytest.skip("build the exe first: python packaging/build.py --skip-installer")
    out = tmp_path / "smoke.json"
    subprocess.run([str(exe), "--smoke-test", str(out)], timeout=300, check=True)
    assert json.loads(out.read_text(encoding="utf-8"))["ok"]


def test_without_inno_setup_the_build_writes_a_zip(tmp_path, monkeypatch):
    import zipfile
    b = build_module()
    monkeypatch.setattr(b, "find_iscc", lambda: None)
    dist = tmp_path / "dist"
    (dist / "AutoSWF").mkdir(parents=True)
    (dist / "AutoSWF" / "AutoSWF.exe").write_bytes(b"MZ")
    path, message = b.package(dist, "0.1.0")
    assert path.name == "AutoSWF-0.1.0-win64.zip" and "Inno Setup was not found" in message
    assert zipfile.ZipFile(path).namelist() == ["AutoSWF/AutoSWF.exe"]


def test_the_installer_script_installs_per_user():
    text = (ROOT / "packaging" / "autoswf.iss").read_text(encoding="utf-8")
    assert "PrivilegesRequired=lowest" in text and r"{localappdata}\Programs\AutoSWF" in text


def test_packaging_lists_the_new_hidden_imports():
    from pathlib import Path
    spec = (Path(__file__).resolve().parents[1] / "packaging" / "autoswf.spec").read_text(encoding="utf-8")
    assert '"keyring.backends.Windows"' in spec and '"pyclipper"' in spec
