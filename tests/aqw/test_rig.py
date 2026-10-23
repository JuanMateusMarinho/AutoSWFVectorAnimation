# tests/aqw/test_rig.py
import pytest
from aqw_fakes import helm, mini_armor, mini_client
from autoswf.aqw.assets import DEFAULT_ARMOR
from autoswf.aqw.rig import BLACK_TINT, AvatarRig
from autoswf.model.geometry import Matrix
from autoswf.swf.decode import MovieData

def rig(gender="M", helm_bytes=None, armor=True):
    return AvatarRig(MovieData(mini_client()), gender, armor=MovieData(mini_armor(gender)) if armor else None, armor_link="TestArmor",
                     helm=MovieData(helm_bytes) if helm_bytes else None, helm_link="Kit" if helm_bytes else None)

def test_armor_head_and_helm_go_where_the_game_puts_them():
    s = rig(helm_bytes=helm("Kit", backhair=True)).skel
    assert s.child_by_name("chest").children[0].class_name == "TestArmorMChest"
    assert [s.child_by_name(n).children[0].class_name for n in ("frontthigh", "backthigh")] == ["TestArmorMThigh"] * 2
    assert s.child_by_name("backhand").children[0].color == BLACK_TINT
    head = s.child_by_name("head")
    assert [c.name for c in head.children] == ["face", "helm", "hair"]
    assert head.children[0].class_name == "mcHeadM" and head.children[0].matrix == Matrix()
    assert head.child_by_name("helm").visible and head.child_by_name("helm").children[0].class_name == "Kit"
    assert not head.child_by_name("hair").visible
    assert s.child_by_name("backhair").visible and s.child_by_name("backhair").children[0].class_name == "Kit_backhair"
    assert not s.child_by_name("frontfoot").visible and s.child_by_name("idlefoot").visible
    assert not any(s.child_by_name(n).visible for n in ("cape", "weapon", "shield", "pvpFlag", "backrobe"))
    assert s.child_by_name("robe").visible

def test_female_parts_and_helm_without_backhair():
    s = rig("F", helm_bytes=helm("Kit", backhair=False)).skel
    assert not s.child_by_name("backhair").visible
    assert s.child_by_name("chest").children[0].class_name == "TestArmorFChest"
    assert s.child_by_name("head").children[0].class_name == "mcHeadF"

def test_missing_armor_keeps_the_placeholders():
    assert rig(armor=False).skel.child_by_name("chest").children[0].class_name is None

def test_idle_holds_and_walk_loops_without_showing_its_loop_frame():
    r = rig(helm_bytes=helm())
    assert r.labels == ["Ready", "Idle", "Walk"] and r.label == "Idle" and r.skel.frame == 1
    seq = []
    for _ in range(3):
        r.tick(); seq.append(r.skel.frame)
    assert seq == [1, 1, 1]
    r.set_label("Walk"); seq = [r.skel.frame]
    for _ in range(4):
        r.tick(); seq.append(r.skel.frame)
    assert seq == [3, 4, 3, 4, 3]
    assert r.head().children[0].class_name == "mcHeadM"

@pytest.mark.aqw
def test_real_client_idle_and_walk(aqw_cache):
    armor = MovieData(aqw_cache.armor_path("M", DEFAULT_ARMOR))
    r = AvatarRig(MovieData(aqw_cache.client_path()), "M", armor=armor, armor_link=DEFAULT_ARMOR)
    assert {"Idle", "Walk", "Attack1", "Cast1"} <= set(r.labels)
    for _ in range(3):
        r.tick()
    assert r.skel.frame == 7 and r.skel.child_by_name("idlefoot").visible and not r.skel.child_by_name("frontfoot").visible
    r.set_label("Walk"); frames = set()
    for _ in range(30):
        r.tick(); frames.add(r.skel.frame)
    assert frames == set(range(53, 67)) and r.skel.child_by_name("frontfoot").visible


def test_an_armor_head_replaces_the_default_head():
    from aqw_fakes import mini_armor_with_pieces
    armor = MovieData(mini_armor_with_pieces("M"))
    rig = AvatarRig(MovieData(mini_client()), "M", armor=armor, armor_link="TestArmor")
    face = rig.head().child_by_name("face")
    assert face.movie is armor and face.char_id == armor.classes["TestArmorMHead"]
    plain = AvatarRig(MovieData(mini_client()), "M", armor=MovieData(mini_armor("M")), armor_link="TestArmor")
    assert plain.head().child_by_name("face").movie is plain.client


