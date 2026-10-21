"""Everything the user decides about one helm (spec §6, §13, §14): the drawing, layer roles, alignment, detail, part
corrections, animation, pivots, export and preview colors. JSON in the project file, and the unit of undo in the app."""
import copy
import math
from dataclasses import dataclass, field
from pathlib import Path

from autoswf.anim.settings import AnimationSettings
from autoswf.aqw.contract import sanitize_link
from autoswf.aqw.template import Alignment
from autoswf.drawing.roles import IGNORE, ROLES
from autoswf.parts.model import Corrections
from autoswf.project.edits import ArtEdits
from autoswf.render.colors import LOCATION_FIELDS

GENDERS = ("M", "F")
SCALE_RANGE = (0.1, 10.0)
KEYS = ("source", "roles", "align", "detail", "gradient", "separate_tones", "corrections", "animation", "pivots",
        "export", "colors", "dismissed", "edits")
EXPORT_KEYS = ("file", "link", "morph", "back_hair", "variants", "genders")
VARIANT_KEYS = ("file", "link", "helm", "parts")


@dataclass
class Adjust:
    """A per-gender adjustment: a move (head units) and a scale."""
    x: float = 0.0
    y: float = 0.0
    scale: float = 1.0

    def to_dict(self) -> dict:
        return {"x": self.x, "y": self.y, "scale": self.scale}

    @classmethod
    def from_dict(cls, data, what: str) -> "Adjust":
        data = _mapping(data, what)
        for key in data:
            if key not in ("x", "y", "scale"):
                raise ValueError("%s: Unknown key '%s'; keys are x, y, scale" % (what, key))
        x, y = (_number(data.get(k, 0.0), "%s %s" % (what, k), -500, 500) for k in ("x", "y"))
        scale = _number(data.get("scale", 1.0), "%s scale" % what, *SCALE_RANGE)
        return cls(x, y, scale)


@dataclass
class Variant:
    """One gender's file of a helm exported as male and female versions."""
    file: str
    link: str
    helm: Adjust = field(default_factory=Adjust)
    parts: dict[str, Adjust] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {"file": self.file, "link": self.link, "helm": self.helm.to_dict(),
                "parts": {name: a.to_dict() for name, a in self.parts.items()}}

    @classmethod
    def from_dict(cls, data, what: str) -> "Variant":
        data = _mapping(data, what)
        _known(data, VARIANT_KEYS, what)
        parts = {str(name): Adjust.from_dict(a, '%s part "%s"' % (what, name))
                 for name, a in _mapping(data.get("parts", {}), what + " parts").items()}
        return cls(_text(data.get("file", ""), what + " file"), _text(data.get("link", ""), what + " link"),
                   Adjust.from_dict(data.get("helm", {}), what + " helm"), parts)


@dataclass
class ExportSettings:
    file: str | None = None              # default: next to the drawing, <stem>.swf
    link: str | None = None              # default: from the file name
    morph: bool = False
    back_hair: bool = True
    variants: bool = False
    genders: dict[str, Variant] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {"file": self.file, "link": self.link, "morph": self.morph, "back_hair": self.back_hair,
                "variants": self.variants, "genders": {g: v.to_dict() for g, v in self.genders.items()}}

    @classmethod
    def from_dict(cls, data) -> "ExportSettings":
        data = _mapping(data, "export")
        _known(data, EXPORT_KEYS, "export")
        genders = {}
        for g, v in _mapping(data.get("genders", {}), "export genders").items():
            if g not in GENDERS:
                raise ValueError("export: Unknown gender '%s'; genders are M and F" % g)
            genders[g] = Variant.from_dict(v, "export %s" % g)
        return cls(_optional_text(data.get("file"), "export file"), _optional_text(data.get("link"), "export link"),
                   _flag(data.get("morph", False), "export morph"), _flag(data.get("back_hair", True), "export back_hair"),
                   _flag(data.get("variants", False), "export variants"), genders)


