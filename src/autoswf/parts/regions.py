"""The region graph of a drawing (spec §9.2): each part folder's flat colors, cut by the line art and by the user's cuts,
become atomic regions with head-local features. Part detection labels regions; it never invents pixels."""
from dataclasses import dataclass
from typing import Sequence

import numpy as np
from PIL import Image, ImageDraw
from scipy import ndimage

from autoswf.aqw.template import Alignment
from autoswf.drawing.passes import Passes
from autoswf.model.geometry import Point
from autoswf.vectorize.art import stroke_coverage
from autoswf.vectorize.palette import merge_small, palette_labels

RGBA = tuple[int, int, int, int]
CUT_WIDTH = 3                  # px: a user cut is drawn this wide


@dataclass
class Region:
    id: int
    group: int
    flat: RGBA                                     # flat color
    pixels: int
    area: float                                    # head units²
    center: Point                                  # head units
    box: tuple[int, int, int, int]                 # x0, y0, x1, y1 canvas px (end exclusive)


@dataclass(eq=False)
class RegionGroup:
    index: int
    hint: str | None                               # the part folder's name
    origin: tuple[int, int]
    labels: np.ndarray                             # local int32 region ids, -1 = none


@dataclass(eq=False)
class RegionGraph:
    width: int
    height: int
    groups: list[RegionGroup]
    regions: list[Region]
    lines: np.ndarray                              # canvas float32 alpha of every line pass
    details: np.ndarray                            # canvas float32 alpha of every details pass
    alignment: Alignment

    @property
    def scale(self) -> float:
        return self.alignment.scale

    def head(self, xs, ys) -> tuple[np.ndarray, np.ndarray]:
        """Canvas pixel indices -> head units of the pixels' centers."""
        m = self.alignment.matrix()
        x, y = np.asarray(xs, np.float64) + 0.5, np.asarray(ys, np.float64) + 0.5
        return m.a * x + m.c * y + m.tx, m.b * x + m.d * y + m.ty

    def region_at(self, x: float, y: float) -> Region | None:
        for group in reversed(self.groups):
            gx, gy = int(np.floor(x)) - group.origin[0], int(np.floor(y)) - group.origin[1]
            h, w = group.labels.shape
            if 0 <= gx < w and 0 <= gy < h and group.labels[gy, gx] >= 0:
                return self.regions[int(group.labels[gy, gx])]
        return None

    def mask(self, region_id: int) -> tuple[RegionGroup, np.ndarray]:
        group = self.groups[self.regions[region_id].group]
        return group, group.labels == region_id

    def canvas_mask(self, region_id: int) -> np.ndarray:
        group, local = self.mask(region_id)
        out = np.zeros((self.height, self.width), bool)
        x0, y0 = group.origin
        out[y0:y0 + local.shape[0], x0:x0 + local.shape[1]] = local
        return out

    def adjacency(self, group_index: int) -> dict[tuple[int, int], float]:
        labels = self.groups[group_index].labels
        pairs = []
        for a, b in ((labels[:, :-1], labels[:, 1:]), (labels[:-1, :], labels[1:, :])):
            touching = (a != b) & (a >= 0) & (b >= 0)
            lo, hi = np.minimum(a[touching], b[touching]), np.maximum(a[touching], b[touching])
            pairs.append(lo.astype(np.int64) * (len(self.regions) + 1) + hi)
        codes, counts = np.unique(np.concatenate(pairs), return_counts=True)
        n = len(self.regions) + 1
        return {(int(c // n), int(c % n)): float(k) / self.scale for c, k in zip(codes, counts)}

    def split(self, region_id: int, pieces: np.ndarray) -> list[int]:
        """Pieces (local int32 over the group): 0 keeps the region's id, each k > 0 becomes a new region. When nothing
        is left for the old id, the first piece keeps it. Returns the pieces' ids."""
        region = self.regions[region_id]
        group = self.groups[region.group]
        inside = group.labels == region_id
        ks = [int(k) for k in np.unique(pieces[inside]) if k > 0]
        keep_old = bool((inside & (pieces <= 0)).any())
        ids = []
        for k in ks:
            if not keep_old and not ids:
                new = region_id
            else:
                new = len(self.regions)
                self.regions.append(Region(new, region.group, region.flat, 0, 0.0, Point(0, 0), region.box))
            group.labels[inside & (pieces == k)] = new
            ids.append(new)
        for rid in set(ids) | {region_id}:
            self._measure(rid)
        return ids

    def _measure(self, region_id: int) -> None:
        """Recompute a region's features; its pixels lie inside its current box (or anywhere when it has none)."""
        region = self.regions[region_id]
        group = self.groups[region.group]
        x0, y0 = group.origin
        bx0, by0, bx1, by1 = region.box
        if bx1 > bx0 and by1 > by0:
            sub = group.labels[by0 - y0:by1 - y0, bx0 - x0:bx1 - x0]
            ys, xs = np.nonzero(sub == region_id)
            ys, xs = ys + (by0 - y0), xs + (bx0 - x0)
        else:
            ys, xs = np.nonzero(group.labels == region_id)
        if not len(xs):
            region.pixels, region.area = 0, 0.0
            return
        cx, cy = self.head(np.array([xs.mean() + x0]), np.array([ys.mean() + y0]))
        region.pixels = int(len(xs))
        region.area = len(xs) / self.scale ** 2
        region.center = Point(float(cx[0]), float(cy[0]))
        region.box = (int(xs.min()) + x0, int(ys.min()) + y0, int(xs.max()) + 1 + x0, int(ys.max()) + 1 + y0)


def _paste_max(canvas: np.ndarray, array: np.ndarray, origin: tuple[int, int]) -> None:
    x0, y0 = origin
    h, w = array.shape
    view = canvas[y0:y0 + h, x0:x0 + w]
    np.maximum(view, array[:view.shape[0], :view.shape[1]], out=view)


def _components(flat: np.ndarray, barrier: np.ndarray) -> np.ndarray:
    """4-connected pieces of each palette label outside the barrier; the label's barrier pixels join the nearest
    piece."""
    out = np.full(flat.shape, -1, np.int32)
    count = 0
    for value, box in enumerate(ndimage.find_objects(flat + 1)):
        if box is None:
            continue
        own = flat[box] == value
        pieces, n = ndimage.label(own & ~barrier[box])
        view = out[box]
        view[pieces > 0] = pieces[pieces > 0] - 1 + count
        count += n
    hole = (flat >= 0) & (out < 0)
    if hole.any() and count:
        _, (iy, ix) = ndimage.distance_transform_edt(out < 0, return_indices=True)
        out[hole] = out[iy[hole], ix[hole]]
    return out


def build_regions(passes: Passes, alignment: Alignment, cuts: Sequence[Sequence[tuple[float, float]]] = (),
                  min_area: int = 12) -> RegionGraph:
    w, h = passes.width, passes.height
    lines = np.zeros((h, w), np.float32)
    details = np.zeros((h, w), np.float32)
    cover = np.zeros((h, w), np.float32)
    for part in passes.parts:
        _paste_max(lines, part.lines[..., 3].astype(np.float32), part.origin)
        _paste_max(details, part.details[..., 3].astype(np.float32), part.origin)
        if part.lines[..., 3].any():
            _paste_max(cover, stroke_coverage(part.lines)[..., 3].astype(np.float32), part.origin)
    cut_image = Image.new("L", (w, h), 0)
    draw = ImageDraw.Draw(cut_image)
    for cut in cuts:
        draw.line([tuple(map(float, p)) for p in cut], fill=1, width=CUT_WIDTH)
    barrier = (cover >= 0.5) | (np.asarray(cut_image) > 0)

    graph = RegionGraph(w, h, [], [], lines, details, alignment)
    for index, part in enumerate(passes.parts):
        x0, y0 = part.origin
        ph, pw = part.flats.shape[:2]
        li = palette_labels(stroke_coverage(part.flats), min_pixels=min_area)
        flat = merge_small(li.labels, min_area)
        pieces = merge_small(_components(flat, barrier[y0:y0 + ph, x0:x0 + pw]), min_area)
        labels = np.full(flat.shape, -1, np.int32)
        group = RegionGroup(index, part.part, (x0, y0), labels)
        graph.groups.append(group)
        for box_index, box in enumerate(ndimage.find_objects(pieces + 1)):
            if box is None:
                continue
            own = pieces[box] == box_index
            colors = flat[box][own]
            colors = colors[colors >= 0]
            color = li.colors[int(np.bincount(colors).argmax())] if colors.size else (0, 0, 0, 0)
            rid = len(graph.regions)
            labels[box][own] = rid
            canvas_box = (box[1].start + x0, box[0].start + y0, box[1].stop + x0, box[0].stop + y0)
            graph.regions.append(Region(rid, index, color, 0, 0.0, Point(0, 0), canvas_box))
            graph._measure(rid)
    return graph
