#!/usr/bin/env python3
"""SWF structure inspector for format research (throwaway, not product code).

Usage: python -I swfinspect.py FILE.swf [--tree] [--abc] [--strings] [--shapes] [--maxdepth N]
"""
import sys, struct, zlib, lzma, collections

TAG_NAMES = {
    0: "End", 1: "ShowFrame", 2: "DefineShape", 4: "PlaceObject", 5: "RemoveObject",
    6: "DefineBits", 7: "DefineButton", 8: "JPEGTables", 9: "SetBackgroundColor",
    10: "DefineFont", 11: "DefineText", 12: "DoAction", 13: "DefineFontInfo",
    14: "DefineSound", 15: "StartSound", 18: "SoundStreamHead", 19: "SoundStreamBlock",
    20: "DefineBitsLossless", 21: "DefineBitsJPEG2", 22: "DefineShape2", 24: "Protect",
    26: "PlaceObject2", 28: "RemoveObject2", 32: "DefineShape3", 33: "DefineText2",
    34: "DefineButton2", 35: "DefineBitsJPEG3", 36: "DefineBitsLossless2",
    37: "DefineEditText", 39: "DefineSprite", 41: "ProductInfo", 43: "FrameLabel",
    45: "SoundStreamHead2", 46: "DefineMorphShape", 48: "DefineFont2", 56: "ExportAssets",
    57: "ImportAssets", 58: "EnableDebugger", 59: "DoInitAction", 60: "DefineVideoStream",
    62: "DefineFontInfo2", 63: "DebugID", 64: "EnableDebugger2", 65: "ScriptLimits",
    66: "SetTabIndex", 69: "FileAttributes", 70: "PlaceObject3", 71: "ImportAssets2",
    72: "DoABC(old)", 73: "DefineFontAlignZones", 74: "CSMTextSettings", 75: "DefineFont3",
    76: "SymbolClass", 77: "Metadata", 78: "DefineScalingGrid", 82: "DoABC",
    83: "DefineShape4", 84: "DefineMorphShape2", 86: "DefineSceneAndFrameLabelData",
    87: "DefineBinaryData", 88: "DefineFontName", 89: "StartSound2", 90: "DefineBitsJPEG4",
    91: "DefineFont4", 93: "EnableTelemetry",
}
SHAPE_TAGS = {2: 1, 22: 2, 32: 3, 83: 4}
BLEND = {0: "normal", 1: "normal", 2: "layer", 3: "multiply", 4: "screen", 5: "lighten",
         6: "darken", 7: "difference", 8: "add", 9: "subtract", 10: "invert", 11: "alpha",
         12: "erase", 13: "overlay", 14: "hardlight"}
FILTERS = {0: "DropShadow", 1: "Blur", 2: "Glow", 3: "Bevel", 4: "GradientGlow",
           5: "Convolution", 6: "ColorMatrix", 7: "GradientBevel"}


