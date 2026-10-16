"""Typed SWF decoding for rendering: shapes, morph shapes, sprites, placements, filters and classes.

Characters are decoded lazily: the constructor only indexes the tags. Edge coordinates stay in integer twips
(exact joins between edges); everything else is in pixels.
"""
import os
import struct
from dataclasses import dataclass, field, replace
from typing import Literal

from autoswf.abc.reader import ABC
from autoswf.model.geometry import ColorTransform, Matrix
from autoswf.swf.reader import BLEND, R, decompress, iter_tags

RGBA = tuple[int, int, int, int]
SHAPE_VERSIONS = {2: 1, 22: 2, 32: 3, 83: 4}
MORPH_VERSIONS = {46: 1, 84: 2}
GRADIENT_KINDS = {0x10: "linear", 0x12: "radial", 0x13: "focal"}
UNSUPPORTED_FILTERS = {3: "Bevel", 4: "GradientGlow", 5: "Convolution", 7: "GradientBevel"}


@dataclass(frozen=True)
class SolidStyle:
    color: RGBA


@dataclass(frozen=True)
class GradientStyle:
    kind: Literal["linear", "radial", "focal"]
    matrix: Matrix              # maps the gradient square (-819.2 .. 819.2 px) into shape space
    stops: tuple[tuple[int, RGBA], ...]
    spread: int = 0             # 0 pad, 1 reflect, 2 repeat
    interpolation: int = 0      # 0 normal RGB, 1 linear RGB
    focal: float = 0.0


@dataclass(frozen=True)
class BitmapStyle:
    bitmap_id: int
    matrix: Matrix


FillStyle = SolidStyle | GradientStyle | BitmapStyle


@dataclass(frozen=True)
class LineStyle:
    width: float
    fill: FillStyle
    start_cap: int = 0          # 0 round, 1 none, 2 square
    end_cap: int = 0
    join: int = 0               # 0 round, 1 bevel, 2 miter
    miter_limit: float = 3.0
    no_hscale: bool = False
    no_vscale: bool = False


@dataclass(frozen=True)
class Edge:
    start: tuple[int, int]
    control: tuple[int, int] | None
    end: tuple[int, int]
    fill0: int | None           # global index into ShapeDef.fills (SWF FillStyle0)
    fill1: int | None
    line: int | None
    layer: int


@dataclass(frozen=True)
class ShapeDef:
    id: int
    bounds: tuple[float, float, float, float]       # xmin, xmax, ymin, ymax (px)
    fills: tuple[FillStyle, ...]
    lines: tuple[LineStyle, ...]
    edges: tuple[Edge, ...]
    nonzero: bool


@dataclass(frozen=True)
class MorphShapeDef:
    id: int
    start: ShapeDef
    end: ShapeDef


@dataclass(frozen=True)
class BlurFilter:
    blur_x: float
    blur_y: float
    passes: int


@dataclass(frozen=True)
class GlowFilter:
    color: RGBA
    blur_x: float
    blur_y: float
    strength: float
    inner: bool
    knockout: bool
    passes: int


@dataclass(frozen=True)
class DropShadowFilter:
    color: RGBA
    blur_x: float
    blur_y: float
    angle: float                # radians
    distance: float
    strength: float
    inner: bool
    knockout: bool
    passes: int


@dataclass(frozen=True)
class ColorMatrixFilter:
    matrix: tuple[float, ...]   # 20 values, row-major 4x5


@dataclass(frozen=True)
class UnsupportedFilter:
    name: str


Filter = BlurFilter | GlowFilter | DropShadowFilter | ColorMatrixFilter | UnsupportedFilter


@dataclass(frozen=True)
class PlaceCommand:
    depth: int
    move: bool = False
    char_id: int | None = None
    matrix: Matrix | None = None
    color: ColorTransform | None = None
    ratio: int | None = None
    name: str | None = None
    clip_depth: int | None = None
    filters: tuple[Filter, ...] | None = None
    blend: str | None = None
    visible: bool | None = None


