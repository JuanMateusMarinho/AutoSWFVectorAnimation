"""Synthetic stand-ins for AQW files, built with AutoSWF's own writer, so tests never need the real game files:
a mini client (mcSkel with the real slot names, labels and frame scripts; mcHeadM/mcHeadF), a mini armor,
helms and a mini cache."""
import json
from pathlib import Path

from autoswf.abc.movieclip_classes import ClassSpec, build_abc
from autoswf.abc.writer import MethodTrait
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
        "Chest": Symbol("Chest", [Frame([Placement(skin, 1), Placement(vest, 3, name="Vest"),
                                         Placement(strap, 5, name="Strap")])]),
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


def labeled_item_swf(link: str, labels: tuple[str, ...]) -> bytes:
    """One exported class whose timeline has these frame labels (a cape: Idle, Move; a pet: Ready, Idle, Walk)."""
    frames = [Frame([Placement(_shape((120, 40, 40, 255), 8 + k, 12), 1)], label) for k, label in enumerate(labels)]
    item = Symbol(link, frames)
    return build_swf([item], {id(item): link}, build_abc([ClassSpec(link)]))


def hair_swf(name: str = "Normal", gender: str = "M") -> bytes:
    front, back = _holder("Front", _shape((110, 60, 30, 255), 20, 12)), _holder("Back", _shape((90, 50, 25, 255), 22, 30))
    names = {id(front): "%s%sHair" % (name, gender), id(back): "%s%sHairBack" % (name, gender)}
    return build_swf([front, back], names, build_abc([ClassSpec(n) for n in names.values()]))


def root_weapon_swf() -> bytes:
    """An uncompressed (FWS) weapon whose art sits on the root timeline: no classes."""
    from swf_builders import place2, shape_tag, swf
    blade = shape_tag(1, 1, [("solid", (200, 200, 220, 255))], [],
                      [{"start": (0, 0), "edges": [(4, 0), (4, 60), (0, 60), (0, 0)], "fill1": 1}])
    grip = shape_tag(2, 1, [("solid", (90, 50, 30, 255))], [],
                     [{"start": (0, 60), "edges": [(4, 60), (4, 75), (0, 75), (0, 60)], "fill1": 1}])
    return swf([blade, grip, place2(1, 1), place2(2, 2)])


