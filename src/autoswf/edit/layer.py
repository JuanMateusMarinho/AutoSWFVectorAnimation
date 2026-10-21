"""An edit layer (Plan 7, spec §8.1-8.5): one element's drawings, bottom to top, and the colors they are made of
(tones), with the editor's operations — Magic Wand, paint, erase, delete and transform — done in vector. Every
operation returns a LayerEdit with the new shapes of the drawings it changed (in each drawing's own px); `applied`
gives the layer after it."""
from dataclasses import dataclass, field, replace

from autoswf.edit.regions import (Area, area_px, components, contains, difference, fill_areas, intersection, offset,
                                  rebuild_shape, transform_area, union)
from autoswf.model.geometry import Matrix, Point
from autoswf.model.shape import GradientFill, LineTo, Path, QuadTo, Shape, SolidFill

RGBA = tuple[int, int, int, int]
CLOSE_GAP_PX = 3.0
CHANGE_PX2 = 0.01                  # less than this (px²) is no change
REGROW_PX = 1.0                    # the Magic Wand's area grows back this much past its gap-closing shrink
SLIVER_PX = 0.5                    # kept areas thinner than twice this hold no line back
NEW_FIXED_COLOR = "New color %s is a fixed color: it does not follow AQW colors."
ONLY_COLORED = "This layer has only AQW-colored drawings; pick one of its colors."


@dataclass(frozen=True)
class ToneRef:
    drawing: str
    fill: int


@dataclass(frozen=True)
class Tone:
    ref: ToneRef
    color: RGBA                                    # as shown (the player color when bound)
    binding: tuple[str, str] | None                # (location, shade) of AQW color custom, None = fixed color


@dataclass
class Drawing:
    key: str
    shape: Shape
    matrix: Matrix                                 # drawing px -> layer px
    colorable: bool                                # inside an AQW-colored clip: the whole drawing takes one tint


@dataclass(frozen=True)
class Selection:
    area: Area
    lines: Area                                    # lines that go with the area (they would be left floating)

    def combined(self, other: "Selection", subtract: bool = False) -> "Selection":
        if subtract:
            gone = union(other.area, other.lines)
            return Selection(difference(self.area, gone), difference(self.lines, gone))
        return Selection(union(self.area, other.area), union(self.lines, other.lines))


@dataclass
class LayerEdit:
    shapes: dict[str, Shape] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    @property
    def empty(self) -> bool:
        return not self.shapes


def _hex(color: RGBA) -> str:
    return "#%02X%02X%02X" % color[:3]


def _moved(shape: Shape, m: Matrix) -> Shape:
    """The shape with every point, control point and gradient mapped exactly by m."""
    def pt(x, y):
        p = m.apply(Point(x, y))
        return p.x, p.y
    fills = [replace(f, matrix=m @ f.matrix) if isinstance(f, GradientFill) else f for f in shape.fills]
    flip = m.a * m.d - m.b * m.c < 0
    paths = []
    for p in shape.paths:
        segs = []
        for s in p.segments:
            if isinstance(s, QuadTo):
                segs.append(QuadTo(*pt(s.cx, s.cy), *pt(s.x, s.y)))
            else:
                segs.append(LineTo(*pt(s.x, s.y)))
        left, right = (p.fill_right, p.fill_left) if flip else (p.fill_left, p.fill_right)
        paths.append(Path(Point(*pt(p.start.x, p.start.y)), segs, left, right))
    return Shape(fills, paths)


def _identity(m: Matrix) -> bool:
    return m == Matrix()


