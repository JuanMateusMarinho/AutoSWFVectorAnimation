"""Shape -> DefineShape4 tag body; MorphShape -> DefineMorphShape tag body."""
from autoswf.model.shape import GradientFill, LineTo, MorphShape, Shape, SolidFill, same_structure
from autoswf.swf.bits import BitWriter, bits_for_signed, bits_for_unsigned, twips, write_matrix, write_rect, write_rgba

MAX_EDGE_BITS = 17     # NumBits field is 4 bits and stores n - 2


def _to_twips(shape: Shape):
    """Paths as (fill_left, fill_right, start, [("L", x, y) | ("Q", cx, cy, x, y)]) in absolute twips."""
    out = []
    for p in shape.paths:
        segs = []
        for s in p.segments:
            if isinstance(s, LineTo):
                segs.append(("L", twips(s.x), twips(s.y)))
            else:
                segs.append(("Q", twips(s.cx), twips(s.cy), twips(s.x), twips(s.y)))
        out.append((p.fill_left, p.fill_right, (twips(p.start.x), twips(p.start.y)), segs))
    return out


def _bounds(paths):
    xs, ys = [], []
    for _, _, (sx, sy), segs in paths:
        xs.append(sx); ys.append(sy)
        for s in segs:
            xs += s[1::2]; ys += s[2::2]
    if not xs:
        return 0, 0, 0, 0
    return min(xs), max(xs), min(ys), max(ys)


def _write_fill(w: BitWriter, fill) -> None:
    if isinstance(fill, SolidFill):
        w.u8(0x00)
        write_rgba(w, fill.color)
    elif isinstance(fill, GradientFill):
        if not 1 <= len(fill.stops) <= 15:
            raise ValueError("A gradient needs 1 to 15 color stops")
        w.u8(0x10 if fill.kind == "linear" else 0x12)
        write_matrix(w, fill.matrix)
        w.ub(0, 2); w.ub(0, 2); w.ub(len(fill.stops), 4)
        for stop in fill.stops:
            w.u8(stop.ratio)
            write_rgba(w, stop.color)
    else:
        raise TypeError("unsupported fill %r" % (fill,))


class _TooLong(Exception):
    pass


def _write_line(w: BitWriter, x0, y0, x1, y1, split: bool = True) -> None:
    dx, dy = x1 - x0, y1 - y0
    if dx == 0 and dy == 0 and split:
        return                   # a morph keeps its zero-length edges: start and end need the same records
    n = max(bits_for_signed(dx, dy), 2)
    if n > MAX_EDGE_BITS:
        if not split:
            raise _TooLong
        mx, my = round((x0 + x1) / 2), round((y0 + y1) / 2)
        _write_line(w, x0, y0, mx, my)
        _write_line(w, mx, my, x1, y1)
        return
    w.ub(1, 1); w.ub(1, 1); w.ub(n - 2, 4)
    if dx != 0 and dy != 0:
        w.ub(1, 1); w.sb(dx, n); w.sb(dy, n)
    elif dx == 0:
        w.ub(0, 1); w.ub(1, 1); w.sb(dy, n)
    else:
        w.ub(0, 1); w.ub(0, 1); w.sb(dx, n)


def _write_quad(w: BitWriter, x0, y0, cx, cy, x1, y1, split: bool = True) -> None:
    deltas = (cx - x0, cy - y0, x1 - cx, y1 - cy)
    n = max(bits_for_signed(*deltas), 2)
    if n > MAX_EDGE_BITS:
        if not split:
            raise _TooLong
        qx0, qy0 = (x0 + cx) / 2, (y0 + cy) / 2
        qx1, qy1 = (cx + x1) / 2, (cy + y1) / 2
        mx, my = round((qx0 + qx1) / 2), round((qy0 + qy1) / 2)
        _write_quad(w, x0, y0, round(qx0), round(qy0), mx, my)
        _write_quad(w, mx, my, round(qx1), round(qy1), x1, y1)
        return
    w.ub(1, 1); w.ub(0, 1); w.ub(n - 2, 4)
    for v in deltas:
        w.sb(v, n)


