"""Each part's own passes (spec §9.3): line and detail pixels go to the part they outline, the parts that stay (face,
hair base, helm) continue under the parts that move (eyes, locks, ears, accessories) and every part reaches 2 px under
the parts above it, copying its own nearest pixels so the hidden fill is already on the palette. Eyes become three
layers (ball, lash, lid) so Blink can fade the ball and move the lid."""
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
    name: str
    parent: str | None
    part: Part
    group: int                                     # the group its passes come from
    regions: list[int]
    ext: list[tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]] = field(default_factory=list)  # ys, xs, sy, sx
    lines: np.ndarray | None = None                # canvas bool
    details: np.ndarray | None = None


def _paste_over(canvas: np.ndarray, array: np.ndarray, origin) -> None:
    x0, y0 = origin
    h, w = array.shape[:2]
    view = canvas[y0:y0 + h, x0:x0 + w]
    view[:] = array + view * (1 - array[..., 3:4])


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
        for part in parts.parts.values():
            group = self.graph.regions[part.regions[0]].group
            if part.kind == "eye":
                ball = [r for r in part.regions if parts.piece_of.get(r) in BALL_PIECES]
                lid = [r for r in part.regions if r not in ball]
                for sub, regions in (("ball", ball), ("lash", lid), ("lid", lid)):
                    self.units.append(_Unit("%s %s" % (part.name, sub), part.name, part, group, regions))
            else:
                self.units.append(_Unit(part.name, None, part, group, list(part.regions)))
        self.unit_of_part = {}
        for i, u in enumerate(self.units):
            self.unit_of_part.setdefault(u.part.name, []).append(i)
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
        for part_name, idx in self.unit_of_part.items():
            if len(idx) != 3:
                continue
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
        for g, part in enumerate(self.passes.parts):                  # fill pixels outside every region
            units = self.group_units[g]
            orphan = (part.fills[..., 3] > 0.02) & (units < 0)
            if orphan.any() and (units >= 0).any():
                _, (iy, ix) = ndimage.distance_transform_edt(units < 0, return_indices=True)
                units[orphan] = units[iy[orphan], ix[orphan]]
        self.top = np.full((self.h, self.w), -1, np.int32)
        for g, group in enumerate(self.graph.groups):
            x0, y0 = group.origin
            hh, ww = group.labels.shape
            view = self.top[y0:y0 + hh, x0:x0 + ww]
            np.maximum(view, self.group_units[g], out=view)

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
        part_names = list(self.parts.parts)
        owner = np.full((self.h, self.w), -1, np.int32)                 # part index
        for p, name in enumerate(part_names):                          # z ascending: higher parts win
            units = self.unit_of_part[name]
            mask = np.isin(self.top, units)
            box = _box(mask, pad=pad, shape=(self.h, self.w))
            if box is None:
                continue
            x0, y0, x1, y1 = box
            near = ndimage.distance_transform_edt(~mask[y0:y1, x0:x1]) <= reach
            owner[y0:y1, x0:x1][near & lines[y0:y1, x0:x1]] = p
        part_of_unit = np.array([part_names.index(u.part.name) for u in self.units] + [-1])
        visible_part = np.where(self.top >= 0, part_of_unit[self.top], -1)
        loose = (lines & (owner < 0)) | details
        nearest = None
        if loose.any() and (self.top >= 0).any():
            _, (iy, ix) = ndimage.distance_transform_edt(self.top < 0, return_indices=True)
            nearest = part_of_unit[self.top[iy, ix]]
            owner = np.where(lines & (owner < 0), nearest, owner)
        detail_owner = np.full((self.h, self.w), -1, np.int32)        # each detail piece stays whole and goes to
        pieces, count = ndimage.label(details, structure=np.ones((3, 3)))   # the highest part under it (details are
        for k, box in enumerate(ndimage.find_objects(pieces), start=1):     # painted above every flat they cover)
            piece = pieces[box] == k
            under = visible_part[box][piece]
            under = under[under >= 0]
            if under.size:
                detail_owner[box][piece] = int(under.max())
            elif nearest is not None:
                ys, xs = np.nonzero(piece)
                detail_owner[box][piece] = int(nearest[box][ys[0], xs[0]])
        self.line_unit = np.full((self.h, self.w), -1, np.int32)
        self.detail_unit = np.full((self.h, self.w), -1, np.int32)
        rows = np.arange(self.h)[:, None]
        for p, name in enumerate(part_names):
            units = self.unit_of_part[name]
            mine, mine_d = owner == p, detail_owner == p
            if len(units) == 3:                                         # an eye: lines above the ball's center
                ball, lash, lid = units                                 # are the lid, below it the lash
                row = self.center_row[name]
                self.line_unit[mine & (rows < row)] = lid
                self.line_unit[mine & (rows >= row)] = lash
                self.detail_unit[mine_d] = ball
            else:
                self.line_unit[mine] = units[0]
                self.detail_unit[mine_d] = units[0]
        self.part_owner = owner

    # ------------------------------------------------------------ hidden fills and underlap

    def _sources(self, i: int, ys: np.ndarray, xs: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """For canvas pixels (ys, xs): the nearest solid pixel unit i owns in its own group."""
        u = self.units[i]
        group = self.graph.groups[u.group]
        part = self.passes.parts[u.group]
        own = self.group_units[u.group] == i
        clear = (part.flats[..., 3] >= SOLID) & (part.lines[..., 3] <= 0.02)        # not under the line art
        core = ndimage.binary_erosion(own, iterations=CORE_DEPTH) & clear          # away from blended edges
        if not core.any():
            core = own & clear if (own & clear).any() else own
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
        part_names = list(self.parts.parts)
        for name in part_names:
            part = self.parts.parts[name]
            if part.kind not in MOVING:
                continue
            units = self.unit_of_part[name]
            hole = np.isin(self.top, units) | np.isin(self.line_unit, units) | np.isin(self.detail_unit, units)
            box = _box(hole, shape=(self.h, self.w))
            if box is None:
                continue
            x0, y0, x1, y1 = box
            grow = max(x1 - x0, y1 - y0) // 2 + 2
            x0, y0, x1, y1 = max(0, x0 - grow), max(0, y0 - grow), min(self.w, x1 + grow), min(self.h, y1 + grow)
            providers = [p for p in part_names if self.parts.parts[p].kind in PROVIDERS
                         and self.parts.parts[p].z < part.z]
            seeds = np.full((y1 - y0, x1 - x0), -1, np.int32)
            top = self.top[y0:y1, x0:x1]
            background = (top < 0) & (self.line_unit[y0:y1, x0:x1] < 0) & (self.detail_unit[y0:y1, x0:x1] < 0)
            empty = len(self.units)
            seeds[background] = empty
            for p in providers:
                (unit,) = self.unit_of_part[p]
                seeds[top == unit] = unit
            if not (seeds >= 0).any():
                continue
            _, (iy, ix) = ndimage.distance_transform_edt(seeds < 0, return_indices=True)
            nearest = seeds[iy, ix]
            local_hole = hole[y0:y1, x0:x1]
            provider_units = [self.unit_of_part[p][0] for p in providers]
            for p in providers:
                (unit,) = self.unit_of_part[p]
                take = local_hole & (nearest == unit)
                higher = local_hole & np.isin(nearest, [u for u in provider_units if u > unit])
                if take.any() and higher.any():                    # reach under the next provider's fill too
                    take |= higher & (ndimage.distance_transform_edt(~take) <= self.reach) \
                        & self.inside[y0:y1, x0:x1]
                take &= ~self.own(unit, (x0, y0, x1, y1))
                if take.any():
                    ys, xs = np.nonzero(take)
                    self._extend(unit, ys + y0, xs + x0)

    def _extend(self, i: int, ys: np.ndarray, xs: np.ndarray) -> None:
        sy, sx = self._sources(i, ys, xs)
        self.units[i].ext.append((ys, xs, sy, sx))

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
        box = _box(own, ext, u.lines, u.details, shape=(self.h, self.w))
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
