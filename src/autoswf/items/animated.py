"""Animated armors (spec §15): every part class empty except <Link><G>Head, a whole animated character that registers
`addAnimationListener(gameLabel, handler[, block])` on the avatar and plays its own labels from the handlers. The
listeners may come from frame scripts (AzraelGuardianArmor.swf) or from methods that run once the head is on stage
(TheSwordHero.swf: bind() walks up to the avatar and registers lists of game labels). A small interpreter runs the head
class's code the way the client would: its fields and methods, arrays and for-each loops, if/else on strings, numbers
and booleans, the avatar around the head (the head clip, the skeleton, the avatar and the world's flags), goto/stop/play,
the skeleton's gotoAndPlay, hiding the avatar's clips and cancelling the parent's transform. It stops with a note on
anything else."""
import ast
import copy
import math
from dataclasses import dataclass, field

from autoswf.abc.disasm import disassemble
from autoswf.abc.reader import ABC
from autoswf.swf.decode import MovieData, SpriteDef

THIS, OTHER, NULL = ("this",), ("other",), ("null",)
PRIMITIVES = ("bool", "int", "str", "null")
OBJECTS = ("this", "method", "array", "matrix")
MAX_STEPS = 50000
MAX_CALL_DEPTH = 16
CALLS = ("callproperty", "callpropvoid", "callproplex")
NEUTRAL = {"nop", "label", "coerce", "coerce_a", "coerce_s", "coerce_i", "coerce_d", "coerce_u", "coerce_o", "convert_s",
           "convert_i", "convert_d", "convert_u", "convert_o", "astype", "checkfilter", "debug", "debugline",
           "debugfile", "bkpt", "bkptline", "timestamp", "popscope"}
CASTS = {"MovieClip", "Sprite", "DisplayObject", "DisplayObjectContainer", "InteractiveObject", "Object"}
DISPLAY = {"parent", "stage", "root", "transform", "currentFrame", "totalFrames", "currentLabel", "numChildren", "x", "y",
           "scaleX", "scaleY", "rotation", "alpha", "visible", "name"}
SCALARS = DISPLAY - {"parent", "stage", "root", "transform"} | {"length"}
AVATAR_MEMBERS = frozenset({"addAnimationListener", "removeAnimationListener", "mcChar", "pAV", "objLinks"})
EVENTS = {"ADDED_TO_STAGE": "addedToStage", "ENTER_FRAME": "enterFrame", "REMOVED_FROM_STAGE": "removedFromStage",
          "ADDED": "added", "REMOVED": "removed"}
HEAD, SKELETON, AVATAR = (1, ()), (2, ()), (3, ())         # places around the armor's head clip (see locate)
FIELD_DEFAULTS = {"Boolean": ("bool", False), "int": ("int", 0), "uint": ("int", 0), "Number": ("int", 0)}
NOT_READ = ("Which game animation plays which of its animations cannot be read from its scripts; the preview plays "
            "them by name")


@dataclass(frozen=True)
class Listen:
    game_label: str
    handler: str
    block: bool


@dataclass(frozen=True)
class Goto:
    target: str | int            # label, or 0-based frame
    play: bool


@dataclass(frozen=True)
class StopClip:
    pass


@dataclass(frozen=True)
class PlayClip:
    pass


@dataclass(frozen=True)
class SkeletonPlay:
    label: str


@dataclass(frozen=True)
class OnEvent:
    """addEventListener on the clip: "addedToStage", "enterFrame"…"""
    event: str
    handler: str


@dataclass(frozen=True)
class SetVisible:
    place: tuple                 # see locate()
    visible: bool


@dataclass(frozen=True)
class Anchor:
    """The clip cancels its parent's transform: it is drawn in the skeleton's space, not the head's."""


@dataclass(frozen=True)
class Unread:
    """An addAnimationListener call whose game label or handler could not be read."""


def _short(name: str) -> str:
    return name.rpartition(".")[2]


def _int(op: str, text: str) -> int:
    v = int(text)
    return v - 256 if op == "pushbyte" and v > 127 else v


def _value(v) -> tuple:
    if v is None:
        return NULL
    if isinstance(v, bool):
        return ("bool", v)
    if isinstance(v, (int, float)):
        return ("int", v)
    return ("str", str(v))


