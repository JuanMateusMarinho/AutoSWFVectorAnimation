"""Animated armors (spec §15, pattern of AzraelGuardianArmor.swf): every part class empty except <Link><G>Head, a whole
animated character whose frame-2 script registers `addAnimationListener(gameLabel, this.onX[, block])` on the avatar;
each handler plays one of the armor's own labels. A small interpreter runs these scripts the way the client would
(booleans kept on the clip, `if`, goto/stop/play, the skeleton's gotoAndPlay, the world's bitWalk)."""
import ast
from dataclasses import dataclass, field

from autoswf.abc.disasm import disassemble
from autoswf.abc.reader import ABC
from autoswf.swf.decode import MovieData, SpriteDef

THIS, OTHER = ("this",), ("other",)
MAX_STEPS = 20000
NEUTRAL = {"nop", "label", "coerce", "coerce_a", "coerce_s", "coerce_b", "convert_b", "convert_s", "convert_i",
           "convert_d", "convert_u", "convert_o", "coerce_i", "coerce_d", "coerce_u", "coerce_o", "popscope", "kill",
           "debug", "debugline", "debugfile"}


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


def _int(op: str, text: str) -> int:
    v = int(text)
    return v - 256 if op == "pushbyte" and v > 127 else v


def run_method(abc: ABC, method: int, state: dict, world: dict, methods: frozenset = frozenset()) -> tuple[list, str | None]:
    """Run one method of the clip's class: the effects it has, in order, and a note when it stopped on an instruction
    this interpreter does not follow. `state` (the clip's booleans) is changed in place; `methods` are the class's
    method names (getproperty of one of them on `this` is a function reference)."""
    instrs = disassemble(abc, abc.bodies.get(method, b""))
    index = {i.offset: k for k, i in enumerate(instrs)}
    stack, effects, pc, steps = [], [], 0, 0

    def pop():
        return stack.pop() if stack else OTHER

    def truth(value) -> bool:
        if value[0] == "bool":
            return value[1]
        if value[0] == "path" and value[1] and value[1][-1] in world:
            return bool(world[value[1][-1]])
        if value[0] in ("int", "str"):
            return bool(value[1])
        raise LookupError

    while 0 <= pc < len(instrs) and steps < MAX_STEPS:
        steps += 1
        i = instrs[pc]
        op, args = i.op, i.args
        pc += 1
        if op == "getlocal0":
            stack.append(THIS)
        elif op in ("findpropstrict", "findproperty"):
            stack.append(("find", args[0]))
        elif op == "getlex":
            stack.append(("path", (args[0],)))
        elif op == "getproperty":
            obj, name = pop(), args[0]
            if obj == THIS:
                stack.append(("method", name) if name in methods else ("bool", bool(state.get(name, False))))
            elif obj[0] == "path":
                stack.append(("path", obj[1] + (name,)))
            else:
                stack.append(OTHER)
        elif op in ("callproperty", "callproplex"):
            call = [pop() for _ in range(int(args[1]))][::-1]
            receiver = pop()
            if args[0].endswith("MovieClip") and len(call) == 1:
                stack.append(call[0])                                     # a cast: MovieClip(x)
            elif args[0] == "getChildAt" and receiver[0] == "path":
                stack.append(("path", receiver[1] + ("getChildAt",)))
            else:
                stack.append(OTHER)
        elif op == "pushstring":
            stack.append(("str", ast.literal_eval(args[0])))
        elif op in ("pushbyte", "pushshort", "pushint"):
            stack.append(("int", _int(op, args[0])))
        elif op in ("pushtrue", "pushfalse"):
            stack.append(("bool", op == "pushtrue"))
        elif op in ("pushnull", "pushundefined"):
            stack.append(("bool", False))
        elif op in ("initproperty", "setproperty"):
            value, obj = pop(), pop()
            if obj == THIS and value[0] == "bool":
                state[args[0]] = value[1]
        elif op in ("iftrue", "iffalse"):
            try:
                taken = truth(pop()) == (op == "iftrue")
            except LookupError:
                return effects, "stopped on a condition it cannot evaluate (offset %d)" % i.offset
            if taken:
                pc = index.get(int(args[0][2:]), len(instrs))
        elif op == "jump":
            pc = index.get(int(args[0][2:]), len(instrs))
        elif op == "callpropvoid":
            call = [pop() for _ in range(int(args[1]))][::-1]
            receiver, name = pop(), args[0]
            on_self = receiver == THIS or (receiver[0] == "find" and receiver[1] == name)
            if name == "addAnimationListener" and len(call) >= 2 and call[0][0] == "str" and call[1][0] == "method":
                effects.append(Listen(call[0][1], call[1][1], len(call) > 2 and call[2] == ("bool", True)))
            elif name in ("gotoAndPlay", "gotoAndStop") and len(call) == 1 and call[0][0] in ("str", "int"):
                target = call[0][1] if call[0][0] == "str" else call[0][1] - 1
                if on_self:
                    effects.append(Goto(target, name == "gotoAndPlay"))
                elif receiver[0] == "path" and receiver[1] == ("parent", "parent") and call[0][0] == "str":
                    effects.append(SkeletonPlay(call[0][1]))
            elif name == "stop" and on_self and not call:
                effects.append(StopClip())
            elif name == "play" and on_self and not call:
                effects.append(PlayClip())
        elif op in ("returnvoid", "returnvalue"):
            break
        elif op in ("pushscope", "pop", "pushwith"):
            pop()
        elif op == "dup":
            v = pop()
            stack += [v, v]
        elif op == "swap":
            a, b = pop(), pop()
            stack += [a, b]
        elif op in ("newactivation", "newcatch", "getlocal", "getlocal1", "getlocal2", "getlocal3", "getscopeobject",
                    "getglobalscope"):
            stack.append(OTHER)
        elif op in ("setlocal", "setlocal1", "setlocal2", "setlocal3"):
            pop()
        elif op == "setslot":
            pop(); pop()
        elif op in NEUTRAL:
            continue
        else:
            return effects, "stopped on '%s' (offset %d)" % (op, i.offset)
    return effects, None


