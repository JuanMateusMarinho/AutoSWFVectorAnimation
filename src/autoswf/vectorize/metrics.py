"""Automatic quality metrics of vector art against its source drawing (spec §7 quality bar): edge distance at source
resolution, gaps at 1x / 2x / 4x zoom and at source scale, color shifts away from edges, size."""
import math
from dataclasses import dataclass

import numpy as np
from PIL import Image
from scipy import ndimage

from autoswf.drawing.passes import Passes
from autoswf.model.geometry import Matrix
from autoswf.model.shape import SolidFill
from autoswf.vectorize.art import VectorArt, segment_count

QUALITY_BARS = {"edge_p95": 1.0, "edge_p99": 2.0, "gaps": 0, "color_shift": 0.005}
ZOOMS = (1, 2, 4)
SHIFT = 12 / 255
LABEL_BLOCK = 1 << 20          # pixel x palette color pairs measured at once (12 MB of float32 differences)


@dataclass(frozen=True)
class QualityReport:
    edge_p95: float              # px at source resolution
    edge_p99: float
    gaps: dict[str, int]         # "1x", "2x", "4x", "source" -> pixels where the background shows through
    color_shift: float           # fraction of flat interior pixels whose color moved
    segments: int
    bytes: int

    def problems(self, bars: dict[str, float] = QUALITY_BARS) -> list[str]:
        out = []
        if self.edge_p95 > bars["edge_p95"]:
            out.append("Edges are off by %.2f px (95th percentile; at most %.1f)" % (self.edge_p95, bars["edge_p95"]))
        if self.edge_p99 > bars["edge_p99"]:
            out.append("Edges are off by %.2f px (99th percentile; at most %.1f)" % (self.edge_p99, bars["edge_p99"]))
        for zoom, count in self.gaps.items():
            if count > bars["gaps"]:
                out.append("Gaps: %d pixels show the background at %s zoom" % (count, zoom))
        if self.color_shift > bars["color_shift"]:
            out.append("Colors shift in %.2f%% of flat areas (at most %.1f%%)"
                       % (self.color_shift * 100, bars["color_shift"] * 100))
        return out

    def format(self) -> str:
        lines = ["Quality against the drawing:",
                 "  Edges: 95%% within %.2f px, 99%% within %.2f px" % (self.edge_p95, self.edge_p99),
                 "  Gaps: " + ", ".join("%s %d" % item for item in self.gaps.items()),
                 "  Color shift: %.2f%% of flat areas" % (self.color_shift * 100),
                 "  Size: %d segments, %.1f KB" % (self.segments, self.bytes / 1024)]
        problems = self.problems()
        lines += ["  Problem: " + p for p in problems] if problems else ["  Meets the quality bar."]
        return "\n".join(lines)


def _inverse(m: Matrix) -> Matrix:
    det = m.a * m.d - m.b * m.c
    return Matrix(m.d / det, -m.b / det, -m.c / det, m.a / det, (m.c * m.ty - m.d * m.tx) / det,
                  (m.b * m.tx - m.a * m.ty) / det)


def _render(swf: bytes, link: str, width: int, height: int, matrix: Matrix) -> np.ndarray:
    from PySide6.QtGui import QGuiApplication
    from autoswf.render.display import ScriptContext, instantiate, run_pending_actions
    from autoswf.render.effects import qimage_to_array
    from autoswf.render.painter import Renderer
    from autoswf.swf.decode import MovieData
    QGuiApplication.instance() or QGuiApplication([])
    movie = MovieData(swf)
    obj = instantiate(movie, movie.classes[link])
    run_pending_actions(obj, ScriptContext(None))
    return qimage_to_array(Renderer(cache_bytes=0).render_image(obj, width, height, matrix, None))


def _straight(rgba: np.ndarray) -> np.ndarray:
    a = rgba[..., 3:4]
    return np.where(a > 0, rgba[..., :3] / np.maximum(a, 1e-12), 0)


