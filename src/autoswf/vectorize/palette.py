"""Snap a painting pass to its palette: a label image whose regions are flat colors, with anti-aliasing assigned to
the neighboring colors it mixes and soft gradients posterized into flat steps."""
from dataclasses import dataclass

import numpy as np
from scipy import ndimage

RGBA = tuple[int, int, int, int]
NEIGHBOR_RADIUS = 3
MAX_STEPS = 8


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
    unique, counts = np.unique(np.round(colors).astype(np.int32), axis=0, return_counts=True)
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


def palette_labels(rgba: np.ndarray, *, tolerance: float = 12.0, posterize: float = 24.0,
                   min_pixels: int = 12) -> LabelImage:
    alpha = rgba[..., 3]
    color = _straight(rgba)
    opaque = alpha >= 0.5
    pure = _pure(color, alpha) & opaque
    palette = _palette(color[pure], tolerance, min_pixels)
    labels = np.full(alpha.shape, -1, np.int32)

    def nearest(pixels: np.ndarray, allowed: np.ndarray | None, pal: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        d = np.linalg.norm(pixels[:, None, :] - pal[None], axis=2)
        if allowed is not None:
            d = np.where(allowed, d, np.inf)
        best = np.argmin(d, axis=1)
        return best, d[np.arange(len(best)), best]

    if len(palette):
        ys, xs = np.nonzero(pure)
        labels[ys, xs] = nearest(color[ys, xs], None, palette)[0]
    rest_y, rest_x = np.nonzero(opaque & (labels < 0))
    residual = np.zeros(alpha.shape, bool)
    if len(rest_y) and len(palette):
        present = np.stack([ndimage.binary_dilation(labels == i, iterations=NEIGHBOR_RADIUS)[rest_y, rest_x]
                            for i in range(len(palette))], axis=1)
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
    for area in range(1, count + 1):
        ys, xs = np.nonzero(areas == area)
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
        median = float(np.median(a)) if a.size else 1.0
        out.append(tuple(int(round(v)) for v in c) + (255 if median >= 0.98 else int(round(median * 255)),))
    return LabelImage(labels, out, frozenset(posterized))


def merge_small(labels: np.ndarray, min_area: int) -> np.ndarray:
    """Specks: 4-connected components smaller than `min_area` take the label they share the most border with (the
    empty label -1 only when nothing else touches them)."""
    labels = labels.astype(np.int32, copy=True)
    for _ in range(3):
        specks = []
        for value in np.unique(labels):
            parts, n = ndimage.label(labels == value)
            if n == 0:
                continue
            sizes = ndimage.sum_labels(np.ones_like(parts), parts, index=np.arange(1, n + 1))
            boxes = ndimage.find_objects(parts)
            for i in np.nonzero(sizes < min_area)[0]:
                specks.append((sizes[i], int(value), parts, i + 1, boxes[i]))
        if not specks:
            break
        changed = False
        for _, value, parts, index, box in sorted(specks, key=lambda s: s[0]):
            y0, y1 = max(box[0].start - 1, 0), min(box[0].stop + 1, labels.shape[0])
            x0, x1 = max(box[1].start - 1, 0), min(box[1].stop + 1, labels.shape[1])
            region = labels[y0:y1, x0:x1]
            mask = parts[y0:y1, x0:x1] == index
            if not (region[mask] == value).all():
                continue                                     # already merged into something else
            ring = ndimage.binary_dilation(mask) & ~mask
            neighbors = region[ring]
            if neighbors.size == 0:
                continue
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