class R:
    def __init__(self, data, pos=0):
        self.d = data; self.p = pos; self.bitpos = 0; self.cur = 0

    def align(self):
        self.bitpos = 0

    def ub(self, n):
        v = 0
        for _ in range(n):
            if self.bitpos == 0:
                self.cur = self.d[self.p]; self.p += 1; self.bitpos = 8
            self.bitpos -= 1
            v = (v << 1) | ((self.cur >> self.bitpos) & 1)
        return v

    def sb(self, n):
        if n == 0:
            return 0
        v = self.ub(n)
        if v & (1 << (n - 1)):
            v -= 1 << n
        return v

    def u8(self):
        self.align(); v = self.d[self.p]; self.p += 1; return v

    def u16(self):
        self.align(); v = struct.unpack_from("<H", self.d, self.p)[0]; self.p += 2; return v

    def s16(self):
        self.align(); v = struct.unpack_from("<h", self.d, self.p)[0]; self.p += 2; return v

    def u32(self):
        self.align(); v = struct.unpack_from("<I", self.d, self.p)[0]; self.p += 4; return v

    def f32(self):
        self.align(); v = struct.unpack_from("<f", self.d, self.p)[0]; self.p += 4; return v

    def string(self):
        self.align(); e = self.d.index(b"\0", self.p); s = self.d[self.p:e].decode("utf-8", "replace"); self.p = e + 1; return s

    def eu32(self):
        self.align(); res = 0; shift = 0
        for _ in range(5):
            b = self.d[self.p]; self.p += 1
            res |= (b & 0x7F) << shift
            if not b & 0x80:
                break
            shift += 7
        return res

    def rect(self):
        self.align(); n = self.ub(5)
        v = (self.sb(n), self.sb(n), self.sb(n), self.sb(n)); self.align(); return v

    def matrix(self):
        self.align(); sx = sy = 1.0; r0 = r1 = 0.0
        if self.ub(1):
            n = self.ub(5); sx = self.sb(n) / 65536; sy = self.sb(n) / 65536
        if self.ub(1):
            n = self.ub(5); r0 = self.sb(n) / 65536; r1 = self.sb(n) / 65536
        n = self.ub(5); tx = self.sb(n); ty = self.sb(n); self.align()
        return (sx, r0, r1, sy, tx / 20, ty / 20)

    def cxform(self, alpha):
        self.align(); has_add = self.ub(1); has_mult = self.ub(1); n = self.ub(4)
        cnt = 4 if alpha else 3
        mult = tuple(self.sb(n) / 256 for _ in range(cnt)) if has_mult else None
        add = tuple(self.sb(n) for _ in range(cnt)) if has_add else None
        self.align(); return {"mult": mult, "add": add}

    def rgb(self):
        return "#%02x%02x%02x" % (self.u8(), self.u8(), self.u8())

    def rgba(self):
        r, g, b, a = self.u8(), self.u8(), self.u8(), self.u8()
        return "#%02x%02x%02x%s" % (r, g, b, "" if a == 255 else "/a%d" % a)


def load(path):
    raw = open(path, "rb").read()
    sig = raw[:3]; ver = raw[3]; flen = struct.unpack_from("<I", raw, 4)[0]
    if sig == b"FWS":
        body = raw[8:]
    elif sig == b"CWS":
        body = zlib.decompress(raw[8:])
    elif sig == b"ZWS":
        props = raw[12:17]
        hdr = props + struct.pack("<Q", flen - 8)
        body = lzma.decompress(hdr + raw[17:], format=lzma.FORMAT_ALONE)
    else:
        raise SystemExit("not a SWF: %r" % sig)
    return sig.decode(), ver, flen, body


def iter_tags(d, pos, end):
    while pos < end:
        cl = struct.unpack_from("<H", d, pos)[0]; pos += 2
        code = cl >> 6; ln = cl & 0x3F
        if ln == 0x3F:
            ln = struct.unpack_from("<I", d, pos)[0]; pos += 4
        yield code, pos, ln
        pos += ln
        if code == 0:
            return


def parse_fill(r, ver):
    t = r.u8()
    if t == 0x00:
        return ("solid", r.rgba() if ver >= 3 else r.rgb())
    if t in (0x10, 0x12, 0x13):
        r.matrix(); r.align(); r.ub(2); r.ub(2); n = r.ub(4)
        stops = [(r.u8(), r.rgba() if ver >= 3 else r.rgb()) for _ in range(n)]
        if t == 0x13:
            r.s16()
        return ({0x10: "linear", 0x12: "radial", 0x13: "focal"}[t], stops)
    if t in (0x40, 0x41, 0x42, 0x43):
        bid = r.u16(); r.matrix(); return ("bitmap", bid)
    raise ValueError("bad fill type %x" % t)


def parse_styles(r, ver):
    n = r.u8()
    if n == 0xFF and ver >= 2:
        n = r.u16()
    fills = [parse_fill(r, ver) for _ in range(n)]
    n = r.u8()
    if n == 0xFF:
        n = r.u16()
    lines = []
    for _ in range(n):
        w = r.u16()
        if ver == 4:
            r.ub(2); join = r.ub(2); has_fill = r.ub(1); r.ub(1); r.ub(1); r.ub(1); r.ub(5); r.ub(1); r.ub(2)
            if join == 2:
                r.u16()
            lines.append(("line", w / 20, parse_fill(r, ver) if has_fill else r.rgba()))
        else:
            lines.append(("line", w / 20, r.rgba() if ver >= 3 else r.rgb()))
    return fills, lines