@dataclass
class HelmSettings:
    source: str
    roles: dict[str, str] = field(default_factory=dict)          # layer name -> role ("line" … "details", "ignore")
    align: str | None = None                                      # Alignment text, None = automatic
    detail: int = 50
    gradient: list[str] = field(default_factory=list)
    separate_tones: bool = False
    corrections: Corrections = field(default_factory=Corrections)
    animation: AnimationSettings = field(default_factory=AnimationSettings)
    pivots: dict[str, tuple[float, float]] = field(default_factory=dict)  # part -> head units
    export: ExportSettings = field(default_factory=ExportSettings)
    colors: dict[str, int] = field(default_factory=dict)          # player colors for the canvas and preview
    dismissed: list[str] = field(default_factory=list)            # suggestions skipped that are not animations
    edits: ArtEdits = field(default_factory=ArtEdits)             # hand edits of the art (the editor, Plan 7)

    def to_dict(self) -> dict:
        return {"source": self.source, "roles": dict(self.roles), "align": self.align, "detail": self.detail,
                "gradient": list(self.gradient), "separate_tones": self.separate_tones,
                "corrections": self.corrections.to_dict(), "animation": self.animation.to_dict(),
                "pivots": {name: [p[0], p[1]] for name, p in self.pivots.items()}, "export": self.export.to_dict(),
                "colors": {loc: "%06X" % rgb for loc, rgb in self.colors.items()}, "dismissed": list(self.dismissed),
                "edits": self.edits.to_dict()}

    @classmethod
    def from_dict(cls, data, source: str = "project") -> "HelmSettings":
        try:
            return cls._from_dict(data)
        except ValueError as e:
            raise ValueError("%s: %s" % (source, e)) from None

    @classmethod
    def _from_dict(cls, data) -> "HelmSettings":
        data = _mapping(data, "settings")
        _known(data, KEYS, "settings")
        roles = {}
        for layer, role in _mapping(data.get("roles", {}), "roles").items():
            if role not in ROLES + (IGNORE,):
                raise ValueError("roles: Unknown role '%s'; roles are %s" % (role, ", ".join(ROLES + (IGNORE,))))
            roles[str(layer)] = role
        align = data.get("align")
        if align is not None:
            try:
                Alignment.parse(_text(align, "align"))         # checked; the text is kept as written (full precision)
            except ValueError as e:
                raise ValueError("align: %s" % e) from None
        detail = data.get("detail", 50)
        if isinstance(detail, bool) or not isinstance(detail, int) or not 0 <= detail <= 100:
            raise ValueError("detail must be a whole number from 0 to 100 (got %r)" % (detail,))
        gradient = data.get("gradient", [])
        if not isinstance(gradient, list) or not all(isinstance(g, str) for g in gradient):
            raise ValueError("gradient must be a list of layer names")
        pivots = {}
        for name, point in _mapping(data.get("pivots", {}), "pivots").items():
            if (not isinstance(point, (list, tuple)) or len(point) != 2
                    or not all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) for v in point)):
                raise ValueError('pivot of "%s" must be two numbers (x, y in head units)' % name)
            pivots[str(name)] = (float(point[0]), float(point[1]))
        colors = {}
        for location, value in _mapping(data.get("colors", {}), "colors").items():
            if location not in LOCATION_FIELDS:
                raise ValueError("colors: Unknown color location '%s'; locations are %s"
                                 % (location, ", ".join(LOCATION_FIELDS)))
            colors[location] = _rgb(value, location)
        dismissed = data.get("dismissed", [])
        if not isinstance(dismissed, list) or not all(isinstance(d, str) for d in dismissed):
            raise ValueError("dismissed must be a list of suggestion names")
        return cls(source=_text(data.get("source", ""), "source"), roles=roles, align=align, detail=detail,
                   gradient=list(gradient), separate_tones=_flag(data.get("separate_tones", False), "separate_tones"),
                   corrections=Corrections.from_dict(data.get("corrections", {}), "corrections"),
                   animation=AnimationSettings.from_dict(data.get("animation", {}), "animation"),
                   pivots=pivots, export=ExportSettings.from_dict(data.get("export", {})), colors=colors,
                   dismissed=list(dismissed), edits=ArtEdits.from_dict(data.get("edits", {})))

    def copy(self) -> "HelmSettings":
        return copy.deepcopy(self)

    def export_file(self) -> Path:
        if self.export.file:
            return Path(self.export.file)
        source = Path(self.source)
        return source.with_name(source.stem + ".swf")

    def export_link(self) -> str:
        return self.export.link or sanitize_link(self.export_file().stem)


def _mapping(value, what: str) -> dict:
    if not isinstance(value, dict):
        raise ValueError("%s must be a JSON object" % what)
    return value


def _known(data: dict, keys: tuple, what: str) -> None:
    for key in data:
        if key not in keys:
            raise ValueError("%s: Unknown key '%s'; keys are %s" % (what, key, ", ".join(keys)))


def _text(value, what: str) -> str:
    if not isinstance(value, str):
        raise ValueError("%s must be text" % what)
    return value


def _optional_text(value, what: str) -> str | None:
    return None if value is None else _text(value, what)


def _flag(value, what: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError("%s must be true or false" % what)
    return value


def _number(value, what: str, low: float, high: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not low <= value <= high:
        raise ValueError("%s must be a number from %g to %g (got %r)" % (what, low, high, value))
    return float(value)


def _rgb(value, location: str) -> int:
    if isinstance(value, int) and not isinstance(value, bool) and 0 <= value <= 0xFFFFFF:
        return value
    text = str(value).strip().lstrip("#")
    if len(text) == 6 and all(c in "0123456789abcdefABCDEF" for c in text):
        return int(text, 16)
    raise ValueError("colors: %s must look like RRGGBB (got %r)" % (location, value))
