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
    def newclass(self, i): return self._op(0x58, u30(i))

    def bytes(self) -> bytes:
        return bytes(self._b)
