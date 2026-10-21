"""Opened AQW SWFs as edit layers (Plan 7, spec §8.5, §8.7): a piece of an item (a placement, as Plan 6's structure
reads it) at a frame of its own timeline becomes an EditLayer whose drawings are the shapes it shows, in the part's
coordinates, with the AQW color each one takes. An edit changes a drawing (a shape character), so it shows wherever
that drawing shows; `drawing_frames` and `drawing_uses` say where that is."""
import math

import pyclipper

from autoswf.edit.layer import Drawing, EditLayer, Tone, ToneRef
from autoswf.edit.regions import TWIPS, Area, area_px, difference, fill_areas, rebuild_shape, union
from autoswf.items.structure import ItemStructure
from autoswf.model.geometry import Matrix, Point
from autoswf.model.shape import GradientFill, GradientStop, LineTo, Path, QuadTo, Shape, SolidFill
from autoswf.render.colors import PlayerColors, player_color_transform
from autoswf.render.display import ClipInstance, ScriptContext, ShapeInstance, instantiate, run_pending_actions
from autoswf.swf.decode import BitmapStyle, GradientStyle, MorphShapeDef, MovieData, ShapeDef, SolidStyle, parse_shape
from autoswf.swf.shape_encoder import encode_define_shape4

TWEEN = "This piece is a shape tween; editing it is not supported yet."
BITMAP = "This drawing uses a bitmap fill; the editor cannot keep it yet."
GRADIENT = "This drawing uses a gradient the editor cannot keep yet."


class UneditableDrawing(ValueError):
    pass


# ---------------------------------------------------------------- shapes

def _fill(style) -> SolidFill | GradientFill:
    if isinstance(style, SolidStyle):
        return SolidFill(style.color)
    if isinstance(style, BitmapStyle):
        raise UneditableDrawing(BITMAP)
    if isinstance(style, GradientStyle) and style.kind in ("linear", "radial") and not style.spread \
            and not style.interpolation:
        return GradientFill(style.kind, tuple(GradientStop(r, c) for r, c in style.stops), style.matrix)
    raise UneditableDrawing(GRADIENT)


def _px(p: tuple[int, int]) -> tuple[float, float]:
    return p[0] / TWIPS, p[1] / TWIPS


def _flatten(start, control, end) -> list[tuple[int, int]]:
    """An edge in twips as points after its start."""
    if control is None:
        return [end]
    d = math.hypot(start[0] - 2 * control[0] + end[0], start[1] - 2 * control[1] + end[1]) / TWIPS
    n = max(1, math.ceil(math.sqrt(d / (4 * 0.25)))) if d > 0 else 1
    out = []
    for k in range(1, n + 1):
        t = k / n
        u = 1 - t
        out.append((round(u * u * start[0] + 2 * u * t * control[0] + t * t * end[0]),
                    round(u * u * start[1] + 2 * u * t * control[1] + t * t * end[1])))
    return out


def _strokes(shape: ShapeDef) -> dict[int, Area]:
    """Each line style's strokes as a filled area (round joins and caps)."""
    runs: dict[int, list[list[tuple[int, int]]]] = {}
    for e in shape.edges:
        if e.line is None:
            continue
        lines = runs.setdefault(e.line, [])
        if lines and lines[-1][-1] == e.start:
            lines[-1].extend(_flatten(e.start, e.control, e.end))
        else:
            lines.append([e.start] + _flatten(e.start, e.control, e.end))
    out = {}
    for line, polylines in runs.items():
        width = max(shape.lines[line].width * TWIPS, 2.0)
        po = pyclipper.PyclipperOffset()
        po.ArcTolerance = 0.25 * TWIPS
        for pl in polylines:
            if len(pl) >= 2:
                po.AddPath(pl, pyclipper.JT_ROUND, pyclipper.ET_OPENROUND)
        out[line] = union([[(x, y) for x, y in p] for p in po.Execute(width / 2)], [])
    return out


def shape_from_def(shape: ShapeDef) -> Shape:
    """A decoded shape as an editable Shape (fills only): its strokes become filled areas of their color."""
    fills = [_fill(s) for s in shape.fills]
    paths: list[Path] = []
    for e in shape.edges:
        if e.fill0 == e.fill1:
            continue
        seg = LineTo(*_px(e.end)) if e.control is None else QuadTo(*_px(e.control), *_px(e.end))
        last = paths[-1] if paths else None
        if last is not None and (last.fill_left, last.fill_right) == (e.fill0, e.fill1) and \
                (last.segments[-1].x, last.segments[-1].y) == _px(e.start):
            last.segments.append(seg)
        else:
            paths.append(Path(Point(*_px(e.start)), [seg], e.fill0, e.fill1))
    base = Shape(fills, paths)
    strokes = _strokes(shape)
    if not strokes:
        return base
    areas = fill_areas(base)
    covered = union([p for a in strokes.values() for p in a], [])
    areas = {f: cut for f, a in areas.items() if (cut := difference(a, covered))}
    for line, area in strokes.items():
        style = shape.lines[line].fill
        if not isinstance(style, SolidStyle):
            raise UneditableDrawing(GRADIENT)
        fills.append(SolidFill(style.color))
        areas[len(fills) - 1] = area
    return rebuild_shape(base, areas, fills)


def shape_def_of(shape: Shape, char_id: int) -> ShapeDef:
    """The shape exactly as export writes it (DefineShape4), decoded again."""
    return parse_shape(encode_define_shape4(shape, char_id), 0, 4)


