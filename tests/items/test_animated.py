# tests/items/test_animated.py
import pytest

from aqw_fakes import animated_armor_swf, mini_armor_with_pieces
from autoswf.items.animated import read_animated_armor
from autoswf.swf.decode import MovieData


def test_an_animated_armor_is_recognized():
    armor = read_animated_armor(MovieData(animated_armor_swf()))
    assert armor.class_name == "TestAnimMHead" and armor.labels == {"Idleing": 2, "Walking": 9, "Attack1": 19}
    assert armor.table() == [("Idle", "Idleing", False), ("Walk", "Walking", True), ("Attack1", "Attack1", False),
                             ("Fight", "Attack1", False)]
    assert armor.notes == []
    assert read_animated_armor(MovieData(mini_armor_with_pieces("M"))) is None


@pytest.mark.real
def test_azrael_guardian_armor(azrael):
    armor = read_animated_armor(MovieData(azrael))
    assert armor.labels == {"Idleing": 2, "Walking": 9, "Attack1": 22, "Attack2": 72, "Attack3": 166}
    assert len(armor.listeners) == 44 and [b for g, _, b in armor.table() if b] == [True]
    assert ("Walk", "Walking", True) in armor.table() and ("Attack1", "Attack1", False) in armor.table()
    assert armor.notes == []


def test_an_armor_that_registers_its_listeners_from_methods_is_recognized():
    from aqw_fakes import listener_armor_swf
    armor = read_animated_armor(MovieData(listener_armor_swf()))
    assert armor.class_name == "TestBindMHead" and armor.labels == {"Portrait": 0, "Idle": 1, "Walk": 2, "Slash": 3}
    assert armor.table() == [("Idle", "Idle", False), ("Fight", "Idle", True), ("Walk", "Walk", True),
                             ("Attack1", "Slash", True), ("Attack2", "Slash", True)]
    assert armor.motions() == ["Portrait", "Idle", "Walk", "Slash"] and armor.notes == []


def test_a_mapping_that_cannot_be_read_still_gives_the_motions():
    from aqw_fakes import listener_armor_swf
    armor = read_animated_armor(MovieData(listener_armor_swf(readable=False)))
    assert armor.table() == [] and armor.motions() == ["Portrait", "Idle", "Walk", "Slash"]
    assert any("cannot be read" in note for note in armor.notes)


@pytest.mark.real
def test_the_sword_hero(the_sword_hero):
    armor = read_animated_armor(MovieData(the_sword_hero))
    assert armor.class_name == "TheSwordHeroMHead" and len(armor.listeners) == 54 and armor.notes == []
    assert armor.motions() == ["Portrait", "Idle", "Walk", "SolarSlash", "CrossFlare", "DawnBurst", "Hit", "Dead"]
    table = armor.table()
    for row in (("Idle", "Idle", False), ("Walk", "Walk", True), ("Attack1", "SolarSlash", True),
                ("Attack2", "CrossFlare", True), ("Cast1", "DawnBurst", True), ("Hit", "Hit", True),
                ("Dead", "Dead", True), ("Getup", "Idle", True)):
        assert row in table


def _with_bodies(head, bodies: dict):
    import copy
    from autoswf.items.animated import HeadClass
    abc = copy.copy(head.abc)
    abc.bodies = {**head.abc.bodies, **bodies}
    return HeadClass(abc, head.name, head.iinit, head.methods, head.fields, head.frame_methods)


def _run_everything(head):
    from autoswf.items.animated import Host, HeadScripts
    head.calls("addAnimationListener")
    scripts = HeadScripts(head, Host({"bitWalk": True}))
    scripts.construct()
    scripts.dispatch("addedToStage")
    for frame in sorted(head.frame_methods):
        scripts.frame(frame)
    scripts.dispatch("enterFrame")
    for handler in head.methods:
        scripts.call(handler)
    return scripts


def test_head_code_that_never_ends_stops_quickly_with_a_note():
    import time
    from aqw_fakes import listener_armor_swf
    head = read_animated_armor(MovieData(listener_armor_swf())).head
    squares = bytes([0x24, 0x02, 0xD5, 0x09, 0xD1, 0xD1, 0xA2, 0xD5, 0x10, 0xF7, 0xFF, 0xFF, 0x47])  # x=2; x*=x forever
    concat = bytes([0x2C, 0x01, 0xD5, 0x09, 0xD1, 0xD1, 0xA0, 0xD5, 0x10, 0xF7, 0xFF, 0xFF, 0x47])  # s=""+…; s+=s
    for body in (squares, concat):
        start = time.monotonic()
        scripts = _run_everything(_with_bodies(head, {head.iinit: body}))
        assert time.monotonic() - start < 3 and any("stopped" in note for note in scripts.notes)


def test_damaged_head_code_is_a_note_never_an_error():
    import random
    from aqw_fakes import animated_armor_swf, listener_armor_swf
    for source in (listener_armor_swf(), animated_armor_swf()):
        head = read_animated_armor(MovieData(source)).head
        methods = [head.iinit, *head.methods.values()]
        rnd = random.Random(7)
        for _ in range(120):
            method = rnd.choice(methods)
            code = bytearray(head.abc.bodies.get(method, b""))
            if rnd.random() < 0.4 and code:
                code = code[:rnd.randrange(len(code))]
            elif code:
                for _ in range(rnd.randint(1, 4)):
                    code[rnd.randrange(len(code))] = rnd.randrange(256)
            _run_everything(_with_bodies(head, {method: bytes(code)}))


def test_a_damaged_class_is_simply_not_an_animated_armor():
    from aqw_fakes import listener_armor_swf
    movie = MovieData(listener_armor_swf())
    abc = movie.abcs[0]
    inst = next(x for x in abc.instances if abc.mname(x["name"]) == "TestBindMHead")
    inst["traits"].append({"name": 10 ** 6, "kind": 0, "slot": 0, "type": 10 ** 6, "default": (0x01, 10 ** 6)})
    assert read_animated_armor(movie) is None
