"""The structure of any AQW item SWF (Open SWF mode): which kind of item it is, its parts the way AQW splits them
(armor classes <Link><M|F><Part>, a helm and its back hair, hair, cape, pet, weapon…) and, under each part, its
sub-pieces — the placements on the part's timeline, expanded through every clip they place."""
import re
from dataclasses import dataclass, field

from autoswf.model.geometry import Matrix
from autoswf.render.scripts import SetColor, class_frame_actions
from autoswf.swf.decode import MorphShapeDef, MovieData, PlaceCommand, ShapeDef, SpriteDef

ARMOR_PARTS = ("Chest", "Hip", "Shoulder", "Hand", "Thigh", "Shin", "Foot", "FootIdle", "Robe", "RobeBack", "Head")
ARMOR_CLASS = re.compile(r"^(.+?)([MF])(Chest|Hip|Shoulder|Hand|Thigh|Shin|FootIdle|Foot|RobeBack|Robe|Head)$")
HAIR_CLASS = re.compile(r"^(.+?)([MF])(HairBack|Hair)$")
GENDER_WORDS = {"M": "male", "F": "female"}
MAX_DEPTH = 12                     # nesting levels expanded under a part


@dataclass(frozen=True)
class PieceRef:
    """A placement: everything the timeline of `sprite` places at `depth` (sprite 0 = the root timeline)."""
    sprite: int
    depth: int


@dataclass(eq=False)
class Piece:
    ref: PieceRef
    char_id: int
    kind: str                                   # "shape", "morph", "clip" or "other"
    class_name: str | None
    instance_name: str | None
    color: tuple[str, str] | None               # a colorable clip's (location, shade)
    matrix: Matrix
    changes: bool                               # other characters are placed at this depth later
    children: list["Piece"] = field(default_factory=list)
    path: str = ""

    @property
    def label(self) -> str:
        if self.color is not None:
            return "%s (%s)" % self.color
        if self.instance_name:
            return self.instance_name
        if self.class_name:
            return self.class_name.rpartition(".")[2]
        return {"shape": "Shape %d", "morph": "Morph shape %d", "clip": "Clip %d"}.get(self.kind, "Character %d") \
            % self.char_id


@dataclass(eq=False)
class ItemPart:
    key: str                                    # "MChest", "Helm", "Backhair", "MHair", "Item", "Root"
    label: str                                  # "Chest (male)"
    gender: str | None
    class_name: str | None
    char_id: int
    pieces: list[Piece] = field(default_factory=list)


@dataclass(eq=False)
class ItemStructure:
    kind: str                                   # armor, hair, helm, cape, pet, item, weapon
    link: str | None
    genders: tuple[str, ...]
    parts: list[ItemPart]
    other_classes: list[str]
    _paths: dict[str, Piece] = field(default_factory=dict, repr=False)
    _instances: dict[PieceRef, list[str]] = field(default_factory=dict, repr=False)

    def piece(self, path: str) -> Piece:
        if path not in self._paths:
            raise KeyError("No piece '%s' in this item" % path)
        return self._paths[path]

    def instances(self, ref: PieceRef) -> list[str]:
        """Every path where this placement shows (more than one when its clip is used in several places)."""
        return list(self._instances.get(ref, []))

    def public_classes(self) -> list[str]:
        return [p.class_name for p in self.parts if p.class_name]

    def walk(self):
        def visit(pieces):
            for p in pieces:
                yield p
                yield from visit(p.children)
        for part in self.parts:
            yield from visit(part.pieces)

    def part_of(self, path: str) -> ItemPart:
        key = path.split("/")[0]
        return next(p for p in self.parts if p.key == key)


def find_armor_link(movie: MovieData, file_name: str = "the file") -> tuple[str, tuple[str, ...]]:
    """The armor's link (the one with the most part classes) and the genders it has."""
    found: dict[str, set[str]] = {}
    for name in movie.classes:
        m = ARMOR_CLASS.match(name)
        if m:
            found.setdefault(m.group(1), set()).add(m.group(2))
    if not found:
        raise ValueError("%s has no armor classes (<Link><M|F><Part>)" % file_name)
    link = max(found, key=lambda k: sum(1 for n in movie.classes if ARMOR_CLASS.match(n) and n.startswith(k)))
    return link, tuple(g for g in "MF" if g in found[link])


