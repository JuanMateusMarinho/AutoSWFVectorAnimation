"""Label a helm drawing's regions with the part taxonomy (spec §9.1-9.2): skin by its color and the face's position,
hair by its contact with the skin and lock evidence, eyes by their white / iris / pupil / highlight structure, then
ears, brows, mouth, nose, locks, horns, the helm shell and accessories by position and shape; part folders and the
user's corrections win over the heuristics. Zones are in head units, measured on the AQW default heads (numbers only)."""
import colorsys
from dataclasses import dataclass, field

import numpy as np
from scipy import ndimage

from autoswf.aqw.template import Alignment
from autoswf.drawing.passes import Passes
from autoswf.model.geometry import Point
from autoswf.parts.locks import LockSettings, split_locks
from autoswf.parts.model import NO_COLOR, Corrections, PartName, default_location, folder_kind
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
HAIR_CONTACT_WEIGHT = 2.0                          # head units² of hair-zone area per head unit of skin contact
HAIR_HUE_SPREAD = 8.0                              # degrees: other flat colors of the hair (drawn shades)
HAIR_SATURATION_SPREAD, HAIR_VALUE_SPREAD = 0.12, 0.35
SKIN_FACE_SHARE = 0.35                             # of a skin color's visible area in the face/ear zones (bald heads: 0.44)
LOCK_EVIDENCE_ELONGATION = 2.5                     # regions cut apart by lines count as locks when this long
OUTLINE_THICKNESS = 1.2                            # head units: thinner dark regions are line art kept in the flats
OUTLINE_NEIGHBOR = 0.25                            # an outline joins the highest part among its main neighbors
FACE_FEATURE = 0.6                                 # regions this much bordered by skin are facial features, not hair
SKIN_SHADE_HUE, SKIN_SHADE_VALUE, SKIN_SHADE_SATURATION = 12.0, 0.2, 0.25
FACE_MIN_AREA, EAR_MIN_AREA, EAR_X, NOSE_MAX_AREA = 200.0, 8.0, 24.0, 30.0
BROW_MAX_AREA, BROW_RATIO, MOUTH_MAX_AREA = 150.0, 1.8, 150.0
LOCK_ELONGATION, LOCK_MAX_FRACTION = 2.0, 0.3
HORN_ELONGATION, HORN_MIN_AREA, HORN_MAX_AREA = 2.5, 4.0, 200.0
INSIDE_FACE = 0.8
LEFTOVER_AREA = 3.0                                # head units²: smaller leftovers join a neighbor, never a part alone
MAX_ACCESSORIES = 8                                # more loose pieces than this are not accessories (sketches)
HELM_MIN_FRACTION, HELM_GROW_FRACTION, HELM_MAX_Y = 0.03, 0.1, 15.0
NEVER_COLORED = ("white", "pupil", "highlight", "lid")
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

    def label_point(self, name: str) -> tuple[int, int]:
        """Drawing pixel deepest inside the part's largest region (where a click selects it)."""
        largest = max(self.parts[name].regions, key=lambda r: self.graph.regions[r].pixels)
        group, local = self.graph.mask(largest)
        depth = ndimage.distance_transform_edt(np.pad(local, 1))[1:-1, 1:-1]
        y, x = np.unravel_index(int(np.argmax(depth)), depth.shape)
        return int(x) + group.origin[0], int(y) + group.origin[1]

    def part_mask(self, name: str) -> np.ndarray:
        out = np.zeros((self.graph.height, self.graph.width), bool)
        for rid in self.parts[name].regions:
            group, local = self.graph.mask(rid)
            x0, y0 = group.origin
            out[y0:y0 + local.shape[0], x0:x0 + local.shape[1]] |= local
        return out


