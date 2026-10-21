"""Each part's own passes (spec §9.3): line and detail pixels go to the part they outline, the parts that stay (face,
hair base, helm) continue under the parts that move (eyes, locks, ears, accessories) and every part reaches 2 px under
the parts above it, copying its own nearest pixels so the hidden fill is already on the palette. Eyes become three
layers (ball, lash, lid) so Blink can fade the ball and move the lid; any other part painted in several folders becomes
one layer per folder, each in its folder's place (the largest keeps the part's name, the others add the folder's)."""
from dataclasses import dataclass, field

import numpy as np
from scipy import ndimage

from autoswf.drawing.passes import PartPasses, Passes, ToneCoverage
from autoswf.model.geometry import Point
from autoswf.parts.detect import Part, PartMap
from autoswf.parts.model import MOVING, PROVIDERS
from autoswf.parts.regions import RGBA

UNDERLAP = 2                                       # px a lower part's line art reaches under the lines above it
UNDERLAP_UNITS = 1.5                               # head units a lower part's fill reaches under the parts above it
SILHOUETTE_MARGIN = 2                              # px: underlaps stay this far inside the drawing's silhouette
BALL_PIECES = ("white", "iris", "pupil", "highlight")
SOLID = 0.99                                       # flats alpha of the pixels hidden fills copy from
CORE_DEPTH = 2                                     # px inside a part's edge where those pixels start
STRAY_COLOR = 40                                   # a part's own pixel this far from its region's flat color is a
                                                   # sliver merged into it (under line art): refilled inside holes
EYE_RING_UNITS = 1.5                               # head units: outlines inside the eye opening closer than this to
                                                   # the ball on both sides (the ring around an iris) go with the ball
SILHOUETTE_UNITS = 1.0                             # head units: a line at most this wide between an eye and the empty
                                                   # canvas is the head's silhouette, the outline of the part under it
OPENING_WIDTHS = 4                                 # outline widths: radius of the disk opening the silhouette, which
                                                   # cuts off line art poking out past it (lids, lashes)
EDGE_BAND_UNITS = 2.0                              # head units of an edge just outside a hole that give its direction
EDGE_GAP = 2                                       # px next to a hole whose classes are redone (slivers hugging it)
HEAD_ON = 0.42                                     # cos 65 degrees: a line meets a hole head-on (it goes on under it)
EDGE_FACING = 0.77                                 # cos 40 degrees: line ends joined across a hole point at each other
EDGE_MAJORITY = 0.6                                # share of a hole piece's border that gives the piece its class
N4 = np.array([[0, 1, 0], [1, 1, 1], [0, 1, 0]], bool)


@dataclass(eq=False)
class PartLayer:
    name: str                                      # "Lock 3", "Eye L ball"
    parent: str | None                             # "Eye L" for an eye's sub-layers
    kind: str
    passes: PartPasses                             # part = name
    locations: list[tuple[RGBA, str]]              # flat colors of its colorable regions -> location
    soft_roles: frozenset[str]
    pivot: Point                                   # head-local px
    back_hair: bool


@dataclass(eq=False)
class _Unit:
    name: str                                      # "Lock 3", "Eye L ball", "Hair (Bangs)"
    parent: str | None
    part: Part
    group: int                                     # the group its passes come from
    regions: list[int]
    ext: list[tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]] = field(default_factory=list)  # ys, xs, sy, sx
    lines: np.ndarray | None = None                # canvas bool
    details: np.ndarray | None = None
    line_ext: list[tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]] = field(default_factory=list)  # hidden lines


def _paste_over(canvas: np.ndarray, array: np.ndarray, origin) -> None:
    x0, y0 = origin
    h, w = array.shape[:2]
    view = canvas[y0:y0 + h, x0:x0 + w]
    view[:] = array + view * (1 - array[..., 3:4])


def _continued(codes: np.ndarray, hole: np.ndarray, band: float, strokes: np.ndarray | None = None,
               stroke_ends: tuple = ()) -> np.ndarray:
    """Classes for a hole's pixels that continue the edges between the classes around it (a shadow's edge, the head's
    silhouette): each edge that runs into the hole head-on is joined to the matching one across the hole by a smooth
    curve leaving and arriving the way the edges go, and each piece of the hole between those curves takes the class
    of the border it touches. A piece whose border stays mixed (an edge found no partner) takes each pixel's nearest
    class, as do pixels away from every edge. Slivers hugging the hole (EDGE_GAP px) take the classes beyond them.
    Line art continued under the hole (`strokes`, with its `stroke_ends`) splits it too, and an edge that runs in along
    such line art (an outline on the silhouette) follows it instead of a curve of its own."""
    known = ~hole
    dist = ndimage.distance_transform_edt(known)                  # known pixels: how far from the hole
    beyond = known & (dist > EDGE_GAP)
    if beyond.any():
        _, (iy, ix) = ndimage.distance_transform_edt(~beyond, return_indices=True)
        codes = np.where(known & ~beyond, codes[iy, ix], codes)
    h, w = codes.shape
    edge = np.zeros_like(hole)
    for dy, dx in ((0, 1), (1, 0)):
        d = known[:h - dy, :w - dx] & known[dy:, dx:] & (codes[:h - dy, :w - dx] != codes[dy:, dx:])
        edge[:h - dy, :w - dx] |= d
        edge[dy:, dx:] |= d
    _, (iy, ix) = ndimage.distance_transform_edt(hole, return_indices=True)
    out = np.where(hole, codes[iy, ix], codes)
    ends = []
    for at, direction in _entries(edge, hole, band, EDGE_GAP, dist):
        normal = np.array([direction[1], -direction[0]])          # its left on a canvas whose y grows downward
        sides = []
        for sign in (1.0, -1.0):
            q = at - direction * np.linspace(EDGE_GAP + 1.0, max(EDGE_GAP + 1.0, band / 2), 6)[:, None]
            q = (q[:, None, :] + sign * normal * np.array([2.0, 3.0, 4.0])[None, :, None]).reshape(-1, 2)
            qx, qy = np.round(q[:, 0]).astype(int), np.round(q[:, 1]).astype(int)
            ok = (qx >= 0) & (qx < w) & (qy >= 0) & (qy < h)
            found = codes[qy[ok], qx[ok]][known[qy[ok], qx[ok]]]
            sides.append(int(np.bincount(found).argmax()) if len(found) else -1)
        if min(sides) >= 0 and sides[0] != sides[1] and not any(
                np.hypot(*(at - e[0])) <= e[4] + EDGE_GAP + 1 for e in stroke_ends):
            ends.append((at, direction, sides[0], sides[1]))
    walls = np.zeros_like(hole) if strokes is None else strokes & hole
    for a, b in _joined(ends, band, hole):
        walls |= _curve(ends[a], ends[b], hole.shape)
    walls &= hole
    pieces, _ = ndimage.label(hole & ~walls, structure=N4)
    border = known & ndimage.binary_dilation(hole, structure=N4)
    for k, sl in enumerate(ndimage.find_objects(pieces), start=1):
        if sl is None:
            continue
        sl = tuple(slice(max(0, s.start - 1), s.stop + 1) for s in sl)
        piece = pieces[sl] == k
        touching = codes[sl][ndimage.binary_dilation(piece, structure=N4) & border[sl]]
        if len(touching):
            counts = np.bincount(touching)
            if counts.max() >= EDGE_MAJORITY * len(touching):
                out[sl][piece] = counts.argmax()
    filled = hole & ~walls
    if walls.any() and filled.any():                              # the curves themselves: as the piece beside them
        _, (iy, ix) = ndimage.distance_transform_edt(~filled, return_indices=True)
        out[walls] = out[iy[walls], ix[walls]]
    return out