@dataclass(frozen=True)
class RemoveCommand:
    depth: int


@dataclass(eq=False)
class SpriteDef:
    id: int
    frame_count: int
    frames: tuple[tuple[PlaceCommand | RemoveCommand, ...], ...]
    labels: dict[str, int]
    _states: dict = field(default_factory=dict, repr=False, compare=False)   # runtime cache (display layer)


# ---------------------------------------------------------------- records

def _matrix(r: R) -> Matrix:
    a, b, c, d, tx, ty = r.matrix()
    return Matrix(a, b, c, d, tx, ty)


def _color(r: R, version: int) -> RGBA:
    if version >= 3:
        return (r.u8(), r.u8(), r.u8(), r.u8())
    return (r.u8(), r.u8(), r.u8(), 255)


def _color_transform(cx: dict) -> ColorTransform:
    mult = tuple(cx["mult"] or (1.0, 1.0, 1.0)) + ((1.0,) if not cx["mult"] or len(cx["mult"]) == 3 else ())
    add = tuple(cx["add"] or (0, 0, 0)) + ((0,) if not cx["add"] or len(cx["add"]) == 3 else ())
    return ColorTransform(tuple(float(v) for v in mult[:4]), tuple(add[:4]))


def _fixed(r: R) -> float:
    return struct.unpack("<i", struct.pack("<I", r.u32()))[0] / 65536


def _fill(r: R, version: int) -> FillStyle:
    t = r.u8()
    if t == 0x00:
        return SolidStyle(_color(r, version))
    if t in GRADIENT_KINDS:
        m = _matrix(r)
        spread, interpolation, n = r.ub(2), r.ub(2), r.ub(4)
        stops = tuple((r.u8(), _color(r, version)) for _ in range(n))
        focal = r.s16() / 256 if t == 0x13 else 0.0
        return GradientStyle(GRADIENT_KINDS[t], m, stops, spread, interpolation, focal)
    if 0x40 <= t <= 0x43:
        return BitmapStyle(r.u16(), _matrix(r))
    raise ValueError("unknown fill style type 0x%02x" % t)


def _line(r: R, version: int) -> LineStyle:
    width = r.u16() / 20
    if version < 4:
        return LineStyle(width, SolidStyle(_color(r, version)))
    start_cap, join, has_fill, no_h, no_v = r.ub(2), r.ub(2), r.ub(1), r.ub(1), r.ub(1)
    r.ub(1); r.ub(5); r.ub(1)
    end_cap = r.ub(2)
    miter = r.u16() / 256 if join == 2 else 3.0
    fill = _fill(r, 4) if has_fill else SolidStyle(_color(r, 4))
    return LineStyle(width, fill, start_cap, end_cap, join, miter, bool(no_h), bool(no_v))


def _count(r: R, extended: bool) -> int:
    n = r.u8()
    return r.u16() if n == 0xFF and extended else n


def _styles(r: R, version: int) -> tuple[list[FillStyle], list[LineStyle]]:
    fills = [_fill(r, version) for _ in range(_count(r, version >= 2))]
    lines = [_line(r, version) for _ in range(_count(r, True))]
    return fills, lines