def parse_shape(d, pos, ln, ver):
    r = R(d, pos); sid = r.u16(); b = r.rect()
    if ver == 4:
        r.rect(); r.u8()
    fills, lines = parse_styles(r, ver)
    all_fills = list(fills); all_lines = list(lines)
    r.align(); nf = r.ub(4); nl = r.ub(4)
    edges = curves = moves = 0
    while True:
        if r.ub(1) == 0:
            f = r.ub(5)
            if f == 0:
                break
            if f & 1:
                n = r.ub(5); r.sb(n); r.sb(n); moves += 1
            if f & 2:
                r.ub(nf)
            if f & 4:
                r.ub(nf)
            if f & 8:
                r.ub(nl)
            if f & 16:
                fl, ll = parse_styles(r, ver); all_fills += fl; all_lines += ll
                r.align(); nf = r.ub(4); nl = r.ub(4)
        else:
            if r.ub(1):
                n = r.ub(4) + 2
                if r.ub(1):
                    r.sb(n); r.sb(n)
                else:
                    r.ub(1); r.sb(n)
                edges += 1
            else:
                n = r.ub(4) + 2
                r.sb(n); r.sb(n); r.sb(n); r.sb(n); edges += 1; curves += 1
    return {"id": sid, "kind": "shape%d" % ver, "bounds": tuple(x / 20 for x in b),
            "fills": all_fills, "lines": all_lines, "edges": edges, "curves": curves, "moves": moves}


def parse_filters(r):
    out = []
    for _ in range(r.u8()):
        fid = r.u8(); name = FILTERS.get(fid, "?%d" % fid)
        if fid == 0:
            c = r.rgba(); r.p += 4 * 4 + 2 + 1; out.append("%s(%s)" % (name, c))
        elif fid == 1:
            bx = r.u32() / 65536; by = r.u32() / 65536; r.p += 1; out.append("Blur(%.1f,%.1f)" % (bx, by))
        elif fid == 2:
            c = r.rgba(); bx = r.u32() / 65536; by = r.u32() / 65536; st = r.u16() / 256; fl = r.u8()
            out.append("Glow(%s blur=%.1f,%.1f str=%.2f inner=%d knock=%d)" % (c, bx, by, st, fl >> 7 & 1, fl >> 6 & 1))
        elif fid == 3:
            r.p += 4 + 4 + 16 + 2 + 1; out.append(name)
        elif fid in (4, 7):
            n = r.u8(); r.p += 5 * n + 16 + 2 + 1; out.append(name)
        elif fid == 5:
            mx = r.u8(); my = r.u8(); r.p += 8 + 4 * mx * my + 4 + 1; out.append(name)
        elif fid == 6:
            m = [r.f32() for _ in range(20)]; out.append("ColorMatrix(%s)" % ",".join("%.2f" % x for x in m))
    return out


def parse_place(d, pos, ln, v3):
    r = R(d, pos); f = r.u8(); f2 = r.u8() if v3 else 0
    o = {"depth": r.u16(), "move": bool(f & 1)}
    if v3 and (f2 & 0x08 or (f2 & 0x10 and f & 0x02)):
        o["class"] = r.string()
    if f & 0x02:
        o["char"] = r.u16()
    if f & 0x04:
        o["matrix"] = r.matrix()
    if f & 0x08:
        o["cx"] = r.cxform(True)
    if f & 0x10:
        o["ratio"] = r.u16()
    if f & 0x20:
        o["name"] = r.string()
    if f & 0x40:
        o["clipdepth"] = r.u16()
    if v3:
        if f2 & 0x01:
            o["filters"] = parse_filters(r)
        if f2 & 0x02:
            o["blend"] = BLEND.get(r.u8(), "?")
        if f2 & 0x04:
            o["cacheAsBitmap"] = r.u8()
        if f2 & 0x20:
            o["visible"] = r.u8()
    return o


