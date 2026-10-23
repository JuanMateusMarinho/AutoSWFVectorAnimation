"""AVM2 bytecode (ABC) parser."""
import struct


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
        n = self.u30(); self.methods = []; self.method_info = []
        for _ in range(n):
            pc = self.u30(); ret = self.u30(); ptypes = [self.u30() for _ in range(pc)]
            name = self.u30(); fl = self.u8(); self.method_flags = getattr(self, "method_flags", []) + [fl]
            self.method_info.append({"params": ptypes, "ret": ret, "name": name, "flags": fl})
            if fl & 0x08:
                optional = []
                for _ in range(self.u30()):
                    index = self.u30(); optional.append((self.u8(), index))
                self.method_info[-1]["optional"] = optional
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
            name = self.u30(); sup = self.u30(); fl = self.u8(); pns = None
            if fl & 0x08:
                pns = self.u30()
            ifaces = [self.u30() for _ in range(self.u30())]
            iinit = self.u30(); traits = self.traits()
            self.instances.append({"name": name, "super": sup, "flags": fl, "protected_ns": pns,
                                   "interfaces": ifaces, "iinit": iinit, "traits": traits})
        self.classes = []
        for _ in range(n):
            cinit = self.u30(); self.classes.append({"cinit": cinit, "traits": self.traits()})
        self.scripts = []
        for _ in range(self.u30()):
            init = self.u30(); self.scripts.append({"init": init, "traits": self.traits()})
        self.bodies = {}; self.body_info = {}
        self.body_pos = {}          # method -> (start of code_length, end of the exception table) in the data
        self.body_traits = {}       # method -> the traits of its activation object (its locals seen by closures)
        for _ in range(self.u30()):
            m = self.u30(); self.body_info[m] = (self.u30(), self.u30(), self.u30(), self.u30())
            start = self.p
            cl = self.u30(); code = self.d[self.p:self.p + cl]; self.p += cl
            for _ in range(self.u30()):
                self.u30(); self.u30(); self.u30(); self.u30(); self.u30()
            self.body_pos[m] = (start, self.p)
            self.body_traits[m] = self.traits()
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
                    info["default"] = (self.u8(), vi)
            elif t in (1, 2, 3):
                self.u30(); info["method"] = self.u30()
            elif t in (4, 5):
                self.u30(); info["ref"] = self.u30()
            if kind & 0x40:
                [self.u30() for _ in range(self.u30())]
            out.append(info)
        return out

    def constant(self, kind: int, index: int):
        """A default value (vkind, vindex) as Python: str, int, float, bool or None (null and undefined)."""
        if kind == 0x01:
            return self.strings[index]
        if kind == 0x03:
            return self.ints[index]
        if kind == 0x04:
            return self.uints[index]
        if kind == 0x06:
            return self.doubles[index]
        return {0x0A: False, 0x0B: True}.get(kind)

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

    NS_KINDS = {0x05: "Private", 0x08: "Namespace", 0x16: "Package", 0x17: "PackageInternal", 0x18: "Protected",
                0x19: "Explicit", 0x1A: "StaticProtected"}

    def ns_raw(self, i):
        k, s = self.ns[i]
        return "%s:%r" % (self.NS_KINDS.get(k, hex(k)), self.strings[s] if s < len(self.strings) else "?")

    def mname_raw(self, i):
        """Multiname with its kind and namespaces spelled out, e.g. QName(Package:'',stage)."""
        if not i or i >= len(self.mn) or self.mn[i] is None:
            return "*"
        m = self.mn[i]
        if m[0] == "Q":
            return "QName(%s,%s)" % (self.ns_raw(m[1]), self.strings[m[2]])
        if m[0] == "M":
            return "Multiname(%s,[%s])" % (self.strings[m[1]], ",".join(self.ns_raw(n) for n in self.nssets[m[2]]))
        return self.mname(i)
