"""MovieClip subclasses with frame scripts, emitted exactly like Flash/Animate does for AQW items.

Patterns verified against official AQW files (hair Normal.swf, redcape.swf, RainbowPet.swf) and the
user's CrystallisOnsenMMorph4.swf: one script per class, dynamic classes with a protected namespace,
frame methods in the package-internal namespace, fixed method-body headers.
"""
from dataclasses import dataclass

from autoswf.abc.code import Code
from autoswf.abc.writer import (NAMESPACE, NEED_ACTIVATION, PACKAGE, PACKAGE_INTERNAL, PRIVATE, PROTECTED,
                                STATIC_PROTECTED, AbcBuilder, MethodTrait, SlotTrait)
from autoswf.model.document import FrameScript, GotoAndPlayScript, SetColorScript, StopScript

ANCESTORS = [("", "Object"), ("flash.events", "EventDispatcher"), ("flash.display", "DisplayObject"),
             ("flash.display", "InteractiveObject"), ("flash.display", "DisplayObjectContainer"),
             ("flash.display", "Sprite"), ("flash.display", "MovieClip")]
AS3_BUILTIN = "http://adobe.com/AS3/2006/builtin"
# The forms of the mcSetColor frame script found in AQW items (verified 2026-10-18): ours and hair/M/Normal.swf
# ("plain", header 4,1,10,11); the call inside try/catch (the user's morph, PalidanRevamp: "try", 4,2,10,13); and
# with an activation object first (the user's KindOfBrave.swf: "activation", 4,3,11,16).
SETCOLOR_FORMS = ("plain", "try", "activation")
SETCOLOR_HEADERS = {"plain": (4, 1, 10, 11), "try": (4, 2, 10, 13), "activation": (4, 3, 11, 16)}


def open_namespaces(class_name: str) -> list[tuple[int, str]]:
    """Namespaces Flash leaves open inside a frame script; `mcSetColor` is resolved through them."""
    package, _, name = class_name.rpartition(".")
    qualified = "%s:%s" % (package, name) if package else name
    spaces = [(PRIVATE, ""), (PACKAGE, "flash.display"), (PACKAGE, ""), (PACKAGE, package),
              (PACKAGE_INTERNAL, package), (NAMESPACE, AS3_BUILTIN), (PROTECTED, qualified), (STATIC_PROTECTED, qualified)]
    spaces += [(STATIC_PROTECTED, "%s:%s" % (ns, cls)) for ns, cls in reversed(ANCESTORS[1:])]
    return list(dict.fromkeys(spaces))


@dataclass(frozen=True)
class ClassSpec:
    qualified_name: str                                         # "Name" or "pkg.Name"
    frame_scripts: tuple[tuple[int, FrameScript], ...] = ()     # (0-based frame index, script)


def expected_setcolor_ops(class_name: str, location: str, shade: str, raw: bool = False,
                          form: str = "plain") -> list[tuple[str, tuple[str, ...]]]:
    """Reference instructions of `MovieClip(stage.getChildAt(0)).mcSetColor(this, location, shade)` in one of the
    SETCOLOR_FORMS. With raw=True (plain form only) multinames are spelled out with their kind and namespaces, as
    `disassemble(raw=True)` prints them. In the try forms the jump's target is written "->end"."""
    if raw:
        mc, stage, child = "QName(Package:'flash.display',MovieClip)", "QName(Package:'',stage)", "QName(Package:'',getChildAt)"
        kinds = {0x05: "Private", 0x08: "Namespace", 0x16: "Package", 0x17: "PackageInternal", 0x18: "Protected",
                 0x1A: "StaticProtected"}
        setcolor = "Multiname(mcSetColor,[%s])" % ",".join("%s:%r" % (kinds[k], n) for k, n in open_namespaces(class_name))
    else:
        mc, stage, child, setcolor = "flash.display.MovieClip", "stage", "getChildAt", "mcSetColor"
    call = [("findpropstrict", (mc,)), ("getlocal0", ()), ("getproperty", (stage,)), ("pushbyte", ("0",)),
            ("callproperty", (child, "1")), ("callproperty", (mc, "1")), ("getlocal0", ()),
            ("pushstring", (repr(location),)), ("pushstring", (repr(shade),)), ("callpropvoid", (setcolor, "3"))]
    head = [("getlocal0", ()), ("pushscope", ())]
    if form == "plain":
        return head + call + [("returnvoid", ())]
    if form == "try":
        handler = [("getlocal0", ()), ("pushscope", ()), ("newcatch", ("0",)), ("dup", ()), ("setlocal1", ()),
                   ("dup", ()), ("pushscope", ()), ("swap", ()), ("setslot", ("1",)), ("popscope", ()), ("kill", ("1",))]
        return head + call + [("jump", ("->end",))] + handler + [("returnvoid", ())]
    if form == "activation":
        head += [("newactivation", ()), ("dup", ()), ("setlocal1", ()), ("pushscope", ())]
        handler = [("getlocal0", ()), ("pushscope", ()), ("getlocal1", ()), ("pushscope", ()), ("newcatch", ("0",)),
                   ("dup", ()), ("setlocal2", ()), ("dup", ()), ("pushscope", ()), ("swap", ()), ("setslot", ("1",)),
                   ("popscope", ()), ("kill", ("2",))]
        return head + call + [("jump", ("->end",))] + handler + [("returnvoid", ())]
    raise ValueError("Unknown mcSetColor form '%s'" % form)