def locate(path: tuple) -> tuple[int, tuple[str, ...]] | None:
    """Where a path from the head clip leads: (how many parents up, then the names down); the avatar's mcChar is the
    skeleton. None for paths that start elsewhere (the stage, a class)."""
    ups, downs = 0, ()
    for name in path:
        if name == "parent":
            if downs:
                downs = downs[:-1]
            else:
                ups += 1
        elif name == "mcChar" and (ups, downs) == AVATAR:
            ups = 2
        elif name in ("stage", "root") or name[:1].isupper():
            return None
        else:
            downs += (name,)
    return ups, downs


class Host:
    """What the head's scripts see around it. This one knows the avatar's shape (the head clip, the skeleton, the
    avatar with addAnimationListener and mcChar above them) and the world's flags; the rig's host also knows its
    clips. Each answer is None when it is unknown."""

    def __init__(self, world: dict | None = None):
        self.world = dict(world or {})

    def value(self, path: tuple) -> tuple | None:
        if path and path[-1] in self.world:
            return _value(self.world[path[-1]])
        return None

    def exists(self, path: tuple) -> bool | None:
        place = locate(path)
        return None if place is None else place[0] <= 4

    def has(self, path: tuple, name: str) -> bool | None:
        place = locate(path)
        if place is None:
            return None
        if place == AVATAR:
            return name in AVATAR_MEMBERS
        return False if name in AVATAR_MEMBERS else None

    def contains(self, path: tuple, other: tuple) -> bool | None:
        place = locate(path)
        if place is not None and not place[1] and 1 <= place[0] <= 3 and other == THIS:
            return True
        return None


@dataclass(eq=False)
class HeadClass:
    """The head's class: its constructor, methods (by short name), fields with their first values and frame
    scripts (0-based frame -> method)."""
    abc: ABC
    name: str
    iinit: int
    methods: dict[str, int]
    fields: dict[str, tuple]
    frame_methods: dict[int, int]
    _code: dict = field(default_factory=dict, repr=False)

    def code(self, method: int):
        if method not in self._code:
            instrs = disassemble(self.abc, self.abc.bodies.get(method, b""))
            self._code[method] = (instrs, {i.offset: k for k, i in enumerate(instrs)})
        return self._code[method]

    def calls(self, name: str) -> bool:
        """Whether any of its code calls a function of this name."""
        return any(i.op in CALLS and _short(i.args[0]) == name
                   for method in (self.iinit, *self.methods.values()) for i in self.code(method)[0])


class _Stop(Exception):
    pass