class _Reader:
    def __init__(self, movie: MovieData):
        self.movie = movie
        self._colors: dict[str, tuple[str, str] | None] = {}
        self.paths: dict[str, Piece] = {}
        self.instances: dict[PieceRef, list[str]] = {}

    def color(self, class_name: str | None) -> tuple[str, str] | None:
        if class_name is None:
            return None
        if class_name not in self._colors:
            actions = class_frame_actions(self.movie.abcs, class_name).get(0, [])
            found = next((a for a in actions if isinstance(a, SetColor)), None)
            self._colors[class_name] = (found.location, found.shade) if found is not None else None
        return self._colors[class_name]

    def pieces(self, sprite_id: int, prefix: str, level: int) -> list[Piece]:
        sprite = self.movie.character(sprite_id)
        if not isinstance(sprite, SpriteDef) or level > MAX_DEPTH:
            return []
        first: dict[int, PlaceCommand] = {}
        changes: set[int] = set()
        for frame in sprite.frames:
            for cmd in frame:
                if not isinstance(cmd, PlaceCommand) or cmd.char_id is None:
                    continue
                if cmd.depth not in first:
                    first[cmd.depth] = cmd
                elif cmd.char_id != first[cmd.depth].char_id:
                    changes.add(cmd.depth)
        out = []
        for depth in sorted(first):
            cmd = first[depth]
            char = self.movie.character(cmd.char_id)
            kind = ("clip" if isinstance(char, SpriteDef) else "morph" if isinstance(char, MorphShapeDef)
                    else "shape" if isinstance(char, ShapeDef) else "other")
            class_name = self.movie.class_name(cmd.char_id)
            piece = Piece(PieceRef(sprite_id, depth), cmd.char_id, kind, class_name, cmd.name,
                          self.color(class_name), cmd.matrix or Matrix(), depth in changes)
            piece.path = "%s/%d" % (prefix, depth)
            self.paths[piece.path] = piece
            self.instances.setdefault(piece.ref, []).append(piece.path)
            if kind == "clip":
                piece.children = self.pieces(cmd.char_id, piece.path, level + 1)
            out.append(piece)
        return out

    def part(self, key: str, label: str, gender: str | None, class_name: str | None, char_id: int) -> ItemPart:
        return ItemPart(key, label, gender, class_name, char_id, self.pieces(char_id, key, 0))


def read_structure(movie: MovieData, file_name: str = "the file") -> ItemStructure:
    reader = _Reader(movie)
    classes = movie.classes
    public = [n for n in classes if "." not in n]
    internal = sorted(n for n in classes if "." in n)
    parts: list[ItemPart] = []
    if any(ARMOR_CLASS.match(n) for n in public):
        link, genders = find_armor_link(movie, file_name)
        for g in genders:
            for part in ARMOR_PARTS:
                name = link + g + part
                if name in classes:
                    parts.append(reader.part(g + part, "%s (%s)" % (part, GENDER_WORDS[g]), g, name, classes[name]))
        kind = "armor"
        other = internal + sorted(n for n in public if not any(p.class_name == n for p in parts))
    elif any(HAIR_CLASS.match(n) for n in public):
        matches = [HAIR_CLASS.match(n) for n in public if HAIR_CLASS.match(n)]
        link = matches[0].group(1)
        genders = tuple(g for g in "MF" if any(m.group(2) == g for m in matches))
        for g in genders:
            for piece, label in (("Hair", "Hair"), ("HairBack", "Back hair")):
                name = link + g + piece
                if name in classes:
                    parts.append(reader.part(g + piece, "%s (%s)" % (label, GENDER_WORDS[g]), g, name, classes[name]))
        kind, other = "hair", internal
    elif public:
        drawable = [n for n in public if isinstance(movie.character(classes[n]), (SpriteDef, ShapeDef, MorphShapeDef))]
        mains = [n for n in drawable if not n.endswith("_backhair")]
        link, genders = (mains[0] if len(mains) == 1 else None), ()
        if link is not None and link + "_backhair" in classes:
            kind = "helm"
            parts = [reader.part("Helm", "Helm", None, link, classes[link]),
                     reader.part("Backhair", "Back hair", None, link + "_backhair", classes[link + "_backhair"])]
        else:
            labels = set(movie.character(classes[mains[0]]).labels) if len(mains) == 1 and isinstance(
                movie.character(classes[mains[0]]), SpriteDef) else set()
            kind = ("cape" if {"Idle", "Move"} <= labels else "pet" if {"Ready", "Idle", "Walk"} <= labels
                    else "item")
            label = {"cape": "Cape", "pet": "Pet"}.get(kind, "Item")
            parts = [reader.part("Item" if len(mains) == 1 else n, label if len(mains) == 1 else n, None, n, classes[n])
                     for n in mains]
        other = internal
    elif movie.root.frames and any(frame for frame in movie.root.frames):
        kind, link, genders, other = "weapon", None, (), internal
        parts = [reader.part("Root", "Root timeline", None, None, 0)]
    else:
        raise ValueError("No AQW item classes were found in %s" % file_name)
    if not parts:
        raise ValueError("No AQW item classes were found in %s" % file_name)
    return ItemStructure(kind, link, genders, parts, other, reader.paths, reader.instances)
