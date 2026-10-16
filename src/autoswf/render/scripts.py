"""Static analysis of AS3 frame scripts: the few effects AQW content relies on (stop, play, goto, mcSetColor,
calls to the clip's own methods). A small stack machine follows the disassembly; anything else ends the analysis."""
import ast
from dataclasses import dataclass

from autoswf.abc.disasm import disassemble
from autoswf.abc.reader import ABC


@dataclass(frozen=True)
class Stop:
    conditional: bool = False


@dataclass(frozen=True)
class Play:
    conditional: bool = False


@dataclass(frozen=True)
class GotoAndPlay:
    target: str | int           # label, or 0-based frame
    conditional: bool = False


@dataclass(frozen=True)
class GotoAndStop:
    target: str | int
    conditional: bool = False


@dataclass(frozen=True)
class SetColor:
    location: str
    shade: str
    conditional: bool = False


@dataclass(frozen=True)
class CallSelf:
    method: str
    conditional: bool = False


FrameAction = Stop | Play | GotoAndPlay | GotoAndStop | SetColor | CallSelf

THIS, OTHER = ("this",), ("other",)
COMPARE_BRANCHES = {"ifeq", "ifne", "iflt", "ifle", "ifgt", "ifge", "ifstricteq", "ifstrictne",
                    "ifnlt", "ifnle", "ifngt", "ifnge"}
BRANCHES = COMPARE_BRANCHES | {"iftrue", "iffalse", "jump", "lookupswitch"}
NEUTRAL = {"popscope", "nop", "label", "coerce", "coerce_a", "coerce_s", "coerce_b", "coerce_i", "coerce_d",
           "coerce_u", "coerce_o", "convert_s", "convert_i", "convert_u", "convert_d", "convert_b", "convert_o"}
CONSTANTS = {"pushtrue", "pushfalse", "pushnull", "pushundefined", "pushnan", "pushdouble", "pushuint"}


def _int(op: str, text: str) -> int:
    v = int(text)
    if op == "pushbyte" and v > 127:
        return v - 256
    return v - (1 << 32) if v >= 1 << 31 else v


def _action(name: str, receiver, args: list, conditional: bool) -> FrameAction | None:
    if name == "mcSetColor" and len(args) == 3 and args[0] == THIS and all(a[0] == "str" for a in args[1:]):
        return SetColor(args[1][1], args[2][1], conditional)
    if receiver != THIS:
        return None
    if name == "stop" and not args:
        return Stop(conditional)
    if name == "play" and not args:
        return Play(conditional)
    if name in ("gotoAndPlay", "gotoAndStop") and len(args) == 1 and args[0][0] in ("str", "int"):
        kind, value = args[0]
        target = value if kind == "str" else value - 1
        return (GotoAndPlay if name == "gotoAndPlay" else GotoAndStop)(target, conditional)
    if not args:
        return CallSelf(name, conditional)
    return None


def analyze_frame_script(ops: list[tuple[str, tuple[str, ...]]]) -> list[FrameAction]:
    stack, actions, conditional = [], [], False

    def pop():
        return stack.pop() if stack else OTHER

    for op, args in ops:
        if op in ("getlocal0", "findpropstrict", "findproperty"):
            stack.append(THIS)
        elif op == "getlex" or op in CONSTANTS:
            stack.append(OTHER)
        elif op == "getproperty":
            pop(); stack.append(("prop", args[0]))
        elif op == "pushstring":
            stack.append(("str", ast.literal_eval(args[0])))
        elif op in ("pushbyte", "pushshort", "pushint"):
            stack.append(("int", _int(op, args[0])))
        elif op in ("pushscope", "pop"):
            pop()
        elif op in ("setproperty", "initproperty"):
            pop(); pop()
        elif op in NEUTRAL:
            continue
        elif op == "dup":
            v = pop(); stack += [v, v]
        elif op == "swap":
            a, b = pop(), pop(); stack += [a, b]
        elif op in ("callproperty", "callproplex"):
            for _ in range(int(args[1]) + 1):
                pop()
            stack.append(OTHER)
        elif op == "callpropvoid":
            call_args = [pop() for _ in range(int(args[1]))][::-1]
            action = _action(args[0], pop(), call_args, conditional)
            if action is not None:
                actions.append(action)
        elif op in BRANCHES:
            if op in COMPARE_BRANCHES:
                pop(); pop()
            elif op != "jump":
                pop()
            conditional = True
        else:                               # returnvoid, returnvalue, or code this analysis does not follow
            break
    return actions


def class_frame_actions(abcs: list[ABC], class_name: str) -> dict[int, list[FrameAction]]:
    """0-based frame -> actions of the class's frame scripts (mapped through its addFrameScript calls)."""
    for abc in abcs:
        for inst in abc.instances:
            if abc.mname(inst["name"]) != class_name:
                continue
            methods = {}
            for t in inst["traits"]:
                if "method" in t:
                    full = abc.mname(t["name"])
                    methods.setdefault(full.rpartition(".")[2], t["method"])    # plain-name references (client code)
                    methods[full] = t["method"]
            ctor = [(i.op, i.args) for i in disassemble(abc, abc.bodies.get(inst["iinit"], b""))]
            frames = {}
            for k, (op, args) in enumerate(ctor):
                if op not in ("pushbyte", "pushshort", "pushint"):
                    continue
                for op2, args2 in ctor[k + 1:k + 3]:
                    if op2 in ("getlex", "getproperty") and args2 and args2[0] in methods:
                        frames[_int(op, args[0])] = methods[args2[0]]
                        break
            return {n: analyze_frame_script([(i.op, i.args) for i in disassemble(abc, abc.bodies.get(m, b""))])
                    for n, m in sorted(frames.items())}
    return {}