def animated_armor_swf(link: str = "TestAnim") -> bytes:
    """A male "animated armor" like AzraelGuardianArmor.swf: every part an empty clip except <Link>MHead, a 30-frame
    character (labels Idleing 3, Walking 10, Attack1 20, 1-based) whose frame 2 registers animation listeners on the
    avatar (Idle -> onIdle, Walk -> onWalk with block, Attack1 -> onAttack, Fight -> onAttack); frame 11 sends the
    skeleton to throneWalk when the world's bitWalk is on; frame 9 stops, frame 19 loops the walk, frame 30 does
    gotoAndStop(2)."""
    from autoswf.abc.code import Code
    from autoswf.abc.movieclip_classes import ANCESTORS, _add_class
    from autoswf.abc.writer import PACKAGE, PACKAGE_INTERNAL, PROTECTED, AbcBuilder
    shapes = {name: _shape(color, 10, 12) for name, color in (("rest", (200, 200, 200, 255)),
                                                               ("idle", (100, 200, 100, 255)),
                                                               ("walk", (100, 100, 220, 255)),
                                                               ("attack", (220, 80, 80, 255)))}
    frames = []
    for k in range(30):
        art = "rest" if k < 2 else "idle" if k < 9 else "walk" if k < 19 else "attack"
        frames.append(Frame([Placement(shapes[art], 1)], {2: "Idleing", 9: "Walking", 19: "Attack1"}.get(k)))
    head = Symbol("Head", frames)
    parts = {part: Symbol(part, [Frame()]) for part in ("Chest", "Hip", "Shoulder", "Hand", "Thigh", "Shin", "Foot",
                                                       "FootIdle", "Robe", "RobeBack")}
    parts["Head"] = head
    names = {id(sym): "%sM%s" % (link, part) for part, sym in parts.items()}

    b = AbcBuilder()
    for name in names.values():
        if not name.endswith("Head"):
            _add_class(b, ClassSpec(name))
    head_name = link + "MHead"
    movieclip = b.qname(PACKAGE, "flash.display", "MovieClip")
    pub = lambda name: b.qname(PACKAGE, "", name)

    def method(code: Code) -> int:
        return b.method(6, 1, 10, 11, code.returnvoid().bytes())

    frame2 = Code().getlocal0().pushscope().getlocal0().pushfalse().initproperty(pub("walking"))
    for label, handler, flag in (("Idle", "onIdle", False), ("Walk", "onWalk", True), ("Attack1", "onAttack", None),
                                 ("Fight", "onAttack", False)):
        frame2.findpropstrict(movieclip).getlex(pub("parent")).getproperty(pub("parent")).getproperty(pub("parent"))
        frame2.callproperty(movieclip, 1).pushstring(b.string(label)).getlocal0().getproperty(pub(handler))
        if flag is not None:
            (frame2.pushtrue() if flag else frame2.pushfalse())
        frame2.callpropvoid(pub("addAnimationListener"), 2 if flag is None else 3)
    frame9 = Code().getlocal0().pushscope().findpropstrict(pub("stop")).callpropvoid(pub("stop"), 0)
    frame11 = Code().getlocal0().pushscope().findpropstrict(movieclip).getlex(pub("stage")).pushbyte(0)
    frame11.callproperty(pub("getChildAt"), 1).callproperty(movieclip, 1).getproperty(pub("world"))
    frame11.getproperty(pub("bitWalk")).iftrue(1).returnvoid()
    frame11.findpropstrict(movieclip).getlex(pub("parent")).getproperty(pub("parent")).callproperty(movieclip, 1)
    frame11.pushstring(b.string("throneWalk")).callpropvoid(pub("gotoAndPlay"), 1)
    frame19 = Code().getlocal0().pushscope().findpropstrict(pub("gotoAndPlay")).pushstring(b.string("Walking"))
    frame19.callpropvoid(pub("gotoAndPlay"), 1)
    frame30 = Code().getlocal0().pushscope().findpropstrict(pub("gotoAndStop")).pushbyte(2)
    frame30.callpropvoid(pub("gotoAndStop"), 1)
    walk_tail = Code().getlocal0().pushtrue().initproperty(pub("walking")).getlocal0().pushstring(b.string("Walking"))
    walk_tail.callpropvoid(pub("gotoAndPlay"), 1)
    on_walk = Code().getlocal0().pushscope().getlocal0().getproperty(pub("walking")).iftrue(len(walk_tail))
    on_walk._b += walk_tail.bytes()                 # if (walking) return; walking = true; gotoAndPlay("Walking")
    on_idle = Code().getlocal0().pushscope().getlocal0().pushfalse().initproperty(pub("walking")).getlocal0()
    on_idle.pushstring(b.string("Idleing")).callpropvoid(pub("gotoAndPlay"), 1)
    on_attack = Code().getlocal0().pushscope().getlocal0().pushfalse().initproperty(pub("walking")).getlocal0()
    on_attack.pushstring(b.string("Attack1")).callpropvoid(pub("gotoAndPlay"), 1)

    frame_methods = [(1, "frame2", frame2), (8, "frame9", frame9), (10, "frame11", frame11), (18, "frame19", frame19),
                     (29, "frame30", frame30)]
    traits, refs = [], []
    for index, trait, code in frame_methods:
        mn = b.qname(PACKAGE_INTERNAL, "", trait)
        traits.append(MethodTrait(mn, method(code)))
        refs.append((index, mn))
    for trait, code in (("onWalk", on_walk), ("onIdle", on_idle), ("onAttack", on_attack)):
        traits.append(MethodTrait(pub(trait), method(code)))
    ctor = Code().getlocal0().pushscope().getlocal0().constructsuper(0).findpropstrict(pub("addFrameScript"))
    for index, mn in refs:
        ctor.pushbyte(index).getlex(mn)
    ctor.callpropvoid(pub("addFrameScript"), 2 * len(refs))
    iinit = b.method(1 + 2 * len(refs), 1, 10, 11, ctor.returnvoid().bytes())
    cinit = b.method(1, 1, 9, 10, Code().getlocal0().pushscope().returnvoid().bytes())
    class_mn = pub(head_name)
    class_index = b.add_class(class_mn, movieclip, b.namespace(PROTECTED, head_name), iinit, cinit, traits)
    init = Code().getlocal0().pushscope().getscopeobject(0)
    for ns, ancestor in ANCESTORS:
        init.getlex(b.qname(PACKAGE, ns, ancestor)).pushscope()
    init.getlex(movieclip).newclass(class_index)
    for _ in ANCESTORS:
        init.popscope()
    init.initproperty(class_mn).returnvoid()
    b.add_script(b.method(2, 1, 1, 9, init.bytes()), class_mn, class_index)
    return build_swf(list(parts.values()), names, b.serialize())