class _Machine:
    def __init__(self, head: HeadClass, state: dict, host: Host):
        self.head, self.state, self.host = head, state, host
        self.effects: list = []
        self.steps = 0

    # ------------------------------------------------------------ values

    def resolve(self, v):
        if v[0] == "path":
            known = self.host.value(v[1])
            if known is not None:
                return known
        return v

    def truth(self, v) -> bool | None:
        v = self.resolve(v)
        kind = v[0]
        if kind in PRIMITIVES:
            return False if kind == "null" else bool(v[1])
        if kind in OBJECTS:
            return True
        if kind == "path":
            return self.host.exists(v[1])
        return None

    def equal(self, a, b) -> bool | None:
        a, b = self.resolve(a), self.resolve(b)
        if a[0] in PRIMITIVES and b[0] in PRIMITIVES:
            if "null" in (a[0], b[0]):
                return a[0] == b[0]
            return a[1] == b[1]
        if a == NULL or b == NULL:
            other = b if a == NULL else a
            if other[0] == "path":
                exists = self.host.exists(other[1])
                return None if exists is None else not exists
            return False if other[0] in OBJECTS else None
        if a[0] == b[0] == "path":
            if a[1][-1] in SCALARS or b[1][-1] in SCALARS:
                return None
            pa, pb = locate(a[1]), locate(b[1])
            return pa == pb if pa is not None and pb is not None else None
        if THIS in (a, b):
            other = b if a == THIS else a
            if other == THIS:
                return True
            if other[0] == "path":
                place = locate(other[1])
                return None if place is None else place == (0, ())
            return False if other[0] in OBJECTS or other[0] in PRIMITIVES else None
        if a[0] == b[0] == "method":
            return a[1] == b[1]
        return None

    def order(self, op: str, a, b) -> bool | None:
        a, b = self.resolve(a), self.resolve(b)
        if a[0] != "int" or b[0] != "int":
            return None
        base = op.replace("ifn", "if").replace("if", "")
        result = {"lt": a[1] < b[1], "le": a[1] <= b[1], "gt": a[1] > b[1], "ge": a[1] >= b[1],
                  "lessthan": a[1] < b[1], "lessequals": a[1] <= b[1], "greaterthan": a[1] > b[1],
                  "greaterequals": a[1] >= b[1]}[base]
        return not result if op.startswith("ifn") else result

    def own(self, name: str):
        """A property of the clip itself."""
        if name in self.head.methods:
            return ("method", name)
        if name in self.state:
            return self.state[name]
        if name in DISPLAY:
            return self.resolve(("path", (name,)))
        return NULL

    def lex(self, name: str, full: str):
        if name in self.head.methods or name in self.state or name in DISPLAY:
            return self.own(name)
        if name[:1].isupper() or "." in full:
            return ("path", (name,))
        return NULL

    def get(self, obj, name: str):
        if obj == THIS or (obj[0] == "find" and obj[1] == name):
            return self.own(name)
        if obj[0] == "path":
            return self.resolve(("path", obj[1] + (name,)))
        if obj[0] == "array" and name == "length":
            return ("int", len(obj[1]))
        return OTHER

    def set(self, obj, name: str, value) -> None:
        if obj == THIS or obj[0] == "find":
            self.state[name] = value
        elif obj[0] == "path":
            place = locate(obj[1])
            if name == "visible" and value[0] == "bool" and place is not None:
                self.effects.append(SetVisible(place, value[1]))
            elif name == "matrix" and place == (0, ("transform",)) and value[0] == "matrix" and value[2] \
                    and value[1] == HEAD:
                self.effects.append(Anchor())

    def has(self, obj, name) -> bool | None:
        if name[0] != "str":
            return None
        if obj == THIS:
            return name[1] in self.head.methods or name[1] in self.state or name[1] in DISPLAY
        if obj[0] == "path":
            return self.host.has(obj[1], name[1])
        return None

    # ------------------------------------------------------------ calls

    def invoke(self, receiver, name: str, args: list, depth: int):
        mine = receiver == THIS or (receiver[0] == "find" and receiver[1] == name)
        if mine and name in self.head.methods:
            return self.call(self.head.methods[name], tuple(args), depth + 1)
        if name == "addAnimationListener":
            if len(args) >= 2 and args[0][0] == "str" and args[1][0] == "method":
                block = len(args) > 2 and self.truth(args[2]) is True
                self.effects.append(Listen(args[0][1], args[1][1], block))
            else:
                self.effects.append(Unread())
            return NULL
        if name in ("gotoAndPlay", "gotoAndStop") and len(args) == 1 and args[0][0] in ("str", "int"):
            target = args[0][1] if args[0][0] == "str" else int(args[0][1]) - 1
            if mine:
                self.effects.append(Goto(target, name == "gotoAndPlay"))
            elif receiver[0] == "path" and locate(receiver[1]) == SKELETON and args[0][0] == "str":
                self.effects.append(SkeletonPlay(args[0][1]))
            return NULL
        if name in ("stop", "play") and mine and not args:
            self.effects.append(StopClip() if name == "stop" else PlayClip())
            return NULL
        if name == "addEventListener" and mine and len(args) >= 2 and args[1][0] == "method":
            event = args[0]
            event = event[1] if event[0] == "str" else event[1][-1] if event[0] == "path" else None
            if event:
                self.effects.append(OnEvent(EVENTS.get(event, event), args[1][1]))
            return NULL
        if name in CASTS and len(args) == 1:
            return args[0]
        if name == "getChildByName" and len(args) == 1 and args[0][0] == "str":
            if mine:
                return ("path", (args[0][1],))
            if receiver[0] == "path":
                return ("path", receiver[1] + (args[0][1],))
        if name == "getChildAt" and receiver[0] == "path":
            return ("path", receiver[1] + ("getChildAt",))
        if name == "contains" and receiver[0] == "path" and len(args) == 1:
            found = self.host.contains(receiver[1], args[0])
            return OTHER if found is None else ("bool", found)
        if name == "clone" and receiver[0] == "path" and receiver[1][-1:] == ("matrix",):
            return ["matrix", locate(receiver[1][:-2]), False]           # mutable: invert() changes it in place
        if name == "invert" and isinstance(receiver, list) and receiver[0] == "matrix":
            receiver[2] = not receiver[2]
            return NULL
        if name == "push" and receiver[0] == "array":
            receiver[1].extend(args)
            return ("int", len(receiver[1]))
        return OTHER

    def call(self, method: int, args: tuple = (), depth: int = 0):
        if depth > MAX_CALL_DEPTH:
            raise _Stop("stopped on calls nested too deep")
        instrs, index = self.head.code(method)
        info = self.head.abc.method_info[method] if method < len(self.head.abc.method_info) else {}
        params, optional = len(info.get("params", ())), info.get("optional", [])
        regs = {0: THIS}
        for k in range(1, max(params, len(args)) + 1):
            j = k - 1 - (params - len(optional))
            regs[k] = args[k - 1] if k <= len(args) else (
                _value(self.head.abc.constant(*optional[j])) if 0 <= j < len(optional) else NULL)
        stack, pc = [], 0

        def pop():
            return stack.pop() if stack else OTHER

        def target(arg: str) -> int:
            return index.get(int(arg[2:]), len(instrs))

        while 0 <= pc < len(instrs):
            self.steps += 1
            if self.steps > MAX_STEPS:
                raise _Stop("stopped after running too long")
            i = instrs[pc]
            op, a = i.op, i.args
            pc += 1
            if op in NEUTRAL:
                continue
            if op == "getlocal0":
                stack.append(THIS)
            elif op in ("getlocal1", "getlocal2", "getlocal3", "getlocal"):
                stack.append(regs.get(int(a[0]) if op == "getlocal" else int(op[-1]), NULL))
            elif op in ("setlocal0", "setlocal1", "setlocal2", "setlocal3", "setlocal"):
                regs[int(a[0]) if op == "setlocal" else int(op[-1])] = pop()
            elif op == "kill":
                regs[int(a[0])] = NULL
            elif op in ("inclocal", "inclocal_i", "declocal", "declocal_i"):
                v = regs.get(int(a[0]), NULL)
                regs[int(a[0])] = ("int", v[1] + (1 if op.startswith("inc") else -1)) if v[0] == "int" else OTHER
            elif op in ("pushscope", "pushwith", "pop"):
                pop()
            elif op == "getscopeobject":
                stack.append(THIS if int(a[0]) == 0 else OTHER)
            elif op in ("getglobalscope", "getouterscope", "newactivation", "newcatch", "newfunction",
                        "getglobalslot", "pushnamespace"):
                stack.append(OTHER)
            elif op in ("findpropstrict", "findproperty", "findpropglobal", "findpropglobalstrict", "finddef"):
                stack.append(("find", _short(a[0])))
            elif op == "getlex":
                stack.append(self.lex(_short(a[0]), a[0]))
            elif op == "getproperty":
                if a[0].startswith("["):
                    key, obj = pop(), pop()
                    items = obj[1] if obj[0] == "array" else None
                    stack.append(items[key[1]] if items is not None and key[0] == "int" and 0 <= key[1] < len(items)
                                 else OTHER)
                else:
                    stack.append(self.get(pop(), _short(a[0])))
            elif op in ("setproperty", "initproperty"):
                value = pop()
                if a[0].startswith("["):
                    key, obj = pop(), pop()
                    if obj[0] == "array" and key[0] == "int" and 0 <= key[1] < len(obj[1]):
                        obj[1][key[1]] = value
                else:
                    self.set(pop(), _short(a[0]), value)
            elif op == "deleteproperty":
                if a[0].startswith("["):
                    pop()
                pop()
                stack.append(("bool", True))
            elif op in CALLS:
                args_ = [pop() for _ in range(int(a[1]))][::-1]
                if a[0].startswith("["):
                    pop()
                result = self.invoke(pop(), _short(a[0]), args_, depth)
                if op != "callpropvoid":
                    stack.append(result)
            elif op in ("callsuper", "callsupervoid", "constructprop"):
                [pop() for _ in range(int(a[1]) + 1)]
                if op != "callsupervoid":
                    stack.append(OTHER)
            elif op in ("call", "construct", "constructsuper"):
                [pop() for _ in range(int(a[0]) + (2 if op == "call" else 1))]
                if op != "constructsuper":
                    stack.append(OTHER)
            elif op == "newarray":
                stack.append(("array", [pop() for _ in range(int(a[0]))][::-1]))
            elif op == "newobject":
                [pop() for _ in range(2 * int(a[0]))]
                stack.append(OTHER)
            elif op == "newclass":
                pop()
                stack.append(OTHER)
            elif op == "pushstring":
                stack.append(("str", ast.literal_eval(a[0])))
            elif op in ("pushbyte", "pushshort", "pushint", "pushuint"):
                stack.append(("int", _int(op, a[0])))
            elif op == "pushdouble":
                stack.append(("int", float(a[0])))
            elif op == "pushnan":
                stack.append(("int", math.nan))
            elif op in ("pushtrue", "pushfalse"):
                stack.append(("bool", op == "pushtrue"))
            elif op in ("pushnull", "pushundefined"):
                stack.append(NULL)
            elif op == "dup":
                v = pop()
                stack += [v, v]
            elif op == "swap":
                x, y = pop(), pop()
                stack += [x, y]
            elif op == "not":
                t = self.truth(pop())
                stack.append(OTHER if t is None else ("bool", not t))
            elif op in ("convert_b", "coerce_b"):
                v = pop()
                t = self.truth(v)
                stack.append(v if t is None else ("bool", t))
            elif op in ("equals", "strictequals"):
                y, x = pop(), pop()
                r = self.equal(x, y)
                stack.append(OTHER if r is None else ("bool", r))
            elif op in ("lessthan", "lessequals", "greaterthan", "greaterequals"):
                y, x = pop(), pop()
                r = self.order(op, x, y)
                stack.append(OTHER if r is None else ("bool", r))
            elif op in ("add", "add_i", "subtract", "subtract_i", "multiply", "multiply_i", "divide", "modulo"):
                y, x = self.resolve(pop()), self.resolve(pop())
                if x[0] == y[0] == "int":
                    stack.append(("int", {"add": x[1] + y[1], "subtract": x[1] - y[1], "multiply": x[1] * y[1],
                                          "divide": x[1] / y[1] if y[1] else math.nan,
                                          "modulo": x[1] % y[1] if y[1] else math.nan}[op.replace("_i", "")]))
                elif op == "add" and "str" in (x[0], y[0]) and x[0] in PRIMITIVES and y[0] in PRIMITIVES:
                    stack.append(("str", "%s%s" % (x[1] if x[0] != "null" else "null",
                                                   y[1] if y[0] != "null" else "null")))
                else:
                    stack.append(OTHER)
            elif op in ("increment", "increment_i", "decrement", "decrement_i", "negate", "negate_i"):
                v = self.resolve(pop())
                if v[0] == "int":
                    stack.append(("int", -v[1] if op.startswith("negate") else v[1] + (1 if op.startswith("inc") else -1)))
                else:
                    stack.append(OTHER)
            elif op == "astypelate":
                pop()
            elif op in ("typeof", "istype"):
                pop()
                stack.append(OTHER)
            elif op in ("istypelate", "instanceof"):
                pop(), pop()
                stack.append(OTHER)
            elif op == "in":
                obj, name = pop(), pop()
                r = self.has(obj, name)
                stack.append(OTHER if r is None else ("bool", r))
            elif op == "hasnext2":
                obj_reg, index_reg = int(a[0]), int(a[1])
                obj, at = regs.get(obj_reg, NULL), regs.get(index_reg, NULL)
                if obj[0] == "array" and at[0] == "int":
                    more = at[1] < len(obj[1])
                    regs[index_reg] = ("int", at[1] + 1) if more else at
                    if not more:
                        regs[obj_reg] = NULL
                    stack.append(("bool", more))
                elif obj == NULL:
                    stack.append(("bool", False))
                else:
                    raise _Stop("stopped on a loop over something it cannot read (offset %d)" % i.offset)
            elif op in ("nextvalue", "nextname"):
                at, obj = pop(), pop()
                if obj[0] == "array" and at[0] == "int" and 1 <= at[1] <= len(obj[1]):
                    stack.append(obj[1][at[1] - 1] if op == "nextvalue" else ("int", at[1] - 1))
                else:
                    stack.append(OTHER)
            elif op in ("iftrue", "iffalse"):
                t = self.truth(pop())
                if t is None:
                    raise _Stop("stopped on a condition it cannot evaluate (offset %d)" % i.offset)
                if t == (op == "iftrue"):
                    pc = target(a[0])
            elif op in ("ifeq", "ifne", "ifstricteq", "ifstrictne"):
                y, x = pop(), pop()
                r = self.equal(x, y)
                if r is None:
                    raise _Stop("stopped on a condition it cannot evaluate (offset %d)" % i.offset)
                if r == (op in ("ifeq", "ifstricteq")):
                    pc = target(a[0])
            elif op in ("iflt", "ifle", "ifgt", "ifge", "ifnlt", "ifnle", "ifngt", "ifnge"):
                y, x = pop(), pop()
                r = self.order(op, x, y)
                if r is None:
                    raise _Stop("stopped on a condition it cannot evaluate (offset %d)" % i.offset)
                if r:
                    pc = target(a[0])
            elif op == "jump":
                pc = target(a[0])
            elif op == "returnvoid":
                return NULL
            elif op == "returnvalue":
                return pop()
            elif op == "getslot":
                pop()
                stack.append(OTHER)
            elif op in ("setslot",):
                pop(), pop()
            elif op in ("setglobalslot", "dxnslate"):
                pop()
            elif op == "dxns":
                continue
            else:
                raise _Stop("stopped on '%s' (offset %d)" % (op, i.offset))
        return NULL