def _continued_strokes(strokes: np.ndarray, hole: np.ndarray, band: float) -> tuple[np.ndarray, list]:
    """The hole's pixels where line art (`strokes`, outside the hole) goes on under it: each stroke that runs into the
    hole head-on is joined to another one across it by a smooth curve as wide as the strokes, drawn where the strokes
    do not draw it already (an outline going on along the hole's border, which the curve follows there). Also returns
    the joined ends (point, direction, -1, -1, half width)."""
    ys, xs = np.nonzero(strokes)
    ends = []
    for at, direction in _entries(strokes, hole, band):
        behind = (xs - at[0]) * direction[0] + (ys - at[1]) * direction[1] <= 0
        near = np.count_nonzero(behind & (np.hypot(xs - at[0], ys - at[1]) <= band))  # a stroke w px wide crosses
        ends.append((at, direction, -1, -1, near / (2 * band)))           # about w * band of these before its end
    out = np.zeros_like(hole)
    joined = []
    cover = ndimage.distance_transform_edt(~strokes)
    for a, b in _joined(ends, band, hole):
        half = max(0.5, (ends[a][4] + ends[b][4]) / 2)                # the strokes' half width
        cy, cx = _curve_points(ends[a], ends[b], hole.shape)
        off, _ = ndimage.label(cover[cy, cx] > half)                  # stretches off the strokes as drawn that leave
        gaps = np.unique(off[cover[cy, cx] > half + 1])               # them, not ones wobbling beside them
        bare = np.isin(off, gaps[gaps > 0])
        if bare.any():
            curve = np.zeros_like(hole)
            curve[cy[bare], cx[bare]] = True
            out |= ndimage.distance_transform_edt(~curve) <= half
        joined += [ends[a], ends[b]]
    return out & hole, joined


def _entries(lines: np.ndarray, hole: np.ndarray, band: float, skip: int = 0, dist: np.ndarray | None = None) -> list:
    """Where `lines` (an edge between classes, or line art) run into the hole head-on, as opposed to running along its
    border: (the point where they meet it, unit direction into the hole) in pixel coordinates (x, y). At each pixel
    touching the hole, the way the line goes is fitted to the same line's pixels around it and the hole's border is
    taken smoothed, so a line ending in a corner of the hole still meets it head-on. Pixels within `skip` of the hole
    are left out of the fit (classes redone there)."""
    known = ~hole
    if dist is None:
        dist = ndimage.distance_transform_edt(known)
    contact = lines & known & (dist <= 1.5)
    if not contact.any():
        return []
    soft = ndimage.gaussian_filter(hole.astype(np.float32), EDGE_GAP + 1.0)
    gy, gx = np.gradient(soft)                                     # uphill: toward the hole
    pieces, _ = ndimage.label(lines & known, structure=np.ones((3, 3)))
    h, w = lines.shape
    r = max(3, int(np.ceil(band)))
    entry = np.zeros_like(hole)
    into = np.zeros(hole.shape + (2,))
    for y, x in zip(*np.nonzero(contact)):
        toward = np.array([gx[y, x], gy[y, x]], float)
        length = float(np.hypot(*toward))
        if length == 0:
            continue
        toward /= length
        y0, y1, x0, x1 = max(0, y - r), min(h, y + r + 1), max(0, x - r), min(w, x + r + 1)
        by, bx = np.nonzero((pieces[y0:y1, x0:x1] == pieces[y, x]) & (dist[y0:y1, x0:x1] > skip))
        if len(by) < 3:
            continue
        points = np.stack([bx + x0, by + y0], axis=1).astype(float)
        spread, axes = np.linalg.eigh(np.cov(points.T))
        if spread[1] < 2 * spread[0]:                              # not a line here
            continue
        t = axes[:, 1]
        along = float(np.dot(t, toward))
        if abs(along) >= HEAD_ON:
            entry[y, x] = True
            into[y, x] = t if along > 0 else -t
    labels, _ = ndimage.label(entry, structure=np.ones((3, 3)))
    out = []
    for k, sl in enumerate(ndimage.find_objects(labels), start=1):
        if sl is None:
            continue
        py, px = np.nonzero(labels[sl] == k)
        py, px = py + sl[0].start, px + sl[1].start
        direction = into[py, px].mean(axis=0)
        length = float(np.hypot(*direction))
        if length >= 0.5:
            out.append((np.array([px.mean(), py.mean()]), direction / length))
    return out


