"""Symbol timeline -> DefineSprite tag body (PlaceObject2 / RemoveObject2 diffs per frame)."""
import struct

from autoswf.model.document import Frame, Symbol
from autoswf.model.geometry import ColorTransform
from autoswf.swf.bits import BitWriter, write_cxform_alpha, write_matrix, write_string

SHOW_FRAME, PLACE_OBJECT2, REMOVE_OBJECT2, FRAME_LABEL, END = 1, 26, 28, 43, 0


def tag(code: int, body: bytes = b"") -> bytes:
    if len(body) < 0x3F:
        return struct.pack("<H", (code << 6) | len(body)) + body
    return struct.pack("<HI", (code << 6) | 0x3F, len(body)) + body


def _place(depth, char_id=None, matrix=None, color=None, name=None, move=False) -> bytes:
    w = BitWriter()
    w.u8((0x20 if name else 0) | (0x08 if color is not None else 0) | (0x04 if matrix is not None else 0)
         | (0x02 if char_id is not None else 0) | (0x01 if move else 0))
    w.u16(depth)
    if char_id is not None:
        w.u16(char_id)
    if matrix is not None:
        write_matrix(w, matrix)
    if color is not None:
        write_cxform_alpha(w, color)
    if name:
        write_string(w, name)
    return tag(PLACE_OBJECT2, w.getvalue())


def _move(depth, old, p) -> bytes:
    """Same item at the same depth: write only what changed (a cleared color becomes the identity)."""
    matrix = p.matrix if p.matrix != old.matrix else None
    color = None
    if p.color != old.color:
        color = p.color if p.color is not None else ColorTransform()
    if matrix is None and color is None:
        return b""
    return _place(depth, matrix=matrix, color=color, move=True)


def encode_define_sprite(symbol: Symbol, char_ids: dict[int, int]) -> bytes:
    frames = symbol.frames or [Frame()]
    out = bytearray(struct.pack("<HH", char_ids[id(symbol)], len(frames)))
    prev = {}
    for frame in frames:
        cur = {p.depth: p for p in frame.placements}
        for depth in sorted(set(prev) - set(cur)):
            out += tag(REMOVE_OBJECT2, struct.pack("<H", depth))
        for depth in sorted(cur):
            p, old = cur[depth], prev.get(depth)
            if old is None:
                out += _place(depth, char_ids[id(p.item)], p.matrix, p.color, p.name)
            elif isinstance(old.item, Symbol) or isinstance(p.item, Symbol):
                if old.item is not p.item:
                    # Players only swap the innards of shapes in place; clips must be removed and placed fresh
                    # so the new clip's class and frame scripts run.
                    out += tag(REMOVE_OBJECT2, struct.pack("<H", depth))
                    out += _place(depth, char_ids[id(p.item)], p.matrix, p.color, p.name)
                else:
                    out += _move(depth, old, p)
            elif old.item is not p.item:
                color = p.color if p.color is not None else (ColorTransform() if old.color is not None else None)
                out += _place(depth, char_ids[id(p.item)], p.matrix, color, move=True)
            else:
                out += _move(depth, old, p)
        if frame.label:
            w = BitWriter(); write_string(w, frame.label)
            out += tag(FRAME_LABEL, w.getvalue())
        out += tag(SHOW_FRAME)
        prev = cur
    out += tag(END)
    return bytes(out)
