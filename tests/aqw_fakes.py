"""Synthetic stand-ins for AQW files, built with AutoSWF's own writer, so tests never need the real game files:
a mini client (mcSkel with the real slot names, labels and frame scripts; mcHeadM/mcHeadF), a mini armor,
helms and a mini cache."""
import json
from pathlib import Path

from autoswf.abc.movieclip_classes import ClassSpec, build_abc
from autoswf.aqw.assets import AqwCache
from autoswf.aqw.helm import HelmItem, export_helm
from autoswf.cli import demo_helm
from autoswf.model.document import Frame, GotoAndPlayScript, Placement, SetColorScript, StopScript, Symbol
from autoswf.model.geometry import ColorTransform, Matrix
from autoswf.model.shape import Shape, SolidFill, ellipse
from autoswf.swf.movie import build_swf

BLACK = (0, 0, 0, 255)
BLACK_TINT = ColorTransform((0.0, 0.0, 0.0, 1.0), (0, 0, 0, 0))
SLOTS = ("backhair", "cape", "backshoulder", "backhand", "backrobe", "backfoot", "backthigh", "backshin", "chest",
         "hip", "frontthigh", "frontshin", "idlefoot", "frontfoot", "robe", "head", "shield", "weapon", "frontshoulder",
         "fronthand", "pvpFlag", "weaponOff", "weaponFist", "weaponFistOff")
TINTED = {"backshoulder", "backfoot", "backthigh", "backshin"}
POSITIONS = {"backhair": (0, -104), "cape": (0, -70), "backshoulder": (10, -78), "backhand": (14, -55),
             "backrobe": (0, -45), "backfoot": (6, -3), "backthigh": (5, -40), "backshin": (5, -20), "chest": (0, -70),
             "hip": (0, -52), "frontthigh": (-5, -40), "frontshin": (-5, -20), "idlefoot": (-6, -3),
             "frontfoot": (-6, -3), "robe": (0, -45), "shield": (25, -60), "weapon": (-25, -60),
             "frontshoulder": (-12, -78), "fronthand": (-16, -55), "pvpFlag": (0, -135), "weaponOff": (25, -50),
             "weaponFist": (-20, -50), "weaponFistOff": (20, -50)}
ARMOR_PARTS = ("Chest", "Hip", "Foot", "FootIdle", "Shoulder", "Hand", "Thigh", "Shin")


def _disc(color, rx, ry=None, cx=0.0, cy=0.0) -> Shape:
    return Shape([SolidFill(color)], [ellipse(0, cx, cy, rx, ry if ry is not None else rx)])


def _holder(name: str, item) -> Symbol:
    return Symbol(name, [Frame([Placement(item, 1)])])


def _placeholder(name: str) -> Symbol:
    """A slot: one child clip with a black silhouette, like the client's loading placeholders."""
    return _holder(name, _holder(name + "Art", _disc(BLACK, 6, 10)))


def mini_client() -> bytes:
    slots = {name: _placeholder(name) for name in SLOTS if name != "head"}
    slots["head"] = Symbol("HeadSlot", [Frame([
        Placement(_holder("FacePlaceholder", _disc(BLACK, 30)), 1, name="face"),
        Placement(_holder("HelmPlaceholder", _disc((1, 1, 1, 0), 30)), 4, name="helm"),
        Placement(_holder("HairPlaceholder", _disc(BLACK, 20)), 6, name="hair")])])

    def frame(index: int, label: str | None = None) -> Frame:
        placements = []
        for i, name in enumerate(SLOTS):
            if name == "head":
                matrix = Matrix(0.25, 0, 0, 0.25, max(0, index - 2), -100)
            else:
                matrix = Matrix.translate(*POSITIONS[name])
            placements.append(Placement(slots[name], 1 + 2 * i, matrix, BLACK_TINT if name in TINTED else None, name=name))
        return Frame(placements, label)

    skel = Symbol("Skel", [frame(0, "Ready"), frame(1, "Idle"), frame(2), frame(3, "Walk"), frame(4), frame(5)])
    face = Symbol("Face", [Frame([Placement(_disc((200, 160, 120, 255), 40), 1)])])
    heads = [Symbol(n, [Frame([Placement(_disc(BLACK, 42), 1), Placement(face, 2)])]) for n in ("HeadM", "HeadF")]
    names = {id(skel): "mcSkel", id(heads[0]): "mcHeadM", id(heads[1]): "mcHeadF", id(face): "client_fla.Face_1"}
    abc = build_abc([ClassSpec("mcSkel", ((0, GotoAndPlayScript("Idle")), (1, StopScript()), (5, GotoAndPlayScript("Walk")))),
                     ClassSpec("mcHeadM"), ClassSpec("mcHeadF"),
                     ClassSpec("client_fla.Face_1", ((0, SetColorScript("Skin", "None")),))])
    return build_swf([skel, *heads], names, abc)