class SWF:
    def __init__(self, path):
        self.sig, self.ver, self.flen, d = load(path)
        self.d = d
        r = R(d, 0); self.size = tuple(x / 20 for x in r.rect()); r.align()
        self.fps = r.u16() / 256; self.frames = r.u16()
        self.chars = {}           # id -> dict(kind=...)
        self.symbols = {}         # id -> class name
        self.exports = {}
        self.abcs = []
        self.tagcount = collections.Counter()
        self.attrs = None
        self.root = self.parse_timeline(r.p, len(d), None)

    def parse_timeline(self, pos, end, sprite_id):
        frames = []; cur = []; labels = {}
        for code, p, ln in iter_tags(self.d, pos, end):
            self.tagcount[TAG_NAMES.get(code, str(code))] += 1
            if code in SHAPE_TAGS:
                try:
                    s = parse_shape(self.d, p, ln, SHAPE_TAGS[code])
                except Exception as e:  # keep going on odd shapes
                    s = {"id": struct.unpack_from("<H", self.d, p)[0], "kind": "shape?", "err": str(e)}
                self.chars[s["id"]] = s
            elif code in (46, 84):
                r = R(self.d, p); cid = r.u16(); sb = r.rect(); eb = r.rect()
                self.chars[cid] = {"id": cid, "kind": "morph", "bounds": tuple(x / 20 for x in sb)}
            elif code == 39:
                r = R(self.d, p); cid = r.u16(); fc = r.u16()
                tl = self.parse_timeline(r.p, p + ln, cid)
                self.chars[cid] = {"id": cid, "kind": "sprite", "nframes": fc, "timeline": tl}
            elif code in (6, 21, 35, 90, 20, 36):
                r = R(self.d, p); cid = r.u16(); info = {"id": cid, "kind": "bitmap"}
                if code in (20, 36):
                    fmt = r.u8(); info["w"] = r.u16(); info["h"] = r.u16()
                self.chars[cid] = info
            elif code in (11, 33, 37):
                cid = struct.unpack_from("<H", self.d, p)[0]
                self.chars[cid] = {"id": cid, "kind": "text"}
            elif code in (10, 48, 75, 91):
                cid = struct.unpack_from("<H", self.d, p)[0]
                self.chars[cid] = {"id": cid, "kind": "font"}
            elif code in (7, 34):
                cid = struct.unpack_from("<H", self.d, p)[0]
                self.chars[cid] = {"id": cid, "kind": "button"}
            elif code == 14:
                cid = struct.unpack_from("<H", self.d, p)[0]
                self.chars[cid] = {"id": cid, "kind": "sound"}
            elif code == 87:
                cid = struct.unpack_from("<H", self.d, p)[0]
                self.chars[cid] = {"id": cid, "kind": "binary", "len": ln - 6}
            elif code in (26, 70):
                o = parse_place(self.d, p, ln, code == 70); o["_t"] = "place"; cur.append(o)
            elif code == 4:
                r = R(self.d, p); cur.append({"_t": "place", "char": r.u16(), "depth": r.u16(), "v1": True})
            elif code in (5, 28):
                r = R(self.d, p)
                if code == 5:
                    r.u16()
                cur.append({"_t": "remove", "depth": r.u16()})
            elif code == 43:
                r = R(self.d, p); labels[len(frames)] = r.string()
            elif code == 1:
                frames.append(cur); cur = []
            elif code == 76:
                r = R(self.d, p)
                for _ in range(r.u16()):
                    cid = r.u16(); self.symbols[cid] = r.string()
            elif code == 56:
                r = R(self.d, p)
                for _ in range(r.u16()):
                    cid = r.u16(); self.exports[cid] = r.string()
            elif code == 82:
                r = R(self.d, p); flags = r.u32(); name = r.string()
                self.abcs.append((name, self.d[r.p:p + ln]))
            elif code == 72:
                self.abcs.append(("(old)", self.d[p:p + ln]))
            elif code == 69:
                self.attrs = self.d[p]
            elif code == 86:
                r = R(self.d, p); sc = r.eu32()
                scenes = [(r.eu32(), r.string()) for _ in range(sc)]
                lc = r.eu32()
                for _ in range(lc):
                    fn = r.eu32(); labels.setdefault(fn, r.string())
        if cur:
            frames.append(cur)
        return {"frames": frames, "labels": labels}


