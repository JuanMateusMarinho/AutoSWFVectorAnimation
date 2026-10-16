"""Structured AVM2 disassembler (debug opcodes dropped)."""
from typing import NamedTuple


class Instr(NamedTuple):
    offset: int
    op: str
    args: tuple[str, ...]


U30, S24, U8, MN, STR, INT, UINT, DBL, CLS, MTH, LSW, DBG, U30U30, MNU30 = range(14)
OPS = {
    0x01: ("bkpt", []), 0x02: ("nop", []), 0x03: ("throw", []), 0x04: ("getsuper", [MN]), 0x05: ("setsuper", [MN]),
    0x06: ("dxns", [STR]), 0x07: ("dxnslate", []), 0x08: ("kill", [U30]), 0x09: ("label", []),
    0x0C: ("ifnlt", [S24]), 0x0D: ("ifnle", [S24]), 0x0E: ("ifngt", [S24]), 0x0F: ("ifnge", [S24]),
    0x10: ("jump", [S24]), 0x11: ("iftrue", [S24]), 0x12: ("iffalse", [S24]), 0x13: ("ifeq", [S24]),
    0x14: ("ifne", [S24]), 0x15: ("iflt", [S24]), 0x16: ("ifle", [S24]), 0x17: ("ifgt", [S24]),
    0x18: ("ifge", [S24]), 0x19: ("ifstricteq", [S24]), 0x1A: ("ifstrictne", [S24]), 0x1B: ("lookupswitch", [LSW]),
    0x1C: ("pushwith", []), 0x1D: ("popscope", []), 0x1E: ("nextname", []), 0x1F: ("hasnext", []),
    0x20: ("pushnull", []), 0x21: ("pushundefined", []), 0x23: ("nextvalue", []), 0x24: ("pushbyte", [U8]),
    0x25: ("pushshort", [U30]), 0x26: ("pushtrue", []), 0x27: ("pushfalse", []), 0x28: ("pushnan", []),
    0x29: ("pop", []), 0x2A: ("dup", []), 0x2B: ("swap", []), 0x2C: ("pushstring", [STR]), 0x2D: ("pushint", [INT]),
    0x2E: ("pushuint", [UINT]), 0x2F: ("pushdouble", [DBL]), 0x30: ("pushscope", []), 0x31: ("pushnamespace", [U30]),
    0x32: ("hasnext2", [U30, U30]), 0x35: ("li8", []), 0x36: ("li16", []), 0x37: ("li32", []), 0x38: ("lf32", []),
    0x39: ("lf64", []), 0x3A: ("si8", []), 0x3B: ("si16", []), 0x3C: ("si32", []), 0x3D: ("sf32", []), 0x3E: ("sf64", []),
    0x40: ("newfunction", [MTH]), 0x41: ("call", [U30]), 0x42: ("construct", [U30]), 0x43: ("callmethod", [U30, U30]),
    0x44: ("callstatic", [MTH, U30]), 0x45: ("callsuper", [MN, U30]), 0x46: ("callproperty", [MN, U30]),
    0x47: ("returnvoid", []), 0x48: ("returnvalue", []), 0x49: ("constructsuper", [U30]),
    0x4A: ("constructprop", [MN, U30]), 0x4C: ("callproplex", [MN, U30]), 0x4E: ("callsupervoid", [MN, U30]),
    0x4F: ("callpropvoid", [MN, U30]), 0x50: ("sxi1", []), 0x51: ("sxi8", []), 0x52: ("sxi16", []),
    0x53: ("applytype", [U30]), 0x55: ("newobject", [U30]), 0x56: ("newarray", [U30]), 0x57: ("newactivation", []),
    0x58: ("newclass", [CLS]), 0x59: ("getdescendants", [MN]), 0x5A: ("newcatch", [U30]), 0x5B: ("findpropglobalstrict", [MN]),
    0x5C: ("findpropglobal", [MN]), 0x5D: ("findpropstrict", [MN]), 0x5E: ("findproperty", [MN]), 0x5F: ("finddef", [MN]),
    0x60: ("getlex", [MN]), 0x61: ("setproperty", [MN]), 0x62: ("getlocal", [U30]), 0x63: ("setlocal", [U30]),
    0x64: ("getglobalscope", []), 0x65: ("getscopeobject", [U8]), 0x66: ("getproperty", [MN]), 0x67: ("getouterscope", [U30]),
    0x68: ("initproperty", [MN]), 0x6A: ("deleteproperty", [MN]), 0x6C: ("getslot", [U30]), 0x6D: ("setslot", [U30]),
    0x6E: ("getglobalslot", [U30]), 0x6F: ("setglobalslot", [U30]), 0x70: ("convert_s", []), 0x71: ("esc_xelem", []),
    0x72: ("esc_xattr", []), 0x73: ("convert_i", []), 0x74: ("convert_u", []), 0x75: ("convert_d", []), 0x76: ("convert_b", []),
    0x77: ("convert_o", []), 0x78: ("checkfilter", []), 0x80: ("coerce", [MN]), 0x81: ("coerce_b", []), 0x82: ("coerce_a", []),
    0x83: ("coerce_i", []), 0x84: ("coerce_d", []), 0x85: ("coerce_s", []), 0x86: ("astype", [MN]), 0x87: ("astypelate", []),
    0x88: ("coerce_u", []), 0x89: ("coerce_o", []), 0x90: ("negate", []), 0x91: ("increment", []), 0x92: ("inclocal", [U30]),
    0x93: ("decrement", []), 0x94: ("declocal", [U30]), 0x95: ("typeof", []), 0x96: ("not", []), 0x97: ("bitnot", []),
    0xA0: ("add", []), 0xA1: ("subtract", []), 0xA2: ("multiply", []), 0xA3: ("divide", []), 0xA4: ("modulo", []),
    0xA5: ("lshift", []), 0xA6: ("rshift", []), 0xA7: ("urshift", []), 0xA8: ("bitand", []), 0xA9: ("bitor", []),
    0xAA: ("bitxor", []), 0xAB: ("equals", []), 0xAC: ("strictequals", []), 0xAD: ("lessthan", []), 0xAE: ("lessequals", []),
    0xAF: ("greaterthan", []), 0xB0: ("greaterequals", []), 0xB1: ("instanceof", []), 0xB2: ("istype", [MN]),
    0xB3: ("istypelate", []), 0xB4: ("in", []), 0xC0: ("increment_i", []), 0xC1: ("decrement_i", []),
    0xC2: ("inclocal_i", [U30]), 0xC3: ("declocal_i", [U30]), 0xC4: ("negate_i", []), 0xC5: ("add_i", []),
    0xC6: ("subtract_i", []), 0xC7: ("multiply_i", []), 0xD0: ("getlocal0", []), 0xD1: ("getlocal1", []),
    0xD2: ("getlocal2", []), 0xD3: ("getlocal3", []), 0xD4: ("setlocal0", []), 0xD5: ("setlocal1", []),
    0xD6: ("setlocal2", []), 0xD7: ("setlocal3", []), 0xEF: ("debug", [DBG]), 0xF0: ("debugline", [U30]),
    0xF1: ("debugfile", [STR]), 0xF2: ("bkptline", [U30]), 0xF3: ("timestamp", []),
}


