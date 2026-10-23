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


def _asm(steps: list):
    """Bytecode (a Code) from (emitter, *args) steps; a "@name" string marks a place, and a jump's argument may name
    one."""
    from autoswf.abc.code import Code
    jumps = {"jump", "iftrue", "iffalse", "ifeq", "ifne"}

    def emit(code, step, offset_of):
        if isinstance(step, str):
            return
        name, *args = step
        if name in jumps and isinstance(args[0], str):
            args = [offset_of(args[0], len(code) + 4)]
        getattr(code, name)(*args)
    places, code = {}, Code()
    for step in steps:
        if isinstance(step, str):
            places[step] = len(code)
        emit(code, step, lambda place, end: 0)
    code = Code()
    for step in steps:
        emit(code, step, lambda place, end: places[place] - end)
    return code


def listener_armor_swf(link: str = "TestBind", readable: bool = True) -> bytes:
    """A male animated armor like TheSwordHero.swf: every part an empty clip except <Link>MHead, whose class registers
    its listeners from methods (no frame scripts). Its constructor stops the clip and listens for ADDED_TO_STAGE
    (bind) and ENTER_FRAME (onTick); bind() walks the parent chain up to the avatar, registers
    listen(["Idle","Fight"], onIdle), listen(["Walk"], onWalk) and listen(["Attack1","Attack2"], onSlash) (each label
    with block = true), goes to its Idle motion, hides the skeleton's cape and the head's hair and cancels its parent's
    transform (anchor). The head has four one-frame labels, Portrait (a shape named headOnly), Idle, Walk and Slash,
    each placing a clip named body that plays 1, 2 and 4 frames; onTick goes back to Idle when the Slash body ends.
    With readable=False the label lists come from Config.LABELS, which a reader cannot know."""
    from autoswf.abc.movieclip_classes import ANCESTORS, _add_class
    from autoswf.abc.writer import PACKAGE, PROTECTED, AbcBuilder, SlotTrait
    colors = {"head": (230, 190, 150, 255), "Idle": (100, 200, 100, 255), "Walk": (100, 100, 220, 255),
              "Slash": (220, 80, 80, 255)}
    bodies = {label: Symbol("Body" + label, [Frame([Placement(_shape(colors[label], 10 + 3 * k, 30), 1)])
                                             for k in range(count)])
              for label, count in (("Idle", 1), ("Walk", 2), ("Slash", 4))}
    head = Symbol("Head", [Frame([Placement(_shape(colors["head"], 12, 12), 1, name="headOnly")], "Portrait")] +
                  [Frame([Placement(bodies[label], 1, name="body")], label) for label in ("Idle", "Walk", "Slash")])
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
    event = b.qname(PACKAGE, "flash.events", "Event")

    def n(name):
        return b.qname(PACKAGE, "", name)

    def s(text):
        return ("pushstring", b.string(text))

    def call(method, *pushes, argc=None, void=True):
        return [("findpropstrict", n(method)), *pushes,
                ("callpropvoid" if void else "callproperty", n(method), len(pushes) if argc is None else argc)]

    def listen(labels, handler):
        if readable:
            pushes = [s(label) for label in labels] + [("newarray", len(labels))]
        else:
            pushes = [("getlex", n("Config")), ("getproperty", n("LABELS"))]
        return [("findpropstrict", n("listen")), *pushes, ("getlex", n(handler)), ("callpropvoid", n("listen"), 2)]

    start = [("getlocal0",), ("pushscope",)]
    code = {
        "iinit": start + [("getlocal0",), ("newarray", 0), ("setproperty", n("registrations")),
                          ("getlocal0",), ("constructsuper", 0)] + call("stop") +
                 [("findpropstrict", n("addEventListener")), ("getlex", event), ("getproperty", n("ADDED_TO_STAGE")),
                  ("getlex", n("onAdded")), ("callpropvoid", n("addEventListener"), 2),
                  ("findpropstrict", n("addEventListener")), ("getlex", event), ("getproperty", n("ENTER_FRAME")),
                  ("getlex", n("onTick")), ("callpropvoid", n("addEventListener"), 2), ("returnvoid",)],
        "onAdded": start + call("bind") + [("returnvoid",)],
        "bind": start + [("getlex", n("avatar")), ("pushnull",), ("ifeq", "@search"), ("returnvoid",),
                         "@search", ("getlex", n("parent")), ("setlocal1",), ("jump", "@check"),
                         "@loop", ("label",), s("addAnimationListener"), ("getlocal1",), ("in_",), ("iffalse", "@up"),
                         ("findproperty", n("avatar")), ("getlocal1",), ("setproperty", n("avatar")), ("jump", "@found"),
                         "@up", ("getlocal1",), ("getproperty", n("parent")), ("setlocal1",),
                         "@check", ("getlocal1",), ("pushnull",), ("ifne", "@loop"),
                         "@found", ("getlex", n("avatar")), ("pushnull",), ("ifne", "@bound"), ("returnvoid",),
                         "@bound"] +
                listen(("Idle", "Fight"), "onIdle") + listen(("Walk",), "onWalk") +
                listen(("Attack1", "Attack2"), "onSlash") + call("setMotion", s("Idle"), ("pushtrue",)) +
                call("hide", ("getlex", n("avatar")), ("getproperty", n("mcChar")), s("cape"),
                     ("callproperty", n("getChildByName"), 1), argc=1) +
                call("hide", ("getlex", n("parent")), s("hair"), ("callproperty", n("getChildByName"), 1), argc=1) +
                call("anchor") + [("returnvoid",)],
        "listen": start + [("pushbyte", 0), ("setlocal", 4), ("getlocal1",), ("coerce_a",), ("setlocal", 5),
                           ("jump", "@next"),
                           "@each", ("label",), ("getlocal", 5), ("getlocal", 4), ("nextvalue",), ("setlocal3",),
                           ("getlex", n("avatar")), ("getlocal3",), ("getlocal2",), ("pushtrue",),
                           ("callpropvoid", n("addAnimationListener"), 3),
                           ("getlex", n("registrations")), ("getlocal3",), ("callpropvoid", n("push"), 1),
                           "@next", ("hasnext2", 5, 4), ("iftrue", "@each"), ("returnvoid",)],
        "hide": start + [("getlocal1",), ("pushnull",), ("ifne", "@go"), ("returnvoid",),
                         "@go", ("getlocal1",), ("pushfalse",), ("setproperty", n("visible")), ("returnvoid",)],
        "anchor": start + [("getlex", n("parent")), ("getproperty", n("transform")), ("getproperty", n("matrix")),
                           ("callproperty", n("clone"), 0), ("setlocal1",), ("getlocal1",),
                           ("callpropvoid", n("invert"), 0), ("getlex", n("transform")), ("getlocal1",),
                           ("setproperty", n("matrix")), ("returnvoid",)],
        "setMotion": start + [("getlex", n("motion")), ("getlocal1",), ("ifne", "@set"), ("getlocal2",),
                              ("iftrue", "@set"), ("returnvoid",),
                              "@set", ("findproperty", n("motion")), ("getlocal1",), ("setproperty", n("motion"))] +
                     call("gotoAndStop", ("getlocal1",)) + [("returnvoid",)],
        "onIdle": start + [("getlex", n("motion")), s("Slash"), ("ifeq", "@skip")] + call("setMotion", s("Idle")) +
                  ["@skip", ("returnvoid",)],
        "onWalk": start + call("setMotion", s("Walk")) + [("returnvoid",)],
        "onSlash": start + call("setMotion", s("Slash"), ("pushtrue",)) + [("returnvoid",)],
        "onTick": start + [("getlex", n("avatar")), ("pushnull",), ("ifne", "@run")] + call("bind") +
                  [("returnvoid",), "@run"] + call("anchor") + call("getChildByName", s("body"), void=False) +
                  [("setlocal2",), ("getlex", n("motion")), s("Slash"), ("ifne", "@end"),
                   ("getlocal2",), ("pushnull",), ("ifeq", "@end"),
                   ("getlocal2",), ("getproperty", n("currentFrame")), ("getlocal2",),
                   ("getproperty", n("totalFrames")), ("ifne", "@end")] +
                  call("setMotion", s("Idle"), ("pushtrue",)) + ["@end", ("returnvoid",)],
    }
    methods = {name: b.method(8, 6, 10, 11, _asm(steps).bytes()) for name, steps in code.items()}
    traits = [SlotTrait(n("avatar"), 0, 0), SlotTrait(n("registrations"), 0, 0),
              SlotTrait(n("motion"), 0, n("String"), b.string("Portrait"))]
    traits += [MethodTrait(n(name), index) for name, index in methods.items() if name != "iinit"]
    cinit = b.method(1, 1, 9, 10, _asm(start + [("returnvoid",)]).bytes())
    class_mn = n(head_name)
    class_index = b.add_class(class_mn, movieclip, b.namespace(PROTECTED, head_name), methods["iinit"], cinit, traits)
    init = _asm(start + [("getscopeobject", 0)])
    for ns, ancestor in ANCESTORS:
        init.getlex(b.qname(PACKAGE, ns, ancestor)).pushscope()
    init.getlex(movieclip).newclass(class_index)
    for _ in ANCESTORS:
        init.popscope()
    init.initproperty(class_mn).returnvoid()
    b.add_script(b.method(2, 1, 1, 9, init.bytes()), class_mn, class_index)
    return build_swf(list(parts.values()), names, b.serialize())