# ---------------------------------------------------------------- ABC
class ABC:
    def __init__(self, data):
        self.d = data; self.p = 0
        self.minor = self.u16(); self.major = self.u16()
        n = self.u30(); self.ints = [0] + [self.s32() for _ in range(max(0, n - 1))]
        n = self.u30(); self.uints = [0] + [self.u30() for _ in range(max(0, n - 1))]
        n = self.u30(); self.doubles = [0.0] + [self.d64() for _ in range(max(0, n - 1))]
        n = self.u30(); self.strings = [""]
        for _ in range(max(0, n - 1)):
            ln = self.u30(); self.strings.append(self.d[self.p:self.p + ln].decode("utf-8", "replace")); self.p += ln
        n = self.u30(); self.ns = [(0, 0)] + [(self.u8(), self.u30()) for _ in range(max(0, n - 1))]
        n = self.u30(); self.nssets = [[]]
        for _ in range(max(0, n - 1)):
            c = self.u30(); self.nssets.append([self.u30() for _ in range(c)])
        n = self.u30(); self.mn = [None]
        for _ in range(max(0, n - 1)):
            k = self.u8()
            if k in (0x07, 0x0D):
                self.mn.append(("Q", self.u30(), self.u30()))
            elif k in (0x0F, 0x10):
                self.mn.append(("RTQ", self.u30()))
            elif k in (0x11, 0x12):
                self.mn.append(("RTQL",))
            elif k in (0x09, 0x0E):
                self.mn.append(("M", self.u30(), self.u30()))
            elif k in (0x1B, 0x1C):
                self.mn.append(("ML", self.u30()))
            elif k == 0x1D:
                q = self.u30(); c = self.u30(); self.mn.append(("T", q, [self.u30() for _ in range(c)]))
            else:
                raise ValueError("multiname kind %x" % k)
        n = self.u30(); self.methods = []
        for _ in range(n):
            pc = self.u30(); ret = self.u30(); [self.u30() for _ in range(pc)]
            name = self.u30(); fl = self.u8()
            if fl & 0x08:
                for _ in range(self.u30()):
                    self.u30(); self.u8()
            if fl & 0x80:
                [self.u30() for _ in range(pc)]
            self.methods.append(name)
        n = self.u30()
        for _ in range(n):
            self.u30()
            for _ in range(self.u30()):
                self.u30(); self.u30()
        n = self.u30(); self.instances = []
        for _ in range(n):
            name = self.u30(); sup = self.u30(); fl = self.u8()
            if fl & 0x08:
                self.u30()
            [self.u30() for _ in range(self.u30())]
            iinit = self.u30(); traits = self.traits()
            self.instances.append({"name": name, "super": sup, "iinit": iinit, "traits": traits})
        self.classes = []
        for _ in range(n):
            cinit = self.u30(); self.classes.append({"cinit": cinit, "traits": self.traits()})
        self.scripts = []
        for _ in range(self.u30()):
            init = self.u30(); self.scripts.append({"init": init, "traits": self.traits()})
        self.bodies = {}
        for _ in range(self.u30()):
            m = self.u30(); self.u30(); self.u30(); self.u30(); self.u30()
            cl = self.u30(); code = self.d[self.p:self.p + cl]; self.p += cl
            for _ in range(self.u30()):
                self.u30(); self.u30(); self.u30(); self.u30(); self.u30()
            self.traits()
            self.bodies[m] = code

    def u8(self):
        v = self.d[self.p]; self.p += 1; return v

    def u16(self):
        v = struct.unpack_from("<H", self.d, self.p)[0]; self.p += 2; return v

    def u30(self):
        res = 0; shift = 0
        for _ in range(5):
            b = self.d[self.p]; self.p += 1
            res |= (b & 0x7F) << shift
            if not b & 0x80:
                break
            shift += 7
        return res

    def s32(self):
        v = self.u30() & 0xFFFFFFFF
        return v - (1 << 32) if v & 0x80000000 else v

    def d64(self):
        v = struct.unpack_from("<d", self.d, self.p)[0]; self.p += 8; return v

    def traits(self):
        out = []
        for _ in range(self.u30()):
            name = self.u30(); kind = self.u8(); t = kind & 0x0F; info = {"name": name, "kind": t}
            if t in (0, 6):
                info["slot"] = self.u30(); info["type"] = self.u30(); vi = self.u30()
                if vi:
                    self.u8()
            elif t in (1, 2, 3):
                self.u30(); info["method"] = self.u30()
            elif t in (4, 5):
                self.u30(); info["ref"] = self.u30()
            if kind & 0x40:
                [self.u30() for _ in range(self.u30())]
            out.append(info)
        return out

    def nsname(self, i):
        k, s = self.ns[i]; return self.strings[s] if s < len(self.strings) else "?"

    def mname(self, i):
        if not i or i >= len(self.mn) or self.mn[i] is None:
            return "*"
        m = self.mn[i]
        if m[0] == "Q":
            ns = self.nsname(m[1]); n = self.strings[m[2]]
            return ns + "." + n if ns else n
        if m[0] in ("RTQ", "M"):
            return self.strings[m[1]]
        if m[0] == "T":
            return "%s<%s>" % (self.mname(m[1]), ",".join(self.mname(x) for x in m[2]))
        return "[%s]" % m[0]