@dataclass(frozen=True)
class ArmorListener:
    game_label: str
    handler: str
    block: bool


@dataclass(eq=False)
class AnimatedArmor:
    class_name: str
    char_id: int
    labels: dict[str, int]                 # the armor's own animations: label -> 0-based frame
    frame_methods: dict[int, int]          # 0-based frame -> method index
    handlers: dict[str, int]               # method name -> method index
    listeners: list[ArmorListener]
    abc: ABC
    notes: list[str] = field(default_factory=list)

    def handler_label(self, handler: str) -> str | None:
        """The armor label a handler plays from the clip's first state."""
        method = self.handlers.get(handler)
        if method is None:
            return None
        effects, _ = run_method(self.abc, method, {}, {"bitWalk": True}, frozenset(self.handlers))
        return next((e.target for e in effects if isinstance(e, Goto) and isinstance(e.target, str)), None)

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
            if j.op in ("getlex", "getproperty") and j.args and j.args[0].rpartition(".")[2] in methods:
                out[_int(i.op, i.args[0])] = methods[j.args[0].rpartition(".")[2]]
                break
    return out


def read_animated_armor(movie: MovieData) -> AnimatedArmor | None:
    """The animated Head of an armor (the first gender that has one), or None for any other file."""
    from autoswf.items.structure import find_armor_link
    try:
        link, genders = find_armor_link(movie)
    except ValueError:
        return None
    for gender in genders:
        name = "%s%sHead" % (link, gender)
        cid = movie.classes.get(name)
        sprite = movie.character(cid) if cid is not None else None
        if not isinstance(sprite, SpriteDef):
            continue
        for abc in movie.abcs:
            inst = next((x for x in abc.instances if abc.mname(x["name"]) == name), None)
            if inst is None:
                continue
            methods = {abc.mname(t["name"]).rpartition(".")[2]: t["method"] for t in inst["traits"] if "method" in t}
            frames = _frame_methods(abc, inst, methods)
            listeners, notes = [], []
            for frame, method in sorted(frames.items()):
                effects, note = run_method(abc, method, {}, {"bitWalk": True}, frozenset(methods))
                listeners += [ArmorListener(e.game_label, e.handler, e.block) for e in effects if isinstance(e, Listen)]
                if note:
                    notes.append("Frame %d script %s" % (frame + 1, note))
            if listeners:
                return AnimatedArmor(name, cid, dict(sprite.labels), frames, methods, listeners, abc, notes)
    return None
