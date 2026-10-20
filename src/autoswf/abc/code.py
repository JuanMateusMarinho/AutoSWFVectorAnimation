"""AVM2 opcode emitter (only the opcodes AutoSWF generates)."""


def u30(n: int) -> bytes:
    out = bytearray()
    while True:
        b = n & 0x7F
        n >>= 7
        out.append(b | (0x80 if n else 0))
        if not n:
            return bytes(out)


class Code:
    def __init__(self):
        self._b = bytearray()

    def _op(self, opcode: int, *operands: bytes) -> "Code":
        self._b.append(opcode)
        for o in operands:
            self._b += o
        return self

    def getlocal0(self): return self._op(0xD0)
    def pushscope(self): return self._op(0x30)
    def popscope(self): return self._op(0x1D)
    def returnvoid(self): return self._op(0x47)
    def constructsuper(self, argc): return self._op(0x49, u30(argc))
    def findpropstrict(self, mn): return self._op(0x5D, u30(mn))
    def getlex(self, mn): return self._op(0x60, u30(mn))
    def getproperty(self, mn): return self._op(0x66, u30(mn))
    def initproperty(self, mn): return self._op(0x68, u30(mn))
    def callproperty(self, mn, argc): return self._op(0x46, u30(mn), u30(argc))
    def callpropvoid(self, mn, argc): return self._op(0x4F, u30(mn), u30(argc))
    def pushbyte(self, v): return self._op(0x24, bytes([v & 0xFF]))
    def pushshort(self, v): return self._op(0x25, u30(v))
    def pushstring(self, idx): return self._op(0x2C, u30(idx))
    def getscopeobject(self, i): return self._op(0x65, bytes([i]))
    def getlocal1(self): return self._op(0xD1)
    def setlocal1(self): return self._op(0xD5)
    def setlocal2(self): return self._op(0xD6)
    def dup(self): return self._op(0x2A)
    def swap(self): return self._op(0x2B)
    def newactivation(self): return self._op(0x57)
    def newcatch(self, i): return self._op(0x5A, u30(i))
    def setslot(self, i): return self._op(0x6D, u30(i))
    def kill(self, i): return self._op(0x08, u30(i))
    def pushtrue(self): return self._op(0x26)
    def pushfalse(self): return self._op(0x27)
    def setproperty(self, mn): return self._op(0x61, u30(mn))

    def pushnull(self): return self._op(0x20)
    def pop(self): return self._op(0x29)
    def label(self): return self._op(0x09)
    def getlocal(self, i): return self._op(0x62, u30(i))
    def setlocal(self, i): return self._op(0x63, u30(i))
    def getlocal2(self): return self._op(0xD2)
    def getlocal3(self): return self._op(0xD3)
    def setlocal3(self): return self._op(0xD7)
    def findproperty(self, mn): return self._op(0x5E, u30(mn))
    def newarray(self, n): return self._op(0x56, u30(n))
    def coerce_a(self): return self._op(0x82)
    def equals(self): return self._op(0xAB)
    def not_(self): return self._op(0x96)
    def in_(self): return self._op(0xB4)
    def hasnext2(self, obj, index): return self._op(0x32, u30(obj), u30(index))
    def nextvalue(self): return self._op(0x23)
    def returnvalue(self): return self._op(0x48)

    def jump(self, offset): return self._op(0x10, (offset & 0xFFFFFF).to_bytes(3, "little"))
    def ifeq(self, offset): return self._op(0x13, (offset & 0xFFFFFF).to_bytes(3, "little"))
    def ifne(self, offset): return self._op(0x14, (offset & 0xFFFFFF).to_bytes(3, "little"))
    def iftrue(self, offset): return self._op(0x11, (offset & 0xFFFFFF).to_bytes(3, "little"))
    def iffalse(self, offset): return self._op(0x12, (offset & 0xFFFFFF).to_bytes(3, "little"))

    def __len__(self) -> int:
        return len(self._b)
    def newclass(self, i): return self._op(0x58, u30(i))

    def bytes(self) -> bytes:
        return bytes(self._b)
