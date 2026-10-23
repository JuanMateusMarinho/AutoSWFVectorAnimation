# tests/ruffle/test_launch.py
import subprocess
from pathlib import Path

from autoswf.ruffle.launch import ARTIX_LAUNCHER, ARTIX_RUFFLE, armor_errors, find_ruffle, launch_ruffle


def touch(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"")
    return path


def test_find_ruffle_prefers_the_users_choice_then_the_games_launcher_then_the_old_launcher(tmp_path):
    old = touch(tmp_path / "PF" / ARTIX_RUFFLE)
    new = touch(tmp_path / "LocalApp" / ARTIX_LAUNCHER)
    chosen = touch(tmp_path / "Downloads" / "Artix Games Launcher.exe")        # a portable copy the user picked
    dirs = [tmp_path / "LocalApp", tmp_path / "PF"]
    assert find_ruffle(str(chosen), dirs) == chosen
    assert find_ruffle(None, dirs) == new
    assert find_ruffle(None, [tmp_path / "PF"]) == old
    assert find_ruffle(str(tmp_path / "gone.exe"), [tmp_path / "none"]) is None     # moved or uninstalled


def test_ruffle_starts_on_the_test_swf_with_a_window_size_and_its_log_piped(tmp_path, monkeypatch):
    calls = []

    class FakePopen:
        def __init__(self, args, **options):
            calls.append((args, options))

    monkeypatch.setattr(subprocess, "Popen", FakePopen)
    launch_ruffle(tmp_path / "ruffle.exe", tmp_path / "t.swf", width=1000, height=680)
    args, options = calls[0]
    assert args == [str(tmp_path / "ruffle.exe"), "--width", "1000", "--height", "680", str(tmp_path / "t.swf")]
    assert options["stdout"] is subprocess.PIPE and "avm2" in options["env"]["RUST_LOG"]


def test_armor_errors_come_from_ruffles_log():
    lines = ['2026-10-23T18:20:20.778446Z \x1b[31mERROR\x1b[0m ruffle_core::avm2::events: Error dispatching event '
             'EventObject { type: "addedToStage", class: flash.events::Event, ptr: 0x1 } to handler '
             'FunctionObject(FunctionObject { ptr: 0x2, name: "TestReleaseMHead/onAdded()" }) : ArgumentError: '
             'Duplicate trigger\n',
             "2026-10-23T18:20:20.779955Z  INFO avm_trace: AUTOSWF CHECK ui | PASS\n",
             "2026-10-23T18:20:18.772461Z  WARN wgpu_hal::vulkan::conv: Unrecognized present mode 1000361000\n"]
    assert armor_errors(lines) == ["TestReleaseMHead/onAdded(): ArgumentError: Duplicate trigger"]