def _labels(rgba: np.ndarray, palette: np.ndarray) -> np.ndarray:
    """Nearest palette color of each pixel (-1 where mostly transparent), a few rows at a time so that the pixel x
    color distances stay around LABEL_BLOCK values whatever the drawing and palette size."""
    pal, out = palette.astype(np.float32), np.empty(rgba.shape[:2], np.int32)
    rows = max(1, LABEL_BLOCK // (rgba.shape[1] * len(pal)))
    for y in range(0, rgba.shape[0], rows):
        color = _straight(rgba[y:y + rows].astype(np.float32))
        out[y:y + rows] = np.argmin(((color[..., None, :] - pal) ** 2).sum(-1), axis=-1)
    out[rgba[..., 3] < 0.5] = -1
    return out


def _edges(labels: np.ndarray) -> np.ndarray:
    e = np.zeros(labels.shape, bool)
    e[:, :-1] |= labels[:, :-1] != labels[:, 1:]
    e[:-1, :] |= labels[:-1, :] != labels[1:, :]
    return e


def _inside(alpha: np.ndarray, tolerance: float) -> np.ndarray:
    """Opaque source pixels deeper than the fitting tolerance plus one anti-aliased pixel from the silhouette (in any
    direction, diagonals included): background showing there is a gap, not an edge within tolerance."""
    depth = 1 + math.ceil(tolerance)
    return ndimage.binary_erosion(alpha >= 0.98, structure=np.ones((3, 3), bool), iterations=depth)


def _resample(rgba: np.ndarray, width: int, height: int) -> np.ndarray:
    return np.stack([np.asarray(Image.fromarray(np.ascontiguousarray(rgba[..., c]), "F").resize((width, height), Image.BOX))
                     for c in range(4)], axis=-1)


def _enlarge(mask: np.ndarray, width: int, height: int) -> np.ndarray:
    """Each pixel of `mask` as the block of pixels it covers at width x height."""
    h, w = mask.shape
    ys = np.minimum(((np.arange(height) + 0.5) * h / height).astype(np.intp), h - 1)
    xs = np.minimum(((np.arange(width) + 0.5) * w / width).astype(np.intp), w - 1)
    return mask[np.ix_(ys, xs)]


def quality_report(passes: Passes, art: VectorArt, swf: bytes, link: str) -> QualityReport:
    w, h = passes.width, passes.height
    to_source = _inverse(art.alignment.matrix())
    rendered = _render(swf, link, w, h, to_source)
    source = passes.full
    soft = ndimage.binary_dilation(art.soft, iterations=2) if art.soft.any() else art.soft

    colors = [f.color[:3] for layer in art.layers for f in layer.shape.fills if isinstance(f, SolidFill)]
    palette = np.array(colors or [(0, 0, 0)], np.float32) / 255
    src_edges, ren_edges = _edges(_labels(source, palette)) & ~soft, _edges(_labels(rendered, palette)) & ~soft
    to_src, to_ren = ndimage.distance_transform_edt(~src_edges), ndimage.distance_transform_edt(~ren_edges)
    distances = np.concatenate([to_src[ren_edges], to_ren[src_edges]])
    p95, p99 = (float(np.percentile(distances, q)) if distances.size else 0.0 for q in (95, 99))

    gaps, solid_at_source = {}, _inside(source[..., 3], art.tolerance)
    for zoom in ZOOMS:
        f = zoom / art.alignment.scale
        zw, zh = max(1, round(w * f)), max(1, round(h * f))
        view = _render(swf, link, zw, zh, Matrix.scale(f, f) @ to_source)
        if f > 1:      # zoomed past the drawing's own pixels: only they say what is solid (no blocky stair steps)
            solid = _enlarge(solid_at_source, zw, zh)
        else:
            solid = _inside(_resample(source, zw, zh)[..., 3], art.tolerance * f)
        gaps["%dx" % zoom] = int((solid & (view[..., 3] < 0.9)).sum())
    gaps["source"] = int((solid_at_source & (rendered[..., 3] < 0.9)).sum())

    interior = ((to_src > 2) & (to_ren > 2) & (source[..., 3] >= 0.99) & (rendered[..., 3] >= 0.99) & ~soft)
    shifted = np.abs(_straight(rendered) - _straight(source)).max(axis=-1) > SHIFT
    shift = float((shifted & interior).sum() / interior.sum()) if interior.any() else 0.0
    return QualityReport(p95, p99, gaps, shift, segment_count(art), len(swf))
