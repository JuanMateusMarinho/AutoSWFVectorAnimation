"""Hand edits of a helm project's art (Plan 7, spec §8.6): the edited shapes of traced layers, kept over rebuilds, and
extra layers drawn by hand or traced from a PNG. Saved in the project's settings as JSON."""
from dataclasses import dataclass, field, replace

from autoswf.model.geometry import Matrix, Point
from autoswf.model.shape import GradientFill, GradientStop, LineTo, Path, QuadTo, Shape, SolidFill
from autoswf.vectorize.art import FaceStyle, VectorArt

EDIT_GONE = "Your edit of %s no longer applies: that part is gone."


def _hex(color) -> str:
    return "#%02X%02X%02X%02X" % tuple(color)


def _color(text: str) -> tuple[int, int, int, int]:
    if not isinstance(text, str) or len(text) != 9 or not text.startswith("#"):
        raise ValueError("a color must be written #RRGGBBAA (got %r)" % (text,))
    return tuple(int(text[i:i + 2], 16) for i in (1, 3, 5, 7))


def shape_to_json(shape: Shape) -> dict:
    fills = []
    for f in shape.fills:
        if isinstance(f, SolidFill):
            fills.append({"solid": _hex(f.color)})
        else:
            m = f.matrix
            fills.append({"kind": f.kind, "stops": [[s.ratio, _hex(s.color)] for s in f.stops],
                          "matrix": [m.a, m.b, m.c, m.d, m.tx, m.ty]})
    paths = []
    for p in shape.paths:
        segs = [["L", s.x, s.y] if isinstance(s, LineTo) else ["Q", s.cx, s.cy, s.x, s.y] for s in p.segments]
        paths.append({"start": [p.start.x, p.start.y], "segments": segs, "left": p.fill_left, "right": p.fill_right})
    return {"fills": fills, "paths": paths}


def shape_from_json(data: dict) -> Shape:
    if not isinstance(data, dict):
        raise ValueError("a shape must be a JSON object")
    fills = []
    for f in data.get("fills", []):
        if "solid" in f:
            fills.append(SolidFill(_color(f["solid"])))
        else:
            fills.append(GradientFill(f["kind"], tuple(GradientStop(int(r), _color(c)) for r, c in f["stops"]),
                                      Matrix(*[float(v) for v in f["matrix"]])))
    paths = []
    for p in data.get("paths", []):
        segs = [LineTo(float(s[1]), float(s[2])) if s[0] == "L" else QuadTo(*[float(v) for v in s[1:5]])
                for s in p["segments"]]
        paths.append(Path(Point(float(p["start"][0]), float(p["start"][1])), segs, p.get("left"), p.get("right")))
    return Shape(fills, paths)


@dataclass
class ExtraLayer:
    name: str
    tones: list[tuple[Shape, str | None, str]] = field(default_factory=list)   # shape, location (None: fixed), shade

    def to_dict(self) -> dict:
        return {"name": self.name, "tones": [{"shape": shape_to_json(s), "location": loc, "shade": shade}
                                             for s, loc, shade in self.tones]}

    @classmethod
    def from_dict(cls, data: dict) -> "ExtraLayer":
        return cls(str(data["name"]), [(shape_from_json(t["shape"]), t.get("location"), t.get("shade", "None"))
                                       for t in data.get("tones", [])])


@dataclass
class ArtEdits:
    shapes: dict[str, Shape] = field(default_factory=dict)        # "<part>/<traced layer name>" -> edited shape
    extras: list[ExtraLayer] = field(default_factory=list)

    def set_shape(self, part: str, traced: str, shape: Shape) -> None:
        self.shapes["%s/%s" % (part, traced)] = shape

    def parts(self) -> set[str]:
        return {key.split("/", 1)[0] for key in self.shapes}

    def without_parts(self, parts) -> "ArtEdits":
        gone = set(parts)
        return ArtEdits({k: v for k, v in self.shapes.items() if k.split("/", 1)[0] not in gone}, list(self.extras))

    def to_dict(self) -> dict:
        return {"shapes": {k: shape_to_json(v) for k, v in self.shapes.items()},
                "extras": [e.to_dict() for e in self.extras]}

    @classmethod
    def from_dict(cls, data, source: str = "edits") -> "ArtEdits":
        if not isinstance(data, dict):
            raise ValueError("%s must be a JSON object" % source)
        try:
            shapes = {str(k): shape_from_json(v) for k, v in data.get("shapes", {}).items()}
            extras = [ExtraLayer.from_dict(e) for e in data.get("extras", [])]
        except (KeyError, TypeError, IndexError) as e:
            raise ValueError("%s: a shape or layer is incomplete (%s)" % (source, e)) from None
        return cls(shapes, extras)


STYLE_MATCH = 24                   # RGB distance within which a kept fill takes a traced face's style


def _styles_for(shape: Shape, traced: list[FaceStyle]) -> list[FaceStyle]:
    """Each fill of an edited shape with the traced style of its own color (the trace may have changed since the
    edit: a style is never paired by position alone); a color no face has is a fixed color."""
    out = []
    for k, fill in enumerate(shape.fills):
        color = tuple(fill.color if isinstance(fill, SolidFill) else fill.stops[0].color)
        if k < len(traced) and tuple(traced[k].color) == color:
            out.append(traced[k])
            continue
        same = next((s for s in traced if tuple(s.color) == color), None)
        if same is None and traced:
            near = min(traced, key=lambda s: sum((int(a) - int(b)) ** 2 for a, b in zip(s.color[:3], color[:3])))
            if sum((int(a) - int(b)) ** 2 for a, b in zip(near.color[:3], color[:3])) <= STYLE_MATCH ** 2:
                same = near
        out.append(same if same is not None else FaceStyle(color, None))
    return out


def apply_art_edits(art: VectorArt, edits: ArtEdits) -> tuple[VectorArt, list[str]]:
    """The art with each edited traced layer's shape replaced (its face map dropped, so assembly uses the shape);
    notes for edits whose part is gone."""
    layers, used = [], set()
    for t in art.layers:
        key = "%s/%s" % (t.part, t.name)
        shape = edits.shapes.get(key)
        if shape is None:
            layers.append(t)
            continue
        used.add(key)
        layers.append(replace(t, shape=shape, styles=_styles_for(shape, t.styles), labels=None))
    gone = sorted({k.split("/", 1)[0] for k in edits.shapes if k not in used})
    return replace(art, layers=layers), [EDIT_GONE % part for part in gone]