def _edges(r: R, version: int, fills: list, lines: list) -> list[Edge]:
    """Shape records -> edges with global style indexes; new style arrays are appended to fills/lines."""
    r.align()
    nf, nl = r.ub(4), r.ub(4)
    x = y = 0
    f0 = f1 = ln = None
    fbase = lbase = layer = 0
    edges = []
    while True:
        if r.ub(1) == 0:
            flags = r.ub(5)
            if flags == 0:
                break
            if flags & 0x01:
                n = r.ub(5); x = r.sb(n); y = r.sb(n)
            raw0 = r.ub(nf) if flags & 0x02 else None
            raw1 = r.ub(nf) if flags & 0x04 else None
            rawl = r.ub(nl) if flags & 0x08 else None
            if flags & 0x10 and version >= 2:
                new_fills, new_lines = _styles(r, version)
                fbase, lbase = len(fills), len(lines)
                fills += new_fills; lines += new_lines
                layer += 1
                f0 = f1 = ln = None
                r.align(); nf, nl = r.ub(4), r.ub(4)
            if raw0 is not None:
                f0 = fbase + raw0 - 1 if raw0 else None
            if raw1 is not None:
                f1 = fbase + raw1 - 1 if raw1 else None
            if rawl is not None:
                ln = lbase + rawl - 1 if rawl else None
        elif r.ub(1):
            n = r.ub(4) + 2
            if r.ub(1):
                dx, dy = r.sb(n), r.sb(n)
            elif r.ub(1):
                dx, dy = 0, r.sb(n)
            else:
                dx, dy = r.sb(n), 0
            edges.append(Edge((x, y), None, (x + dx, y + dy), f0, f1, ln, layer))
            x, y = x + dx, y + dy
        else:
            n = r.ub(4) + 2
            cdx, cdy, adx, ady = r.sb(n), r.sb(n), r.sb(n), r.sb(n)
            cx, cy = x + cdx, y + cdy
            edges.append(Edge((x, y), (cx, cy), (cx + adx, cy + ady), f0, f1, ln, layer))
            x, y = cx + adx, cy + ady
    return edges


def _bounds(r: R) -> tuple[float, float, float, float]:
    return tuple(v / 20 for v in r.rect())


def parse_shape(d: bytes, pos: int, version: int) -> ShapeDef:
    r = R(d, pos)
    cid = r.u16(); bounds = _bounds(r)
    nonzero = False
    if version == 4:
        r.rect(); nonzero = bool(r.u8() & 0x04)
    fills, lines = _styles(r, version)
    edges = _edges(r, version, fills, lines)
    return ShapeDef(cid, bounds, tuple(fills), tuple(lines), tuple(edges), nonzero)


def _morph_fill(r: R) -> tuple[FillStyle, FillStyle]:
    t = r.u8()
    if t == 0x00:
        return SolidStyle(_color(r, 3)), SolidStyle(_color(r, 3))
    if t in GRADIENT_KINDS:
        sm, em = _matrix(r), _matrix(r)
        head = r.u8()
        spread, interpolation, n = head >> 6, (head >> 4) & 3, head & 0x0F
        pairs = [((r.u8(), _color(r, 3)), (r.u8(), _color(r, 3))) for _ in range(n)]
        sf = ef = 0.0
        if t == 0x13:
            sf, ef = r.s16() / 256, r.s16() / 256
        kind = GRADIENT_KINDS[t]
        return (GradientStyle(kind, sm, tuple(p[0] for p in pairs), spread, interpolation, sf),
                GradientStyle(kind, em, tuple(p[1] for p in pairs), spread, interpolation, ef))
    if 0x40 <= t <= 0x43:
        bid = r.u16()
        return BitmapStyle(bid, _matrix(r)), BitmapStyle(bid, _matrix(r))
    raise ValueError("unknown morph fill style type 0x%02x" % t)


def _morph_line(r: R, version: int) -> tuple[LineStyle, LineStyle]:
    sw, ew = r.u16() / 20, r.u16() / 20
    if version == 1:
        return LineStyle(sw, SolidStyle(_color(r, 3))), LineStyle(ew, SolidStyle(_color(r, 3)))
    start_cap, join, has_fill, no_h, no_v = r.ub(2), r.ub(2), r.ub(1), r.ub(1), r.ub(1)
    r.ub(1); r.ub(5); r.ub(1)
    end_cap = r.ub(2)
    miter = r.u16() / 256 if join == 2 else 3.0
    sfill, efill = _morph_fill(r) if has_fill else (SolidStyle(_color(r, 3)), SolidStyle(_color(r, 3)))
    extra = (start_cap, end_cap, join, miter, bool(no_h), bool(no_v))
    return LineStyle(sw, sfill, *extra), LineStyle(ew, efill, *extra)


