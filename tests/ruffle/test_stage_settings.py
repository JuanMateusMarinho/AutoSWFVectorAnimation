# tests/ruffle/test_stage_settings.py
import json

from autoswf.swf.decode import MovieData


def test_skill_slots_follow_aqws_class_skill_labels():
    from autoswf.ruffle.settings import skill_slots
    table = [("Attack1", "Skill1", True), ("Attack2", "Skill2", True), ("Attack3", "Skill2", True),
             ("Attack4", "Skill1", True), ("Cast1", "Skill3", True), ("Cast2", "Skill4", True), ("Cast3", "Skill5", True)]
    assert [(s["slot"], s["game"], s["armor"]) for s in skill_slots(table)] == [
        (1, "Attack1", "Skill1"), (2, "Attack2", "Skill2"), (3, "Cast1", "Skill3"), (4, "Cast2", "Skill4"),
        (5, "Cast3", "Skill5")]
    assert [s["game"] for s in skill_slots([])] == ["Attack1", "Attack2", "Attack3", "Attack4", "Cast1"]


def test_groups():
    from autoswf.ruffle.settings import group_of
    skeleton = {"Attack1", "Cast3", "Walk", "Dead", "Dance", "PolearmAttack1", "Sword/ShieldFight"}
    assert [group_of(label, skeleton) for label in ("Attack1", "Cast3", "Walk", "Dead", "Dance", "PolearmAttack1",
                                                    "Sword/ShieldFight", "Skill2")] == [
        "Skills", "Skills", "Movement", "Movement", "Emotes", "Weapons", "Weapons", "Other"]


def test_settings_for_a_release_style_armor():
    from aqw_fakes import mini_client, release_armor_swf      # mini_client's skeleton labels: Ready, Idle, Walk
    from autoswf.ruffle.settings import stage_settings
    s = stage_settings(MovieData(mini_client()), MovieData(release_armor_swf()))
    assert s["link"] == "TestRelease" and s["genders"] == ["M"] and s["auto"] == ["Attack1", "Attack2"]
    assert [r["name"] for r in s["labels"]] == ["Ready", "Idle", "Walk", "Skill1", "Attack1", "Skill2", "Cast1"]
    rows = {r["name"]: r for r in s["labels"]}
    assert rows["Attack1"]["group"] == "Skills" and rows["Attack1"]["armor"]["M"] == "Skill1"
    assert rows["Attack1"]["block"]["M"] is True and rows["Ready"]["armor"]["M"] is None
    assert rows["Skill2"]["group"] == "Other" and rows["Walk"]["armor"]["M"] == "Walk"
    assert [x["armor"] for x in s["skills"]["M"]][:2] == ["Skill1", "Skill2"]
    assert s["motions"]["M"] == ["Portrait", "Idle", "Walk", "Skill1", "Skill2"]
    assert set(s["colors"]) == {"Hair", "Skin", "Eye", "Base", "Trim", "Accessory"}
    assert "head" in s["slots"] and s["head"]["M"]["Idle"]["frames"] and set(s["head"]["M"]) == {"Ready", "Idle", "Walk"}
    json.dumps(s)                                                      # JSON-able


def test_a_head_track_follows_the_skeleton_and_knows_held_labels():
    from aqw_fakes import mini_client
    from autoswf.ruffle.settings import head_track
    client = MovieData(mini_client())
    idle, walk = head_track(client, "M", "Idle"), head_track(client, "M", "Walk")
    assert idle["loop"] is False and len(idle["frames"]) == 1           # mini skeleton's Idle stops on its frame
    # Walk shows frames 4 and 5 (1-based); frame 6 sends it back to Walk before it is shown, as Flash does
    assert walk["loop"] is True and len(walk["frames"]) == 2
    assert [f[4] for f in walk["frames"]] == [1.0, 2.0]                  # the head slot moves right each frame