def _joined(ends: list, band: float, hole: np.ndarray) -> list[tuple[int, int]]:
    """The line ends to join across the hole: pointing at each other, their curve mostly inside the hole and, for edges
    between classes, the same two classes on swapped sides (one edge going on); the straightest pairs first, then the
    closest."""
    pairs = []
    for i in range(len(ends)):
        for j in range(i + 1, len(ends)):
            pa, da, la, ra = ends[i][:4]
            pb, db, lb, rb = ends[j][:4]
            if la != rb or ra != lb:
                continue
            gap = pb - pa
            length = float(np.hypot(*gap))
            if length < 2:
                continue
            ca, cb = float(np.dot(da, gap / length)), float(np.dot(db, -gap / length))
            if ca >= EDGE_FACING and cb >= EDGE_FACING:
                if hole[_curve_points(ends[i], ends[j], hole.shape)].mean() >= 0.5:
                    pairs.append((2 - ca - cb + 0.05 * length / band, i, j))
    used, out = set(), []
    for _, i, j in sorted(pairs):
        if i not in used and j not in used:
            used |= {i, j}
            out.append((i, j))
    return out


def _curve_points(a, b, shape) -> tuple[np.ndarray, np.ndarray]:
    """The pixels (ys, xs) of a cubic curve leaving end a the way its line goes and arriving at end b the way its line
    comes."""
    (pa, da), (pb, db) = a[:2], b[:2]
    length = float(np.hypot(*(pb - pa)))
    c1, c2 = pa + da * length / 3, pb + db * length / 3
    t = np.linspace(0.0, 1.0, int(length * 4) + 2)[:, None]
    p = (1 - t) ** 3 * pa + 3 * (1 - t) ** 2 * t * c1 + 3 * (1 - t) * t ** 2 * c2 + t ** 3 * pb
    h, w = shape
    return np.clip(np.round(p[:, 1]).astype(int), 0, h - 1), np.clip(np.round(p[:, 0]).astype(int), 0, w - 1)


def _curve(a, b, shape) -> np.ndarray:
    out = np.zeros(shape, bool)
    out[_curve_points(a, b, shape)] = True
    return out


def _thick(lines: np.ndarray, width: float) -> np.ndarray:
    """The line art wider than `width` px (what survives an opening by a disk of half that width)."""
    r = max(1, int(round(width / 2)))
    yy, xx = np.mgrid[-r:r + 1, -r:r + 1]
    opened = ndimage.binary_opening(np.pad(lines, r + 1), structure=xx * xx + yy * yy <= r * r)
    return opened[r + 1:-r - 1, r + 1:-r - 1]


def _box(*masks, pad: int = 0, shape=None) -> tuple[int, int, int, int] | None:
    ys, xs = [], []
    for m in masks:
        if m is None:
            continue
        y, x = np.nonzero(m)
        ys.append(y)
        xs.append(x)
    if not ys or not sum(len(y) for y in ys):
        return None
    ys, xs = np.concatenate(ys), np.concatenate(xs)
    h, w = shape
    return (max(0, int(xs.min()) - pad), max(0, int(ys.min()) - pad), min(w, int(xs.max()) + 1 + pad),
            min(h, int(ys.max()) + 1 + pad))


