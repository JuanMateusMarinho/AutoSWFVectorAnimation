"""Hand-assembled SWF tags for decoder and renderer tests (independent of the production encoders)."""
import struct

from autoswf.model.geometry import Matrix
from autoswf.swf.bits import (BitWriter, bits_for_signed, bits_for_unsigned, twips, write_cxform_alpha, write_matrix,
                              write_rect, write_string)
from autoswf.swf.decode import BlurFilter, ColorMatrixFilter, DropShadowFilter, GlowFilter
from autoswf.swf.sprite_encoder import tag

SHAPE_CODES = {1: 2, 2: 22, 3: 32, 4: 83}


def swf(tags: list[bytes]) -> bytes:
    """A complete FWS file (v15, 24 fps) with one root frame."""
    w = BitWriter()
    write_rect(w, 0, 11000, 0, 8000)
    w.u16(24 * 256); w.u16(1)
    body = w.getvalue() + b"".join(tags) + tag(1) + tag(0)
    return b"FWS" + bytes([15]) + struct.pack("<I", 8 + len(body)) + body


def _color(w: BitWriter, rgba, version: int) -> None:
    w.raw(bytes(rgba[:3]) if version < 3 else bytes(rgba))


def _fill(w: BitWriter, fill, version: int) -> None:
    if fill[0] == "solid":
        w.u8(0x00); _color(w, fill[1], version)
        return
    kind, matrix, stops = fill
    w.u8({"linear": 0x10, "radial": 0x12}[kind])
    write_matrix(w, matrix)
    w.u8(len(stops))
    for ratio, rgba in stops:
        w.u8(ratio); _color(w, rgba, version)


def _styles(w: BitWriter, fills, lines, version: int) -> None:
    w.u8(len(fills))
    for f in fills:
        _fill(w, f, version)
    w.u8(len(lines))
    for width, rgba in lines:
        w.u16(twips(width))
        if version == 4:
            w.u16(0)
        _color(w, rgba, version)


def _points(paths):
    for p in paths:
        yield p["start"]
        for e in p["edges"]:
            yield e[:2]
            if len(e) == 4:
                yield e[2:]


def _bounds(points):
    pts = list(points) or [(0, 0)]
    xs, ys = [twips(x) for x, _ in pts], [twips(y) for _, y in pts]
    return min(xs), max(xs), min(ys), max(ys)


def _edge(w: BitWriter, x: int, y: int, e) -> tuple[int, int]:
    if len(e) == 2:
        nx, ny = twips(e[0]), twips(e[1])
        dx, dy = nx - x, ny - y
        n = max(bits_for_signed(dx, dy), 2)
        w.ub(1, 1); w.ub(1, 1); w.ub(n - 2, 4); w.ub(1, 1); w.sb(dx, n); w.sb(dy, n)
        return nx, ny
    cx, cy, nx, ny = (twips(v) for v in e)
    vals = (cx - x, cy - y, nx - cx, ny - cy)
    n = max(bits_for_signed(*vals), 2)
    w.ub(1, 1); w.ub(0, 1); w.ub(n - 2, 4)
    for v in vals:
        w.sb(v, n)
    return nx, ny


def _records(w: BitWriter, paths, nf: int, nl: int, version: int) -> None:
    w.align(); w.ub(nf, 4); w.ub(nl, 4)
    for p in paths:
        new = p.get("new_styles") if version >= 2 else None
        x, y = twips(p["start"][0]), twips(p["start"][1])
        w.ub(0, 1); w.ub((0x10 if new else 0) | 0x08 | 0x04 | 0x02 | 0x01, 5)
        n = bits_for_signed(x, y)
        w.ub(n, 5); w.sb(x, n); w.sb(y, n)
        w.ub(p.get("fill0", 0), nf); w.ub(p.get("fill1", 0), nf); w.ub(p.get("line", 0), nl)
        if new:
            _styles(w, new[0], new[1], version)
            nf, nl = bits_for_unsigned(len(new[0])), bits_for_unsigned(len(new[1]))
            w.ub(nf, 4); w.ub(nl, 4)
        for e in p["edges"]:
            x, y = _edge(w, x, y, e)
    w.ub(0, 6)
    w.align()


def shape_tag(cid: int, version: int, fills, lines, paths, nonzero: bool = False) -> bytes:
    w = BitWriter()
    w.u16(cid)
    bounds = _bounds(_points(paths))
    write_rect(w, *bounds)
    if version == 4:
        write_rect(w, *bounds); w.u8(0x04 if nonzero else 0)
    _styles(w, fills, lines, version)
    _records(w, paths, bits_for_unsigned(len(fills)), bits_for_unsigned(len(lines)), version)
    return tag(SHAPE_CODES[version], w.getvalue())