def run_method(head: HeadClass, method: int, state: dict, host: Host, args: tuple = ()) -> tuple[list, str | None]:
    """Run one method of the head's class: the effects it has, in order, and a note when it stopped on code this
    interpreter does not follow. `state` (the clip's fields) is changed in place."""
    machine = _Machine(head, state, host)
    try:
        machine.call(method, args)
    except _Stop as e:
        return machine.effects, str(e)
    return machine.effects, None


@dataclass(frozen=True)
class ArmorListener:
    game_label: str
    handler: str
    block: bool


class HeadScripts:
    """One running instance of an animated head: its fields, the events it listens to and the game labels it has
    registered, run when the client would run them."""

    def __init__(self, head: HeadClass, host: Host, state: dict | None = None):
        self.head, self.host = head, host
        self.state = copy.deepcopy(head.fields if state is None else state)
        self.events: dict[str, list[str]] = {}
        self.listeners: list[ArmorListener] = []
        self.notes: list[str] = []
        self.unread = 0

    def run(self, method: int, args: tuple, where: str) -> list:
        effects, note = run_method(self.head, method, self.state, self.host, args)
        if note and "%s %s" % (where, note) not in self.notes:
            self.notes.append("%s %s" % (where, note))
        for e in effects:
            if isinstance(e, OnEvent):
                handlers = self.events.setdefault(e.event, [])
                if e.handler not in handlers and e.handler in self.head.methods:
                    handlers.append(e.handler)
            elif isinstance(e, Listen):
                listener = ArmorListener(e.game_label, e.handler, e.block)
                if listener not in self.listeners:
                    self.listeners.append(listener)
            elif isinstance(e, Unread):
                self.unread += 1
        return effects

    def construct(self) -> list:
        return self.run(self.head.iinit, (), "The constructor")

    def dispatch(self, event: str) -> list:
        out = []
        for handler in list(self.events.get(event, [])):
            out += self.run(self.head.methods[handler], (OTHER,), "The %s handler %s" % (event, handler))
        return out

    def frame(self, frame: int) -> list:
        method = self.head.frame_methods.get(frame)
        return [] if method is None else self.run(method, (), "Frame %d script" % (frame + 1))

    def call(self, handler: str) -> list:
        method = self.head.methods.get(handler)
        return [] if method is None else self.run(method, (), "The handler %s" % handler)


