# tests/app/test_smoke.py
import json

from autoswf.app.main import run_app


def test_smoke_test_imports_builds_and_exports(qapp, tmp_path):
    out = tmp_path / "smoke.json"
    assert run_app(["--smoke-test", str(out)]) == 0
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["ok"] and data["problems"] == [] and data["size"] > 0 and data["version"] == "0.1.0"
