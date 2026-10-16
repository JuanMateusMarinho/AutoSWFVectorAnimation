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
