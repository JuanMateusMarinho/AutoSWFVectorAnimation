"""The helm part taxonomy (spec §9.1): part names, their z order and color defaults, part hints from folder names, and
the user's corrections (a `<drawing>.parts.json` file next to the drawing) that Plan 6's click-to-fix will drive."""
import json
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

from autoswf.aqw.contract import LOCATIONS

KINDS = ("back_hair", "face", "nose", "mouth", "ear", "brow", "eye", "hair", "lock", "horn", "shell", "accessory")
KIND_NAMES = {"back_hair": "Back hair", "face": "Face", "nose": "Nose", "mouth": "Mouth", "ear": "Ear", "brow": "Brow",
              "eye": "Eye", "hair": "Hair", "lock": "Lock", "horn": "Horn", "shell": "Helm", "accessory": "Accessory"}
SIDED = frozenset({"ear", "brow", "eye", "horn"})
NUMBERED = frozenset({"lock", "accessory"})
EYE_PIECES = ("white", "iris", "pupil", "highlight", "lid")
MOVING = frozenset({"eye", "lock", "ear", "accessory"})
PROVIDERS = frozenset({"face", "hair", "shell"})
NO_COLOR = "none"
NAMING = ("Face, Ear L/R, Nose, Mouth, Brow L/R, Eye L/R, Hair, Lock N, Back hair, Horn L/R, Helm, Accessory N")

# Folder words (English, Portuguese, Japanese), checked in this order: back hair before hair.
FOLDER_WORDS = (
    ("back_hair", ("back hair", "backhair", "cabelo de tras", "後ろ髪")),
    ("hair", ("hair", "cabelo", "cabelos", "franja", "bangs", "髪", "前髪")),
    ("face", ("face", "rosto", "skin", "pele", "head", "cabeca", "顔", "肌")),
    ("eye", ("eye", "eyes", "olho", "olhos", "目")),
    ("ear", ("ear", "ears", "orelha", "orelhas", "耳")),
    ("brow", ("brow", "brows", "eyebrow", "eyebrows", "sobrancelha", "sobrancelhas", "眉")),
    ("mouth", ("mouth", "boca", "口")),
    ("nose", ("nose", "nariz", "鼻")),
    ("horn", ("horn", "horns", "chifre", "chifres", "角")),
    ("shell", ("helm", "helmet", "hat", "cap", "capacete", "chapeu", "elmo", "帽子")),
    ("accessory", ("accessory", "accessories", "acessorio", "acessorios", "ribbon", "laco", "feather", "pena", "gem",
                   "joia", "飾り")),
)


def _fold(text: str) -> str:
    return "".join(ch for ch in unicodedata.normalize("NFKD", text) if not unicodedata.combining(ch)).casefold()


def _words(text: str) -> list[str]:
    return "".join(ch if ch.isalnum() else " " for ch in _fold(text)).split()


def folder_kind(name: str) -> str | None:
    """The part kind a folder name hints at, or None."""
    words = _words(name)
    for kind, phrases in FOLDER_WORDS:
        for phrase in phrases:
            phrase = _fold(phrase)
            if not phrase.isascii():
                if any(phrase in w for w in words):
                    return kind
                continue
            p = phrase.split()
            if any(words[i:i + len(p)] == p for i in range(len(words) - len(p) + 1)):
                return kind
    return None


@dataclass(frozen=True)
class PartName:
    kind: str
    side: str | None = None
    index: int | None = None

    @property
    def name(self) -> str:
        text = KIND_NAMES[self.kind]
        if self.side:
            text += " " + self.side
        if self.index is not None:
            text += " %d" % self.index
        return text

    @property
    def z(self) -> tuple[int, int, int]:
        return KINDS.index(self.kind), 0 if self.side in (None, "L") else 1, self.index or 0

    @classmethod
    def parse(cls, text: str) -> "PartName":
        words = text.casefold().split()
        kinds = {v.casefold(): k for k, v in KIND_NAMES.items()}
        kind, rest = None, []
        if words[:2] == ["back", "hair"]:
            kind, rest = "back_hair", words[2:]
        elif words and words[0] in kinds and words[0] != "back":
            kind, rest = kinds[words[0]], words[1:]
        if kind in SIDED and len(rest) == 1 and rest[0] in ("l", "r"):
            return cls(kind, side=rest[0].upper())
        if kind in NUMBERED and len(rest) == 1 and rest[0].isdigit() and int(rest[0]) > 0:
            return cls(kind, index=int(rest[0]))
        if kind is not None and kind not in SIDED | NUMBERED and not rest:
            return cls(kind)
        raise ValueError("Unknown part '%s'; parts are named %s" % (text, NAMING))