@dataclass(eq=False)
class AnimatedArmor:
    class_name: str
    char_id: int
    labels: dict[str, int]                 # the armor's own animations: label -> 0-based frame
    head: HeadClass
    listeners: list[ArmorListener]
    notes: list[str] = field(default_factory=list)
    start: dict = field(default_factory=dict, repr=False)      # the fields once constructed

    @property
    def frame_methods(self) -> dict[int, int]:
        return self.head.frame_methods

    @property
    def handlers(self) -> dict[str, int]:
        return self.head.methods

    def motions(self) -> list[str]:
        """The armor's own animations, in timeline order."""
        return sorted(self.labels, key=self.labels.get)

    def handler_label(self, handler: str) -> str | None:
        """The armor label a handler plays from the clip's first state."""
        scripts = HeadScripts(self.head, Host({"bitWalk": True}), self.start)
        return next((e.target for e in scripts.call(handler) if isinstance(e, Goto) and isinstance(e.target, str)),
                    None)

    def table(self) -> list[tuple[str, str | None, bool]]:
        """(game label, the armor animation it plays, whether it blocks the body), first listener per game label."""
        seen, out = set(), []
        for listener in self.listeners:
            if listener.game_label not in seen:
                seen.add(listener.game_label)
                out.append((listener.game_label, self.handler_label(listener.handler),
                            listener.block and listener.game_label != "Idle"))
        return out