# ---------------------------------------------------------------- pieces

def _root(movie: MovieData, char_id: int):
    if char_id == 0:
        clip = ClipInstance(movie, 0, sprite=movie.root)
        clip._reconcile(0)
        return clip
    return instantiate(movie, char_id)


def _target(movie: MovieData, structure: ItemStructure, path: str, frame: int, ctx: ScriptContext):
    """(the piece's display object, the matrix and AQW color above it) with every clip on the way at the frame that
    shows the next piece, and the piece itself at `frame` of its own timeline."""
    part = structure.part_of(path)
    root = _root(movie, part.char_id)
    if root is None:
        raise ValueError("The part %s cannot be shown" % part.label)
    run_pending_actions(root, ctx)
    target, prefix, chain = root, part.key, []
    for comp in path.split("/")[1:]:
        prefix += "/" + comp
        piece = structure.piece(prefix)
        if not isinstance(target, ClipInstance):
            raise ValueError("Piece %s is not in a clip" % path)
        target.driven = True
        target.goto(piece.frame)
        run_pending_actions(root, ctx)
        child = target.child_at_depth(piece.ref.depth)
        if child is None or child.char_id != piece.char_id:
            raise ValueError("Piece %s is not shown" % path)
        chain.append(child)
        target = child
    if isinstance(target, ClipInstance) and target.sprite.frame_count > 1:
        target.driven = True
        target.goto(max(0, min(frame, target.sprite.frame_count - 1)))
        run_pending_actions(root, ctx)
    above, color = Matrix(), None
    for obj in chain[:-1]:
        above = above @ obj.matrix
        color = obj.color_custom or color
    return target, above, color


def _shapes(obj, matrix: Matrix, color, out: list) -> None:
    m = matrix @ obj.matrix
    color = obj.color_custom or color
    if isinstance(obj, ShapeInstance):
        shape = obj.movie.character(obj.char_id)
        if isinstance(shape, MorphShapeDef):
            raise UneditableDrawing(TWEEN)
        out.append((obj.char_id, shape, m, color))
    elif isinstance(obj, ClipInstance) and obj.visible:
        for child in obj.children:
            _shapes(child, m, color, out)


def _perimeter_px(area: Area) -> float:
    return sum(math.hypot(p[i][0] - p[i - 1][0], p[i][1] - p[i - 1][1]) for p in area for i in range(len(p))) / TWIPS


def _luminance(c) -> float:
    return 0.299 * c[0] + 0.587 * c[1] + 0.114 * c[2]


def swf_layer(movie: MovieData, structure: ItemStructure, path: str, frame: int,
              colors: PlayerColors | None = None) -> EditLayer:
    """The piece at `path` as an EditLayer; `frame` is a frame of the piece's own timeline (a clip with several frames),
    ignored otherwise. Drawing keys are the shape's char id ("12"; "12#2" for its second placement in the piece)."""
    colors = colors or PlayerColors()
    target, above, color = _target(movie, structure, path, frame, ScriptContext(colors))
    found: list = []
    _shapes(target, above, color, found)
    drawings, tones, seen = [], [], {}
    for cid, shape_def, m, binding in found:
        seen[cid] = seen.get(cid, 0) + 1
        key = str(cid) if seen[cid] == 1 else "%d#%d" % (cid, seen[cid])
        shape = shape_from_def(shape_def)
        drawings.append(Drawing(key, shape, m, binding is not None))
        for f, fill in enumerate(shape.fills):
            if binding is not None:
                ct = player_color_transform(binding[0], binding[1], colors)
                shown = tuple(max(0, min(255, int(v))) for v in ct.add[:3]) + (255,)
            elif isinstance(fill, SolidFill):
                shown = fill.color
            else:
                shown = fill.stops[0].color
            tones.append(Tone(ToneRef(key, f), shown, binding))
    layer = EditLayer(path, drawings, tones, None, 1.0)
    visible = layer.visible_areas()
    shown = [t for t in tones if t.ref in visible]
    if shown:
        line = min(shown, key=lambda t: _luminance(t.color))
        area = visible[line.ref]
        width = 2 * area_px(area) / max(_perimeter_px(area), 1e-6)
        layer = EditLayer(path, drawings, tones, line.ref, max(1.0, width))
    return layer


def drawing_frames(movie: MovieData, structure: ItemStructure, path: str, char_id: int) -> list[int]:
    """0-based frames of the piece's own timeline that show the drawing (frame 0 for a piece without one)."""
    ctx = ScriptContext(PlayerColors())
    target, _, _ = _target(movie, structure, path, 0, ctx)
    count = target.sprite.frame_count if isinstance(target, ClipInstance) else 1
    out = []
    for f in range(count):
        if f:
            target, _, _ = _target(movie, structure, path, f, ctx)
        found: list = []
        try:
            _shapes(target, Matrix(), None, found)
        except UneditableDrawing:
            pass
        if any(cid == char_id for cid, _, _, _ in found):
            out.append(f)
    return out


def drawing_uses(movie: MovieData, structure: ItemStructure, path: str, char_id: int) -> list[str]:
    """Other pieces that show the drawing (outside the piece at `path`)."""
    return [p.path for p in structure.walk() if p.kind == "shape" and p.char_id == char_id
            and p.path != path and not p.path.startswith(path + "/")]