def parse_morph(d: bytes, pos: int, version: int) -> MorphShapeDef:
    r = R(d, pos)
    cid = r.u16(); sbounds, ebounds = _bounds(r), _bounds(r)
    if version == 2:
        r.rect(); r.rect(); r.u8()
    offset = r.u32()
    end_pos = r.p + offset
    fills = [_morph_fill(r) for _ in range(_count(r, True))]
    lines = [_morph_line(r, version) for _ in range(_count(r, True))]
    sfills, slines = [f[0] for f in fills], [ln[0] for ln in lines]
    start = _edges(r, 3, sfills, slines)
    end = _edges(R(d, end_pos), 3, [], [])
    end = [replace(e, fill0=s.fill0, fill1=s.fill1, line=s.line, layer=s.layer) for e, s in zip(end, start)] + end[len(start):]
    return MorphShapeDef(cid, ShapeDef(cid, sbounds, tuple(sfills), tuple(slines), tuple(start), False),
                         ShapeDef(cid, ebounds, tuple(f[1] for f in fills), tuple(ln[1] for ln in lines), tuple(end), False))


def _filters(r: R) -> tuple[Filter, ...]:
    out = []
    for _ in range(r.u8()):
        fid = r.u8()
        if fid == 0:
            color = _color(r, 3)
            bx, by, angle, distance = _fixed(r), _fixed(r), _fixed(r), _fixed(r)
            strength, flags = r.u16() / 256, r.u8()
            out.append(DropShadowFilter(color, bx, by, angle, distance, strength, bool(flags & 0x80), bool(flags & 0x40), flags & 0x1F))
        elif fid == 1:
            bx, by = _fixed(r), _fixed(r)
            out.append(BlurFilter(bx, by, r.u8() >> 3))
        elif fid == 2:
            color = _color(r, 3)
            bx, by = _fixed(r), _fixed(r)
            strength, flags = r.u16() / 256, r.u8()
            out.append(GlowFilter(color, bx, by, strength, bool(flags & 0x80), bool(flags & 0x40), flags & 0x1F))
        elif fid == 3:
            r.p += 4 + 4 + 16 + 2 + 1
            out.append(UnsupportedFilter("Bevel"))
        elif fid in (4, 7):
            n = r.u8(); r.p += 5 * n + 16 + 2 + 1
            out.append(UnsupportedFilter(UNSUPPORTED_FILTERS[fid]))
        elif fid == 5:
            mx, my = r.u8(), r.u8(); r.p += 8 + 4 * mx * my + 4 + 1
            out.append(UnsupportedFilter("Convolution"))
        elif fid == 6:
            out.append(ColorMatrixFilter(tuple(r.f32() for _ in range(20))))
        else:
            raise ValueError("unknown filter id %d" % fid)
    return tuple(out)


def parse_place(d: bytes, pos: int, v3: bool) -> PlaceCommand:
    r = R(d, pos)
    f = r.u8(); f2 = r.u8() if v3 else 0
    depth = r.u16()
    if v3 and (f2 & 0x08 or (f2 & 0x10 and f & 0x02)):
        r.string()
    char_id = r.u16() if f & 0x02 else None
    matrix = _matrix(r) if f & 0x04 else None
    color = _color_transform(r.cxform(True)) if f & 0x08 else None
    ratio = r.u16() if f & 0x10 else None
    name = r.string() if f & 0x20 else None
    clip_depth = r.u16() if f & 0x40 else None
    filters = _filters(r) if f2 & 0x01 else None
    blend = BLEND.get(r.u8(), "normal") if f2 & 0x02 else None
    if f2 & 0x04:
        r.u8()
    visible = bool(r.u8()) if f2 & 0x20 else None
    return PlaceCommand(depth, bool(f & 0x01), char_id, matrix, color, ratio, name, clip_depth, filters, blend, visible)


# ---------------------------------------------------------------- movie