@dataclass(eq=False)
class EditLayer:
    name: str
    drawings: list[Drawing]
    tones: list[Tone]
    line_tone: ToneRef | None
    line_width: float
    _cache: dict = field(default_factory=dict, repr=False)

    # ------------------------------------------------------------ reading

    def _local(self, d: Drawing, area: Area) -> Area:
        return area if _identity(d.matrix) else transform_area(area, d.matrix.inverse())

    def _drawing_areas(self, d: Drawing) -> dict[int, Area]:
        key = ("own", d.key)
        if key not in self._cache:
            self._cache[key] = fill_areas(d.shape)
        return self._cache[key]

    def _layer_areas(self, d: Drawing) -> dict[int, Area]:
        key = ("layer", d.key)
        if key not in self._cache:
            own = self._drawing_areas(d)
            self._cache[key] = own if _identity(d.matrix) else {f: transform_area(a, d.matrix) for f, a in own.items()}
        return self._cache[key]

    def visible_areas(self) -> dict[ToneRef, Area]:
        if "visible" not in self._cache:
            out, above = {}, []
            for d in reversed(self.drawings):
                areas = self._layer_areas(d)
                for f, a in areas.items():
                    seen = difference(a, above) if above else a
                    if seen:
                        out[ToneRef(d.key, f)] = seen
                above = union(above, [p for a in areas.values() for p in a])
            self._cache["visible"] = out
        return self._cache["visible"]

    def tone_at(self, x: float, y: float) -> ToneRef | None:
        return next((ref for ref, a in self.visible_areas().items() if contains(a, x, y)), None)

    def _tone(self, ref: ToneRef) -> Tone | None:
        return next((t for t in self.tones if t.ref == ref), None)

    def _index(self, key: str) -> int:
        return next(i for i, d in enumerate(self.drawings) if d.key == key)

    # ------------------------------------------------------------ Magic Wand

    def wand(self, x: float, y: float, *, close_gap: float = CLOSE_GAP_PX) -> Selection | None:
        ref = self.tone_at(x, y)
        if ref is None:
            return None
        visible = self.visible_areas()
        tone_area = visible[ref]
        others = [p for r, a in visible.items() if r != ref for p in a]
        part = None
        if close_gap > 0 and others:
            free = difference(tone_area, offset(others, close_gap / 2))
            part = next((c for c in components(free) if contains(c, x, y)), None)
            if part is not None:
                # grown back a little past the shrink, so no sliver of the area stays behind along the lines
                part = intersection(offset(part, close_gap / 2 + REGROW_PX), tone_area)
        if part is None:
            part = next((c for c in components(tone_area) if contains(c, x, y)), tone_area)
        lines: Area = []
        if self.line_tone is not None and ref != self.line_tone and self.line_tone in visible:
            kept = difference([p for r, a in visible.items() if r != self.line_tone for p in a], part)
            kept = offset(offset(kept, -SLIVER_PX), SLIVER_PX)          # slivers keep no line
            near = intersection(visible[self.line_tone], offset(part, self.line_width + close_gap))
            lines = difference(near, offset(kept, self.line_width + 1)) if kept else near
        return Selection(part, lines)

    # ------------------------------------------------------------ edits

    def _changed(self, before: dict[int, Area], after: dict[int, Area]) -> bool:
        for f in set(before) | set(after):
            a, b = before.get(f, []), after.get(f, [])
            if area_px(difference(a, b)) > CHANGE_PX2 or area_px(difference(b, a)) > CHANGE_PX2:
                return True
        return False

    def _cut(self, d: Drawing, area: Area, areas: dict[int, Area] | None = None) -> dict[int, Area]:
        local = self._local(d, area)
        own = self._drawing_areas(d) if areas is None else areas
        return {f: cut for f, a in own.items() if (cut := difference(a, local))}

    def erase(self, area: Area) -> LayerEdit:
        edit = LayerEdit()
        if not area:
            return edit
        for d in self.drawings:
            before = self._drawing_areas(d)
            after = self._cut(d, area)
            if self._changed(before, after):
                edit.shapes[d.key] = rebuild_shape(d.shape, after)
        return edit

    def delete(self, selection: Selection) -> LayerEdit:
        return self.erase(union(selection.area, selection.lines))

    def paint(self, area: Area, color: "ToneRef | RGBA") -> LayerEdit:
        if not area:
            return LayerEdit()
        notes = []
        fills = None
        if isinstance(color, ToneRef):
            ref = color
        else:
            known = next((t.ref for t in self.tones if t.color == tuple(color)), None)
            if known is not None:
                ref = known
            else:
                target = next((d for d in reversed(self.drawings) if not d.colorable), None)
                if target is None:
                    return LayerEdit({}, [ONLY_COLORED])
                fills = list(target.shape.fills) + [SolidFill(tuple(color))]
                ref = ToneRef(target.key, len(fills) - 1)
                notes.append(NEW_FIXED_COLOR % _hex(tuple(color)))
        at = self._index(ref.drawing)
        edit = LayerEdit({}, notes)
        d = self.drawings[at]
        local = self._local(d, area)
        before = self._drawing_areas(d)
        after = {f: cut for f, a in before.items() if f != ref.fill and (cut := difference(a, local))}
        after[ref.fill] = union(before.get(ref.fill, []), local)
        if self._changed(before, after):
            edit.shapes[d.key] = rebuild_shape(d.shape, after, fills)
        for above in self.drawings[at + 1:]:
            mine = self._drawing_areas(above)
            cut = self._cut(above, area)
            if self._changed(mine, cut):
                edit.shapes[above.key] = rebuild_shape(above.shape, cut)
        if edit.empty:
            edit.notes = []
        return edit

    def transform(self, selection: Selection | None, matrix: Matrix) -> LayerEdit:
        if selection is None:
            edit = LayerEdit()
            for d in self.drawings:
                local = d.matrix.inverse() @ matrix @ d.matrix
                edit.shapes[d.key] = _moved(d.shape, local)
            return edit
        chosen = union(selection.area, selection.lines)
        pieces = []
        for d in self.drawings:
            for f, a in self._layer_areas(d).items():
                piece = intersection(a, chosen)
                if piece:
                    pieces.append((ToneRef(d.key, f), transform_area(piece, matrix)))
        work = self.applied(self.erase(chosen))
        for ref, moved in pieces:
            work = work.applied(work.paint(moved, ref))
        return LayerEdit({d.key: d.shape for d, old in zip(work.drawings, self.drawings) if d.shape is not old.shape})

    # ------------------------------------------------------------ after an edit

    def applied(self, edit: LayerEdit) -> "EditLayer":
        if edit.empty:
            return self
        drawings = [replace(d, shape=edit.shapes.get(d.key, d.shape)) for d in self.drawings]
        tones = list(self.tones)
        known = {t.ref for t in tones}
        for d in drawings:
            for f, fill in enumerate(d.shape.fills):
                if ToneRef(d.key, f) not in known and isinstance(fill, SolidFill):
                    tones.append(Tone(ToneRef(d.key, f), fill.color, None))
        return EditLayer(self.name, drawings, tones, self.line_tone, self.line_width)