def test_an_animated_armor_plays_its_own_walk_and_blocks_the_body():
    from aqw_fakes import animated_armor_swf
    armor = MovieData(animated_armor_swf())
    rig = AvatarRig(MovieData(mini_client()), "M", armor=armor, armor_link="TestAnim")
    for _ in range(2):
        rig.tick()                                    # the head reaches frame 2 and registers its listeners
    assert set(rig.anim_events) == {"Idle", "Walk", "Attack1", "Fight"}
    head = rig.head().child_by_name("face")
    skel_frame = rig.skel.frame
    rig.play("Walk")
    assert head.frame == 9 and rig.skel.frame == skel_frame        # blocked: the body stays
    rig.play("Walk")
    assert head.frame == 9                                          # walking: the handler does not restart it
    rig.play("Attack1")
    assert head.frame == 19                                         # not blocked (the mini client has no Attack1)
    for _ in range(11):
        rig.tick()
    assert head.frame == 1                                          # gotoAndStop(2) at the end of the attack


@pytest.mark.real
@pytest.mark.aqw
def test_azrael_walks_with_the_throne_walk(azrael, aqw_cache):
    rig = AvatarRig(MovieData(aqw_cache.client_path()), "M", armor=MovieData(azrael), armor_link="AzraelGuardianArmor")
    for _ in range(3):
        rig.tick()
    rig.play("Walk")
    for _ in range(3):
        rig.tick()
    assert rig.label == "throneWalk" and 9 <= rig.head().child_by_name("face").frame <= 21


def test_a_head_that_registers_from_its_methods_plays_its_motions_on_the_avatar():
    from aqw_fakes import listener_armor_swf
    rig = AvatarRig(MovieData(mini_client()), "M", armor=MovieData(listener_armor_swf()), armor_link="TestBind")
    face = rig.head().child_by_name("face")
    assert set(rig.anim_events) == {"Idle", "Fight", "Walk", "Attack1", "Attack2"}    # bind() when it was added
    assert face.frame == 1 and not face.playing                                         # its own Idle
    assert not rig.head().child_by_name("hair").visible and not rig._slot("cape").visible
    assert face.script_transformed and face.matrix == rig.head().matrix.inverse()     # drawn in the skeleton's space
    rig.play("Walk")
    assert face.frame == 2 and rig.label == "Idle"                                      # blocked: the body stays
    rig.play("Attack1")
    assert face.frame == 3
    for _ in range(5):
        rig.tick()
    assert face.frame == 1                                                               # onTick: the Slash body ended
    assert face.matrix == rig.head().matrix.inverse()


def test_a_head_that_reads_its_skills_from_another_class_plays_them_on_the_avatar():
    from aqw_fakes import release_armor_swf
    rig = AvatarRig(MovieData(mini_client()), "M", armor=MovieData(release_armor_swf()), armor_link="TestRelease")
    face = rig.head().child_by_name("face")
    assert set(rig.anim_events) == {"Skill1", "Attack1", "Skill2", "Cast1", "Idle", "Walk"}
    assert face.frame == 1 and not face.playing                                         # its own Idle, not Portrait
    assert not rig.head().child_by_name("hair").visible and not rig._slot("cape").visible
    assert face.script_transformed and face.matrix == rig.head().matrix.inverse()     # drawn in the skeleton's space
    rig.play("Walk")
    assert face.frame == 2 and rig.label == "Idle"                                      # blocked: the body stays
    rig.play("Attack1")
    assert face.frame == 3
    rig.tick()
    assert face.child_by_name("body").frame == 1
    rig.play("Attack1")                                                                 # the same skill starts over
    body = face.child_by_name("body")
    assert face.frame == 3 and body.frame == 0 and body.child_by_name("spark").frame == 0
    for _ in range(3):
        rig.tick()
    assert face.frame == 1                                                              # its body ended: back to Idle
    rig.play("Cast1")
    assert face.frame == 4
    assert face.matrix == rig.head().matrix.inverse()


@pytest.mark.real
def test_the_sword_hero_release_plays_on_the_avatar(the_sword_hero_release):
    rig = AvatarRig(MovieData(mini_client()), "M", armor=MovieData(the_sword_hero_release), armor_link="TheSwordHero")
    face = rig.head().child_by_name("face")
    labels = face.sprite.labels
    assert face.frame == labels["Idle"] and face.matrix == rig.head().matrix.inverse()
    rig.play("Walk")
    assert face.frame == labels["Walk"]
    rig.play("Attack1")
    assert face.frame == labels["Skill1"]
    rig.play("Cast3")
    assert face.frame == labels["Skill5"]


def test_an_armors_own_motion_plays_by_name():
    from aqw_fakes import animated_armor_swf, listener_armor_swf
    rig = AvatarRig(MovieData(mini_client()), "M", armor=MovieData(listener_armor_swf(readable=False)),
                    armor_link="TestBind")
    face = rig.head().child_by_name("face")
    assert rig.anim_events == {}
    rig.play_motion("Slash")
    rig.tick()
    assert face.frame == 3                                                               # a one-frame motion holds
    rig = AvatarRig(MovieData(mini_client()), "M", armor=MovieData(animated_armor_swf()), armor_link="TestAnim")
    face = rig.head().child_by_name("face")
    rig.play_motion("Walking")
    seen = set()
    for _ in range(25):
        rig.tick()
        seen.add(face.frame)
    assert seen <= set(range(9, 19)) and len(seen) > 5                                   # a longer motion loops
