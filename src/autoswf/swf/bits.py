"""Bit-level writer and encoders for SWF basic records."""
import struct

from autoswf.model.geometry import ColorTransform, Matrix


class BitWriter:
    def __init__(self):
        self._buf = bytearray()
        self._cur = 0
        self._nbits = 0          # bits already used in self._cur

    def ub(self, value: int, nbits: int) -> None:
        for i in range(nbits - 1, -1, -1):
            self._cur = (self._cur << 1) | ((value >> i) & 1)
            self._nbits += 1
            if self._nbits == 8:
                self._buf.append(self._cur)
                self._cur = 0
                self._nbits = 0

    def sb(self, value: int, nbits: int) -> None:
        self.ub(value & ((1 << nbits) - 1) if nbits else 0, nbits)

    def fb(self, value: float, nbits: int) -> None:
        self.sb(round(value * 65536), nbits)

    def align(self) -> None:
        if self._nbits:
            self._buf.append(self._cur << (8 - self._nbits))
            self._cur = 0
            self._nbits = 0

    def raw(self, b: bytes) -> None:
        self.align()
        self._buf += b

    def u8(self, v: int) -> None:
        self.raw(struct.pack("<B", v))

    def u16(self, v: int) -> None:
        self.raw(struct.pack("<H", v))

    def s16(self, v: int) -> None:
        self.raw(struct.pack("<h", v))

    def u32(self, v: int) -> None:
        self.raw(struct.pack("<I", v))

    def getvalue(self) -> bytes:
        self.align()
        return bytes(self._buf)


def bits_for_unsigned(*values: int) -> int:
    return max((v.bit_length() for v in values), default=0)


def bits_for_signed(*values: int) -> int:
    n = 0
    for v in values:
        if v > 0:
            n = max(n, v.bit_length() + 1)
        elif v < 0:
            n = max(n, (-v - 1).bit_length() + 1)
    return n


def twips(px: float) -> int:
    return round(px * 20)


def write_rect(w: BitWriter, xmin: int, xmax: int, ymin: int, ymax: int) -> None:
    w.align()
    n = bits_for_signed(xmin, xmax, ymin, ymax)
    w.ub(n, 5)
    for v in (xmin, xmax, ymin, ymax):
        w.sb(v, n)
    w.align()


def write_matrix(w: BitWriter, m: Matrix) -> None:
    w.align()
    if m.a == 1.0 and m.d == 1.0:
        w.ub(0, 1)
    else:
        sx, sy = round(m.a * 65536), round(m.d * 65536)
        n = max(bits_for_signed(sx, sy), 1)
        w.ub(1, 1); w.ub(n, 5); w.sb(sx, n); w.sb(sy, n)
    if m.b == 0.0 and m.c == 0.0:
        w.ub(0, 1)
    else:
        r0, r1 = round(m.b * 65536), round(m.c * 65536)
        n = max(bits_for_signed(r0, r1), 1)
        w.ub(1, 1); w.ub(n, 5); w.sb(r0, n); w.sb(r1, n)
    tx, ty = twips(m.tx), twips(m.ty)
    n = bits_for_signed(tx, ty)
    w.ub(n, 5); w.sb(tx, n); w.sb(ty, n)
    w.align()


def write_cxform_alpha(w: BitWriter, ct: ColorTransform) -> None:
    w.align()
    mult = [round(v * 256) for v in ct.mult] if any(v != 1.0 for v in ct.mult) else None
    add = list(ct.add) if any(v != 0 for v in ct.add) else None
    terms = (mult or []) + (add or [])
    n = max(bits_for_signed(*terms), 1) if terms else 0
    w.ub(1 if add else 0, 1)
    w.ub(1 if mult else 0, 1)
    w.ub(n, 4)
    for v in terms:
        w.sb(v, n)
    w.align()


def write_rgba(w: BitWriter, color: tuple[int, int, int, int]) -> None:
    w.raw(bytes(color))


def write_string(w: BitWriter, s: str) -> None:
    w.raw(s.encode("utf-8") + b"\0")


def write_eu32(w: BitWriter, n: int) -> None:
    out = bytearray()
    while True:
        b = n & 0x7F
        n >>= 7
        out.append(b | (0x80 if n else 0))
        if not n:
            break
    w.raw(bytes(out))