def default_location(kind: str, piece: str | None) -> str | None:
    """The color slot a part's regions follow when their color matches the skin or hair colors (spec §10)."""
    if kind in ("face", "ear", "nose"):
        return "Skin"
    if kind in ("hair", "lock", "back_hair", "brow"):
        return "Hair"
    if kind == "eye" and piece == "iris":
        return "Eye"
    return None


def check_color(part: str, location: str) -> tuple[str, str]:
    """A (part name, location or "none") pair checked and spelled the canonical way."""
    name = PartName.parse(part).name
    canonical = {loc.casefold(): loc for loc in LOCATIONS + (NO_COLOR,)}
    if location.strip().casefold() not in canonical:
        raise ValueError("Unknown color '%s'; use %s or %s" % (location, ", ".join(LOCATIONS), NO_COLOR))
    return name, canonical[location.strip().casefold()]


@dataclass(frozen=True)
class Assign:
    at: tuple[float, float]              # drawing pixels
    part: str
    piece: str | None = None


def _point(value, what: str) -> tuple[float, float]:
    if (not isinstance(value, (list, tuple)) or len(value) != 2
            or not all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in value)):
        raise ValueError("%s must be two numbers (x, y in drawing pixels)" % what)
    return float(value[0]), float(value[1])


@dataclass
class Corrections:
    assign: list[Assign] = field(default_factory=list)
    cuts: list[list[tuple[float, float]]] = field(default_factory=list)
    colors: dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data, source: str = "parts file") -> "Corrections":
        def fail(message):
            return ValueError("%s: %s" % (source, message))
        if not isinstance(data, dict):
            raise fail("it must hold a JSON object with \"assign\", \"cuts\" and \"colors\"")
        for key in data:
            if key not in ("assign", "cuts", "colors"):
                raise fail("Unknown key '%s'; use assign, cuts, colors" % key)
        out = cls()
        for n, entry in enumerate(data.get("assign", []), start=1):
            where = "entry %d of \"assign\": " % n
            try:
                if not isinstance(entry, dict) or "part" not in entry or "at" not in entry:
                    raise ValueError("it needs \"at\" and \"part\"")
                at = _point(entry["at"], "\"at\"")
                part = PartName.parse(str(entry["part"]))
                piece = entry.get("piece")
                if piece is not None:
                    if part.kind != "eye":
                        raise ValueError("'%s' has no pieces; only eyes have pieces" % part.name)
                    if piece not in EYE_PIECES:
                        raise ValueError("Unknown eye piece '%s'; use %s" % (piece, ", ".join(EYE_PIECES)))
            except ValueError as e:
                raise fail(where + str(e)) from None
            out.assign.append(Assign(at, part.name, piece))
        for n, cut in enumerate(data.get("cuts", []), start=1):
            where = "entry %d of \"cuts\": " % n
            if not isinstance(cut, list) or len(cut) < 2:
                raise fail(where + "a cut needs at least two points")
            try:
                out.cuts.append([_point(p, "each point") for p in cut])
            except ValueError as e:
                raise fail(where + str(e)) from None
        colors = data.get("colors", {})
        if not isinstance(colors, dict):
            raise fail("\"colors\" must map part names to colors")
        for part, location in colors.items():
            try:
                name, loc = check_color(str(part), str(location))
            except ValueError as e:
                raise fail("colors: " + str(e)) from None
            out.colors[name] = loc
        return out

    def to_dict(self) -> dict:
        assign = []
        for a in self.assign:
            entry = {"at": list(a.at), "part": a.part}
            if a.piece is not None:
                entry["piece"] = a.piece
            assign.append(entry)
        return {"assign": assign, "cuts": [[list(p) for p in cut] for cut in self.cuts], "colors": dict(self.colors)}

    @classmethod
    def load(cls, path: str | Path) -> "Corrections":
        path = Path(path)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            raise ValueError("%s is not valid JSON (line %d, column %d)" % (path.name, e.lineno, e.colno)) from None
        except OSError as e:
            raise ValueError("Could not read %s: %s" % (path.name, e.strerror or e)) from None
        return cls.from_dict(data, path.name)

    def save(self, path: str | Path) -> None:
        Path(path).write_text(json.dumps(self.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
