import pytest
from PySide6.QtCore import QSettings

from autoswf.ai.nvidia import (check_connection, list_models, load_key, preferred_model, remove_key, save_key)
from autoswf.app.main import qt_arguments

KEY = "nvapi-test-0123456789"


def test_models_are_listed_and_nemotron_vl_is_preferred(fake_nvidia):
    models = list_models(KEY, base_url=fake_nvidia.url)
    assert preferred_model(models) == "nvidia/nemotron-3.5-super-vl-120b-a12b"
    assert fake_nvidia.auth[-1] == "Bearer " + KEY


@pytest.mark.parametrize("status,kind", [(200, "ok"), (401, "bad_key"), (403, "no_access"), (404, "no_access"),
                                         (429, "rate_limit"), (500, "error")])
def test_check_connection_reports_each_failure_kind(fake_nvidia, status, kind):
    fake_nvidia.status = status
    result = check_connection(KEY, "nvidia/nemotron-3.5-super-vl-120b-a12b", base_url=fake_nvidia.url)
    assert result.kind == kind and KEY not in result.message
    assert fake_nvidia.bodies[-1]["max_tokens"] == 1


def test_check_connection_offline():
    assert check_connection(KEY, "m", base_url="http://127.0.0.1:9/v1").kind == "offline"


def test_the_key_is_kept_by_keyring(memory_keyring):
    assert load_key() is None
    save_key(KEY)
    assert load_key() == KEY and memory_keyring.store == {("AutoSWF", "nvidia-api-key"): KEY}
    remove_key()
    assert load_key() is None


def test_wintab_setting_adds_the_platform_option(tmp_path):
    s = QSettings(str(tmp_path / "ui.ini"), QSettings.Format.IniFormat)
    assert qt_arguments(["AutoSWF.exe"], s) == ["AutoSWF.exe"]
    s.setValue("tablet/wintab", True)
    assert qt_arguments(["AutoSWF.exe"], s) == ["AutoSWF.exe", "-platform", "windows:wintab"]
    assert qt_arguments(["AutoSWF.exe", "-platform", "offscreen"], s) == ["AutoSWF.exe", "-platform", "offscreen"]
