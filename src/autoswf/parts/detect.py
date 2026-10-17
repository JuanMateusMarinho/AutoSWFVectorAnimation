"""Label a helm drawing's regions with the part taxonomy (spec §9.1-9.2): skin by its color and the face's position,
hair by its contact with the skin and lock evidence, eyes by their white / iris / pupil / highlight structure. Zones are
in head units, measured on the AQW default heads (numbers only)."""
import colorsys
from dataclasses import dataclass, field

import numpy as np
from scipy import ndimage

from autoswf.aqw.template import Alignment
from autoswf.drawing.passes import Passes
from autoswf.model.geometry import Point
from autoswf.parts.locks import split_locks
from autoswf.parts.model import Corrections, PartName, default_location
from autoswf.parts.regions import RGBA, RegionGraph, build_regions
from autoswf.vectorize.fit import detail_settings

FACE_ZONE = ((-8.75, 18.0), (30.0, 24.0))          # ellipse center, radii: the lower face
EAR_ZONE = (-56.0, -24.0, -10.0, 30.0)             # x0, x1, y0, y1
HAIR_ZONE = ((-8.75, -1.45), (50.0, 58.0), 5.0)    # ellipse center, radii, and only above this y
EYE_BAND = (-34.0, 30.0, -14.0, 20.0)
MOUTH_ZONE = (-26.0, 12.0, 18.0, 38.0)
NOSE_ZONE = (-4.0, 14.0, 10.0, 22.0)
HEAD_CENTER_X = -8.75
SAME_COLOR = 20                                    # max channel difference of "the same" flat color
SKIN_MIN_SCORE = 5.0                               # head units²
HAIR_MIN_AREA, HAIR_MIN_THICKNESS, HAIR_MIN_SCORE = 40.0, 1.5, 10.0
CONTACT_WIDTH = 0.6                                # head units
HAIR_HUE_SPREAD = 12.0                             # degrees: other flat colors of the hair (drawn shades)
HAIR_VALUE_SPREAD = 0.35
NO_SKIN_NOTE = "No skin found: nothing follows the player's Skin color"
NO_HAIR_NOTE = "No hair found: nothing follows the player's Hair color"


def hsv(color) -> tuple[float, float, float]:
    h, s, v = colorsys.rgb_to_hsv(*(np.asarray(color[:3], float) / 255))
    return h * 360, s, v


def white_ish(color) -> bool:
    _, s, v = hsv(color)
    return v >= 0.85 and s <= 0.15


def gray_ish(color) -> bool:
    _, s, v = hsv(color)
    return s <= 0.15 and 0.45 <= v < 0.85


def dark(color) -> bool:
    _, s, v = hsv(color)
    return v < 0.15 or (v < 0.25 and s < 0.35)


def colored(color) -> bool:
    return not (white_ish(color) or gray_ish(color) or dark(color)) and hsv(color)[1] >= 0.2


def same_color(a, b) -> bool:
    return max(abs(int(x) - int(y)) for x, y in zip(a[:3], b[:3])) <= SAME_COLOR


@dataclass
class Part:
    name: str
    kind: str
    side: str | None
    index: int | None
    regions: list[int]
    z: tuple
    pivot: Point | None = None                     # head units
    tip: Point | None = None


@dataclass(eq=False)
class PartMap:
    graph: RegionGraph
    parts: dict[str, Part]                         # ordered by z
    part_of: dict[int, str]
    piece_of: dict[int, str]
    location_of: dict[int, str | None]
    skin: RGBA | None
    hair: list[RGBA]
    notes: list[str] = field(default_factory=list)

    def region_at(self, x: float, y: float):
        return self.graph.region_at(x, y)

    def part_mask(self, name: str) -> np.ndarray:
        out = np.zeros((self.graph.height, self.graph.width), bool)
        for rid in self.parts[name].regions:
            group, local = self.graph.mask(rid)
            x0, y0 = group.origin
            out[y0:y0 + local.shape[0], x0:x0 + local.shape[1]] |= local
        return out