class _Splitter:
    def __init__(self, passes: Passes, parts: PartMap):
        self.passes, self.parts, self.graph = passes, parts, parts.graph
        self.h, self.w = self.graph.height, self.graph.width
        # wide enough to stay a full pixel at the smallest zoom (one pixel per head unit), so shapes never just touch
        self.reach = max(UNDERLAP, int(np.ceil(UNDERLAP_UNITS * self.graph.scale)))
        drawn = passes.full[..., 3] > 0.02
        self.inside = ndimage.distance_transform_edt(drawn) >= SILHOUETTE_MARGIN
        self.units: list[_Unit] = []
        used = set(parts.parts)
        for part in parts.parts.values():
            if part.kind == "eye":
                group = self.graph.regions[part.regions[0]].group
                ball = [r for r in part.regions if parts.piece_of.get(r) in BALL_PIECES]
                lid = [r for r in part.regions if r not in ball]
                for sub, regions in (("ball", ball), ("lash", lid), ("lid", lid)):
                    self.units.append(_Unit("%s %s" % (part.name, sub), part.name, part, group, regions))
                continue
            by_group: dict[int, list[int]] = {}
            for r in part.regions:
                by_group.setdefault(self.graph.regions[r].group, []).append(r)
            main = max(by_group, key=lambda g: sum(self.graph.regions[r].pixels for r in by_group[g]))
            for g, regions in sorted(by_group.items()):
                name = part.name
                if g != main:
                    hint = self.graph.groups[g].hint
                    base = name = "%s (%s)" % (part.name, hint or "folder %d" % (g + 1))
                    k = 2
                    while name in used:
                        name, k = "%s %d" % (base, k), k + 1
                    used.add(name)
                self.units.append(_Unit(name, None, part, g, regions))
        self.units.sort(key=lambda u: (u.group,) + tuple(u.part.z[1:]))   # bottom to top, later folders above
        self.unit_of_part = {}
        for i, u in enumerate(self.units):
            self.unit_of_part.setdefault(u.part.name, []).append(i)
        self.eyes = {name: idx for name, idx in self.unit_of_part.items() if parts.parts[name].kind == "eye"}
        self.owners: list[list[int]] = []                  # units sharing line art, bottom to top: an eye's three
        for i, u in enumerate(self.units):                 # layers, else each unit alone
            if u.parent is None:
                self.owners.append([i])
            elif self.unit_of_part[u.parent][0] == i:
                self.owners.append(list(self.unit_of_part[u.parent]))
        self._bits: dict[int, np.ndarray] = {}
        self._own_maps()

    # ------------------------------------------------------------ own pixels

    def _own_maps(self) -> None:
        """Per group: the unit owning each pixel (eye lid regions split at the ball's center row); on the canvas: the
        topmost unit per pixel."""
        n_regions = len(self.graph.regions)
        unit_of_region = np.full(n_regions + 1, -1, np.int32)
        for i, u in enumerate(self.units):
            if u.name.endswith(" lid"):
                continue                                   # lid regions are split by row below
            unit_of_region[u.regions] = i
        self.group_units = [unit_of_region[g.labels] for g in self.graph.groups]
        self.center_row = {}
        for part_name, idx in self.eyes.items():
            ball, lash, lid = idx
            group = self.graph.groups[self.units[ball].group]
            local = np.isin(group.labels, self.units[ball].regions)
            ys = np.nonzero(local)[0]
            row = float(ys.mean()) + group.origin[1] if len(ys) else 0.0
            self.center_row[part_name] = row
            for g, group in enumerate(self.graph.groups):
                lids = np.isin(group.labels, self.units[lid].regions)
                if lids.any():
                    rows = np.arange(group.labels.shape[0])[:, None] + group.origin[1]
                    self.group_units[g][lids & (rows < row)] = lid
                    self.group_units[g][lids & (rows >= row)] = lash
        self.eye_inside = {part_name: self._eye_opening(idx[0]) for part_name, idx in self.eyes.items()}
        for part_name, (ball, lash, lid) in self.eyes.items():
            inside = self.eye_inside[part_name]
            for g, group in enumerate(self.graph.groups):
                x0, y0 = group.origin
                hh, ww = group.labels.shape
                units = self.group_units[g]
                units[np.isin(units, (lash, lid)) & inside[y0:y0 + hh, x0:x0 + ww]] = ball
        for g, part in enumerate(self.passes.parts):                  # fill pixels outside every region
            units = self.group_units[g]
            orphan = (part.fills[..., 3] > 0.02) & (units < 0)
            if orphan.any() and (units >= 0).any():
                _, (iy, ix) = ndimage.distance_transform_edt(units < 0, return_indices=True)
                units[orphan] = units[iy[orphan], ix[orphan]]
        self.stray = self._stray()
        self.top = np.full((self.h, self.w), -1, np.int32)
        for g, group in enumerate(self.graph.groups):
            x0, y0 = group.origin
            hh, ww = group.labels.shape
            view = self.top[y0:y0 + hh, x0:x0 + ww]
            np.maximum(view, self.group_units[g], out=view)

    def _stray(self) -> np.ndarray:
        """Canvas mask of pixels whose drawn flat color is not their region's: small slivers of another color (often
        under line art) merged into a neighboring region. Inside a moving part's hole they are refilled, so a blink or
        a swaying lock never shows them."""
        out = np.zeros((self.h, self.w), bool)
        flat = np.array([r.flat[:3] for r in self.graph.regions] + [(0, 0, 0)], np.float32)
        for g, group in enumerate(self.graph.groups):
            part = self.passes.parts[g]
            labels = group.labels
            a = part.flats[..., 3]
            rgb = part.flats[..., :3] / np.maximum(a[..., None], 1e-6) * 255
            far = np.abs(rgb - flat[labels]).max(axis=2) > STRAY_COLOR
            x0, y0 = group.origin
            hh, ww = labels.shape
            out[y0:y0 + hh, x0:x0 + ww] |= (labels >= 0) & (a > 0.5) & far
        return out

    def _eye_opening(self, ball: int) -> np.ndarray:
        """Canvas mask of the eye's opening: the ball's pixels with the gaps between its pieces closed (the dark ring
        drawn between an iris and the white), so outlines there move with the ball, not with the lid or lash."""
        mask = self.own(ball)
        out = np.zeros_like(mask)
        r = max(2, int(np.ceil(EYE_RING_UNITS * self.graph.scale)))
        box = _box(mask, pad=2 * r + 1, shape=(self.h, self.w))
        if box is None:
            return out
        x0, y0, x1, y1 = box
        yy, xx = np.mgrid[-r:r + 1, -r:r + 1]
        disk = xx * xx + yy * yy <= r * r
        local = np.pad(mask[y0:y1, x0:x1], r + 1)
        closed = ndimage.binary_fill_holes(ndimage.binary_closing(local, structure=disk))[r + 1:-r - 1, r + 1:-r - 1]
        out[y0:y1, x0:x1] = closed
        return out

    def own(self, i: int, box=None) -> np.ndarray:
        """Canvas (or box) mask of unit i's own pixels in any group."""
        bx0, by0, bx1, by1 = box or (0, 0, self.w, self.h)
        out = np.zeros((by1 - by0, bx1 - bx0), bool)
        for g, group in enumerate(self.graph.groups):
            x0, y0 = group.origin
            hh, ww = group.labels.shape
            ix0, iy0, ix1, iy1 = max(bx0, x0), max(by0, y0), min(bx1, x0 + ww), min(by1, y0 + hh)
            if ix1 <= ix0 or iy1 <= iy0:
                continue
            out[iy0 - by0:iy1 - by0, ix0 - bx0:ix1 - bx0] |= \
                self.group_units[g][iy0 - y0:iy1 - y0, ix0 - x0:ix1 - x0] == i
        return out

    # ------------------------------------------------------------ line and detail ownership

    def ownership(self) -> None:
        lines, details = self.graph.lines > 0.02, self.graph.details > 0.02
        solid = self.graph.lines >= 0.5
        half = float(np.percentile(ndimage.distance_transform_edt(solid)[solid], 95)) if solid.any() else 1.0
        reach = 1 + 2 * half
        pad = int(np.ceil(reach)) + 1
        owner = np.full((self.h, self.w), -1, np.int32)                 # owner index
        for o, units in enumerate(self.owners):                        # bottom to top: higher owners win
            mask = np.isin(self.top, units)
            box = _box(mask, pad=pad, shape=(self.h, self.w))
            if box is None:
                continue
            x0, y0, x1, y1 = box
            near = ndimage.distance_transform_edt(~mask[y0:y1, x0:x1]) <= reach
            owner[y0:y1, x0:x1][near & lines[y0:y1, x0:x1]] = o
        owner_of_unit = np.full(len(self.units) + 1, -1, np.int32)     # the last entry: no unit (top = -1)
        for o, units in enumerate(self.owners):
            owner_of_unit[units] = o
        visible_owner = owner_of_unit[self.top]
        loose = (lines & (owner < 0)) | details
        nearest = None
        if loose.any() and (self.top >= 0).any():
            _, (iy, ix) = ndimage.distance_transform_edt(self.top < 0, return_indices=True)
            nearest = owner_of_unit[self.top[iy, ix]]
            owner = np.where(lines & (owner < 0), nearest, owner)
        self.outline = self._outline_width()
        self.silhouette = self._silhouette(owner, lines, owner_of_unit)
        self._lid_tips(owner, lines)
        detail_owner = np.full((self.h, self.w), -1, np.int32)        # each detail piece stays whole and goes to
        pieces, count = ndimage.label(details, structure=np.ones((3, 3)))   # the highest part under it (details are
        for k, box in enumerate(ndimage.find_objects(pieces), start=1):     # painted above every flat they cover)
            piece = pieces[box] == k
            under = visible_owner[box][piece]
            under = under[under >= 0]
            if under.size:
                detail_owner[box][piece] = int(under.max())
            elif nearest is not None:
                ys, xs = np.nonzero(piece)
                detail_owner[box][piece] = int(nearest[box][ys[0], xs[0]])
        self.line_unit = np.full((self.h, self.w), -1, np.int32)
        self.detail_unit = np.full((self.h, self.w), -1, np.int32)
        rows = np.arange(self.h)[:, None]
        for o, units in enumerate(self.owners):
            mine, mine_d = owner == o, detail_owner == o
            if len(units) == 3:                                         # an eye: lines above the ball's center
                ball, lash, lid = units                                 # are the lid, below it the lash
                row = self.center_row[self.units[ball].parent]
                self.line_unit[mine & (rows < row)] = lid
                self.line_unit[mine & (rows >= row)] = lash
                self.line_unit[mine & self.eye_inside[self.units[ball].parent]] = ball
                self.detail_unit[mine_d] = ball
            else:
                self.line_unit[mine] = units[0]
                self.detail_unit[mine_d] = units[0]

    def _outline_width(self) -> int:
        """How wide the drawing's outline is, in px: the depth inside the silhouette down to which most of the canvas
        is solid line art (0 for art drawn without an outline)."""
        depth = ndimage.distance_transform_edt(self.passes.full[..., 3] > 0.02)
        solid = self.graph.lines >= 0.5
        width = 0
        for d in range(1, 64):
            ring = (depth > d - 1) & (depth <= d)
            n = np.count_nonzero(ring)
            if not n:
                break
            if np.count_nonzero(solid & ring) >= 0.5 * n:
                width = d
            elif width:
                break
        return width

    def _outline_band(self, o: int, owner: np.ndarray, lines: np.ndarray, silhouette: np.ndarray, box,
                      r: int) -> tuple[np.ndarray, np.ndarray]:
        """In the box, eye o's line pixels on the head's outline: inside the silhouette opened by a disk of radius r
        (what pokes out past it cut off) and no deeper than the drawing's outline. Line art outside that opened
        silhouette and touching eye o's lines (a lash's tip) becomes eye o's; returned second."""
        x0, y0, x1, y1 = box
        yy, xx = np.mgrid[-r:r + 1, -r:r + 1]
        pad = r + 1
        opened = ndimage.binary_opening(np.pad(silhouette[y0:y1, x0:x1], pad, mode="edge"),
                                        structure=xx * xx + yy * yy <= r * r)
        depth = ndimage.distance_transform_edt(opened)[pad:-pad, pad:-pad]
        opened = opened[pad:-pad, pad:-pad]
        local_lines, local_owner = lines[y0:y1, x0:x1], owner[y0:y1, x0:x1]
        mine = local_lines & (local_owner == o)
        tips, count = ndimage.label(local_lines & ~opened, structure=np.ones((3, 3)))
        taken = np.zeros_like(mine)
        if count:
            touching = np.unique(tips[ndimage.binary_dilation(mine, iterations=2)])
            taken = np.isin(tips, touching[touching > 0])
            local_owner[taken] = o
        return mine & opened & (depth <= self.outline + 1), taken

    def _silhouette(self, owner: np.ndarray, lines: np.ndarray, owner_of_unit: np.ndarray) -> np.ndarray:
        """Eyes sit inside the face, so a thin line squeezed between an eye (its ball, or the part it lies on) and the
        empty canvas is the head's outline: it goes to the part under the eye (the nearest one that stays) and stays
        when the eye blinks, as does whatever line art of the eye lies in the band along the silhouette as wide as the
        drawing's outline (an outline thicker than a head unit). Thick line art there (a lid poking out past the face)
        stays the eye's, and line art poking out past the silhouette and touching an eye (a lash's tip) moves with that
        eye. Returns the canvas mask of the lines that stay."""
        out = np.zeros((self.h, self.w), bool)
        silhouette = self.passes.full[..., 3] > 0.02
        outside = ~silhouette
        stays = np.isin(self.top, [i for i, u in enumerate(self.units) if u.part.kind in PROVIDERS])
        if not outside.any() or not stays.any():
            return out
        width = SILHOUETTE_UNITS * self.graph.scale
        r = OPENING_WIDTHS * max(self.outline, 1) + 1
        nearest = None
        for o, units in enumerate(self.owners):
            if len(units) != 3:
                continue
            mine = (owner == o) & lines
            box = _box(mine, pad=max(int(np.ceil(width)), 4 * r) + 2, shape=(self.h, self.w))
            if box is None:
                continue
            x0, y0, x1, y1 = box
            band, tips = self._outline_band(o, owner, lines, silhouette, box, r)
            d_out = ndimage.distance_transform_edt(~outside[y0:y1, x0:x1])
            d_in = np.minimum(ndimage.distance_transform_edt(~self.own(units[0], box)),
                              ndimage.distance_transform_edt(~stays[y0:y1, x0:x1]))
            thin = mine[y0:y1, x0:x1] & ~_thick(lines[y0:y1, x0:x1], width) & (d_out + d_in <= width + 1) & ~tips
            outline = thin | band
            if not outline.any():
                continue
            if nearest is None:
                nearest = ndimage.distance_transform_edt(~stays, return_distances=False, return_indices=True)
            ys, xs = np.nonzero(outline)
            ys, xs = ys + y0, xs + x0
            owner[ys, xs] = owner_of_unit[self.top[nearest[0][ys, xs], nearest[1][ys, xs]]]
            out[ys, xs] = True
        return out

    def _lid_tips(self, owner: np.ndarray, lines: np.ndarray) -> None:
        """A thick stroke is one piece: where an eye owns most of a stroke thicker than SILHOUETTE_UNITS and than the
        drawing's outline with its blended fringe (a lid and its tip poking out past the face, farther from the eye's
        pixels than line ownership reaches), the rest of it is the eye's too, so it moves with the lid instead of
        staying behind with the part under the eye, its rim included (the blended edge and the corners that measuring
        it rounds off), but not thin lines going on away from it. Where it crosses the head's outline it is the eye's
        as well (the outline goes on under it in the hidden fills)."""
        width = max(SILHOUETTE_UNITS * self.graph.scale, self.outline + 2)
        rim = int(np.ceil((np.sqrt(2) - 1) * max(1, round(width / 2)))) + 1   # px past what _thick keeps of a stroke
        stay = [k for k, units in enumerate(self.owners) if self.units[units[0]].part.kind in PROVIDERS]
        lower = None
        for o, units in enumerate(self.owners):
            if len(units) != 3:
                continue
            mine = (owner == o) & lines
            box = _box(mine, pad=int(np.ceil(self.reach)) * 2, shape=(self.h, self.w))
            if box is None:
                continue
            if lower is None:
                lower = np.isin(owner, stay)
            x0, y0, x1, y1 = box
            strokes, count = ndimage.label(_thick(lines[y0:y1, x0:x1], width), structure=np.ones((3, 3)))
            if not count:
                continue
            ours = np.bincount(strokes[mine[y0:y1, x0:x1]], minlength=count + 1)
            theirs = np.bincount(strokes[lower[y0:y1, x0:x1]], minlength=count + 1)
            ours[0] = 0
            taken = np.nonzero((ours > 0) & (ours >= theirs))[0]
            core = np.isin(strokes, taken)
            rest, _ = ndimage.label(lines[y0:y1, x0:x1] & ~core & lower[y0:y1, x0:x1], structure=np.ones((3, 3)))
            near = ndimage.binary_dilation(core, structure=np.ones((3, 3)), iterations=rim)
            away = np.unique(rest[(rest > 0) & ~near])                # thin lines going on away from the stroke
            take = (core & lower[y0:y1, x0:x1]) | ((rest > 0) & ~np.isin(rest, away))
            owner[y0:y1, x0:x1][take] = o
            self.silhouette[y0:y1, x0:x1][take] = False

    # ------------------------------------------------------------ hidden fills and underlap

    def _tone_bits(self, g: int) -> np.ndarray:
        """Per pixel of group g: which of its tones cover it (bit t for tone t, at half coverage or more)."""
        if g not in self._bits:
            bits = np.zeros(self.graph.groups[g].labels.shape, np.int64)
            for t, tone in enumerate(self.passes.parts[g].tones):
                bits |= (tone.alpha >= 0.5).astype(np.int64) << t
            self._bits[g] = bits
        return self._bits[g]

    def _classes(self, box, providers: list[int], hole: np.ndarray) -> tuple[np.ndarray | None, list]:
        """Per pixel of the box, an index into the returned keys: the empty canvas ("empty", -1, -1, 0) or a fill of a
        part that stays ("fill", unit, flat region, tone bits). The hole's pixels are -1; other pixels (other parts,
        line art over the canvas, blended edges outside every region) take their nearest neighbour's. None when no part
        that stays is around."""
        x0, y0, x1, y1 = box
        top, line = self.top[y0:y1, x0:x1], self.line_unit[y0:y1, x0:x1]
        codes = np.full(top.shape, -1, np.int64)
        keys = [("empty", -1, -1, 0)]
        codes[(top < 0) & (line < 0) & (self.detail_unit[y0:y1, x0:x1] < 0) & ~hole] = 0
        for unit in providers:
            mine = (top == unit) & ~hole
            if mine.any():
                group = self.units[unit].group
                gx, gy = self.graph.groups[group].origin
                ys, xs = np.nonzero(mine)
                ly, lx = ys + y0 - gy, xs + x0 - gx
                region = self.graph.groups[group].labels[ly, lx]
                inner = region >= 0                                   # blended edge pixels take their neighbour's
                ys, xs, ly, lx = ys[inner], xs[inner], ly[inner], lx[inner]
                if not len(ys):
                    continue
                found, inverse = np.unique(np.stack([region[inner], self._tone_bits(group)[ly, lx]], axis=1),
                                           axis=0, return_inverse=True)
                codes[ys, xs] = len(keys) + inverse.ravel()
                keys += [("fill", unit, int(r), int(b)) for r, b in found]
        if not (codes > 0).any():
            return None, keys
        loose = (codes < 0) & ~hole
        if loose.any():
            _, (iy, ix) = ndimage.distance_transform_edt(codes < 0, return_indices=True)
            codes[loose] = codes[iy[loose], ix[loose]]
        return codes, keys

    def _sources(self, i: int, ys: np.ndarray, xs: np.ndarray, key=None) -> tuple[np.ndarray, np.ndarray]:
        """For canvas pixels (ys, xs): the nearest solid pixel unit i owns in its own group (of the flat region and
        tones of `key`, a "fill" class, when it has such pixels)."""
        u = self.units[i]
        group = self.graph.groups[u.group]
        part = self.passes.parts[u.group]
        own = self.group_units[u.group] == i
        clear = (part.flats[..., 3] >= SOLID) & (part.lines[..., 3] <= 0.02)        # not under the line art
        x0, y0 = group.origin
        hh, ww = own.shape
        clear &= ~self.stray[y0:y0 + hh, x0:x0 + ww]                               # never copy a merged sliver
        core = ndimage.binary_erosion(own, iterations=CORE_DEPTH) & clear          # away from blended edges
        if not core.any():
            core = own & clear if (own & clear).any() else own
        if key is not None:
            same = core & (group.labels == key[2]) & (self._tone_bits(u.group) == key[3])
            if same.any():
                core = same
        x0, y0 = group.origin
        hh, ww = core.shape
        qx0, qy0, qx1, qy1 = int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1
        reach = max(qx1 - qx0, qy1 - qy0) + 2 * UNDERLAP + 2
        for attempt in range(2):                       # first a box around the pixels, then the whole group
            if attempt == 0:
                bx0, by0 = max(qx0 - reach, x0), max(qy0 - reach, y0)
                bx1, by1 = min(qx1 + reach, x0 + ww), min(qy1 + reach, y0 + hh)
            else:
                bx0, by0, bx1, by1 = x0, y0, x0 + ww, y0 + hh
            bx0, by0 = min(bx0, qx0), min(by0, qy0)
            bx1, by1 = max(bx1, qx1), max(by1, qy1)
            area = np.zeros((by1 - by0, bx1 - bx0), bool)
            cx0, cy0, cx1, cy1 = max(bx0, x0), max(by0, y0), min(bx1, x0 + ww), min(by1, y0 + hh)
            area[cy0 - by0:cy1 - by0, cx0 - bx0:cx1 - bx0] = core[cy0 - y0:cy1 - y0, cx0 - x0:cx1 - x0]
            if area.any():
                break
        _, (iy, ix) = ndimage.distance_transform_edt(~area, return_indices=True)
        return iy[ys - by0, xs - bx0] + by0, ix[ys - by0, xs - bx0] + bx0

    def hidden(self) -> None:
        provider_units = [i for i, u in enumerate(self.units) if u.part.kind in PROVIDERS]
        for units in self.owners:
            if self.units[units[0]].part.kind not in MOVING:
                continue
            hole = np.isin(self.top, units) | np.isin(self.line_unit, units) | np.isin(self.detail_unit, units)
            band = EDGE_BAND_UNITS * self.graph.scale                  # the hole and the edges running into it
            box = _box(hole, pad=int(np.ceil(max(band, self.reach))) + EDGE_GAP + 2, shape=(self.h, self.w))
            if box is None:
                continue
            x0, y0, x1, y1 = box
            providers = [p for p in provider_units if p < units[0]]          # the parts that stay, below it
            local_hole = hole[y0:y1, x0:x1]
            codes, keys = self._classes((x0, y0, x1, y1), providers, local_hole)
            if codes is None:
                continue
            strokes_of, stroke_ends = {}, []                         # their outlines going on under the moving part
            for unit in providers:
                strokes = (self.line_unit[y0:y1, x0:x1] == unit) & ~local_hole
                if strokes.any():
                    strokes_of[unit], ends = _continued_strokes(strokes, local_hole, band)
                    stroke_ends += ends
            barrier = np.zeros_like(local_hole)
            for lines in strokes_of.values():
                barrier |= lines
            codes = _continued(codes, local_hole, band, barrier, tuple(stroke_ends))
            unit_of = np.array([k[1] for k in keys])[codes]           # the part that stays each pixel continues
            for unit in providers:
                take = local_hole & (unit_of == unit)
                higher = local_hole & np.isin(unit_of, [u for u in providers if u > unit])
                if take.any() and higher.any():                    # reach under the next provider's fill too
                    take |= higher & (ndimage.distance_transform_edt(~take) <= self.reach) \
                        & self.inside[y0:y1, x0:x1]
                take &= ~self.own(unit, (x0, y0, x1, y1)) | self.stray[y0:y1, x0:x1]     # slivers get refilled
                for code in np.unique(codes[take]):                # copies from the class each piece continues
                    ys, xs = np.nonzero(take & (codes == code))
                    key = keys[code] if keys[code][0] == "fill" and keys[code][1] == unit else None
                    self._extend(unit, ys + y0, xs + x0, key)
                lines = strokes_of.get(unit)
                if lines is not None and lines.any():
                    ys, xs = np.nonzero(lines)
                    self._extend_lines(unit, ys + y0, xs + x0)

    def _extend(self, i: int, ys: np.ndarray, xs: np.ndarray, key=None) -> None:
        sy, sx = self._sources(i, ys, xs, key)
        self.units[i].ext.append((ys, xs, sy, sx))

    def _extend_lines(self, i: int, ys: np.ndarray, xs: np.ndarray) -> None:
        """Hidden line art of unit i at canvas pixels (ys, xs), copied from its nearest line pixel as opaque as its
        line art usually is (not from the blended edge where a moving part cuts it)."""
        mine = self.line_unit == i
        level = min(SOLID, float(np.percentile(self.graph.lines[mine], 90))) if mine.any() else SOLID
        solid = mine & (self.graph.lines >= max(0.5, level))
        qx0, qy0, qx1, qy1 = int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1
        pad = max(qx1 - qx0, qy1 - qy0) + 2
        bx0, by0, bx1, by1 = max(0, qx0 - pad), max(0, qy0 - pad), min(self.w, qx1 + pad), min(self.h, qy1 + pad)
        if not solid[by0:by1, bx0:bx1].any():
            if not solid.any():
                return
            bx0, by0, bx1, by1 = 0, 0, self.w, self.h
        _, (iy, ix) = ndimage.distance_transform_edt(~solid[by0:by1, bx0:bx1], return_indices=True)
        self.units[i].line_ext.append((ys, xs, iy[ys - by0, xs - bx0] + by0, ix[ys - by0, xs - bx0] + bx0))

    def underlap(self) -> None:
        for i, u in enumerate(self.units):
            own = self.top == i
            box = _box(own, pad=self.reach + 1, shape=(self.h, self.w))
            if box is not None:
                x0, y0, x1, y1 = box
                near = ndimage.distance_transform_edt(~own[y0:y1, x0:x1]) <= self.reach
                take = (near & (self.top[y0:y1, x0:x1] > i) & ~self.own(i, (x0, y0, x1, y1))
                        & self.inside[y0:y1, x0:x1])
                if take.any():
                    ys, xs = np.nonzero(take)
                    self._extend(i, ys + y0, xs + x0)
            mine = self.line_unit == i
            u.lines = mine.copy()
            if u.parent is not None:                   # an eye's piece still draws the head's outline over its own
                u.lines |= self.silhouette & (self.top == i)   # fill, so the rest pose keeps it on top
            lbox = _box(mine, pad=UNDERLAP + 1, shape=(self.h, self.w))
            if lbox is not None:
                x0, y0, x1, y1 = lbox
                near = ndimage.distance_transform_edt(~mine[y0:y1, x0:x1]) <= UNDERLAP
                u.lines[y0:y1, x0:x1] |= near & (self.line_unit[y0:y1, x0:x1] > i)
            u.details = self.detail_unit == i

    # ------------------------------------------------------------ the layers

    def layers(self) -> list[PartLayer]:
        lines = np.zeros((self.h, self.w, 4), np.float32)
        details = np.zeros((self.h, self.w, 4), np.float32)
        for part in self.passes.parts:
            _paste_over(lines, part.lines.astype(np.float32), part.origin)
            _paste_over(details, part.details.astype(np.float32), part.origin)
        out = []
        for i, u in enumerate(self.units):
            layer = self._layer(i, u, lines, details)
            if layer is not None:
                out.append(layer)
        return out

    def _layer(self, i: int, u: _Unit, lines: np.ndarray, details: np.ndarray) -> PartLayer | None:
        own = self.own(i)
        ext = np.zeros((self.h, self.w), bool)
        for ys, xs, _, _ in u.ext:
            ext[ys, xs] = True
        line_ext = np.zeros((self.h, self.w), bool)
        for ys, xs, _, _ in u.line_ext:
            line_ext[ys, xs] = True
        box = _box(own, ext, u.lines, line_ext, u.details, shape=(self.h, self.w))
        if box is None:
            return None
        x0, y0, x1, y1 = box
        hh, ww = y1 - y0, x1 - x0
        src = self.passes.parts[u.group]
        flats = np.zeros((hh, ww, 4), np.float32)
        fills = np.zeros((hh, ww, 4), np.float32)
        tone_alpha = [np.zeros((hh, ww), np.float32) for _ in src.tones]
        for g, part in enumerate(self.passes.parts):                   # own pixels, from the group that has them
            mine = self.group_units[g] == i
            if not mine.any():
                continue
            gx, gy = part.origin
            ys, xs = np.nonzero(mine)
            cy, cx = ys + gy - y0, xs + gx - x0
            flats[cy, cx] = part.flats[ys, xs]
            fills[cy, cx] = part.fills[ys, xs]
            if g == u.group:
                for t, tone in enumerate(part.tones):
                    tone_alpha[t][cy, cx] = tone.alpha[ys, xs]
        gx, gy = src.origin
        for ys, xs, sy, sx in u.ext:                                     # hidden fills and underlap: copies
            ly, lx = sy - gy, sx - gx
            flats[ys - y0, xs - x0] = src.flats[ly, lx]
            fills[ys - y0, xs - x0] = src.fills[ly, lx]
            for t, tone in enumerate(src.tones):
                tone_alpha[t][ys - y0, xs - x0] = tone.alpha[ly, lx]
        line_rgba = np.where(u.lines[y0:y1, x0:x1, None], lines[y0:y1, x0:x1], 0).astype(np.float32)
        for ys, xs, sy, sx in u.line_ext:                                # hidden line art: copies
            line_rgba[ys - y0, xs - x0] = lines[sy, sx]
        detail_rgba = np.where(u.details[y0:y1, x0:x1, None], details[y0:y1, x0:x1], 0).astype(np.float32)
        tones = [ToneCoverage(t.role, a, t.soft, t.layers, t.blends, t.color, t.gradient)
                 for t, a in zip(src.tones, tone_alpha) if a.any()]
        order = list(src.order)
        if detail_rgba[..., 3].any() and "details" not in order:
            order.insert(order.index("line") if "line" in order else len(order), "details")
        if line_rgba[..., 3].any() and "line" not in order:
            order.append("line")
        if not fills[..., 3].any() and "fills" in order:
            order.remove("fills")
        if not order:
            return None
        passes = PartPasses(u.name, (x0, y0), flats, tones, fills, detail_rgba, line_rgba, order, src.tone_above_lines,
                            ext[y0:y1, x0:x1] & ~own[y0:y1, x0:x1])
        locations = []
        for rid in u.regions:
            location = self.parts.location_of.get(rid)
            entry = (self.graph.regions[rid].flat, location)
            if location is not None and entry not in locations:
                locations.append(entry)
        if u.parent is None or u.name.endswith(" ball"):
            pivot = u.part.pivot
        else:
            ys, xs = np.nonzero(own | u.lines)
            hx, hy = self.graph.head(np.array([xs.mean()]), np.array([ys.mean()])) if len(xs) else ([0.0], [0.0])
            pivot = Point(float(hx[0]), float(hy[0]))
        return PartLayer(u.name, u.parent, u.part.kind, passes, locations,
                         frozenset(t.role for t in tones if t.soft), pivot, u.part.kind == "back_hair")


def split_passes(passes: Passes, parts: PartMap) -> list[PartLayer]:
    s = _Splitter(passes, parts)
    s.ownership()
    s.hidden()
    s.underlap()
    return s.layers()


def layered_passes(passes: Passes, layers: list[PartLayer]) -> Passes:
    return Passes(passes.width, passes.height, [layer.passes for layer in layers], passes.full, passes.flattened,
                  list(passes.notes), passes.gradient_layers)
