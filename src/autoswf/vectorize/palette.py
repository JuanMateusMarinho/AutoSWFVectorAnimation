"""Snap a painting pass to its palette: a label image whose regions are flat colors, with anti-aliasing assigned to
the neighboring colors it mixes and soft gradients posterized into flat steps."""
from dataclasses import dataclass

import numpy as np
from scipy import ndimage

RGBA = tuple[int, int, int, int]
NEIGHBOR_RADIUS = 3
MAX_STEPS = 8
CHUNK = 1 << 16                  # pixels per block when comparing with the palette


@dataclass
class LabelImage:
    labels: np.ndarray                   # H x W int32, -1 = empty
    colors: list[RGBA]                   # straight RGBA per label
    posterized: frozenset[int]           # labels made for soft color areas


def relative_threshold(alpha: np.ndarray) -> float:
    """Half of the layer's own solid alpha (its 95th percentile), so faint pencils and full inks both threshold well."""
    nonzero = alpha[alpha > 0]
    return 0.5 if nonzero.size == 0 else 0.5 * float(np.percentile(nonzero, 95))


def _straight(rgba: np.ndarray) -> np.ndarray:
    a = rgba[..., 3:4]
    return np.where(a > 0, rgba[..., :3] / np.maximum(a, 1e-12), 0) * 255


def _pure(color: np.ndarray, alpha: np.ndarray) -> np.ndarray:
    """Pixels inside flat paint: opaque, and their 3 x 3 neighborhood spans at most 2 levels per channel (pixels on the
    image border, whose neighborhood is cut, never count as pure)."""
    visible = (alpha > 0)[..., None]
    high = ndimage.maximum_filter(np.where(visible, color, -1e9), size=(3, 3, 1), mode="constant", cval=1e9)
    low = ndimage.minimum_filter(np.where(visible, color, 1e9), size=(3, 3, 1), mode="constant", cval=-1e9)
    return (alpha >= 0.99) & ((high - low).max(axis=-1) <= 2)


def _weighted_median(values: np.ndarray, weights: np.ndarray) -> float:
    order = np.argsort(values)
    cumulative = np.cumsum(weights[order])
    return float(values[order][np.searchsorted(cumulative, cumulative[-1] / 2)])


def _palette(colors: np.ndarray, tolerance: float, min_pixels: int) -> np.ndarray:
    """Group the pure colors greedily by frequency; each kept group's color is its weighted median."""
    if len(colors) == 0:
        return np.zeros((0, 3))
    rgb = np.clip(np.round(colors), 0, 255).astype(np.int64)
    codes, counts = np.unique((rgb[:, 0] << 16) | (rgb[:, 1] << 8) | rgb[:, 2], return_counts=True)
    unique = np.stack([codes >> 16, (codes >> 8) & 255, codes & 255], axis=1)
    order = np.argsort(-counts)
    unique, counts = unique[order], counts[order]
    seeds, members = [], []
    for i, c in enumerate(unique):
        if seeds:
            d = np.abs(np.array(seeds) - c).max(axis=1)
            j = int(np.argmin(d))
            if d[j] <= tolerance:
                members[j].append(i)
                continue
        seeds.append(c)
        members.append([i])
    out = []
    for group in members:
        w = counts[group]
        if w.sum() >= min_pixels:
            out.append([_weighted_median(unique[group, k].astype(float), w) for k in range(3)])
    return np.array(out, float).reshape(-1, 3)


def _segment_distance(p: np.ndarray, a: np.ndarray, b: np.ndarray) -> np.ndarray:
    ab = b - a
    t = np.clip(((p - a) @ ab) / max(float(ab @ ab), 1e-12), 0, 1)
    return np.linalg.norm(p - (a + t[:, None] * ab), axis=1)


def _kmeans_steps(x: np.ndarray, limit: float) -> np.ndarray:
    """Fewest centers (1..MAX_STEPS) that leave every color within `limit` of its center; deterministic seeding along
    the colors' main axis, so a gradient becomes ordered steps."""
    mean = x.mean(axis=0)
    axis = np.linalg.svd(x - mean, full_matrices=False)[2][0] if len(x) > 1 else np.zeros(3)
    order = np.argsort((x - mean) @ axis)
    centers = x[:1]
    for k in range(1, MAX_STEPS + 1):
        centers = np.array([x[chunk].mean(axis=0) for chunk in np.array_split(order, k)])
        for _ in range(10):
            nearest = np.argmin(((x[:, None] - centers[None]) ** 2).sum(-1), axis=1)
            centers = np.array([x[nearest == i].mean(axis=0) if (nearest == i).any() else centers[i] for i in range(k)])
        nearest = np.argmin(((x[:, None] - centers[None]) ** 2).sum(-1), axis=1)
        if np.linalg.norm(x - centers[nearest], axis=1).max() <= limit:
            break
    return centers