def mini_armor(gender: str, link: str = "TestArmor", robe: bool = True) -> bytes:
    parts = ARMOR_PARTS + (("Robe",) if robe else ())
    symbols = [_holder(part, _disc((90, 110, 140, 255), 7, 11)) for part in parts]
    names = {id(s): "%s%s%s" % (link, gender, part) for s, part in zip(symbols, parts)}
    return build_swf(symbols, names, build_abc([ClassSpec(n) for n in names.values()]))


def helm(link: str = "Kit", backhair: bool = True) -> bytes:
    item = demo_helm(link)
    if backhair:
        item.backhair = _holder("Back", _disc((40, 40, 40, 255), 30, 40, 0, 10))
    return export_helm(item)


def blob_helm(link: str, radius: float) -> bytes:
    return export_helm(HelmItem(link, _holder("Blob", _disc(BLACK, radius))))


def write_mini_cache(root: Path, armor: str = "TestArmor") -> AqwCache:
    cache = AqwCache(Path(root))
    cache.version_file().parent.mkdir(parents=True, exist_ok=True)
    cache.version_file().write_text(json.dumps({"sFile": "GameMini.swf"}), encoding="utf-8")
    cache.file_path("GameMini.swf").parent.mkdir(parents=True, exist_ok=True)
    cache.file_path("GameMini.swf").write_bytes(mini_client())
    for g in "MF":
        cache.armor_path(g, armor).parent.mkdir(parents=True, exist_ok=True)
        cache.armor_path(g, armor).write_bytes(mini_armor(g, armor))
    return cache


def _shape(color, rx, ry=None, cx=0.0, cy=0.0) -> Shape:
    return _disc(color, rx, ry, cx, cy)


def mini_armor_with_pieces(gender: str = "M", link: str = "TestArmor", setcolor_form: str = "plain") -> bytes:
    """A small armor whose parts hold sub-pieces like official ones: Chest = a colorable skin clip, a "Vest" (a shape and
    the shared "Stud") and a "Strap" (the "Stud"); Shoulder = a shape and the "Stud"; the "Stud" holds one "Gem" shape
    (so that placement shows under Chest twice and Shoulder once); RobeBack = a "Quiver" (a shape and three "Arrow"
    clips); Head = a clip named "Face" and a 3-frame "Blinker" (places, moves, then removes a shape at depth 2)."""
    from autoswf.model.document import ColorCustom
    stud = _holder("Stud", _shape((230, 190, 40, 255), 2))
    skin = Symbol("Skin", [Frame([Placement(_shape((240, 200, 160, 255), 9, 12), 1)])],
                  color_custom=ColorCustom("Skin", "None"))
    vest = Symbol("Vest", [Frame([Placement(_shape((30, 100, 100, 255), 8, 11), 1),
                                  Placement(stud, 2, Matrix.translate(3, 2))])])
    strap = Symbol("Strap", [Frame([Placement(stud, 1, Matrix.translate(-2, 5))])])
    arrow = _holder("Arrow", _shape((200, 40, 40, 255), 1, 6))
    quiver = Symbol("Quiver", [Frame([Placement(_shape((90, 60, 30, 255), 4, 9), 1)]
                                     + [Placement(arrow, 1 + k, Matrix.translate(-2 + 2 * k, -8)) for k in (1, 2, 3)])])
    face = _holder("FaceArt", _shape((240, 200, 160, 255), 10, 11))
    a, b = _shape((20, 20, 20, 255), 2), _shape((255, 255, 255, 255), 1.5)
    blinker = Symbol("Blinker", [Frame([Placement(a, 1), Placement(b, 2)]),
                                 Frame([Placement(a, 1), Placement(b, 2, Matrix.translate(1, 0))]),
                                 Frame([Placement(a, 1)])])
    parts = {
        "Chest": Symbol("Chest", [Frame([Placement(skin, 1), Placement(vest, 3), Placement(strap, 5)])]),
        "Shoulder": Symbol("Shoulder", [Frame([Placement(_shape((90, 110, 140, 255), 5, 8), 1),
                                               Placement(stud, 3, Matrix.translate(0, 4))])]),
        "RobeBack": Symbol("RobeBack", [Frame([Placement(quiver, 1)])]),
        "Head": Symbol("Head", [Frame([Placement(face, 1, name="Face"), Placement(blinker, 3, Matrix.translate(4, 0))])]),
    }
    for part in ("Hip", "Hand", "Thigh", "Shin", "Foot", "FootIdle", "Robe"):
        parts[part] = _holder(part, _shape((90, 110, 140, 255), 6, 9))
    names = {id(s): "%s%s%s" % (link, gender, part) for part, s in parts.items()}
    names[id(skin)] = "%s_fla.Skin_1" % link
    specs = [ClassSpec(n) for n in names.values() if "_fla." not in n]
    specs.append(ClassSpec(names[id(skin)], ((0, SetColorScript("Skin", "None")),)))
    return build_swf(list(parts.values()), names, build_abc(specs, setcolor_form=setcolor_form))
