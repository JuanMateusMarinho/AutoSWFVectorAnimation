"""New layers in an opened item SWF (Plan 7, spec §8.8 "New layer"): a layer is a new clip placed on top of a part,
holding one drawing per tone; a tone that follows an AQW color sits in its own clip whose class runs the official
frame-1 mcSetColor script, so the game tints it like any colorable clip."""
import struct
from dataclasses import dataclass

from autoswf.abc.movieclip_classes import ClassSpec
from autoswf.model.document import SetColorScript
from autoswf.model.shape import Shape
from autoswf.swf.shape_encoder import encode_define_shape4
from autoswf.swf.sprite_encoder import tag

PREFIX = "AutoSWFLayer"


@dataclass
class NewLayer:
    part_char: int                                           # the part's sprite (0 = the root timeline)
    name: str
    tones: list[tuple[Shape, tuple[str, str] | None]]        # drawing, and its (location, shade) or None (fixed)


def place(depth: int, char_id: int) -> bytes:
    """PlaceObject2 of a character at a depth, no transform."""
    return tag(26, struct.pack("<BHH", 0x02, depth, char_id))


def _sprite(char_id: int, children: list[int]) -> bytes:
    body = struct.pack("<HH", char_id, 1) + b"".join(place(d + 1, c) for d, c in enumerate(children)) + tag(1) + tag(0)
    return tag(39, body)


def free_number(names, package: str) -> int:
    """The first k with no class named <package>_fla.AutoSWFLayer<k>_…"""
    k = 1
    while any(n.startswith("%s_fla.%s%d_" % (package, PREFIX, k)) for n in names):
        k += 1
    return k


def layer_tags(layer: NewLayer, first_id: int, package: str, number: int):
    """(definition tags, class specs, {char id: class name}, the layer's sprite id, the next free id)."""
    tags, specs, symbols, children = [], [], {}, []
    nid = first_id
    for shape, binding in layer.tones:
        shape_id = nid
        nid += 1
        tags.append(tag(83, encode_define_shape4(shape, shape_id)))
        if binding is None:
            children.append(shape_id)
            continue
        clip_id = nid
        nid += 1
        tags.append(_sprite(clip_id, [shape_id]))
        base = "%s_fla.%s%d_%s%s" % (package, PREFIX, number, binding[0], binding[1])
        name, n = base, 2
        while name in symbols.values():
            name, n = "%s_%d" % (base, n), n + 1
        specs.append(ClassSpec(name, ((0, SetColorScript(*binding)),)))
        symbols[clip_id] = name
        children.append(clip_id)
    layer_id = nid
    tags.append(_sprite(layer_id, children))
    return tags, specs, symbols, layer_id, nid + 1