class MovieData:
    """A decoded SWF. `cache` is free memo space for the runtime and render layers (per movie)."""

    def __init__(self, source: bytes | str | os.PathLike):
        raw = source if isinstance(source, (bytes, bytearray)) else open(source, "rb").read()
        _, self.version, _, self._d = decompress(bytes(raw))
        r = R(self._d, 0)
        self.size = _bounds(r)
        self.frame_rate = r.u16() / 256
        frame_count = r.u16()
        self.classes: dict[str, int] = {}
        self.cache: dict = {}
        self._index: dict[int, tuple[int, int, int]] = {}
        self._chars: dict[int, ShapeDef | MorphShapeDef | SpriteDef | None] = {}
        self._abc_blocks: list[bytes] = []
        self._abcs: list[ABC] | None = None
        frames, labels = self._timeline(r.p, len(self._d), top=True)
        self.root = _sprite(0, frame_count, frames, labels)
        self._names = {cid: name for name, cid in self.classes.items()}

    def class_name(self, char_id: int) -> str | None:
        return self._names.get(char_id)

    @property
    def abcs(self) -> list[ABC]:
        if self._abcs is None:
            self._abcs = []
            for block in self._abc_blocks:
                try:
                    self._abcs.append(ABC(block))
                except (ValueError, IndexError, struct.error):
                    continue
        return self._abcs

    def character(self, char_id: int) -> ShapeDef | MorphShapeDef | SpriteDef | None:
        if char_id in self._chars:
            return self._chars[char_id]
        entry = self._index.get(char_id)
        char = None
        if entry is not None:
            code, pos, length = entry
            try:
                if code in SHAPE_VERSIONS:
                    char = parse_shape(self._d, pos, SHAPE_VERSIONS[code])
                elif code in MORPH_VERSIONS:
                    char = parse_morph(self._d, pos, MORPH_VERSIONS[code])
                else:
                    count = struct.unpack_from("<H", self._d, pos + 2)[0]
                    frames, labels = self._timeline(pos + 4, pos + length, top=False)
                    char = _sprite(char_id, count, frames, labels)
            except (ValueError, IndexError, struct.error) as e:
                raise ValueError("Could not decode character %d: %s" % (char_id, e)) from e
        self._chars[char_id] = char
        return char

    def _timeline(self, pos: int, end: int, top: bool):
        d = self._d
        frames, current, labels = [], [], {}
        for code, p, ln in iter_tags(d, pos, end):
            if code == 1:
                frames.append(tuple(current)); current = []
            elif code in (26, 70):
                current.append(parse_place(d, p, code == 70))
            elif code == 4:
                r = R(d, p)
                cid, depth = r.u16(), r.u16()
                matrix = _matrix(r)
                color = _color_transform(r.cxform(False)) if r.p < p + ln else None
                current.append(PlaceCommand(depth, False, cid, matrix, color))
            elif code == 5:
                current.append(RemoveCommand(struct.unpack_from("<H", d, p + 2)[0]))
            elif code == 28:
                current.append(RemoveCommand(struct.unpack_from("<H", d, p)[0]))
            elif code == 43:
                labels.setdefault(R(d, p).string(), len(frames))
            elif not top:
                continue
            elif code in SHAPE_VERSIONS or code in MORPH_VERSIONS or code == 39:
                self._index[struct.unpack_from("<H", d, p)[0]] = (code, p, ln)
            elif code == 76:
                r = R(d, p)
                for _ in range(r.u16()):
                    cid = r.u16(); self.classes[r.string()] = cid
            elif code == 82:
                r = R(d, p); r.u32(); r.string()
                self._abc_blocks.append(d[r.p:p + ln])
            elif code == 72:
                self._abc_blocks.append(d[p:p + ln])
            elif code == 86:
                r = R(d, p)
                for _ in range(r.eu32()):
                    r.eu32(); r.string()
                for _ in range(r.eu32()):
                    frame = r.eu32(); labels.setdefault(r.string(), frame)
        if current:
            frames.append(tuple(current))
        return frames, labels


def _sprite(cid: int, count: int, frames: list, labels: dict) -> SpriteDef:
    count = max(1, count)
    frames = (frames + [()] * count)[:count]
    return SpriteDef(cid, count, tuple(frames), labels)