def rd_u30(code, p):
    res = 0; shift = 0
    for _ in range(5):
        b = code[p]; p += 1
        res |= (b & 0x7F) << shift
        if not b & 0x80:
            break
        shift += 7
    return res, p


def rd_s24(code, p):
    v = code[p] | (code[p + 1] << 8) | (code[p + 2] << 16)
    if v & 0x800000:
        v -= 1 << 24
    return v, p + 3


def disassemble(abc, code: bytes) -> list[Instr]:
    out = []; p = 0
    while p < len(code):
        start = p; op = code[p]; p += 1
        name, kinds = OPS.get(op, ("op_%02x" % op, []))
        args = []
        for a in kinds:
            if a == S24:
                v, p = rd_s24(code, p); args.append("->%d" % (p + v))
            elif a == U8:
                args.append(str(code[p])); p += 1
            elif a == LSW:
                d, p = rd_s24(code, p); n, p = rd_u30(code, p)
                for _ in range(n + 1):
                    _, p = rd_s24(code, p)
                args.append("[%d cases]" % (n + 1))
            elif a == DBG:
                p += 1; _, p = rd_u30(code, p); p += 1; _, p = rd_u30(code, p)
            else:
                v, p = rd_u30(code, p)
                if a == MN:
                    args.append(abc.mname(v))
                elif a == STR:
                    args.append(repr(abc.strings[v]) if v < len(abc.strings) else "?")
                elif a == INT:
                    args.append(str(abc.ints[v]))
                elif a == UINT:
                    args.append(str(abc.uints[v]))
                elif a == DBL:
                    args.append(str(abc.doubles[v]))
                else:
                    args.append(str(v))
        if name in ("debugline", "debug", "debugfile"):
            continue
        out.append(Instr(start, name, tuple(args)))
    return out


def method_owners(abc) -> dict[int, str]:
    """Map method index -> 'Class.member' label (<init>, <cinit>, trait name)."""
    own = {}
    for ci, inst in enumerate(abc.instances):
        cn = abc.mname(inst["name"])
        own[inst["iinit"]] = cn + ".<init>"
        own[abc.classes[ci]["cinit"]] = cn + ".<cinit>"
        for t in inst["traits"]:
            if "method" in t:
                own[t["method"]] = cn + "." + abc.mname(t["name"])
        for t in abc.classes[ci]["traits"]:
            if "method" in t:
                own[t["method"]] = cn + ".static " + abc.mname(t["name"])
    return own