def _public(b: AbcBuilder, name: str) -> int:
    return b.qname(PACKAGE, "", name)


def _setcolor_method(b: AbcBuilder, script: SetColorScript, class_name: str, form: str) -> int:
    c = Code().getlocal0().pushscope()
    if form == "activation":
        c.newactivation().dup().setlocal1().pushscope()
    start = len(c)
    movieclip = b.qname(PACKAGE, "flash.display", "MovieClip")
    c.findpropstrict(movieclip).getlocal0().getproperty(_public(b, "stage")).pushbyte(0)
    c.callproperty(_public(b, "getChildAt"), 1).callproperty(movieclip, 1).getlocal0()
    c.pushstring(b.string(script.location)).pushstring(b.string(script.shade))
    c.callpropvoid(b.multiname("mcSetColor", open_namespaces(class_name)), 3)
    if form == "plain":
        return b.method(*SETCOLOR_HEADERS[form], c.returnvoid().bytes())
    end_of_try = len(c)
    handler = Code().getlocal0().pushscope()
    if form == "activation":
        handler.getlocal1().pushscope()
    local = 2 if form == "activation" else 1
    handler.newcatch(0).dup()
    (handler.setlocal2() if local == 2 else handler.setlocal1())
    handler.dup().pushscope().swap().setslot(1).popscope().kill(local)
    c.jump(len(handler))
    target = len(c)
    code = c.bytes() + handler.bytes() + Code().returnvoid().bytes()
    error, e = b.qname(PACKAGE, "", "Error"), b.qname(PACKAGE, "", "e")
    traits = (SlotTrait(e, 1, error),) if form == "activation" else ()
    return b.method(*SETCOLOR_HEADERS[form], code, flags=NEED_ACTIVATION if form == "activation" else 0,
                    exceptions=((start, end_of_try, target, error, e),), traits=traits)


def _frame_method(b: AbcBuilder, script: FrameScript, class_name: str, setcolor_form: str = "plain") -> int:
    c = Code().getlocal0().pushscope()
    if isinstance(script, SetColorScript):
        return _setcolor_method(b, script, class_name, setcolor_form)
    if isinstance(script, StopScript):
        stop = _public(b, "stop")
        return b.method(1, 1, 10, 11, c.findpropstrict(stop).callpropvoid(stop, 0).returnvoid().bytes())
    if isinstance(script, GotoAndPlayScript):
        goto = _public(b, "gotoAndPlay")
        c.findpropstrict(goto).pushstring(b.string(script.label)).callpropvoid(goto, 1).returnvoid()
        return b.method(2, 1, 10, 11, c.bytes())
    raise TypeError("unsupported frame script %r" % (script,))


def _add_class(b: AbcBuilder, spec: ClassSpec, setcolor_form: str = "plain") -> None:
    package, _, name = spec.qualified_name.rpartition(".")
    movieclip = b.qname(PACKAGE, "flash.display", "MovieClip")
    class_mn = b.qname(PACKAGE, package, name)
    protected = b.namespace(PROTECTED, "%s:%s" % (package, name) if package else name)

    traits, refs = [], []
    for index, script in sorted(spec.frame_scripts, key=lambda s: s[0]):
        trait_mn = b.qname(PACKAGE_INTERNAL, package, "frame%d" % (index + 1))
        traits.append(MethodTrait(trait_mn, _frame_method(b, script, spec.qualified_name, setcolor_form)))
        refs.append((index, trait_mn))

    ctor = Code().getlocal0().pushscope().getlocal0().constructsuper(0)
    if refs:
        add_frame_script = _public(b, "addFrameScript")
        ctor.findpropstrict(add_frame_script)
        for index, trait_mn in refs:
            (ctor.pushbyte(index) if index < 128 else ctor.pushshort(index)).getlex(trait_mn)
        ctor.callpropvoid(add_frame_script, 2 * len(refs))
    iinit = b.method(1 + 2 * len(refs), 1, 10, 11, ctor.returnvoid().bytes())
    cinit = b.method(1, 1, 9, 10, Code().getlocal0().pushscope().returnvoid().bytes())
    class_index = b.add_class(class_mn, movieclip, protected, iinit, cinit, traits)

    init = Code().getlocal0().pushscope().getscopeobject(0)
    for ns, ancestor in ANCESTORS:
        init.getlex(b.qname(PACKAGE, ns, ancestor)).pushscope()
    init.getlex(movieclip).newclass(class_index)
    for _ in ANCESTORS:
        init.popscope()
    init.initproperty(class_mn).returnvoid()
    b.add_script(b.method(2, 1, 1, 9, init.bytes()), class_mn, class_index)


def build_abc(classes: list[ClassSpec], setcolor_form: str = "plain") -> bytes:
    """`setcolor_form` other than "plain" reproduces AQW's other official forms (test material; AutoSWF writes
    "plain")."""
    if setcolor_form not in SETCOLOR_FORMS:
        raise ValueError("Unknown mcSetColor form '%s'" % setcolor_form)
    b = AbcBuilder()
    for spec in classes:
        _add_class(b, spec, setcolor_form)
    return b.serialize()