def morph_tag(cid: int, start_color, end_color, start, end) -> bytes:
    """DefineMorphShape with one solid fill (on FillStyle1) and straight edges through the given points."""
    def edges(points, fill_bits):
        w = BitWriter()
        _records(w, [{"fill1": 1 if fill_bits else 0, "start": points[0], "edges": points[1:]}], fill_bits, 0, 3)
        return w.getvalue()
    styles = BitWriter()
    styles.u8(1); styles.u8(0x00); styles.raw(bytes(start_color)); styles.raw(bytes(end_color)); styles.u8(0)
    head = styles.getvalue() + edges(start, 1)
    w = BitWriter()
    w.u16(cid); write_rect(w, *_bounds(start)); write_rect(w, *_bounds(end)); w.u32(len(head))
    w.raw(head + edges(end, 0))
    return tag(46, w.getvalue())


def sprite_tag(cid: int, frames: list[list[bytes]]) -> bytes:
    body = struct.pack("<HH", cid, len(frames)) + b"".join(b"".join(f) + tag(1) for f in frames) + tag(0)
    return tag(39, body)


def place2(depth, cid=None, matrix=None, cx=None, name=None, clip_depth=None, ratio=None, move=False) -> bytes:
    w = BitWriter()
    flags = ((0x01 if move else 0) | (0x02 if cid is not None else 0) | (0x04 if matrix is not None else 0)
             | (0x08 if cx is not None else 0) | (0x10 if ratio is not None else 0) | (0x20 if name else 0)
             | (0x40 if clip_depth is not None else 0))
    w.u8(flags); w.u16(depth)
    if cid is not None:
        w.u16(cid)
    if matrix is not None:
        write_matrix(w, matrix)
    if cx is not None:
        write_cxform_alpha(w, cx)
    if ratio is not None:
        w.u16(ratio)
    if name:
        write_string(w, name)
    if clip_depth is not None:
        w.u16(clip_depth)
    return tag(26, w.getvalue())


def _fixed(v: float) -> bytes:
    return struct.pack("<i", round(v * 65536))


def _filter(f) -> bytes:
    if isinstance(f, (bytes, bytearray)):
        return bytes(f)
    if isinstance(f, BlurFilter):
        return b"\x01" + _fixed(f.blur_x) + _fixed(f.blur_y) + bytes([f.passes << 3])
    if isinstance(f, ColorMatrixFilter):
        return b"\x06" + b"".join(struct.pack("<f", v) for v in f.matrix)
    flags = (0x80 if f.inner else 0) | (0x40 if f.knockout else 0) | 0x20 | f.passes
    if isinstance(f, GlowFilter):
        return (b"\x02" + bytes(f.color) + _fixed(f.blur_x) + _fixed(f.blur_y)
                + struct.pack("<H", round(f.strength * 256)) + bytes([flags]))
    if isinstance(f, DropShadowFilter):
        return (b"\x00" + bytes(f.color) + _fixed(f.blur_x) + _fixed(f.blur_y) + _fixed(f.angle) + _fixed(f.distance)
                + struct.pack("<H", round(f.strength * 256)) + bytes([flags]))
    raise TypeError(f)


def place3(depth, cid, filters=(), blend=None, matrix=None) -> bytes:
    flags = 0x02 | (0x04 if matrix is not None else 0)
    flags2 = (0x01 if filters else 0) | (0x02 if blend is not None else 0)
    body = struct.pack("<BBHH", flags, flags2, depth, cid)
    if matrix is not None:
        w = BitWriter(); write_matrix(w, matrix); body += w.getvalue()
    if filters:
        body += bytes([len(filters)]) + b"".join(_filter(f) for f in filters)
    if blend is not None:
        body += bytes([blend])
    return tag(70, body)


def remove2(depth: int) -> bytes:
    return tag(28, struct.pack("<H", depth))


def frame_label(name: str) -> bytes:
    return tag(43, name.encode("utf-8") + b"\0")


def symbol_class(mapping: dict[int, str]) -> bytes:
    return tag(76, struct.pack("<H", len(mapping)) + b"".join(struct.pack("<H", cid) + n.encode() + b"\0"
                                                               for cid, n in mapping.items()))


def doabc_tag(abc: bytes) -> bytes:
    return tag(82, struct.pack("<I", 1) + b"\0" + abc)