def _frame_methods(abc: ABC, inst: dict, methods: dict[str, int]) -> dict[int, int]:
    ctor = disassemble(abc, abc.bodies.get(inst["iinit"], b""))
    out = {}
    for k, i in enumerate(ctor):
        if i.op not in ("pushbyte", "pushshort", "pushint"):
            continue
        for j in ctor[k + 1:k + 4]:
            if j.op in ("getlex", "getproperty") and j.args and _short(j.args[0]) in methods:
                out[_int(i.op, i.args[0])] = methods[_short(j.args[0])]
                break
    return out


def head_class(abc: ABC, inst: dict, name: str) -> HeadClass:
    methods = {_short(abc.mname(t["name"])): t["method"] for t in inst["traits"] if "method" in t}
    fields = {}
    for t in inst["traits"]:
        if "slot" not in t:
            continue
        default = t.get("default")
        fields[_short(abc.mname(t["name"]))] = (_value(abc.constant(*default)) if default
                                               else FIELD_DEFAULTS.get(_short(abc.mname(t["type"])), NULL))
    return HeadClass(abc, name, inst["iinit"], methods, fields, _frame_methods(abc, inst, methods))


def read_animated_armor(movie: MovieData, gender: str | None = None) -> AnimatedArmor | None:
    """The animated Head of an armor (of that gender, else the first that has one), or None for any other file: a Head
    whose class calls addAnimationListener anywhere. Its listeners are read by running the head the way the client
    does: constructed, added to the stage, then its frame scripts."""
    from autoswf.items.structure import find_armor_link
    try:
        link, genders = find_armor_link(movie)
    except ValueError:
        return None
    for g in (genders if gender is None else [gender] if gender in genders else []):
        name = "%s%sHead" % (link, g)
        cid = movie.classes.get(name)
        sprite = movie.character(cid) if cid is not None else None
        if not isinstance(sprite, SpriteDef):
            continue
        for abc in movie.abcs:
            inst = next((x for x in abc.instances if abc.mname(x["name"]) == name), None)
            if inst is None:
                continue
            head = head_class(abc, inst, name)
            if not head.calls("addAnimationListener"):
                continue
            scripts = HeadScripts(head, Host({"bitWalk": True}))
            scripts.construct()
            start = copy.deepcopy(scripts.state)
            scripts.dispatch("addedToStage")
            for frame in sorted(head.frame_methods):
                scripts.frame(frame)
            if not scripts.listeners:
                scripts.dispatch("enterFrame")
            notes = list(scripts.notes)
            if not scripts.listeners or scripts.unread:
                notes.insert(0, NOT_READ if not scripts.listeners else
                             "%d of its animation listeners cannot be read from its scripts" % scripts.unread)
            return AnimatedArmor(name, cid, dict(sprite.labels), head, list(scripts.listeners), notes, start)
    return None
