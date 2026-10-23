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
                 "background", "gender switch", "walk", "arrive Idle", "faces target", "walks into range", "dummy hit")


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


@pytest.mark.real
def test_the_sword_hero_release_in_ruffle(tmp_path, ruffle_exe, the_sword_hero_release):
    # on the cached AQW client, with AQW's own Training Dummy (mon/TrainingDummy.swf) as the target
    checks = run_selftest(ruffle_exe, make_test_swf(tmp_path, the_sword_hero_release, client="aqw"))
    assert checks.get("dummy original") == "PASS" and checks.get("dummy hit") == "PASS", checks
    assert checks and not failures(checks), checks
