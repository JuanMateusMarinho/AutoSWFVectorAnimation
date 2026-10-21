"""Shapes, layers and files the editor tests share (Plan 7)."""
from autoswf.model.geometry import Point
from autoswf.model.shape import LineTo, Path, Shape, SolidFill


def square(x: float, y: float, size: float, fill: int, hole: bool = False) -> Path:
    """A square path, clockwise on screen; filled inside (or, as a hole, filled on its outside)."""
    segments = [LineTo(x + size, y), LineTo(x + size, y + size), LineTo(x, y + size), LineTo(x, y)]
    if hole:
        return Path(Point(x, y), segments, fill_left=fill)
    return Path(Point(x, y), segments, fill_right=fill)


def rect_path(x0: float, y0: float, x1: float, y1: float, fill: int) -> Path:
    return Path(Point(x0, y0), [LineTo(x1, y0), LineTo(x1, y1), LineTo(x0, y1), LineTo(x0, y0)], fill_right=fill)


def rect_area(x0: float, y0: float, x1: float, y1: float):
    """An Area (twips) of the rectangle x0..x1, y0..y1 (px)."""
    from autoswf.edit.regions import TWIPS
    pts = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
    return [[(round(x * TWIPS), round(y * TWIPS)) for x, y in pts]]


def height_at(area, x: float) -> float:
    """The area's vertical extent (px) on the line at x."""
    from autoswf.edit.regions import bounds_px, intersection
    box = bounds_px(intersection(area, rect_area(x - 0.05, -10000, x + 0.05, 10000)))
    return 0.0 if box is None else box[3] - box[2]


BASE, SHADE = (230, 180, 140, 255), (40, 90, 200, 255)


def two_fills() -> Shape:
    """Fill 0 on 0..100 x 0..100 and fill 1 on 100..200 x 0..100, sharing the edge x = 100."""
    shared = Path(Point(100, 0), [LineTo(100, 100)], fill_left=1, fill_right=0)
    left = Path(Point(100, 100), [LineTo(0, 100), LineTo(0, 0), LineTo(100, 0)], fill_right=0)
    right = Path(Point(100, 0), [LineTo(200, 0), LineTo(200, 100), LineTo(100, 100)], fill_right=1)
    return Shape([SolidFill(BASE), SolidFill(SHADE)], [shared, left, right])


def painted_two_fills():
    """two_fills() with fill 1 painted into a notch of fill 0 (60..100 x 20..80): (shape, {0: shrunk, 1: grown})."""
    from autoswf.edit.regions import difference, fill_areas, union
    shape = two_fills()
    areas = fill_areas(shape)
    notch = rect_area(60, 20, 100, 80)
    return shape, {0: difference(areas[0], notch), 1: union(areas[1], notch)}


# ---------------------------------------------------------------- the face with a strip (the user's case, mockup)

FACE = [(160, 10), (292, 32), (296, 135), (270, 163), (264, 176), (240, 215), (190, 268), (180, 272), (165, 268),
        (85, 210), (62, 178), (40, 182), (18, 160), (10, 118), (100, 55)]
STRIP = [(276, 29.33), (292, 32), (296, 135), (270, 163), (264, 176)]      # beyond the correct edge
SHADOW_BOX = (40, 120, 80, 160)
SKIN_RGBA, SHADOW_RGBA, LINE_RGBA = (255, 201, 149, 255), (227, 162, 116, 255), (58, 36, 20, 255)
LINE_WIDTH = 3.0
STRIP_CENTER = (283, 100)
RIGHT_OF_EDGE_BOX = (281, 40, 300, 150)