class _Detector:
    def __init__(self, graph: RegionGraph, corrections: Corrections):
        self.graph = graph
        self.scale = graph.scale
        self.corrections = corrections
        self.notes: list[str] = []
        self.name_of: dict[int, str] = {}
        self.piece_of: dict[int, str] = {}
        self.forced: dict[int, tuple[str, str | None]] = {}
        self.outlines: list[int] = []
        self.locks: list[list[int]] = []               # automatic locks (their regions), numbered at the end
        self.skin: RGBA | None = None
        self.skin_extra: list[RGBA] = []               # colors the user marked as skin (face, ear, nose clicks)
        self.hair: list[RGBA] = []
        self.joined_outlines: set[int] = set()
        self.eyes: dict[str, list[int]] = {}           # eye name -> its white regions
        self.hair_pool: list[int] = []                 # regions of hair folders
        self.accessory_pool: list[int] = []            # regions of accessory folders
        self.reserved: set[int] = set()                # pools: no other rule takes them

    # ------------------------------------------------------------ region features

    def region(self, rid: int):
        return self.graph.regions[rid]

    def measure(self) -> None:
        g, n = self.graph, len(self.graph.regions)
        self.in_face_or_ear = np.zeros(n)
        self.in_hair_zone = np.zeros(n)
        self.perimeter = np.zeros(n)
        (fcx, fcy), (frx, fry) = FACE_ZONE
        (hcx, hcy), (hrx, hry), hymax = HAIR_ZONE
        ex0, ex1, ey0, ey1 = EAR_ZONE
        self.head_xy = []
        top = np.full((g.height, g.width), -1, np.int64)          # the visible region per pixel (later folders on top)
        for group in g.groups:
            labels = group.labels
            ys, xs = np.mgrid[0:labels.shape[0], 0:labels.shape[1]]
            hx, hy = g.head(xs + group.origin[0], ys + group.origin[1])
            self.head_xy.append((hx.astype(np.float32), hy.astype(np.float32)))
            x0, y0 = group.origin
            view = top[y0:y0 + labels.shape[0], x0:x0 + labels.shape[1]]
            sub = labels[:view.shape[0], :view.shape[1]]
            view[sub >= 0] = sub[sub >= 0]
        ys, xs = np.mgrid[0:g.height, 0:g.width]
        hx, hy = g.head(xs, ys)
        face = ((hx - fcx) / frx) ** 2 + ((hy - fcy) / fry) ** 2 <= 1
        ear = (hx >= ex0) & (hx <= ex1) & (hy >= ey0) & (hy <= ey1)
        hair = (((hx - hcx) / hrx) ** 2 + ((hy - hcy) / hry) ** 2 <= 1) & (hy < hymax)
        seen = top >= 0
        self.visible = np.bincount(top[seen], minlength=n)[:n] / self.scale ** 2
        self.in_face_or_ear = np.bincount(top[seen & (face | ear)], minlength=n)[:n] / self.scale ** 2
        self.in_hair_zone = np.bincount(top[seen & hair], minlength=n)[:n] / self.scale ** 2
        del top, ys, xs, hx, hy, face, ear, hair, seen
        for group in g.groups:
            labels = group.labels
            if not (labels >= 0).any():
                continue
            padded = np.pad(labels, 1, constant_values=-1)
            core = padded[1:-1, 1:-1]
            for other in (padded[1:-1, 2:], padded[1:-1, :-2], padded[2:, 1:-1], padded[:-2, 1:-1]):
                edge = (core >= 0) & (core != other)
                self.perimeter += np.bincount(core[edge], minlength=n)[:n] / self.scale
        self.adjacent: dict[int, dict[int, float]] = {}
        for gi in range(len(g.groups)):
            for (a, b), length in g.adjacency(gi).items():
                self.adjacent.setdefault(a, {})[b] = length
                self.adjacent.setdefault(b, {})[a] = length

    def thickness(self, rid: int) -> float:
        return 2 * self.region(rid).area / max(self.perimeter[rid], 1e-9)

    def elongation(self, rid: int) -> float:
        """Length over width: the square root of the ratio of the pixel covariance's eigenvalues."""
        group, local = self.graph.mask(rid)
        ys, xs = np.nonzero(local)
        if len(xs) < 3:
            return 1.0
        values = np.linalg.eigvalsh(np.cov(np.stack([xs, ys]).astype(float)))
        return float(np.sqrt(max(values[1], 1e-9) / max(values[0], 1e-9)))

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
        """Regions no rule has named yet (part-folder pools are only free when asked for by id)."""
        if rids is None:
            rids = [r for r in range(len(self.graph.regions)) if r not in self.reserved]
        return [r for r in rids if r not in self.name_of and r not in self.outlines and self.region(r).pixels > 0]

    def is_skin_color(self, color) -> bool:
        return any(same_color(color, c) for c in ([self.skin] if self.skin is not None else []) + self.skin_extra)

    def is_hair_color(self, color) -> bool:
        return any(same_color(color, c) for c in self.hair)

    def could_be_eye_white(self, rid: int, band: bool = True) -> bool:
        x0, x1, y0, y1 = EYE_BAND
        r = self.region(rid)
        return (white_ish(r.flat) and 3 <= r.area <= 400
                and (not band or (x0 <= r.center.x <= x1 and y0 <= r.center.y <= y1)))

    def name(self, rids, name: str) -> None:
        for rid in rids:
            self.name_of[rid] = name

    # ------------------------------------------------------------ colors: skin and hair

    def _classes(self, rids) -> tuple[dict[int, int], list[RGBA]]:
        """Region -> color class (flat colors within SAME_COLOR of a class's first, largest member)."""
        reps, out = [], {}
        for rid in sorted(rids, key=lambda r: -self.region(r).area):
            color = self.region(rid).flat
            for k, c in enumerate(reps):
                if same_color(color, c):
                    out[rid] = k
                    break
            else:
                out[rid] = len(reps)
                reps.append(color)
        return out, reps

    def face_folders(self) -> None:
        """A folder named like a face says what the skin is: its largest color (part hints beat the heuristics)."""
        for group in self.graph.groups:
            if group.hint and folder_kind(group.hint) == "face":
                rids = [r.id for r in self.graph.regions if r.group == group.index and r.pixels]
                if rids:
                    self.skin = self.region(max(rids, key=lambda r: self.region(r).area)).flat
                    return

    def find_skin(self) -> None:
        if self.skin is not None:
            return
        classes, reps = self._classes(self.free())
        score: dict[int, float] = {}
        zone: dict[int, float] = {}
        seen: dict[int, float] = {}
        for rid, cls in classes.items():
            color = self.region(rid).flat
            h, s, v = hsv(color)
            if v < 0.4 or white_ish(color) or s > 0.8:
                continue
            warm = 1.5 if (h <= 50 and 0.1 <= s <= 0.6 and v >= 0.5) else 1.0
            score[cls] = score.get(cls, 0.0) + warm * self.in_face_or_ear[rid]
            zone[cls] = zone.get(cls, 0.0) + self.in_face_or_ear[rid]
            seen[cls] = seen.get(cls, 0.0) + self.visible[rid]
        faces = [c for c in score if score[c] >= SKIN_MIN_SCORE and zone[c] >= SKIN_FACE_SHARE * seen[c]]
        if faces:                                      # most of what shows of a skin is where a face or ear is
            self.skin = reps[max(faces, key=score.get)]

    def _contact(self) -> np.ndarray:
        """Per region: length (head units) of its pixels lying within CONTACT_WIDTH of skin regions."""
        n = len(self.graph.regions)
        out = np.zeros(n)
        skin_regions = [r for r in self.free() if self.is_skin_color(self.region(r).flat)]
        if not skin_regions:
            return out
        skin = self.canvas(skin_regions)
        ring = (ndimage.distance_transform_edt(~skin) <= CONTACT_WIDTH * self.scale) & ~skin
        for group in self.graph.groups:
            x0, y0 = group.origin
            h, w = group.labels.shape
            local = ring[y0:y0 + h, x0:x0 + w] & (group.labels >= 0)
            out += np.bincount(group.labels[local], minlength=n)[:n]
        return out / (CONTACT_WIDTH * self.scale) / self.scale     # pixels in the band / its width -> head units

    def _lock_evidence(self, rids: list[int]) -> bool:
        cut = [r for r in rids if self.region(r).area >= 6 and self.elongation(r) >= LOCK_EVIDENCE_ELONGATION]
        if len(cut) >= 3:                              # locks the line art already cut apart
            return True
        masses, _ = ndimage.label(self.canvas(rids))
        for k, box in enumerate(ndimage.find_objects(masses), start=1):
            piece = masses[box] == k
            if piece.sum() / self.scale ** 2 < HAIR_MIN_AREA:
                continue
            if split_locks(np.pad(piece, 2), self.scale)[0].max() >= 2:
                return True
        return False

    def skin_shade(self, color) -> bool:
        """A shade of the skin painted in the flats (close hue, value and saturation)."""
        if self.skin is None:
            return False
        h0, s0, v0 = hsv(self.skin)
        h, s, v = hsv(color)
        dh = abs(h - h0)
        return (min(dh, 360 - dh) <= SKIN_SHADE_HUE and abs(v - v0) <= SKIN_SHADE_VALUE
                and abs(s - s0) <= SKIN_SHADE_SATURATION)

    def _skin_border(self) -> np.ndarray:
        """Per region: the share of its boundary shared with skin-colored regions."""
        out = np.zeros(len(self.graph.regions))
        for rid, neighbors in self.adjacent.items():
            shared = sum(length for o, length in neighbors.items() if self.is_skin_color(self.region(o).flat))
            out[rid] = shared / max(self.perimeter[rid], 1e-9)
        return out

    def find_hair(self) -> None:
        border = self._skin_border()
        candidates = [r for r in self.free() if not self.is_skin_color(self.region(r).flat)
                      and not self.skin_shade(self.region(r).flat) and not self.could_be_eye_white(r)
                      and border[r] < FACE_FEATURE]
        classes, reps = self._classes(candidates)
        contact = self._contact()
        by_class: dict[int, list[int]] = {}
        for rid, cls in classes.items():
            by_class.setdefault(cls, []).append(rid)
        scored = []
        for cls, rids in by_class.items():
            thick = [r for r in rids if self.thickness(r) >= HAIR_MIN_THICKNESS]
            if sum(self.region(r).area for r in thick) < HAIR_MIN_AREA:
                continue
            score = sum(self.in_hair_zone[r] for r in rids) + HAIR_CONTACT_WEIGHT * sum(contact[r] for r in rids)
            if score >= HAIR_MIN_SCORE:
                scored.append((score, cls, rids))
        primary = next((cls for _, cls, rids in sorted(scored, key=lambda t: -t[0]) if self._lock_evidence(rids)), None)
        if primary is None:
            return
        self.hair = [reps[primary]]
        self._extend_hair(set(by_class[primary]), classes, reps)

    def _extend_hair(self, hair: set[int], classes: dict[int, int], reps: list[RGBA]) -> None:
        """Other flat colors touching the hair with nearly its hue and value (shades drawn in the flats)."""
        h0, s0, v0 = hsv(self.hair[0])
        for rid in list(hair):
            for other in self.adjacent.get(rid, {}):
                if other not in classes:
                    continue
                color = reps[classes[other]]
                h, s, v = hsv(color)
                dh = abs(h - h0)
                if (min(dh, 360 - dh) <= HAIR_HUE_SPREAD and s >= 0.2 and abs(s - s0) <= HAIR_SATURATION_SPREAD
                        and abs(v - v0) <= HAIR_VALUE_SPREAD
                        and not self.is_skin_color(color) and not self.is_hair_color(color)):
                    self.hair.append(color)

    # ------------------------------------------------------------ folders (part hints)

    def folder_hints(self) -> None:
        for group in self.graph.groups:
            kind = folder_kind(group.hint) if group.hint else None
            if kind is None:
                continue
            rids = self.free([r.id for r in self.graph.regions if r.group == group.index])
            if not rids:
                continue
            largest = max(rids, key=lambda r: self.region(r).area)
            if kind == "eye":
                self.find_eyes(rids, band=False)
                for rid in self.free(rids):
                    eye = min(self.eyes, key=lambda e: self._distance(rid, self.eyes[e][0])) if self.eyes else None
                    self.name_of[rid] = eye or ("Eye L" if self.region(rid).center.x < 0 else "Eye R")
                    self.piece_of[rid] = "lid"
                continue
            if kind in ("hair", "back_hair"):
                if not self.is_hair_color(self.region(largest).flat):
                    self.hair.append(self.region(largest).flat)
                if kind == "back_hair":
                    self.name(rids, "Back hair")
                else:
                    self.hair_pool.extend(rids)
                    self.reserved.update(rids)
                continue
            if kind == "accessory":
                self.accessory_pool.extend(rids)
                self.reserved.update(rids)
                continue
            if kind in ("ear", "brow", "horn"):
                for rid in rids:
                    side = "L" if self.region(rid).center.x < HEAD_CENTER_X else "R"
                    self.name_of[rid] = PartName(kind, side).name
                continue
            self.name(rids, PartName(kind).name)

    def _distance(self, a: int, b: int) -> float:
        ca, cb = self.region(a).center, self.region(b).center
        return float(np.hypot(ca.x - cb.x, ca.y - cb.y))

    # ------------------------------------------------------------ eyes

    def find_eyes(self, rids=None, band: bool = True) -> None:
        pool = self.free(rids)
        whites = [r for r in pool if self.could_be_eye_white(r, band)]  # white hair: eye whites share its color
        eyes: list[list[int]] = []
        for rid in sorted(whites, key=lambda r: -self.region(r).area):
            near = [e for e in eyes if self._distance(rid, e[0]) <= 1.2 * np.sqrt(self.region(e[0]).area) + 4]
            if near:
                near[0].append(rid)
            elif len(eyes) < 2:
                eyes.append([rid])
        eyes.sort(key=lambda e: self.region(e[0]).center.x)
        for k, eye in enumerate(eyes):
            side = ("L", "R")[k] if len(eyes) == 2 else ("L" if self.region(eye[0]).center.x < 0 else "R")
            name = PartName("eye", side).name
            if name in self.eyes:
                name = PartName("eye", "R" if side == "L" else "L").name
            if self._eye_pieces(name, eye, pool):
                self.eyes[name] = eye

    def _eye_pieces(self, name: str, eye: list[int], pool: list[int]) -> bool:
        """Name the eye's pieces; an eye needs an iris or a dark piece (else it is not an eye and nothing is named)."""
        boxes = [self._head_box(r) for r in eye]
        bx0, by0 = min(b[0] for b in boxes), min(b[1] for b in boxes)
        bx1, by1 = max(b[2] for b in boxes), max(b[3] for b in boxes)
        grow = max(3.0, 0.6 * max(bx1 - bx0, by1 - by0))
        white_area = sum(self.region(r).area for r in eye)
        members = {r: "white" for r in eye}
        for rid in self.free(pool):
            reg = self.region(rid)
            light = white_ish(reg.flat) or gray_ish(reg.flat)
            if rid in members or self.is_skin_color(reg.flat) or (self.is_hair_color(reg.flat) and not light):
                continue
            hx0, hy0, hx1, hy1 = self._head_box(rid)           # the whole piece lies around the eye
            if not (bx0 - grow - 2 <= hx0 and hx1 <= bx1 + grow + 2 and by0 - grow - 2 <= hy0 and hy1 <= by1 + grow + 2):
                continue
            if hy1 < by0 and (hx1 - hx0) >= BROW_RATIO * max(hy1 - hy0, 1e-9):
                continue                                         # wholly above the white and wide: a brow
            if reg.area > 3 * white_area + 20:
                continue
            if white_ish(reg.flat) or gray_ish(reg.flat):
                members[rid] = "white"
            elif colored(reg.flat):
                members[rid] = "iris"
            elif dark(reg.flat):
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
            inside_iris = bool(irises) and ix0 <= reg.center.x <= ix1 and iy0 <= reg.center.y <= iy1
            if piece == "dark":
                members[rid] = "pupil" if inside_iris and reg.area < 0.6 * iris_area else "lid"
            elif rid != eye[0] and inside_iris and reg.area < 0.25 * iris_area and (
                    white_ish(reg.flat) or hsv(reg.flat)[2] >= iris_v + 0.3):
                members[rid] = "highlight"
        if not any(p in ("iris", "pupil", "lid") for p in members.values()):
            return False
        for rid, piece in members.items():
            self.name_of[rid] = name
            self.piece_of[rid] = piece
        return True

    def _head_box(self, rid: int) -> tuple[float, float, float, float]:
        x0, y0, x1, y1 = self.region(rid).box
        hx, hy = self.graph.head(np.array([x0, x1 - 1, x0, x1 - 1]), np.array([y0, y0, y1 - 1, y1 - 1]))
        return float(hx.min()), float(hy.min()), float(hx.max()), float(hy.max())

    # ------------------------------------------------------------ the rest of the taxonomy

    def hold_outlines(self) -> None:
        for rid in self.free():
            if dark(self.region(rid).flat) and self.thickness(rid) < OUTLINE_THICKNESS:
                self.outlines.append(rid)

    def skin_parts(self) -> None:
        skin = [r for r in self.free() if self.is_skin_color(self.region(r).flat)]
        faces = set()
        for group in self.graph.groups:
            mine = [r for r in skin if self.region(r).group == group.index]
            if mine:
                largest = max(mine, key=lambda r: self.region(r).area)
                if self.region(largest).area >= FACE_MIN_AREA:
                    faces.add(largest)
        for rid in skin:
            reg = self.region(rid)
            x0, x1, y0, y1 = NOSE_ZONE
            if rid in faces:
                self.name_of[rid] = "Face"
            elif reg.area >= EAR_MIN_AREA and (reg.center.x < -EAR_X or reg.center.x > EAR_X):
                self.name_of[rid] = "Ear L" if reg.center.x < -EAR_X else "Ear R"
            elif LEFTOVER_AREA <= reg.area <= NOSE_MAX_AREA and x0 <= reg.center.x <= x1 and y0 <= reg.center.y <= y1:
                self.name_of[rid] = "Nose"
            else:
                self.name_of[rid] = "Face"

    def brows(self) -> None:
        for name, whites in self.eyes.items():
            boxes = [self._head_box(r) for r in whites]
            top, ex0, ex1 = min(b[1] for b in boxes), min(b[0] for b in boxes), max(b[2] for b in boxes)
            side = name.split()[1]
            for rid in self.free():
                reg = self.region(rid)
                if self.is_skin_color(reg.flat) or reg.area > BROW_MAX_AREA:
                    continue
                c = reg.center
                bx0, by0, bx1, by1 = self._head_box(rid)
                if (top - 10 <= c.y <= top + 1 and ex0 - 6 <= c.x <= ex1 + 6
                        and (bx1 - bx0) >= BROW_RATIO * max(by1 - by0, 1e-9)):
                    self.name_of[rid] = "Brow " + side

    def mouth_and_nose(self) -> None:
        mx0, mx1, my0, my1 = MOUTH_ZONE
        nx0, nx1, ny0, ny1 = NOSE_ZONE
        for rid in self.free():
            reg = self.region(rid)
            if self.is_skin_color(reg.flat) or self.is_hair_color(reg.flat):
                continue
            c = reg.center
            if reg.area <= MOUTH_MAX_AREA and mx0 <= c.x <= mx1 and my0 <= c.y <= my1:
                self.name_of[rid] = "Mouth"
            elif reg.area <= NOSE_MAX_AREA and nx0 <= c.x <= nx1 and ny0 <= c.y <= ny1:
                self.name_of[rid] = "Nose"

    def force_assignments(self) -> None:
        """Corrections, before lock splitting: a region marked Hair is split into locks like detected hair; any other
        name is final."""
        for n, a in enumerate(self.corrections.assign, start=1):
            region = self.graph.region_at(*a.at)
            if region is None:
                continue
            self.forced[region.id] = (a.part, a.piece)
            kind = PartName.parse(a.part).kind
            if kind in ("hair", "lock", "back_hair") and not self.is_hair_color(region.flat):
                self.hair.append(region.flat)            # the user says this color is hair
            if kind in ("face", "ear", "nose") and not self.is_skin_color(region.flat):
                self.skin_extra.append(region.flat)
            self.name_of.pop(region.id, None)
            self.piece_of.pop(region.id, None)
            if region.id in self.outlines:
                self.outlines.remove(region.id)
            if a.part != "Hair":
                self.name_of[region.id] = a.part
                if a.piece:
                    self.piece_of[region.id] = a.piece

    def hair_and_locks(self) -> None:
        pool = set(self.hair_pool) | {r for r in self.free() if self.is_hair_color(self.region(r).flat)}
        pool |= {r for r, (name, _) in self.forced.items() if name == "Hair"}
        pool = {r for r in pool if self.region(r).pixels > 0}
        for rid in pool:
            self.name_of.pop(rid, None)
        if not pool:
            return
        hair_area = sum(self.region(r).area for r in pool)
        for group in self.graph.groups:
            mine = [r for r in pool if self.region(r).group == group.index]
            if not mine:
                continue
            wanted = np.zeros(len(self.graph.regions) + 1, bool)
            wanted[mine] = True
            masses, count = ndimage.label(wanted[group.labels])
            for k, box in enumerate(ndimage.find_objects(masses), start=1):
                if box is None:
                    continue
                y0, x0 = max(0, box[0].start - 2), max(0, box[1].start - 2)
                y1, x1 = box[0].stop + 2, box[1].stop + 2
                mass = masses[y0:y1, x0:x1] == k
                pieces, _ = split_locks(mass, self.scale)
                if pieces.max() == 0:
                    continue
                full = np.zeros(group.labels.shape, np.int32)
                full[y0:y1, x0:x1] = pieces
                new_locks: dict[int, list[int]] = {}
                for rid in [r for r in mine if (masses[group.labels == r] == k).any()]:
                    ks = [int(v) for v in np.unique(full[group.labels == rid]) if v > 0]
                    if not ks:
                        continue
                    ids = self.graph.split(rid, full)
                    for piece_k, new in zip(ks, ids):
                        new_locks.setdefault(piece_k, []).append(new)
                for regions in new_locks.values():
                    self.locks.append(regions)
                    pool.difference_update(regions)
        if self.locks:
            self.measure()                                  # features of the regions the cuts made
        in_locks = {r for lock in self.locks for r in lock}
        for rid in sorted(pool - in_locks):
            reg = self.region(rid)
            if (reg.pixels and LockSettings().min_area <= reg.area <= LOCK_MAX_FRACTION * hair_area
                    and self.elongation(rid) >= LOCK_ELONGATION):
                self.locks.append([rid])
            else:
                self.name_of[rid] = "Hair"
        for lock in self.locks:
            self.name(lock, "Lock ?")

    def horns(self) -> None:
        total = sum(r.area for r in self.graph.regions)
        for rid in self.free():
            reg = self.region(rid)
            if (self.is_skin_color(reg.flat) or self.is_hair_color(reg.flat) or reg.area > HORN_MAX_AREA
                    or reg.area < HORN_MIN_AREA):
                continue
            if reg.center.y >= 0 or self.elongation(rid) < HORN_ELONGATION:
                continue
            touching = [o for o in self.adjacent.get(rid, {}) if o != rid and (
                self.name_of.get(o, "").startswith(("Hair", "Lock", "Face"))
                or self.region(o).area >= HELM_MIN_FRACTION * total)]
            if touching:
                self.name_of[rid] = "Horn L" if reg.center.x < HEAD_CENTER_X else "Horn R"

    def inside_face(self) -> None:
        for rid in self.free():
            shared = sum(length for o, length in self.adjacent.get(rid, {}).items() if self.name_of.get(o) == "Face")
            if self.perimeter[rid] > 0 and shared >= INSIDE_FACE * self.perimeter[rid]:
                self.name_of[rid] = "Face"

    def helm(self) -> None:
        total = sum(r.area for r in self.graph.regions)
        helm = [r for r in self.free() if self.region(r).center.y < HELM_MAX_Y
                and self.region(r).area >= HELM_MIN_FRACTION * total]
        self.name(helm, "Helm")
        grew = True
        while grew:
            grew = False
            for rid in self.free():
                reg = self.region(rid)
                if reg.center.y >= HELM_MAX_Y:
                    continue
                if any(self.name_of.get(o) == "Helm" and reg.area >= HELM_GROW_FRACTION * self.region(o).area
                       for o in self.adjacent.get(rid, {})):
                    self.name_of[rid] = "Helm"
                    grew = True

    def accessories(self) -> None:
        rest = set(self.free()) | set(self.free(self.accessory_pool))
        groups = []
        while rest:
            stack, comp = [rest.pop()], []
            while stack:
                rid = stack.pop()
                comp.append(rid)
                for o in self.adjacent.get(rid, {}):
                    if o in rest:
                        rest.discard(o)
                        stack.append(o)
            if sum(self.region(r).area for r in comp) < LEFTOVER_AREA and not set(comp) & set(self.accessory_pool):
                shared: dict[str, float] = {}               # a sliver left over (a tip cut off by its outline)
                for rid in comp:                            # joins the part it borders most
                    for o, length in self.adjacent.get(rid, {}).items():
                        if o in self.name_of and self.name_of[o] != "Lock ?":
                            shared[self.name_of[o]] = shared.get(self.name_of[o], 0.0) + length
                if shared:
                    self.name(comp, max(shared, key=shared.get))
                    continue
            groups.append(comp)
        loose = [c for c in groups if not set(c) & set(self.accessory_pool)]
        if len(loose) > MAX_ACCESSORIES:                    # a sketch or a busy drawing: not accessories
            for comp in loose:
                self.name(comp, "Helm")
            groups = [c for c in groups if c not in loose]
            self.notes.append("%d small pieces were left over; they stay together in Helm (a correction can make any "
                              "of them an accessory)" % len(loose))
        used = {PartName.parse(n).index for n in set(self.name_of.values()) | {f[0] for f in self.forced.values()}
                if n.startswith("Accessory")}
        k = 0
        for comp in sorted(groups, key=lambda c: min(self.region(r).center.x for r in c)):
            k += 1
            while k in used:
                k += 1
            self.name(comp, "Accessory %d" % k)

    def join_outlines(self) -> None:
        leftover = []
        for rid in list(self.outlines):
            shared = {o: length for o, length in self.adjacent.get(rid, {}).items() if o in self.name_of}
            neighbors = [o for o, length in shared.items() if length >= OUTLINE_NEIGHBOR * max(shared.values())]
            if neighbors:
                best = max(neighbors, key=lambda o: self._z(self.name_of[o], rid))
                self.name_of[rid] = self.name_of[best]
                self.joined_outlines.add(rid)
                for lock in self.locks:
                    if best in lock:
                        lock.append(rid)
            else:
                leftover.append(rid)                    # outlines touching no part are left over like any region
        self.outlines = []
        if leftover:
            self.accessories()

    def _z(self, name: str, rid: int) -> tuple:
        if name == "Lock ?":
            return (self.region(rid).group, *PartName("lock", index=1).z)
        return (self.region(rid).group, *PartName.parse(name).z)

    def final_assignments(self) -> None:
        for n, a in enumerate(self.corrections.assign, start=1):
            region = self.graph.region_at(*a.at)
            if region is None:
                self.notes.append("Correction %d at (%g, %g) is not on any region; skipped" % (n, a.at[0], a.at[1]))
                continue
            self.name_of[region.id] = a.part
            self.piece_of.pop(region.id, None)
            if a.piece:
                self.piece_of[region.id] = a.piece

    # ------------------------------------------------------------ pivots, names, locations

    def _anchor_mean(self, rids: list[int], anchors: set[int]) -> Point | None:
        """Mean head position of the part's pixels that touch the anchor regions."""
        xs, ys = [], []
        for group in self.graph.groups:
            mine = [r for r in rids if self.region(r).group == group.index]
            if not mine:
                continue
            labels = group.labels
            own = np.isin(labels, mine)
            anchor = np.isin(labels, list(anchors))
            near = np.zeros_like(own)
            near[:, 1:] |= anchor[:, :-1]
            near[:, :-1] |= anchor[:, 1:]
            near[1:, :] |= anchor[:-1, :]
            near[:-1, :] |= anchor[1:, :]
            touch = own & near
            hx, hy = self.head_xy[group.index]
            xs.append(hx[touch])
            ys.append(hy[touch])
        if not xs or not sum(len(x) for x in xs):
            return None
        return Point(float(np.concatenate(xs).mean()), float(np.concatenate(ys).mean()))

    def _centroid(self, rids: list[int]) -> Point:
        weights = np.array([self.region(r).pixels for r in rids], float)
        xs = np.array([self.region(r).center.x for r in rids])
        ys = np.array([self.region(r).center.y for r in rids])
        total = max(weights.sum(), 1e-9)
        return Point(float((xs * weights).sum() / total), float((ys * weights).sum() / total))

    def _far_point(self, rids: list[int], origin: Point) -> Point:
        best, best_d = origin, -1.0
        for group in self.graph.groups:
            mine = [r for r in rids if self.region(r).group == group.index]
            if not mine:
                continue
            own = np.isin(group.labels, mine)
            hx, hy = self.head_xy[group.index]
            d = (hx - origin.x) ** 2 + (hy - origin.y) ** 2
            d = np.where(own, d, -1)
            i = int(np.argmax(d))
            if d.flat[i] > best_d:
                best_d, best = float(d.flat[i]), Point(float(hx.flat[i]), float(hy.flat[i]))
        return best

    def _regions_named(self, *prefixes) -> set[int]:
        return {r for r, n in self.name_of.items() if n.startswith(prefixes)}

    def pivots(self, parts: dict[str, Part]) -> None:
        for name, part in parts.items():
            anchors: set[int] = set()
            if part.kind == "lock":
                anchors = self._regions_named("Hair", "Helm")
            elif part.kind == "ear":
                anchors = self._regions_named("Face")
            elif part.kind == "horn":
                anchors = self._regions_named("Hair", "Helm", "Face")
            elif part.kind == "accessory":
                shared: dict[str, float] = {}
                for rid in part.regions:
                    for o, length in self.adjacent.get(rid, {}).items():
                        other = self.name_of.get(o)
                        if other and other != name:
                            shared[other] = shared.get(other, 0.0) + length
                if shared:
                    best = max(shared, key=shared.get)
                    anchors = {r for r, n in self.name_of.items() if n == best}
            if part.kind == "eye":
                ball = [r for r in part.regions if self.piece_of.get(r) in ("white", "iris", "pupil", "highlight")]
                part.pivot = self._centroid(ball or part.regions)
            elif anchors:
                part.pivot = self._anchor_mean(part.regions, anchors - set(part.regions)) or self._centroid(part.regions)
            else:
                part.pivot = self._centroid(part.regions)
            if part.kind == "lock":
                part.tip = self._far_point(part.regions, part.pivot)

    def number_locks(self) -> None:
        """Automatic locks are numbered left to right by root x, skipping numbers the user gave."""
        used = {PartName.parse(n).index for n in self.name_of.values() if n.startswith("Lock ") and n != "Lock ?"}
        hair = self._regions_named("Hair", "Helm")
        roots = []
        for lock in self.locks:
            lock = [r for r in lock if self.name_of.get(r) == "Lock ?"]
            if lock:
                root = self._anchor_mean(lock, hair) or self._centroid(lock)
                roots.append((root.x, lock))
        k = 0
        for _, lock in sorted(roots, key=lambda t: t[0]):
            k += 1
            while k in used:
                k += 1
            self.name(lock, "Lock %d" % k)

    def locations(self) -> dict[int, str | None]:
        out = {}
        for rid, name in self.name_of.items():
            kind = PartName.parse(name).kind
            color = self.region(rid).flat
            location = default_location(kind, self.piece_of.get(rid))
            if location == "Skin" and not self.is_skin_color(color):
                location = None
            if location == "Hair" and not self.is_hair_color(color):
                location = None
            out[rid] = location
        return out

    def part_map(self) -> PartMap:
        self.number_locks()
        for rid in list(self.name_of):
            if PartName.parse(self.name_of[rid]).kind != "eye":
                self.piece_of.pop(rid, None)
        parts: dict[str, Part] = {}
        for rid in sorted(self.name_of):
            if self.region(rid).pixels == 0:
                continue
            name = self.name_of[rid]
            if name not in parts:
                pn = PartName.parse(name)
                parts[name] = Part(name, pn.kind, pn.side, pn.index, [], (self.region(rid).group,) + pn.z)
            parts[name].regions.append(rid)
        ordered = dict(sorted(parts.items(), key=lambda kv: kv[1].z))
        self.pivots(ordered)
        location_of = self.locations()
        colors = dict(self.corrections.colors)
        if "Hair" in colors:                             # the hair's slot is its locks' slot too
            for name in ordered:
                if name.startswith("Lock "):
                    colors.setdefault(name, colors["Hair"])
        kept = False
        for part_name, location in colors.items():
            if part_name not in ordered:
                if part_name in self.corrections.colors:
                    self.notes.append("Color for '%s' skipped: there is no such part" % part_name)
                continue
            for rid in ordered[part_name].regions:
                if location != NO_COLOR and (self.piece_of.get(rid) in NEVER_COLORED or rid in self.joined_outlines):
                    kept = True
                    continue
                location_of[rid] = None if location == NO_COLOR else location
        if kept:
            self.notes.append("Eye whites, pupils, highlights, lids and outlines keep their colors (color slots only "
                              "recolor the rest of a part)")
        if self.skin is None:
            self.notes.append(NO_SKIN_NOTE)
        if not self.hair:
            self.notes.append(NO_HAIR_NOTE)
        names = {rid: n for rid, n in self.name_of.items() if self.region(rid).pixels > 0}
        return PartMap(self.graph, ordered, names, dict(self.piece_of), location_of, self.skin, list(self.hair),
                       self.notes)


def detect_parts(passes: Passes, alignment: Alignment, corrections: Corrections = Corrections(),
                 detail: int = 50) -> PartMap:
    graph = build_regions(passes, alignment, corrections.cuts, detail_settings(detail).min_area)
    d = _Detector(graph, corrections)
    d.measure()
    d.face_folders()
    d.find_skin()
    d.find_hair()
    d.folder_hints()
    d.find_eyes()
    d.hold_outlines()
    d.skin_parts()
    d.brows()
    d.mouth_and_nose()
    d.force_assignments()
    d.hair_and_locks()
    d.horns()
    d.inside_face()
    d.helm()
    d.accessories()
    d.join_outlines()
    d.final_assignments()
    return d.part_map()