def throwing_armor_swf() -> bytes:
    """release_armor_swf whose skill lists name Attack1 twice, so its bind() throws ArgumentError("Duplicate trigger")
    after registering Skill1, Attack1, Skill2 and Cast1."""
    return release_armor_swf(aqw_labels=(("Skill1", "Attack1"), ("Skill2", "Cast1", "Attack1")))


def release_armor_swf(link: str = "TestRelease",
                      aqw_labels: tuple[tuple[str, ...], ...] = (("Skill1", "Attack1"), ("Skill2", "Cast1"))) -> bytes:
    """A male animated armor like the TheSwordHero release of 2026-10-23. Its head's bind() finds the avatar as
    listener_armor_swf's does, then reads which game labels play which skill from another class, <Link>Skills (static
    ANIMATIONS, AQW_LABELS and NATIVE_HOLDS arrays and a static labelFor(slot)): AQW_LABELS[1] = Skill1, Attack1 and
    AQW_LABELS[2] = Skill2, Cast1 go to callbacks [null, onSkill1, onSkill2], an object remembering the labels taken
    (a repeat throws). Then it listens to each of its own frame labels (currentLabels) but Portrait and Skill* through a
    function made per label (nativeCallback(label) returns function () { playStandard(label) }), plays Idle, hides
    the cape and the hair and anchors. Every listener blocks. The head has five one-frame labels: Portrait (a shape
    named headOnly), then Idle, Walk, Skill1 and Skill2, each placing a clip named body that plays 1, 2, 3 and 2 frames
    (the Skill1 body also holds a clip named spark). setMotion goes to the label, restarts the body (gotoAndPlay(1))
    and its child clips; a motion not in NATIVE_HOLDS (Idle, Walk) is transient: onTick goes back to Idle when its body
    ends."""
    from autoswf.abc.movieclip_classes import ANCESTORS, _add_class
    from autoswf.abc.writer import NEED_ACTIVATION, PACKAGE, PROTECTED, AbcBuilder, SlotTrait
    colors = {"head": (230, 190, 150, 255), "Idle": (100, 200, 100, 255), "Walk": (100, 100, 220, 255),
              "Skill1": (220, 80, 80, 255), "Skill2": (200, 120, 220, 255)}
    spark = Symbol("Spark", [Frame([Placement(_shape((250, 230, 90, 255), 3 + k), 1)]) for k in range(4)])
    bodies = {label: Symbol("Body" + label,
                            [Frame([Placement(_shape(colors[label], 10 + 3 * k, 30), 1)] +
                                   ([Placement(spark, 2, name="spark")] if label == "Skill1" else []))
                             for k in range(count)])
              for label, count in (("Idle", 1), ("Walk", 2), ("Skill1", 3), ("Skill2", 2))}
    head = Symbol("Head", [Frame([Placement(_shape(colors["head"], 12, 12), 1, name="headOnly")], "Portrait")] +
                  [Frame([Placement(bodies[label], 1, name="body")], label)
                   for label in ("Idle", "Walk", "Skill1", "Skill2")])
    parts = {part: Symbol(part, [Frame()]) for part in ("Chest", "Hip", "Shoulder", "Hand", "Thigh", "Shin", "Foot",
                                                       "FootIdle", "Robe", "RobeBack")}
    parts["Head"] = head
    names = {id(sym): "%sM%s" % (link, part) for part, sym in parts.items()}

    b = AbcBuilder()
    for name in names.values():
        if not name.endswith("Head"):
            _add_class(b, ClassSpec(name))
    head_name, skills_name = link + "MHead", link + "Skills"
    movieclip = b.qname(PACKAGE, "flash.display", "MovieClip")
    event = b.qname(PACKAGE, "flash.events", "Event")
    late = b.multiname_late([(PACKAGE, "")])

    def n(name):
        return b.qname(PACKAGE, "", name)

    def s(text):
        return ("pushstring", b.string(text))

    def call(method, *pushes, argc=None, void=True):
        return [("findpropstrict", n(method)), *pushes,
                ("callpropvoid" if void else "callproperty", n(method), len(pushes) if argc is None else argc)]

    def method(steps, scopes: int = 1, **options):
        """`scopes`: how many scopes the code pushes (a real AVM2 verifies it)."""
        return b.method(8, 10, 10, 10 + scopes, _asm(steps).bytes(), **options)

    start = [("getlocal0",), ("pushscope",)]
    body = call("getChildByName", s("body"), void=False) + [("getlex", movieclip), ("astypelate",)]
    closure = method(call("playStandard", ("getlex", n("label"))) + [("returnvoid",)])
    code = {
        "iinit": start + [("getlocal0",), ("newarray", 0), ("setproperty", n("registrations")),
                          ("getlocal0",), ("constructsuper", 0)] + call("stop") +
                 [("findpropstrict", n("addEventListener")), ("getlex", event), ("getproperty", n("ADDED_TO_STAGE")),
                  ("getlex", n("onAdded")), ("callpropvoid", n("addEventListener"), 2),
                  ("findpropstrict", n("addEventListener")), ("getlex", event), ("getproperty", n("ENTER_FRAME")),
                  ("getlex", n("onTick")), ("callpropvoid", n("addEventListener"), 2), ("returnvoid",)],
        "onAdded": start + call("bind") + [("returnvoid",)],
        "bind": start + [("getlex", n("avatar")), ("pushnull",), ("ifeq", "@search"), ("returnvoid",),
                         "@search", ("getlex", n("parent")), ("setlocal1",), ("jump", "@check"),
                         "@loop", ("label",), s("addAnimationListener"), ("getlocal1",), ("in_",), ("iffalse", "@up"),
                         ("findproperty", n("avatar")), ("getlocal1",), ("setproperty", n("avatar")), ("jump", "@found"),
                         "@up", ("getlocal1",), ("getproperty", n("parent")), ("setlocal1",),
                         "@check", ("getlocal1",), ("pushnull",), ("ifne", "@loop"),
                         "@found", ("getlex", n("avatar")), ("pushnull",), ("ifne", "@bound"), ("returnvoid",),
                         # var taken = {}, callbacks = [null, onSkill1, onSkill2]
                         "@bound", ("newobject", 0), ("setlocal2",),
                         ("pushnull",), ("getlex", n("onSkill1")), ("getlex", n("onSkill2")), ("newarray", 3),
                         ("setlocal3",),
                         # for (slot = 1; slot < 3; slot++) for each (label in Skills.AQW_LABELS[slot])
                         ("pushbyte", 1), ("setlocal", 5), ("jump", "@slots"),
                         "@slot", ("label",), ("pushbyte", 0), ("setlocal", 7),
                         ("getlex", n(skills_name)), ("getproperty", n("AQW_LABELS")), ("getlocal", 5),
                         ("getproperty", late), ("coerce_a",), ("setlocal", 8), ("jump", "@labels"),
                         "@label", ("label",), ("getlocal", 8), ("getlocal", 7), ("nextvalue",), ("coerce_s",),
                         ("setlocal", 4),
                         ("getlocal2",), ("getlocal", 4), ("getproperty", late), ("iffalse", "@fresh"),
                         ("findpropstrict", n("ArgumentError")), s("Duplicate trigger"),
                         ("constructprop", n("ArgumentError"), 1), ("throw",),
                         "@fresh", ("findpropstrict", n("listen")), ("getlocal", 4), ("getlocal3",), ("getlocal", 5),
                         ("getproperty", late), ("callpropvoid", n("listen"), 2),
                         ("getlocal2",), ("getlocal", 4), ("pushtrue",), ("setproperty", late),
                         "@labels", ("hasnext2", 8, 7), ("iftrue", "@label"),
                         ("kill", 8), ("kill", 7), ("inclocal_i", 5),
                         "@slots", ("getlocal", 5), ("pushbyte", 3), ("lessthan",), ("iftrue", "@slot"),
                         # for each (item in currentLabels): skip Portrait, Skill* and taken labels
                         ("pushbyte", 0), ("setlocal", 7), ("getlex", n("currentLabels")), ("coerce_a",),
                         ("setlocal", 8), ("jump", "@natives"),
                         "@native", ("label",), ("getlocal", 8), ("getlocal", 7), ("nextvalue",), ("setlocal", 6),
                         ("getlocal", 6), ("getproperty", n("name")), ("convert_s",), ("setlocal", 4),
                         ("getlocal", 4), s("Portrait"), ("ifeq", "@natives"),
                         ("getlocal", 4), s("Skill"), ("callproperty", n("indexOf"), 1), ("pushbyte", 0),
                         ("ifeq", "@natives"),
                         ("getlocal2",), ("getlocal", 4), ("getproperty", late), ("iftrue", "@natives"),
                         ("findpropstrict", n("listen")), ("getlocal", 4), ("findpropstrict", n("nativeCallback")),
                         ("getlocal", 4), ("callproperty", n("nativeCallback"), 1), ("callpropvoid", n("listen"), 2),
                         "@natives", ("hasnext2", 8, 7), ("iftrue", "@native")] +
                call("playStandard", s("Idle"), ("pushtrue",)) +
                call("hide", ("getlex", n("avatar")), ("getproperty", n("mcChar")), s("cape"),
                     ("callproperty", n("getChildByName"), 1), argc=1) +
                call("hide", ("getlex", n("parent")), s("hair"), ("callproperty", n("getChildByName"), 1), argc=1) +
                call("anchor") + [("returnvoid",)],
        "listen": start + [("getlex", n("avatar")), ("getlocal1",), ("getlocal2",), ("pushtrue",),
                           ("callpropvoid", n("addAnimationListener"), 3),
                           ("getlex", n("registrations")), ("getlocal1",), ("getlocal2",), ("newarray", 2),
                           ("callpropvoid", n("push"), 1), ("returnvoid",)],
        "onSkill1": start + call("playSkill", ("pushbyte", 1)) + [("returnvoid",)],
        "onSkill2": start + call("playSkill", ("pushbyte", 2)) + [("returnvoid",)],
        "playSkill": start + [("getlex", n(skills_name)), ("getlocal1",), ("callproperty", n("labelFor"), 1),
                              ("coerce_s",), ("setlocal2",)] + call("setMotion", ("getlocal2",), ("pushtrue",)) +
                     [("findproperty", n("transient")), ("pushtrue",), ("setproperty", n("transient")),
                      ("returnvoid",)],
        "playStandard": start + call("hasLabel", ("getlocal1",), void=False) + [("iftrue", "@has"), ("returnvoid",),
                        "@has", ("findproperty", n("transient")), ("getlex", n(skills_name)),
                        ("getproperty", n("NATIVE_HOLDS")), ("getlocal1",), ("callproperty", n("indexOf"), 1),
                        ("pushbyte", 0), ("lessthan",), ("setproperty", n("transient"))] +
                        call("setMotion", ("getlocal1",), ("getlocal2",)) + [("returnvoid",)],
        "hasLabel": start + [("pushbyte", 0), ("setlocal3",), ("getlex", n("currentLabels")), ("coerce_a",),
                             ("setlocal", 4), ("jump", "@next"),
                             "@each", ("label",), ("getlocal", 4), ("getlocal3",), ("nextvalue",), ("setlocal2",),
                             ("getlocal2",), ("getproperty", n("name")), ("getlocal1",), ("ifne", "@next"),
                             ("pushtrue",), ("returnvalue",),
                             "@next", ("hasnext2", 4, 3), ("iftrue", "@each"), ("pushfalse",), ("returnvalue",)],
        "setMotion": start + [("getlex", n("motion")), ("getlocal1",), ("ifne", "@set"), ("getlocal2",),
                              ("iftrue", "@set"), ("returnvoid",),
                              "@set", ("findproperty", n("motion")), ("getlocal1",), ("setproperty", n("motion"))] +
                     call("gotoAndStop", ("getlocal1",)) + body +
                     [("setlocal3",), ("getlocal3",), ("pushnull",), ("ifeq", "@end"),
                      ("getlocal3",), ("pushbyte", 1), ("callpropvoid", n("gotoAndPlay"), 1)] +
                     call("restartChildren", ("getlocal3",)) + ["@end", ("returnvoid",)],
        "restartChildren": start + [("pushbyte", 0), ("setlocal2",), ("jump", "@check"),
                                    "@loop", ("label",), ("getlocal1",), ("getlocal2",),
                                    ("callproperty", n("getChildAt"), 1), ("getlex", movieclip), ("astypelate",),
                                    ("setlocal3",), ("getlocal3",), ("pushnull",), ("ifeq", "@skip"),
                                    ("getlocal3",), ("pushbyte", 1), ("callpropvoid", n("gotoAndPlay"), 1)] +
                           call("restartChildren", ("getlocal3",)) +
                           ["@skip", ("inclocal_i", 2),
                            "@check", ("getlocal2",), ("getlocal1",), ("getproperty", n("numChildren")), ("lessthan",),
                            ("iftrue", "@loop"), ("returnvoid",)],
        "hide": start + [("getlocal1",), ("pushnull",), ("ifne", "@go"), ("returnvoid",),
                         "@go", ("getlocal1",), ("pushfalse",), ("setproperty", n("visible")), ("returnvoid",)],
        "anchor": start + [("getlex", n("parent")), ("getproperty", n("transform")), ("getproperty", n("matrix")),
                           ("callproperty", n("clone"), 0), ("setlocal1",), ("getlocal1",),
                           ("callpropvoid", n("invert"), 0), ("getlex", n("transform")), ("getlocal1",),
                           ("setproperty", n("matrix")), ("returnvoid",)],
        "onTick": start + [("getlex", n("avatar")), ("pushnull",), ("ifne", "@run")] + call("bind") +
                  [("returnvoid",), "@run"] + call("anchor") + body +
                  [("setlocal2",), ("getlex", n("transient")), ("iffalse", "@end"),
                   ("getlocal2",), ("pushnull",), ("ifeq", "@end"),
                   ("getlocal2",), ("getproperty", n("currentFrame")), ("getlocal2",),
                   ("getproperty", n("totalFrames")), ("ifne", "@end"),
                   ("findproperty", n("transient")), ("pushfalse",), ("setproperty", n("transient"))] +
                  call("setMotion", s("Idle"), ("pushtrue",)) + ["@end", ("returnvoid",)],
    }
    native_callback = start + [("newactivation",), ("dup",), ("setlocal2",), ("pushscope",), ("getscopeobject", 1),
                               ("getlocal1",), ("coerce_s",), ("setslot", 1), ("newfunction", closure),
                               ("returnvalue",)]
    # the arguments each method takes, as a real AVM2 checks them (restart:Boolean = false is optional)
    params = {"onAdded": 1, "onTick": 1, "listen": 2, "playSkill": 1, "playStandard": 2, "hasLabel": 1, "setMotion": 2,
              "restartChildren": 1, "hide": 1}
    false_default = ((0x0A, 0),)
    methods = {name: method(steps, params=params.get(name, 0),
                            optional=false_default if name in ("playStandard", "setMotion") else ())
               for name, steps in code.items()}
    methods["nativeCallback"] = method(native_callback, scopes=2, flags=NEED_ACTIVATION, params=1,
                                       traits=(SlotTrait(n("label"), 1, n("String")),))
    traits = [SlotTrait(n("avatar"), 0, 0), SlotTrait(n("registrations"), 0, 0),
              SlotTrait(n("motion"), 0, n("String"), b.string("Portrait")), SlotTrait(n("transient"), 0, n("Boolean"))]
    traits += [MethodTrait(n(name), index) for name, index in methods.items() if name != "iinit"]
    cinit = method(start + [("returnvoid",)])
    class_mn = n(head_name)
    class_index = b.add_class(class_mn, movieclip, b.namespace(PROTECTED, head_name), methods["iinit"], cinit, traits)
    init = _asm(start + [("getscopeobject", 0)])
    for ns, ancestor in ANCESTORS:
        init.getlex(b.qname(PACKAGE, ns, ancestor)).pushscope()
    init.getlex(movieclip).newclass(class_index)
    for _ in ANCESTORS:
        init.popscope()
    init.initproperty(class_mn).returnvoid()
    b.add_script(b.method(2, 1, 1, 9, init.bytes()), class_mn, class_index)

    skills_init = method(start + [("findproperty", n("ANIMATIONS")), ("pushnull",), s("Skill1"), s("Skill2"),
                                  ("newarray", 3), ("initproperty", n("ANIMATIONS")),
                                  ("findproperty", n("AQW_LABELS")), ("pushnull",)] +
                         [step for labels in aqw_labels for step in [s(label) for label in labels] +
                          [("newarray", len(labels))]] +
                         [("newarray", 1 + len(aqw_labels)), ("initproperty", n("AQW_LABELS")),
                                  ("findproperty", n("NATIVE_HOLDS")), s("Idle"), s("Walk"), ("newarray", 2),
                                  ("initproperty", n("NATIVE_HOLDS")), ("returnvoid",)])
    label_for = method(start + [("getlex", n("ANIMATIONS")), ("getlocal1",), ("getproperty", late), ("convert_s",),
                                ("returnvalue",)], params=1)
    statics = [SlotTrait(n("ANIMATIONS"), 1, n("Array")), SlotTrait(n("AQW_LABELS"), 2, n("Array")),
               SlotTrait(n("NATIVE_HOLDS"), 3, n("Array")), MethodTrait(n("labelFor"), label_for)]
    skills_mn, base = n(skills_name), n("Object")
    skills_index = b.add_class(skills_mn, base, b.namespace(PROTECTED, skills_name),
                               method(start + [("getlocal0",), ("constructsuper", 0), ("returnvoid",)]), skills_init,
                               [], statics)
    init = _asm(start + [("getscopeobject", 0), ("getlex", base), ("pushscope",), ("getlex", base),
                         ("newclass", skills_index), ("popscope",), ("initproperty", skills_mn), ("returnvoid",)])
    b.add_script(b.method(2, 1, 1, 9, init.bytes()), skills_mn, skills_index)
    return build_swf(list(parts.values()), names, b.serialize())