def _edge(start_late: float = 0.0):
    """Brush samples along the correct edge, (276, 29.3) -> (264, 176), starting `start_late` px below the top
    outline (which it meets almost square)."""
    from autoswf.edit.brush import Sample
    (x0, y0), (x1, y1) = (276, 29.33), (264, 176)
    length = ((x1 - x0) ** 2 + (y1 - y0) ** 2) ** 0.5
    n = int(length // 2)
    out = []
    for k in range(n + 1):
        t = (start_late + k / n * (length - start_late)) / length
        out.append(Sample(x0 + (x1 - x0) * t, y0 + (y1 - y0) * t, 1.0))
    return out


CORRECT_EDGE = _edge()
CORRECT_EDGE_SHORT_BY_2PX = _edge(5.0)        # the cap and the outline's inner half leave a 2 px opening
CORRECT_EDGE_SHORT_BY_8PX = _edge(11.0)


def polygon_area(points):
    from autoswf.edit.regions import TWIPS, union
    return union([[(round(x * TWIPS), round(y * TWIPS)) for x, y in points]], [])


def shape_of(areas: dict, fills) -> Shape:
    from autoswf.edit.regions import rebuild_shape
    return rebuild_shape(Shape([SolidFill(c) for c in fills], []), areas)


def face_with_strip(colored_only: bool = False):
    """An EditLayer: "skin" (base, Skin None), "shadow" (Skin Dark, above it), "line" (a 3 px outline ring)."""
    from autoswf.edit.layer import Drawing, EditLayer, Tone, ToneRef
    from autoswf.edit.regions import difference, offset
    from autoswf.model.geometry import Matrix
    face = polygon_area(FACE)
    ring = difference(offset(face, LINE_WIDTH / 2), offset(face, -LINE_WIDTH / 2))
    drawings = [Drawing("skin", shape_of({0: face}, [SKIN_RGBA]), Matrix(), True),
                Drawing("shadow", shape_of({0: rect_area(*SHADOW_BOX)}, [SHADOW_RGBA]), Matrix(), True)]
    tones = [Tone(ToneRef("skin", 0), SKIN_RGBA, ("Skin", "None")), Tone(ToneRef("shadow", 0), SHADOW_RGBA, ("Skin", "Dark"))]
    line = None
    if not colored_only:
        drawings.append(Drawing("line", shape_of({0: ring}, [LINE_RGBA]), Matrix(), False))
        tones.append(Tone(ToneRef("line", 0), LINE_RGBA, None))
        line = ToneRef("line", 0)
    return EditLayer("Skin", drawings, tones, line, LINE_WIDTH)


def strip_constants():
    """(STRIP_AREA, FACE_AREA): the strip's and the whole face's visible base once the correct edge is brushed."""
    from autoswf.edit.brush import stroke_area
    from autoswf.edit.regions import area_px, difference, offset, union
    face = polygon_area(FACE)
    lines = union(difference(offset(face, LINE_WIDTH / 2), offset(face, -LINE_WIDTH / 2)), stroke_area(CORRECT_EDGE, 3))
    strip = difference(polygon_area(STRIP), lines)
    base = difference(difference(face, rect_area(*SHADOW_BOX)), lines)
    return area_px(strip), area_px(base)


def busy_layer(drawings: int = 4, edges_each: int = 360):
    """A layer of `drawings` wobbly discs of `edges_each` edges each, like an armor piece's drawings."""
    import math
    from autoswf.edit.layer import Drawing, EditLayer, Tone, ToneRef
    from autoswf.model.geometry import Matrix
    out, tones = [], []
    for d in range(drawings):
        r = 120 - 20 * d
        pts = [(150 + (r + 4 * math.sin(9 * k * 2 * math.pi / edges_each)) * math.cos(2 * math.pi * k / edges_each),
                150 + (r + 4 * math.sin(9 * k * 2 * math.pi / edges_each)) * math.sin(2 * math.pi * k / edges_each))
               for k in range(edges_each)]
        color = (40 * d, 100, 200 - 40 * d, 255)
        out.append(Drawing("d%d" % d, shape_of({0: polygon_area(pts)}, [color]), Matrix(), False))
        tones.append(Tone(ToneRef("d%d" % d, 0), color, None))
    return EditLayer("Busy", out, tones, tones[-1].ref, 3.0)


def long_stroke():
    from autoswf.edit.brush import Sample
    return [Sample(20 + k * 1.3, 40 + k * 1.1, 0.5 + 0.5 * ((k % 20) / 20)) for k in range(200)]


# ---------------------------------------------------------------- PNGs from Clip Studio

def _image(width: int, height: int, draw) -> "np.ndarray":
    import numpy as np
    from PIL import Image, ImageDraw
    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw(ImageDraw.Draw(img))
    return np.array(img)


def three_color_disc():
    """A 120 px disc: base, a shadow crescent and a dark 3 px outline, on transparency."""
    def draw(d):
        d.ellipse((10, 10, 110, 110), fill=SKIN_RGBA)
        d.ellipse((50, 20, 105, 100), fill=SHADOW_RGBA)
        d.ellipse((10, 10, 110, 110), outline=LINE_RGBA, width=3)
    return _image(120, 120, draw)


FACE_FIXED = [FACE[0], (276, 29.33), FACE[4]] + FACE[5:]          # the face as it should be: no strip


def face_like_png():
    """The face of face_with_strip() as it should be (no strip), in its own colors at layer coordinates."""
    def draw(d):
        d.polygon(FACE_FIXED, fill=SKIN_RGBA)
        d.rectangle(SHADOW_BOX, fill=SHADOW_RGBA)
        d.line(FACE_FIXED + FACE_FIXED[:1], fill=LINE_RGBA, width=3)
    return _image(320, 290, draw)


def green_patch_png():
    def draw(d):
        d.polygon(FACE, fill=SKIN_RGBA)
        d.rectangle((120, 120, 160, 160), fill=(0, 255, 0, 255))
    return _image(320, 290, draw)


def hair_colored_png():
    return _image(60, 40, lambda d: d.ellipse((5, 5, 55, 35), fill=(112, 58, 31, 255)))


# ---------------------------------------------------------------- SWF look-alikes

HAIR_RGBA = (110, 60, 30, 255)


def _hair_shape(k: int) -> Shape:
    return shape_of({0: polygon_area([(150 + 3 * k, 0), (312, 20), (312, 120), (262, 70), (200, 45)])}, [HAIR_RGBA])


def strip_face_armor(link: str = "StripHero", hair_drawings: int = 1) -> bytes:
    """A male armor whose Head has a "skinLayer" clip (a Skin-colored face with the strip, a Skin Dark shadow and a
    fixed outline ring) and a "hair" clip over it (with `hair_drawings` frames of its own drawings) — a look-alike of
    TheSwordHero's head pieces."""
    from aqw_fakes import _disc, _holder
    from autoswf.abc.movieclip_classes import ClassSpec, build_abc
    from autoswf.edit.regions import difference, offset
    from autoswf.model.document import ColorCustom, Frame, Placement, SetColorScript, Symbol
    from autoswf.swf.movie import build_swf
    face = polygon_area(FACE)
    ring = difference(offset(face, LINE_WIDTH / 2), offset(face, -LINE_WIDTH / 2))
    skin = Symbol("Skin", [Frame([Placement(shape_of({0: face}, [SKIN_RGBA]), 1)])], color_custom=ColorCustom("Skin", "None"))
    shadow = Symbol("Shadow", [Frame([Placement(shape_of({0: rect_area(*SHADOW_BOX)}, [SHADOW_RGBA]), 1)])],
                    color_custom=ColorCustom("Skin", "Dark"))
    skin_layer = Symbol("SkinLayer", [Frame([Placement(skin, 1), Placement(shadow, 2),
                                             Placement(shape_of({0: ring}, [LINE_RGBA]), 3)])])
    hair = Symbol("Hair", [Frame([Placement(_hair_shape(k), 1)]) for k in range(hair_drawings)])
    head = Symbol("Head", [Frame([Placement(skin_layer, 1, name="skinLayer"), Placement(hair, 2, name="hair")])])
    parts = {"Head": head}
    for part in ("Chest", "Hip", "Shoulder", "Hand", "Thigh", "Shin", "Foot", "FootIdle", "Robe", "RobeBack"):
        parts[part] = _holder(part, _disc((90, 110, 140, 255), 6, 9))
    names = {id(s): "%sM%s" % (link, part) for part, s in parts.items()}
    names[id(skin)] = "%s_fla.Skin_1" % link
    names[id(shadow)] = "%s_fla.Shadow_2" % link
    specs = [ClassSpec(n) for n in names.values() if "_fla." not in n]
    specs.append(ClassSpec(names[id(skin)], ((0, SetColorScript("Skin", "None")),)))
    specs.append(ClassSpec(names[id(shadow)], ((0, SetColorScript("Skin", "Dark")),)))
    return build_swf(list(parts.values()), names, build_abc(specs))


def swf_tags(data: bytes) -> list[tuple[int, bytes]]:
    """(code, header + body) of every top-level tag."""
    from autoswf.swf.reader import R, decompress
    import struct
    _, _, _, body = decompress(data)
    r = R(body, 0)
    r.rect()
    r.align()
    pos, out = r.p + 4, []
    while pos < len(body):
        cl = struct.unpack_from("<H", body, pos)[0]
        code, length, size = cl >> 6, cl & 0x3F, 2
        if length == 0x3F:
            length, size = struct.unpack_from("<I", body, pos + 2)[0], 6
        out.append((code, body[pos:pos + size + length]))
        pos += size + length
        if code == 0:
            break
    return out


def changed_tag_indexes(before: bytes, after: bytes) -> list[int]:
    a, b = swf_tags(before), swf_tags(after)
    assert len(a) == len(b)
    return [i for i, (x, y) in enumerate(zip(a, b)) if x != y]


def index_of_shape(data: bytes, cid: int) -> int:
    import struct
    return next(i for i, (code, raw) in enumerate(swf_tags(data))
                if code in (2, 22, 32, 83) and struct.unpack_from("<H", raw, 6 if (struct.unpack_from("<H", raw, 0)[0] & 0x3F) == 0x3F else 2)[0] == cid)


def setcolor_of(abc: bytes, class_name: str):
    """(location, shade) of the class's frame-1 mcSetColor call, read back from the ABC."""
    from autoswf.abc.reader import ABC
    from autoswf.render.scripts import SetColor, class_frame_actions
    action = next(a for a in class_frame_actions([ABC(abc)], class_name).get(0, []) if isinstance(a, SetColor))
    return action.location, action.shade


def part_by_key(structure, key: str):
    return next(p for p in structure.parts if p.key == key)


def depth_is_top(movie, part, piece) -> bool:
    from autoswf.swf.decode import PlaceCommand
    sprite = movie.character(part.char_id)
    depths = [c.depth for frame in sprite.frames for c in frame if isinstance(c, PlaceCommand)]
    return piece.ref.depth == max(depths)


def unchanged_tags_identical(before: bytes, after: bytes, allowed: dict) -> bool:
    """Every tag of `before` is still in `after`, byte for byte and in order, except the DefineSprite tags whose ids are
    in allowed["DefineSprite"]; `after` may hold new tags in between."""
    import struct
    skip = set(allowed.get("DefineSprite", []))
    old = [raw for code, raw in swf_tags(before)
           if not (code == 39 and struct.unpack_from("<H", raw, 6 if (raw[0] & 0x3F) == 0x3F else 2)[0] in skip)]
    new = [raw for _, raw in swf_tags(after)]
    i = 0
    for raw in new:
        if i < len(old) and raw == old[i]:
            i += 1
    return i == len(old)


def edges_in_twips(shape_def) -> list:
    return sorted((e.start, e.control, e.end, e.fill0, e.fill1) for e in shape_def.edges)


def background_pixels_inside(shape: Shape, scale: float) -> int:
    """Background pixels inside the union of the shape's fills, rendered at `scale` (a 1 px rim excluded)."""
    import numpy as np
    from PySide6.QtGui import QImage

    from swf_builders import swf
    from autoswf.edit.regions import bounds_px, fill_areas, offset, union
    from autoswf.model.geometry import Matrix
    from autoswf.render.display import instantiate
    from autoswf.render.painter import Renderer
    from autoswf.swf.decode import MovieData
    from autoswf.swf.shape_encoder import encode_define_shape4
    from autoswf.swf.sprite_encoder import tag

    obj = instantiate(MovieData(swf([tag(83, encode_define_shape4(shape, 1))])), 1)
    total = []
    for a in fill_areas(shape).values():
        total = union(total, a)
    x0, x1, y0, y1 = bounds_px(total)
    w, h = int((x1 - x0) * scale) + 4, int((y1 - y0) * scale) + 4
    view = Matrix.translate(2, 2) @ Matrix.scale(scale, scale) @ Matrix.translate(-x0, -y0)
    img = Renderer().render_image(obj, w, h, view, None).convertToFormat(QImage.Format.Format_RGBA8888)
    alpha = np.frombuffer(bytes(img.constBits()), np.uint8).reshape(h, w, 4)[:, :, 3]
    inner = offset(total, -1.0 / scale)
    count = 0
    for yy in range(h):
        for xx in range(w):
            px, py = (xx + 0.5 - 2) / scale + x0, (yy + 0.5 - 2) / scale + y0
            if alpha[yy, xx] < 250 and _inside(inner, px, py):
                count += 1
    return count


def _inside(area, x: float, y: float) -> bool:
    from autoswf.edit.regions import contains
    return contains(area, x, y)