def fmt_place(o, swf):
    c = swf.chars.get(o.get("char"), {})
    parts = ["d%d" % o["depth"]]
    if "char" in o:
        k = c.get("kind", "?")
        cls = swf.symbols.get(o["char"])
        parts.append("%s#%d%s" % (k, o["char"], ("(" + cls + ")") if cls else ""))
    if o.get("move"):
        parts.append("move")
    if "name" in o:
        parts.append('name="%s"' % o["name"])
    if "matrix" in o:
        sx, r0, r1, sy, tx, ty = o["matrix"]
        parts.append("at(%.1f,%.1f)" % (tx, ty) + ("" if (sx, r0, r1, sy) == (1, 0, 0, 1) else " m(%.2f,%.2f,%.2f,%.2f)" % (sx, r0, r1, sy)))
    if "cx" in o:
        parts.append("cx%s" % (o["cx"],))
    for k in ("ratio", "clipdepth", "blend", "filters", "class", "visible", "cacheAsBitmap"):
        if k in o:
            parts.append("%s=%s" % (k, o[k]))
    return " ".join(parts)


def dump_sprite(swf, cid, indent, maxdepth, seen, allframes=False):
    c = swf.chars.get(cid)
    if not c or c["kind"] != "sprite":
        return
    tl = c["timeline"]
    pad = "  " * indent
    lab = (" labels=%s" % tl["labels"]) if tl["labels"] else ""
    print("%ssprite#%d frames=%d%s" % (pad, cid, c["nframes"], lab))
    if indent >= maxdepth:
        return
    frames = tl["frames"] if allframes else tl["frames"][:1]
    for fi, fr in enumerate(frames):
        if allframes and len(tl["frames"]) > 1:
            print("%s  [frame %d]" % (pad, fi + 1))
        for o in fr:
            if o["_t"] == "place":
                print("%s  - %s" % (pad, fmt_place(o, swf)))
                ch = o.get("char")
                if ch is not None and ch not in seen and swf.chars.get(ch, {}).get("kind") == "sprite":
                    seen.add(ch)
                    dump_sprite(swf, ch, indent + 2, maxdepth, seen)
            else:
                print("%s  - remove d%d" % (pad, o["depth"]))
    if not allframes and len(tl["frames"]) > 1:
        # summarize later frames: named instances that appear
        names = collections.OrderedDict()
        for fr in tl["frames"][1:]:
            for o in fr:
                if o["_t"] == "place" and "name" in o:
                    names[o["name"]] = 1
        if names:
            print("%s  (later frames add names: %s)" % (pad, ", ".join(names)))


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    a = sys.argv[1:]
    path = a[0]; opts = set(x for x in a[1:] if x.startswith("--"))
    maxdepth = 6
    if "--maxdepth" in a:
        maxdepth = int(a[a.index("--maxdepth") + 1])
    swf = SWF(path)
    print("== %s  sig=%s ver=%d size=%sx%s fps=%.2f frames=%d fileattrs=%s" % (
        path, swf.sig, swf.ver, swf.size[1] - swf.size[0], swf.size[3] - swf.size[2], swf.fps, swf.frames,
        None if swf.attrs is None else bin(swf.attrs)))
    print("tags:", dict(swf.tagcount))
    kinds = collections.Counter(c["kind"] for c in swf.chars.values())
    print("characters:", dict(kinds))
    print("SymbolClass:")
    for cid, name in sorted(swf.symbols.items(), key=lambda x: x[1]):
        c = swf.chars.get(cid, {})
        extra = ""
        if c.get("kind") == "sprite":
            extra = " frames=%d labels=%s" % (c["nframes"], c["timeline"]["labels"] or "")
        print("  %-40s -> %s#%d%s" % (name, c.get("kind", "?"), cid, extra))
    if swf.exports:
        print("ExportAssets:", swf.exports)
    if swf.root["labels"]:
        print("root labels:", swf.root["labels"])
    if "--tree" in opts:
        seen = set()
        for cid, name in sorted(swf.symbols.items(), key=lambda x: x[1]):
            if swf.chars.get(cid, {}).get("kind") == "sprite":
                print("\n### %s" % name)
                dump_sprite(swf, cid, 1, maxdepth, seen, allframes="--allframes" in opts)
        print("\n### root timeline (frame 1)")
        for o in swf.root["frames"][:1][0] if swf.root["frames"] else []:
            if o["_t"] == "place":
                print("  - " + fmt_place(o, swf))
    if "--shapes" in opts:
        cols = collections.Counter()
        for c in swf.chars.values():
            if c["kind"].startswith("shape") and "fills" in c:
                for f in c["fills"]:
                    cols[f[0] if f[0] != "solid" else f[1]] += 1
                for l in c["lines"]:
                    cols["LINE w=%.2f %s" % (l[1], l[2] if isinstance(l[2], str) else l[2][0])] += 1
        print("\nfill/line usage (top 60):")
        for k, v in cols.most_common(60):
            print("  %5d  %s" % (v, k))
        tot = [c for c in swf.chars.values() if c["kind"].startswith("shape") and "edges" in c]
        print("shapes=%d edges=%d curves=%d" % (len(tot), sum(c["edges"] for c in tot), sum(c["curves"] for c in tot)))
    if "--abc" in opts or "--strings" in opts:
        for name, data in swf.abcs:
            try:
                abc = ABC(data)
            except Exception as e:
                print("ABC %s parse error: %s" % (name, e)); continue
            print("\nABC block %r: v%d.%d classes=%d methods=%d strings=%d" % (
                name, abc.major, abc.minor, len(abc.instances), len(abc.methods), len(abc.strings)))
            if "--abc" in opts:
                for inst in abc.instances:
                    tr = []
                    for t in inst["traits"]:
                        kn = {0: "var", 1: "fn", 2: "get", 3: "set", 4: "class", 5: "func", 6: "const"}[t["kind"]]
                        tr.append("%s %s%s" % (kn, abc.mname(t["name"]), (":" + abc.mname(t["type"])) if "type" in t else ""))
                    print("  class %s extends %s" % (abc.mname(inst["name"]), abc.mname(inst["super"])))
                    for x in tr:
                        print("      " + x)
            if "--strings" in opts:
                print("  strings:", " | ".join(s for s in abc.strings if s))


if __name__ == "__main__":
    main()