class _Detector:
    def __init__(self, graph: RegionGraph):
        self.graph = graph
        self.scale = graph.scale
        self.notes: list[str] = []
        self.name_of: dict[int, str] = {}
        self.piece_of: dict[int, str] = {}
        self._measure_groups()

    # ------------------------------------------------------------ region features

    def _measure_groups(self) -> None:
        g, n = self.graph, len(self.graph.regions)
        self.in_face_or_ear = np.zeros(n)
        self.in_hair_zone = np.zeros(n)
        self.perimeter = np.zeros(n)
        (fcx, fcy), (frx, fry) = FACE_ZONE
        (hcx, hcy), (hrx, hry), hymax = HAIR_ZONE
        ex0, ex1, ey0, ey1 = EAR_ZONE
        for group in g.groups:
            labels = group.labels
            if not (labels >= 0).any():
                continue
            ys, xs = np.mgrid[0:labels.shape[0], 0:labels.shape[1]]
            hx, hy = g.head(xs + group.origin[0], ys + group.origin[1])
            face = ((hx - fcx) / frx) ** 2 + ((hy - fcy) / fry) ** 2 <= 1
            ear = (hx >= ex0) & (hx <= ex1) & (hy >= ey0) & (hy <= ey1)
            hair = (((hx - hcx) / hrx) ** 2 + ((hy - hcy) / hry) ** 2 <= 1) & (hy < hymax)
            inside = labels >= 0
            self.in_face_or_ear += np.bincount(labels[inside & (face | ear)], minlength=n)[:n] / self.scale ** 2
            self.in_hair_zone += np.bincount(labels[inside & hair], minlength=n)[:n] / self.scale ** 2
            padded = np.pad(labels, 1, constant_values=-1)
            for a, b in ((padded[1:-1, 1:-1], padded[1:-1, 2:]), (padded[1:-1, 1:-1], padded[1:-1, :-2]),
                         (padded[1:-1, 1:-1], padded[2:, 1:-1]), (padded[1:-1, 1:-1], padded[:-2, 1:-1])):
                edge = (a >= 0) & (a != b)
                self.perimeter += np.bincount(a[edge], minlength=n)[:n] / self.scale

    def region(self, rid: int):
        return self.graph.regions[rid]

    def thickness(self, rid: int) -> float:
        return 2 * self.region(rid).area / max(self.perimeter[rid], 1e-9)

    def canvas(self, rids) -> np.ndarray:
        out = np.zeros((self.graph.height, self.graph.width), bool)
        wanted = np.zeros(len(self.graph.regions) + 1, bool)
        wanted[list(rids)] = True
        for group in self.graph.groups:
            x0, y0 = group.origin
            h, w = group.labels.shape
            out[y0:y0 + h, x0:x0 + w] |= wanted[group.labels]
        return out

    def free(self, rids=None) -> list[int]:
        rids = range(len(self.graph.regions)) if rids is None else rids
        return [r for r in rids if r not in self.name_of and self.region(r).pixels > 0]

    # ------------------------------------------------------------ skin

    def find_skin(self) -> None:
        score: dict[int, float] = {}
        rep: dict[int, RGBA] = {}
        classes = self._classes()
        for rid, cls in classes.items():
            color = self.region(rid).flat
            h, s, v = hsv(color)
            if v < 0.4 or white_ish(color) or s > 0.8:
                continue
            warm = 1.5 if (h <= 50 and 0.1 <= s <= 0.6 and v >= 0.5) else 1.0
            score[cls] = score.get(cls, 0.0) + warm * self.in_face_or_ear[rid]
            rep.setdefault(cls, color)
        best = max(score, key=score.get) if score else None
        self.skin = rep[best] if best is not None and score[best] >= SKIN_MIN_SCORE else None
        if self.skin is None:
            self.notes.append(NO_SKIN_NOTE)
        self.skin_regions = [r for r in self.free() if self.skin is not None and same_color(self.region(r).flat, self.skin)]

    def _classes(self) -> dict[int, int]:
        """Region -> color class (flat colors within SAME_COLOR of a class's first, largest member)."""
        reps, out = [], {}
        for rid in sorted(self.free(), key=lambda r: -self.region(r).area):
            color = self.region(rid).flat
            for k, c in enumerate(reps):
                if same_color(color, c):
                    out[rid] = k
                    break
            else:
                out[rid] = len(reps)
                reps.append(color)
        self._class_colors = reps
        return out

    # ------------------------------------------------------------ hair

    def _contact(self) -> np.ndarray:
        """Per region: length (head units) of its pixels lying within CONTACT_WIDTH of skin regions."""
        n = len(self.graph.regions)
        out = np.zeros(n)
        if not self.skin_regions:
            return out
        skin = self.canvas(self.skin_regions)
        ring = (ndimage.distance_transform_edt(~skin) <= CONTACT_WIDTH * self.scale) & ~skin
        for group in self.graph.groups:
            x0, y0 = group.origin
            h, w = group.labels.shape
            local = ring[y0:y0 + h, x0:x0 + w] & (group.labels >= 0)
            out += np.bincount(group.labels[local], minlength=n)[:n]
        return out / (CONTACT_WIDTH * self.scale)

    def _lock_evidence(self, rids: list[int]) -> bool:
        if len([r for r in rids if self.region(r).area >= 6]) >= 3:
            return True
        mask = self.canvas(rids)
        masses, count = ndimage.label(mask)
        for k, box in enumerate(ndimage.find_objects(masses), start=1):
            piece = masses[box] == k
            if piece.sum() / self.scale ** 2 < HAIR_MIN_AREA:
                continue
            if split_locks(np.pad(piece, 2), self.scale)[0].max() >= 2:
                return True
        return False

    def find_hair(self) -> None:
        classes = self._classes()
        contact = self._contact()
        by_class: dict[int, list[int]] = {}
        for rid, cls in classes.items():
            if self.skin is not None and same_color(self.region(rid).flat, self.skin):
                continue
            if self.could_be_eye_white(rid):
                continue
            by_class.setdefault(cls, []).append(rid)
        scored = []
        for cls, rids in by_class.items():
            thick = [r for r in rids if self.thickness(r) >= HAIR_MIN_THICKNESS]
            if sum(self.region(r).area for r in thick) < HAIR_MIN_AREA:
                continue
            score = sum(contact[r] for r in rids) + 0.05 * sum(self.in_hair_zone[r] for r in rids)
            if score >= HAIR_MIN_SCORE:
                scored.append((score, cls, rids))
        self.hair_classes: set[int] = set()
        for score, cls, rids in sorted(scored, key=lambda t: -t[0]):
            if self._lock_evidence(rids):
                self.hair_classes.add(cls)
                break
        if self.hair_classes:
            (primary,) = self.hair_classes
            _, _, value = hsv(self._class_colors[primary])
            hue = hsv(self._class_colors[primary])[0]
            hair = set(by_class[primary])
            for gi in range(len(self.graph.groups)):
                for a, b in self.graph.adjacency(gi):
                    for x, y in ((a, b), (b, a)):
                        if x in hair and y in classes and classes[y] not in self.hair_classes:
                            color = self._class_colors[classes[y]]
                            dh = abs(hsv(color)[0] - hue)
                            if (min(dh, 360 - dh) <= HAIR_HUE_SPREAD and hsv(color)[1] >= 0.2
                                    and abs(hsv(color)[2] - value) <= HAIR_VALUE_SPREAD
                                    and not (self.skin is not None and same_color(color, self.skin))):
                                self.hair_classes.add(classes[y])
        else:
            self.notes.append(NO_HAIR_NOTE)
        self.hair = [self._class_colors[c] for c in sorted(self.hair_classes)]
        self.hair_regions = [r for r in self.free() if self.is_hair_color(self.region(r).flat)]

    def could_be_eye_white(self, rid: int) -> bool:
        x0, x1, y0, y1 = EYE_BAND
        r = self.region(rid)
        return white_ish(r.flat) and x0 <= r.center.x <= x1 and y0 <= r.center.y <= y1 and 3 <= r.area <= 400

    def is_hair_color(self, color) -> bool:
        return any(same_color(color, c) for c in getattr(self, "hair", []))

    # ------------------------------------------------------------ eyes

    def find_eyes(self) -> None:
        skin = set(self.skin_regions)
        hair = set(self.hair_regions)
        whites = [r for r in self.free() if r not in hair and self.could_be_eye_white(r)]
        eyes: list[list[int]] = []
        for rid in sorted(whites, key=lambda r: -self.region(r).area):
            c = self.region(rid).center
            near = [e for e in eyes if np.hypot(c.x - self.region(e[0]).center.x, c.y - self.region(e[0]).center.y)
                    <= 1.2 * np.sqrt(self.region(e[0]).area) + 4]
            if near:
                near[0].append(rid)
            elif len(eyes) < 2:
                eyes.append([rid])
        eyes.sort(key=lambda e: self.region(e[0]).center.x)
        taken = set()
        for k, eye in enumerate(eyes):
            side = ("L", "R")[k] if len(eyes) == 2 else ("L" if self.region(eye[0]).center.x < 0 else "R")
            name = PartName("eye", side).name
            boxes = [self._head_box(r) for r in eye]
            bx0, by0 = min(b[0] for b in boxes), min(b[1] for b in boxes)
            bx1, by1 = max(b[2] for b in boxes), max(b[3] for b in boxes)
            grow = max(3.0, 0.6 * max(bx1 - bx0, by1 - by0))
            white_area = sum(self.region(r).area for r in eye)
            members = {r: "white" for r in eye}
            for rid in self.free():
                if rid in members or rid in taken or rid in skin or rid in hair:
                    continue
                c, reg = self.region(rid).center, self.region(rid)
                if not (bx0 - grow <= c.x <= bx1 + grow and by0 - grow <= c.y <= by1 + grow):
                    continue
                if reg.area > 3 * white_area + 20:
                    continue
                color = reg.flat
                if white_ish(color) or gray_ish(color):
                    members[rid] = "white"
                elif colored(color):
                    members[rid] = "iris"
                elif dark(color):
                    members[rid] = "dark"
            irises = [r for r, p in members.items() if p == "iris"]
            if irises:
                iboxes = [self._head_box(r) for r in irises]
                ix0, iy0 = min(b[0] for b in iboxes) - 0.5, min(b[1] for b in iboxes) - 0.5
                ix1, iy1 = max(b[2] for b in iboxes) + 0.5, max(b[3] for b in iboxes) + 0.5
                iris_area = sum(self.region(r).area for r in irises)
                iris_v = max(hsv(self.region(r).flat)[2] for r in irises)
            for rid, piece in list(members.items()):
                reg = self.region(rid)
                inside_iris = irises and ix0 <= reg.center.x <= ix1 and iy0 <= reg.center.y <= iy1
                if piece == "dark":
                    members[rid] = "pupil" if inside_iris and reg.area < 0.6 * iris_area else "lid"
                elif rid != eye[0] and inside_iris and reg.area < 0.25 * iris_area and (
                        white_ish(reg.flat) or hsv(reg.flat)[2] >= iris_v + 0.3):
                    members[rid] = "highlight"
            for rid, piece in members.items():
                self.name_of[rid] = name
                self.piece_of[rid] = piece
                taken.add(rid)

    def _head_box(self, rid: int) -> tuple[float, float, float, float]:
        x0, y0, x1, y1 = self.region(rid).box
        hx, hy = self.graph.head(np.array([x0, x1 - 1, x0, x1 - 1]), np.array([y0, y0, y1 - 1, y1 - 1]))
        return float(hx.min()), float(hy.min()), float(hx.max()), float(hy.max())

    # ------------------------------------------------------------ the rest (Task 5 completes the taxonomy)

    def label_rest(self) -> None:
        for rid in self.free():
            if rid in self.skin_regions:
                self.name_of[rid] = "Face"
            elif rid in self.hair_regions:
                self.name_of[rid] = "Hair"
            else:
                self.name_of[rid] = "Accessory 1"

    # ------------------------------------------------------------ result

    def locations(self) -> dict[int, str | None]:
        out = {}
        for rid, name in self.name_of.items():
            kind = PartName.parse(name).kind
            color = self.region(rid).flat
            location = default_location(kind, self.piece_of.get(rid))
            if location == "Skin" and not (self.skin is not None and same_color(color, self.skin)):
                location = None
            if location == "Hair" and not self.is_hair_color(color):
                location = None
            out[rid] = location
        return out

    def part_map(self) -> PartMap:
        parts: dict[str, Part] = {}
        for rid in sorted(self.name_of):
            name = self.name_of[rid]
            if name not in parts:
                pn = PartName.parse(name)
                parts[name] = Part(name, pn.kind, pn.side, pn.index, [], (self.region(rid).group,) + pn.z)
            parts[name].regions.append(rid)
        ordered = dict(sorted(parts.items(), key=lambda kv: kv[1].z))
        return PartMap(self.graph, ordered, dict(self.name_of), dict(self.piece_of), self.locations(), self.skin,
                       list(getattr(self, "hair", [])), self.notes)


def detect_parts(passes: Passes, alignment: Alignment, corrections: Corrections = Corrections(),
                 detail: int = 50) -> PartMap:
    graph = build_regions(passes, alignment, corrections.cuts, detail_settings(detail).min_area)
    d = _Detector(graph)
    d.find_skin()
    d.find_hair()
    d.find_eyes()
    d.label_rest()
    return d.part_map()