def _nearest(pixels: np.ndarray, allowed: np.ndarray | None, palette: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Index of and distance to the nearest palette color (only `allowed` ones when given), in chunks so memory stays
    flat on big drawings."""
    best = np.empty(len(pixels), np.int64)
    dist = np.empty(len(pixels), np.float32)
    pal = palette.astype(np.float32)
    for i in range(0, len(pixels), CHUNK):
        d = ((pixels[i:i + CHUNK, None, :].astype(np.float32) - pal[None]) ** 2).sum(axis=-1)
        if allowed is not None:
            d[~allowed[i:i + CHUNK]] = np.inf
        b = np.argmin(d, axis=1)
        best[i:i + CHUNK] = b
        dist[i:i + CHUNK] = np.sqrt(d[np.arange(len(b)), b])
    return best, dist


def _presence(labels: np.ndarray, count: int, ys: np.ndarray, xs: np.ndarray) -> np.ndarray:
    """For the pixels (ys, xs): which labels lie within NEIGHBOR_RADIUS px (dilation done inside each label's box)."""
    present = np.zeros((len(ys), count), bool)
    h, w = labels.shape
    r = NEIGHBOR_RADIUS
    for i, box in enumerate(ndimage.find_objects(labels + 1, max_label=count)):
        if box is None:
            continue
        y0, y1 = max(box[0].start - r, 0), min(box[0].stop + r, h)
        x0, x1 = max(box[1].start - r, 0), min(box[1].stop + r, w)
        near = ndimage.binary_dilation(labels[y0:y1, x0:x1] == i, iterations=r)
        inside = (ys >= y0) & (ys < y1) & (xs >= x0) & (xs < x1)
        present[inside, i] = near[ys[inside] - y0, xs[inside] - x0]
    return present


def palette_labels(rgba: np.ndarray, *, tolerance: float = 12.0, posterize: float = 24.0,
                   min_pixels: int = 12) -> LabelImage:
    alpha = rgba[..., 3]
    color = _straight(rgba)
    opaque = alpha >= 0.5
    pure = _pure(color, alpha) & opaque
    palette = _palette(color[pure], tolerance, min_pixels)
    labels = np.full(alpha.shape, -1, np.int32)

    nearest = _nearest

    if len(palette):
        ys, xs = np.nonzero(pure)
        labels[ys, xs] = nearest(color[ys, xs], None, palette)[0]
    rest_y, rest_x = np.nonzero(opaque & (labels < 0))
    residual = np.zeros(alpha.shape, bool)
    if len(rest_y) and len(palette):
        present = _presence(labels, len(palette), rest_y, rest_x)
        allowed = present.copy()
        allowed[~present.any(axis=1)] = True                 # nothing nearby: any palette color
        pix = color[rest_y, rest_x]
        best, dist = nearest(pix, allowed, palette)
        labels[rest_y, rest_x] = best
        far = dist > posterize
        if far.any():
            mix = np.full(far.sum(), np.inf)
            fp, fpresent = pix[far], present[far]          # a mix needs both colors nearby
            for i in range(len(palette)):
                for j in range(i + 1, len(palette)):
                    both = fpresent[:, i] & fpresent[:, j]
                    if both.any():
                        mix[both] = np.minimum(mix[both], _segment_distance(fp[both], palette[i], palette[j]))
            residual[rest_y[far][mix > posterize], rest_x[far][mix > posterize]] = True
    elif len(rest_y):
        residual[rest_y, rest_x] = True

    colors = [tuple(c) for c in palette]
    posterized = set()
    areas, count = ndimage.label(residual, structure=np.ones((3, 3)))
    for area, box in enumerate(ndimage.find_objects(areas), start=1):
        ys, xs = np.nonzero(areas[box] == area)
        ys, xs = ys + box[0].start, xs + box[1].start
        if len(ys) < min_pixels and len(palette):          # a few odd pixels: keep their nearest neighbor color
            continue
        centers = _kmeans_steps(color[ys, xs], posterize)
        ids = []
        for c in centers:
            ids.append(len(colors))
            colors.append(tuple(c))
            posterized.add(ids[-1])
        choices = np.array([colors[i] for i in ids], float)
        labels[ys, xs] = np.array(ids)[nearest(color[ys, xs], None, choices)[0]]

    out = []
    for i, c in enumerate(colors):
        a = alpha[labels == i]
        level = float(np.percentile(a, 95)) if a.size else 1.0     # thin strokes are mostly edge pixels
        out.append(tuple(int(round(v)) for v in c) + (255 if level >= 0.98 else int(round(level * 255)),))
    return LabelImage(labels, out, frozenset(posterized))


def merge_small(labels: np.ndarray, min_area: int) -> np.ndarray:
    """Specks: 4-connected components smaller than `min_area` take the label they share the most border with (the
    empty label -1 only when nothing else touches them)."""
    labels = labels.astype(np.int32, copy=True)
    h, w = labels.shape
    for _ in range(3):
        specks = []
        for index, box in enumerate(ndimage.find_objects(labels + 2), start=1):
            if box is None:
                continue
            value = index - 2
            parts, n = ndimage.label(labels[box] == value)
            if n == 0:
                continue
            sizes = np.bincount(parts.ravel())[1:]
            small = np.nonzero(sizes < min_area)[0]
            if not len(small):
                continue
            boxes = ndimage.find_objects(parts)
            for i in small:
                sub = boxes[i]
                y0, x0 = box[0].start + sub[0].start, box[1].start + sub[1].start
                specks.append((int(sizes[i]), value, y0, x0, parts[sub] == i + 1))
        if not specks:
            break
        changed = False
        for _, value, sy, sx, own in sorted(specks, key=lambda s: s[0]):
            y0, x0 = max(sy - 1, 0), max(sx - 1, 0)
            y1, x1 = min(sy + own.shape[0] + 1, h), min(sx + own.shape[1] + 1, w)
            region = labels[y0:y1, x0:x1]
            mask = np.zeros(region.shape, bool)
            mask[sy - y0:sy - y0 + own.shape[0], sx - x0:sx - x0 + own.shape[1]] = own
            if not (region[mask] == value).all():
                continue                                     # already merged into something else
            ring = ndimage.binary_dilation(mask) & ~mask
            neighbors = region[ring]
            if neighbors.size == 0:                          # the speck is the whole image: outside is empty
                target = -1
            else:
                values, counts = np.unique(neighbors, return_counts=True)
                if (values != -1).any():
                    counts = np.where(values == -1, -1, counts)
                target = int(values[np.argmax(counts)])
            if target != value:
                region[mask] = target
                changed = True
        if not changed:
            break
    return labels
