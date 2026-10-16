"""MovieClip subclasses with frame scripts, emitted exactly like Flash/Animate does for AQW items.

Patterns verified against official AQW files (hair Normal.swf, redcape.swf, RainbowPet.swf) and the
user's CrystallisOnsenMMorph4.swf: one script per class, dynamic classes with a protected namespace,
frame methods in the package-internal namespace, fixed method-body headers.
"""
from dataclasses import dataclass

from autoswf.abc.code import Code
from autoswf.abc.writer import PACKAGE, PACKAGE_INTERNAL, PROTECTED, AbcBuilder, MethodTrait
from autoswf.model.document import FrameScript, GotoAndPlayScript, SetColorScript, StopScript

ANCESTORS = [("", "Object"), ("flash.events", "EventDispatcher"), ("flash.display", "DisplayObject"),
             ("flash.display", "InteractiveObject"), ("flash.display", "DisplayObjectContainer"),
             ("flash.display", "Sprite"), ("flash.display", "MovieClip")]


@dataclass(frozen=True)
class ClassSpec:
    qualified_name: str                                         # "Name" or "pkg.Name"
    frame_scripts: tuple[tuple[int, FrameScript], ...] = ()     # (0-based frame index, script)


def expected_setcolor_ops(package: str, location: str, shade: str) -> list[tuple[str, tuple[str, ...]]]:
    """Reference instructions of `MovieClip(stage.getChildAt(0)).mcSetColor(this, location, shade)`."""
    return [("getlocal0", ()), ("pushscope", ()), ("findpropstrict", ("flash.display.MovieClip",)), ("getlocal0", ()),
            ("getproperty", ("stage",)), ("pushbyte", ("0",)), ("callproperty", ("getChildAt", "1")),
            ("callproperty", ("flash.display.MovieClip", "1")), ("getlocal0", ()), ("pushstring", (repr(location),)),
            ("pushstring", (repr(shade),)), ("callpropvoid", ("mcSetColor", "3")), ("returnvoid", ())]


def _public(b: AbcBuilder, name: str) -> int:
    return b.qname(PACKAGE, "", name)


def _frame_method(b: AbcBuilder, script: FrameScript) -> int:
    c = Code().getlocal0().pushscope()
    if isinstance(script, SetColorScript):
        movieclip = b.qname(PACKAGE, "flash.display", "MovieClip")
        c.findpropstrict(movieclip).getlocal0().getproperty(_public(b, "stage")).pushbyte(0)
        c.callproperty(_public(b, "getChildAt"), 1).callproperty(movieclip, 1).getlocal0()
        c.pushstring(b.string(script.location)).pushstring(b.string(script.shade))
        c.callpropvoid(_public(b, "mcSetColor"), 3).returnvoid()
        return b.method(4, 1, 10, 11, c.bytes())
    if isinstance(script, StopScript):
        stop = _public(b, "stop")
        return b.method(1, 1, 10, 11, c.findpropstrict(stop).callpropvoid(stop, 0).returnvoid().bytes())
    if isinstance(script, GotoAndPlayScript):
        goto = _public(b, "gotoAndPlay")
        c.findpropstrict(goto).pushstring(b.string(script.label)).callpropvoid(goto, 1).returnvoid()
        return b.method(2, 1, 10, 11, c.bytes())
    raise TypeError("unsupported frame script %r" % (script,))


def _add_class(b: AbcBuilder, spec: ClassSpec) -> None:
    package, _, name = spec.qualified_name.rpartition(".")
    movieclip = b.qname(PACKAGE, "flash.display", "MovieClip")
    class_mn = b.qname(PACKAGE, package, name)
    protected = b.namespace(PROTECTED, "%s:%s" % (package, name) if package else name)

    traits, refs = [], []
    for index, script in sorted(spec.frame_scripts, key=lambda s: s[0]):
        trait_mn = b.qname(PACKAGE_INTERNAL, package, "frame%d" % (index + 1))
        traits.append(MethodTrait(trait_mn, _frame_method(b, script)))
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


def build_abc(classes: list[ClassSpec]) -> bytes:
    b = AbcBuilder()
    for spec in classes:
        _add_class(b, spec)
    return b.serialize()
