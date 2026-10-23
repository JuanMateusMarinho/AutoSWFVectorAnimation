# tests/ruffle/test_in_ruffle.py — the test stage itself, run in the user's Ruffle (Artix Game Launcher build)
import pytest

from ruffle_selftest import installed_ruffle, make_test_swf, run_selftest

pytestmark = pytest.mark.ruffle


@pytest.fixture
def ruffle_exe():
    path = installed_ruffle()
    if path is None:
        pytest.skip("Ruffle (Artix Game Launcher) is not installed")
    return path


def failures(checks: dict[str, str]) -> dict[str, str]:
    return {name: result for name, result in checks.items() if result.startswith("FAIL")}


AVATAR_CHECKS = ("listeners", "idle", "anchored", "hair hidden", "skill Attack1", "back to Idle", "color Hair", "ui")
WINDOW_CHECKS = ("list rows", "list scrolls to end", "nothing off window", "pause holds", "step +1", "step -1", "zoom",
                 "background", "gender switch", "walk", "arrive Idle", "faces target", "walks into range", "dummy hit",
                 # the final review's fixes
                 "status follows the head", "step back after the armor returns", "motion then Idle", "list scrollbar",
                 "head follows the skeleton")


def test_the_stage_builds_the_avatar_like_aqw(tmp_path, ruffle_exe):
    from aqw_fakes import release_armor_swf
    checks = run_selftest(ruffle_exe, make_test_swf(tmp_path, release_armor_swf()))
    for name in AVATAR_CHECKS + WINDOW_CHECKS:
        assert checks.get(name) == "PASS", (name, checks)
    assert not failures(checks), checks


def test_an_armor_with_both_heads_gets_a_male_female_switch(tmp_path, ruffle_exe):
    from aqw_fakes import release_armor_swf
    checks = run_selftest(ruffle_exe, make_test_swf(tmp_path, release_armor_swf(genders=("M", "F"))))
    assert checks.get("gender switch") == "PASS" and not failures(checks), checks


def test_an_armor_that_throws_still_gets_its_window(tmp_path, ruffle_exe):
    # Ruffle logs an error thrown in the armor's own event handlers (its bind() here) and does not pass it to the
    # stage; AutoSWF reads it from Ruffle's log (Task 5). The window must keep working with what was registered.
    from aqw_fakes import throwing_armor_swf
    checks = run_selftest(ruffle_exe, make_test_swf(tmp_path, throwing_armor_swf()))
    assert "finished" not in checks, checks                              # it reached AUTOSWF DONE
    assert checks.get("ui") == "PASS" and checks.get("listeners") == "PASS", checks
    assert checks.get("skill Attack1") == "PASS", checks                 # registered before the throw


def test_a_head_that_throws_when_made_shows_the_error_and_the_window(tmp_path, ruffle_exe):
    from aqw_fakes import release_armor_swf
    from autoswf.ruffle.launch import armor_errors
    log = []
    checks = run_selftest(ruffle_exe, make_test_swf(tmp_path, release_armor_swf(throw_in_constructor=True)), log=log)
    assert "finished" not in checks and checks.get("ui") == "PASS", checks
    assert checks.get("armor error shown") == "PASS", checks
    assert any("Constructor bug" in message for message in armor_errors(log)), log[-10:]     # AutoSWF shows it too


def test_an_armor_playing_from_frame_scripts_runs_on_the_skeleton(tmp_path, ruffle_exe):
    # AzraelGuardianArmor's way: listeners from a frame-2 script, the head not anchored, so the head slot must follow
    # the real skeleton's placement for every label the armor does not block
    from aqw_fakes import animated_armor_swf
    checks = run_selftest(ruffle_exe, make_test_swf(tmp_path, animated_armor_swf()))
    assert "finished" not in checks, checks
    for name in ("listeners", "idle", "skill Attack1", "head follows the skeleton", "list scrollbar", "walk"):
        assert checks.get(name) == "PASS", (name, checks)
    assert checks.get("anchored", "").startswith("SKIP"), checks


def test_an_error_in_an_armors_frame_script_reaches_autoswf(tmp_path, ruffle_exe):
    from aqw_fakes import animated_armor_swf
    from autoswf.ruffle.launch import armor_errors
    log = []
    checks = run_selftest(ruffle_exe, make_test_swf(tmp_path, animated_armor_swf(throw_in_frame2=True)), log=log)
    assert "finished" not in checks, checks
    assert "frame script: ArgumentError: Frame script bug" in armor_errors(log), log[-10:]


@pytest.mark.real
def test_the_azrael_guardian_armor_in_ruffle(tmp_path, ruffle_exe, azrael):
    checks = run_selftest(ruffle_exe, make_test_swf(tmp_path, azrael, client="aqw"))
    assert "finished" not in checks, checks
    for name in ("listeners", "idle", "skill Attack1", "list scrollbar", "dummy hit"):
        assert checks.get(name) == "PASS", (name, checks)


@pytest.mark.real
def test_the_sword_hero_release_in_ruffle(tmp_path, ruffle_exe, the_sword_hero_release):
    # on the cached AQW client, with AQW's own Training Dummy (mon/TrainingDummy.swf) as the target
    checks = run_selftest(ruffle_exe, make_test_swf(tmp_path, the_sword_hero_release, client="aqw"))
    assert checks.get("dummy original") == "PASS" and checks.get("dummy hit") == "PASS", checks
    assert checks and not failures(checks), checks
