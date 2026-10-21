"""Change which AQW color a clip takes (Plan 7, spec §8.1 "Color ▾"): rewrite the location and shade its frame-1
`MovieClip(stage.getChildAt(0)).mcSetColor(this, Location, Shade)` call pushes, in any of AQW's official forms. Only
that method body (and, when a new word is needed, the string pool) changes."""
from autoswf.abc.code import u30
from autoswf.abc.disasm import disassemble
from autoswf.abc.reader import ABC

PUSHSTRING = 0x2C


def _u30_at(data: bytes, pos: int) -> tuple[int, int]:
    value = shift = 0
    for _ in range(5):
        b = data[pos]
        pos += 1
        value |= (b & 0x7F) << shift
        if not b & 0x80:
            break
        shift += 7
    return value, pos


def _with_strings(abc: bytes, words: list[str]) -> bytes:
    """The ABC with `words` added at the end of its string pool when missing (no index moves)."""
    pos = 4
    for width in ("int", "uint", "double"):
        count, pos = _u30_at(abc, pos)
        for _ in range(max(0, count - 1)):
            if width == "double":
                pos += 8
            else:
                _, pos = _u30_at(abc, pos)
    start = pos
    count, pos = _u30_at(abc, pos)
    strings = []
    for _ in range(max(0, count - 1)):
        length, pos = _u30_at(abc, pos)
        strings.append(abc[pos:pos + length].decode("utf-8", "surrogateescape"))
        pos += length
    missing = [w for w in dict.fromkeys(words) if w not in strings]
    if not missing:
        return abc
    pool = bytearray(u30(max(count, 1) + len(missing)))
    for s in strings + missing:
        data = s.encode("utf-8", "surrogateescape")
        pool += u30(len(data)) + data
    return abc[:start] + bytes(pool) + abc[pos:]


def _frame_one(abc: ABC, class_name: str) -> int | None:
    from autoswf.items.animated import _frame_methods
    inst = next((x for x in abc.instances if abc.mname(x["name"]) == class_name), None)
    if inst is None:
        return None
    methods = {abc.mname(t["name"]).rpartition(".")[2]: t["method"] for t in inst["traits"] if "method" in t}
    return _frame_methods(abc, inst, methods).get(0)


def has_class(abc: bytes, class_name: str) -> bool:
    a = ABC(abc)
    return any(a.mname(x["name"]) == class_name for x in a.instances)


def rebind_setcolor(abc: bytes, class_name: str, location: str, shade: str) -> bytes:
    abc = _with_strings(abc, [location, shade])
    a = ABC(abc)
    method = _frame_one(a, class_name)
    code = a.bodies.get(method, b"") if method is not None else b""
    ins = disassemble(a, code)
    k = next((i for i, x in enumerate(ins) if x.op == "callpropvoid" and x.args and x.args[0].endswith("mcSetColor")
              and i >= 2 and ins[i - 1].op == "pushstring" and ins[i - 2].op == "pushstring"), None)
    if k is None:
        raise ValueError("%s has no AQW color script" % class_name)
    first, call = ins[k - 2].offset, ins[k].offset
    new_code = (code[:first] + bytes([PUSHSTRING]) + u30(a.strings.index(location, 1))
                + bytes([PUSHSTRING]) + u30(a.strings.index(shade, 1)) + code[call:])
    delta = len(new_code) - len(code)
    start, end = a.body_pos[method]
    length, pos = _u30_at(abc, start)
    pos += length
    count, pos = _u30_at(abc, pos)
    table = bytearray(u30(count))
    for _ in range(count):
        values = []
        for _ in range(5):
            v, pos = _u30_at(abc, pos)
            values.append(v)
        for i in range(3):                       # from, to, target: offsets after the call move with it
            if values[i] >= call:
                values[i] += delta
        table += b"".join(u30(v) for v in values)
    return abc[:start] + u30(len(new_code)) + new_code + bytes(table) + abc[end:]
