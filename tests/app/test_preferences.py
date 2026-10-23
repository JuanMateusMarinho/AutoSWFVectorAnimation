import time
from pathlib import Path

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

from app_helpers import window
from autoswf.app.preferences import PreferencesDialog

KEY = "nvapi-secret-9876543210"


def wait_until(condition, seconds=10.0):
    end = time.time() + seconds
    while time.time() < end and not condition():
        QApplication.processEvents()
        time.sleep(0.02)
    return condition()


def test_the_ruffle_page_chooses_a_ruffle_and_goes_back_to_the_default(qapp, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QFileDialog
    from autoswf.ruffle import launch
    store = QSettings(str(tmp_path / "ui.ini"), QSettings.Format.IniFormat)
    portable = tmp_path / "Artix Games Launcher.exe"
    portable.write_bytes(b"")
    monkeypatch.setattr(launch, "find_ruffle", lambda saved, dirs=None: Path(saved) if saved else None)
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *a, **k: (str(portable), ""))
    d = PreferencesDialog(store)
    assert "No Ruffle found" in d.ruffle_label.text()
    d.choose_ruffle()
    assert store.value("ruffle/path") == str(portable) and str(portable) in d.ruffle_label.text()
    d.default_ruffle()
    assert store.value("ruffle/path") is None and "No Ruffle found" in d.ruffle_label.text()


def test_preferences_preselect_nemotron_vl_and_keep_a_missing_choice(qapp, tmp_path, fake_nvidia, memory_keyring):
    store = QSettings(str(tmp_path / "ui.ini"), QSettings.Format.IniFormat)
    d = PreferencesDialog(store, base_url=fake_nvidia.url)
    d.key_edit.setText(KEY)
    d.save_key()
    d.refresh_models()
    assert wait_until(lambda: d.model_box.count() == 3)
    assert d.model_box.currentText() == "nvidia/nemotron-3.5-super-vl-120b-a12b"
    store.setValue("ai/model", "nvidia/retired-model")
    d2 = PreferencesDialog(store, base_url=fake_nvidia.url)
    d2.refresh_models()
    assert wait_until(lambda: d2.model_box.count() == 4)
    assert d2.model_box.currentText() == "nvidia/retired-model"
    assert "is not in NVIDIA's list right now" in d2.status.text()


def test_test_connection_reports_in_plain_words(qapp, tmp_path, fake_nvidia, memory_keyring):
    store = QSettings(str(tmp_path / "ui.ini"), QSettings.Format.IniFormat)
    d = PreferencesDialog(store, base_url=fake_nvidia.url)
    d.key_edit.setText(KEY)
    d.save_key()
    d.model_box.addItem("nvidia/nemotron-3.5-super-vl-120b-a12b")
    fake_nvidia.status = 401
    d.test_connection()
    assert wait_until(lambda: "refused" in d.status.text())


def test_the_key_never_lands_in_any_file(qapp, tmp_path, fake_nvidia, memory_keyring, app_cache):
    w = window(app_cache, tmp_path)
    d = PreferencesDialog(w.settings_store, base_url=fake_nvidia.url)
    d.key_edit.setText(KEY)
    d.save_key()
    assert d.key_edit.text() == "" and "A key is saved" in d.key_edit.placeholderText()
    w.settings_store.sync()
    for f in tmp_path.rglob("*"):
        if f.is_file():
            assert KEY.encode() not in f.read_bytes(), f
    assert memory_keyring.store[("AutoSWF", "nvidia-api-key")] == KEY


def test_edit_menu_opens_preferences(qapp, tmp_path, app_cache):
    w = window(app_cache, tmp_path)
    assert w.actions["preferences"].shortcut().toString() == "Ctrl+K"