def _write_records(w: BitWriter, paths, fill_bits: int, styles: bool = True, split: bool = True) -> None:
    """Shape records: per path a style change (move-to, plus both fills unless `styles` is off), then its edges."""
    for fill_left, fill_right, (sx, sy), segs in paths:
        w.ub(0, 1)               # style change record
        w.ub(0b00111 if styles else 0b00001, 5)          # fill1, fill0, moveTo (moveTo only in a morph's end)
        n = bits_for_signed(sx, sy)
        w.ub(n, 5); w.sb(sx, n); w.sb(sy, n)
        if styles:
            w.ub(0 if fill_left is None else fill_left + 1, fill_bits)
            w.ub(0 if fill_right is None else fill_right + 1, fill_bits)
        x, y = sx, sy
        for s in segs:
            if s[0] == "L":
                _write_line(w, x, y, s[1], s[2], split); x, y = s[1], s[2]
            else:
                _write_quad(w, x, y, s[1], s[2], s[3], s[4], split); x, y = s[3], s[4]
    w.ub(0, 6)                   # end shape record


def _write_count(w: BitWriter, count: int) -> None:
    if count >= 0xFF:
        w.u8(0xFF); w.u16(count)
    else:
        w.u8(count)


def encode_define_shape4(shape: Shape, char_id: int) -> bytes:
    paths = _to_twips(shape)
    w = BitWriter()
    w.u16(char_id)
    bounds = _bounds(paths)
    write_rect(w, *bounds)       # ShapeBounds
    write_rect(w, *bounds)       # EdgeBounds
    w.u8(0x00)                   # no winding rule, no strokes
    count = len(shape.fills)
    _write_count(w, count)
    for fill in shape.fills:
        _write_fill(w, fill)
    w.u8(0)                      # no line styles
    fill_bits = bits_for_unsigned(count)
    w.ub(fill_bits, 4); w.ub(0, 4)
    _write_records(w, paths, fill_bits)
    return w.getvalue()


def _write_morph_fill(w: BitWriter, start, end) -> None:
    if isinstance(start, SolidFill):
        w.u8(0x00)
        write_rgba(w, start.color)
        write_rgba(w, end.color)
        return
    if not 1 <= len(start.stops) <= 15:
        raise ValueError("A gradient needs 1 to 15 color stops")
    w.u8(0x10 if start.kind == "linear" else 0x12)
    write_matrix(w, start.matrix)
    write_matrix(w, end.matrix)
    w.u8(len(start.stops))
    for a, b in zip(start.stops, end.stops):
        w.u8(a.ratio); write_rgba(w, a.color)
        w.u8(b.ratio); write_rgba(w, b.color)


def encode_define_morph_shape(morph: MorphShape, char_id: int) -> bytes:
    """DefineMorphShape (tag 46): the start edges carry the fills, the end edges only their move-to points."""
    if not same_structure(morph.start, morph.end):
        raise ValueError("A morph shape's start and end must have the same fills, paths and segment kinds")
    start, end = _to_twips(morph.start), _to_twips(morph.end)
    head = BitWriter()
    head.u16(char_id)
    write_rect(head, *_bounds(start))
    write_rect(head, *_bounds(end))
    body = BitWriter()
    count = len(morph.start.fills)
    _write_count(body, count)
    for a, b in zip(morph.start.fills, morph.end.fills):
        _write_morph_fill(body, a, b)
    body.u8(0)                   # no line styles
    fill_bits = bits_for_unsigned(count)
    body.ub(fill_bits, 4); body.ub(0, 4)
    tail = BitWriter()
    tail.ub(0, 4); tail.ub(0, 4)
    try:
        _write_records(body, start, fill_bits, split=False)
        _write_records(tail, end, 0, styles=False, split=False)
    except _TooLong:
        raise ValueError("A morph shape edge is too long to encode") from None
    first = body.getvalue()
    head.u32(len(first))         # offset from here to EndEdges
    return head.getvalue() + first + tail.getvalue()
