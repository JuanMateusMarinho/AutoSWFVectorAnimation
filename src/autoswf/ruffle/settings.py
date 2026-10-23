"""The settings record the Ruffle test stage reads (spec §5.2-5.5): the skeleton's game labels grouped for the list, what
the armor does with each (from its own code, read by items.animated; for display only), the skill bar, the player
colors, the skeleton's slot names and, per game label, where the skeleton puts its head slot on each frame (§5.4)."""
from autoswf.aqw.rig import AvatarRig
from autoswf.items.animated import read_animated_armor
from autoswf.items.structure import find_armor_link
from autoswf.render.colors import PlayerColors
from autoswf.swf.decode import MovieData

SKILL_LABELS = ("Attack1", "Attack2", "Attack3", "Attack4", "Cast1", "Cast2", "Cast3")
GROUPS = ("Skills", "Movement", "Emotes", "Weapons", "Other")
LOCATIONS = ("Hair", "Skin", "Eye", "Base", "Trim", "Accessory")
SKILL_BAR = 5
SKILLS = set(SKILL_LABELS) | {"Castgood", "Stab", "Thrash"}
MOVEMENT = {"Ready", "Idle", "Walk", "mountWalk", "horseWalk", "throneWalk", "Fight", "Hit", "Dodge", "Knockout", "Getup",
            "Dead", "Feign", "Unsheath"}
WEAPONS = ("Sword/Shield", "ShieldBlock", "DuelWield", "Fistweapon", "Polearm", "Ranged", "Unarmed", "Rifle", "Gun",
           "Whip", "Kick", "Flip")


def group_of(label: str, skeleton: set[str]) -> str:
    """The list group of a game label: by name, else Emotes for the skeleton's other labels, else Other."""
    if label in SKILLS:
        return "Skills"
    if label in MOVEMENT:
        return "Movement"
    if label.startswith(WEAPONS):
        return "Weapons"
    return "Emotes" if label in skeleton else "Other"


def skill_slots(table: list[tuple[str, str | None, bool]]) -> list[dict]:
    """The five skill-bar slots: AQW's class-skill labels whose armor animation is new, in order, then the unused
    labels."""
    armor = {}
    for game, animation, _ in table:
        armor.setdefault(game, animation)
    chosen, taken = [], set()
    for game in SKILL_LABELS:
        if armor.get(game) is not None and armor[game] not in taken:
            chosen.append(game)
            taken.add(armor[game])
    chosen += [game for game in SKILL_LABELS if game not in chosen][:SKILL_BAR - len(chosen)]
    return [{"slot": n, "game": game, "armor": armor.get(game)} for n, game in enumerate(chosen[:SKILL_BAR], start=1)]


def _matrix(m) -> list[float]:
    return [m.a, m.b, m.c, m.d, m.tx, m.ty]


def _track(rig: AvatarRig, label: str) -> dict:
    """The head slot's transform on each frame the skeleton shows for a label: until it loops back, holds (a stop) or
    leaves the label."""
    rig.set_label(label)
    frames, held = [_matrix(rig.head().matrix)], rig._hold
    for _ in range(rig._end - rig._start):
        if held:
            break
        rig.tick()
        if rig.skel.frame == rig._start:
            break
        if not rig._start <= rig.skel.frame < rig._end:
            held = True
            break
        frames.append(_matrix(rig.head().matrix))
        held = rig._hold
    return {"frames": frames, "loop": not held}


def head_track(client: MovieData, gender: str, label: str) -> dict:
    """{"frames": [[a, b, c, d, tx, ty], ...], "loop": bool} for one game label of the bare skeleton."""
    return _track(AvatarRig(client, gender), label)


def stage_settings(client: MovieData, armor: MovieData, *, colors: PlayerColors | None = None,
                   tracks: dict | None = None) -> dict:
    """`tracks` ({gender: {label: head_track}}) keeps the skeleton's head tracks between calls on the same client:
    they do not depend on the armor and take most of the time."""
    colors = colors or PlayerColors()
    tracks = {} if tracks is None else tracks
    link, _ = find_armor_link(armor)
    animated = {g: a for g in "MF" if (a := read_animated_armor(armor, g)) is not None}
    sprite = client.character(client.classes["mcSkel"])
    skeleton = sorted(sprite.labels, key=sprite.labels.get)
    tables = {g: a.table() for g, a in animated.items()}
    names = list(skeleton)
    for table in tables.values():
        names += [game for game, _, _ in table if game not in names]
    rows = []
    for name in names:
        rows.append({"name": name, "group": group_of(name, set(skeleton)),
                     "armor": {g: next((a for game, a, _ in t if game == name), None) for g, t in tables.items()},
                     "block": {g: next((b for game, _, b in t if game == name), False) for g, t in tables.items()}})
    first = AvatarRig(client, next(iter(animated), "M"))
    slots = [c.name for c in first.skel.children if c.name]          # read before the tracks move the skeleton
    for g in animated:
        if g not in tracks:
            rig = first if first.gender == g else AvatarRig(client, g)
            tracks[g] = {label: _track(rig, label) for label in skeleton}
    return {"link": link, "genders": list(animated), "labels": rows,
            "motions": {g: a.motions() for g, a in animated.items()},
            "skills": {g: skill_slots(t) for g, t in tables.items()},
            "auto": ["Attack1", "Attack2"],
            "colors": {location: colors.get(location) for location in LOCATIONS},
            "slots": slots,
            "head": {g: tracks[g] for g in animated}}
