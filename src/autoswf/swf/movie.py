"""Assemble a complete AS3 SWF file (CWS) from symbols, class names and ABC bytecode."""
import struct
import zlib

from autoswf.model.document import Symbol
from autoswf.model.shape import MorphShape, Shape
from autoswf.swf.bits import BitWriter, twips, write_eu32, write_rect, write_string
from autoswf.swf.shape_encoder import encode_define_morph_shape, encode_define_shape4
from autoswf.swf.sprite_encoder import encode_define_sprite, tag

SWF_VERSION = 15
FILE_ATTRIBUTES_AS3 = 0x08
BACKGROUND = (0x66, 0x66, 0x66)
TAG_SHOW_FRAME, TAG_END, TAG_SET_BACKGROUND, TAG_SPRITE, TAG_MORPH = 1, 0, 9, 39, 46
TAG_FILE_ATTRIBUTES, TAG_SYMBOL_CLASS, TAG_DO_ABC, TAG_SHAPE4, TAG_SCENES = 69, 76, 82, 83, 86


def _characters(symbols: list[Symbol]) -> list[Shape | MorphShape | Symbol]:
    """Every shape and symbol reachable from `symbols`, children before parents, each once."""
    order, seen = [], set()

    def visit(item):
        if id(item) in seen:
            return
        seen.add(id(item))
        if isinstance(item, Symbol):
            for frame in item.frames:
                for p in frame.placements:
                    visit(p.item)
        order.append(item)

    for s in symbols:
        visit(s)
    return order


def swf_file(tags: bytes, *, width: float, height: float, fps: float) -> bytes:
    """A one-frame AS3 SWF (CWS): header, FileAttributes and background, then `tags` (which end with ShowFrame, End)."""
    w = BitWriter()
    write_rect(w, 0, twips(width), 0, twips(height))
    w.u16(round(fps * 256))
    w.u16(1)
    body = bytearray(w.getvalue())
    body += tag(TAG_FILE_ATTRIBUTES, struct.pack("<I", FILE_ATTRIBUTES_AS3))
    body += tag(TAG_SET_BACKGROUND, bytes(BACKGROUND))
    body += tags
    return b"CWS" + bytes([SWF_VERSION]) + struct.pack("<I", 8 + len(body)) + zlib.compress(bytes(body), 9)


def build_swf(symbols: list[Symbol], class_names: dict[int, str], abc: bytes, *,
              width: float = 550, height: float = 400, fps: float = 24.0) -> bytes:
    chars = _characters(symbols)
    char_ids = {id(item): n for n, item in enumerate(chars, start=1)}

    body = bytearray()
    scenes = BitWriter()
    write_eu32(scenes, 1); write_eu32(scenes, 0); write_string(scenes, "Scene 1"); write_eu32(scenes, 0)
    body += tag(TAG_SCENES, scenes.getvalue())
    body += tag(TAG_DO_ABC, struct.pack("<I", 1) + b"\0" + abc)
    for item in chars:
        if isinstance(item, Shape):
            body += tag(TAG_SHAPE4, encode_define_shape4(item, char_ids[id(item)]))
        elif isinstance(item, MorphShape):
            body += tag(TAG_MORPH, encode_define_morph_shape(item, char_ids[id(item)]))
        else:
            body += tag(TAG_SPRITE, encode_define_sprite(item, char_ids))
    exported = [(char_ids[id(item)], class_names[id(item)]) for item in chars if id(item) in class_names]
    sc = BitWriter()
    sc.u16(len(exported))
    for char_id, name in exported:
        sc.u16(char_id)
        write_string(sc, name)
    body += tag(TAG_SYMBOL_CLASS, sc.getvalue())
    body += tag(TAG_SHOW_FRAME) + tag(TAG_END)
    return swf_file(bytes(body), width=width, height=height, fps=fps)
