# tests/app/test_smoke.py
import json

from autoswf.app.main import run_app


def test_smoke_test_imports_builds_and_exports(qapp, tmp_path):
    out = tmp_path / "smoke.json"
    assert run_app(["--smoke-test", str(out)]) == 0
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["ok"] and data["problems"] == [] and data["size"] > 0 and data["version"] == "0.1.0"


def test_an_unexpected_error_is_shown_and_logged(qapp, tmp_path, monkeypatch):
    import sys
    import threading
    from autoswf.app.main import install_error_report
    monkeypatch.setattr(sys, "excepthook", sys.excepthook)
    monkeypatch.setattr(threading, "excepthook", threading.excepthook)
    shown = []
    install_error_report(tmp_path / "logs", show=shown.append)
    try:
        raise RuntimeError("boom")
    except RuntimeError:
        sys.excepthook(*sys.exc_info())
    log = (tmp_path / "logs" / "autoswf.log").read_text(encoding="utf-8")
    assert "RuntimeError: boom" in log and "boom" in shown[0] and str(tmp_path / "logs") in shown[0]
    worker = threading.Thread(target=lambda: 1 / 0)
    worker.start()
    worker.join()
    assert "ZeroDivisionError" in (tmp_path / "logs" / "autoswf.log").read_text(encoding="utf-8")
    assert len(shown) == 1                                   # another thread only logs (no window off the GUI thread)
