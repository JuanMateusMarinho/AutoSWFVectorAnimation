# tests/vectorize/test_metrics.py
from drawings import disc, drawing_from_specs, rect
from autoswf.aqw.helm import export_helm
from autoswf.aqw.template import Alignment
from autoswf.drawing.passes import extract_passes
from autoswf.drawing.roles import assign_roles
from autoswf.drawing.writers import LayerSpec
from autoswf.vectorize.art import helm_from_art, vectorize

W = H = 160
SPECS = [LayerSpec("Flats", disc(W, H, (200, 40, 40, 255), 80, 80, 60)),
         LayerSpec("Shadow", rect(W, H, (90, 80, 160, 255), 100, 0, 160, 160), blend="multiply", clipping=True),
         LayerSpec("Line", rect(W, H, (20, 10, 30, 255), 30, 76, 130, 82))]

def report_for(alignment_for_export=None, drop_path=False, scale=4, specs=SPECS):
    from autoswf.vectorize.metrics import quality_report
    d = drawing_from_specs(W, H, specs)
    passes = extract_passes(d, assign_roles(d))
    art = vectorize(passes, Alignment(scale, (80, 80)))
    if alignment_for_export:
        art = vectorize(passes, alignment_for_export); art.alignment = Alignment(scale, (80, 80))
    if drop_path:
        paths = art.layers[0].shape.paths
        paths.remove(max(paths, key=lambda p: len(p.segments)))
    return quality_report(passes, art, export_helm(helm_from_art(art, "Q")), "Q")

def test_clean_art_meets_the_bars(qapp):
    r = report_for()
    assert r.problems() == [] and set(r.gaps) == {"1x", "2x", "4x", "source"} and r.segments > 0 and r.bytes > 0

def test_shifted_art_fails_the_edge_bar(qapp):
    r = report_for(alignment_for_export=Alignment(4, (77, 80)))
    assert r.edge_p95 >= 2 and any(p.startswith("Edges") for p in r.problems())

def test_missing_edge_shows_as_gaps(qapp):
    r = report_for(drop_path=True)
    assert max(r.gaps.values()) > 0 and any(p.startswith("Gaps") for p in r.problems())

def test_zooms_past_the_drawing_pixels_measure_gaps_at_drawing_resolution(qapp):
    # At 1 px per head unit, 4x zoom shows each drawing pixel as 4 x 4. A 3 x 3 speck that the default detail drops is
    # within the edge tolerance at the drawing's resolution, so it is no gap when zoomed in either.
    flats = disc(W, H, (200, 40, 40, 255), 80, 80, 40)
    flats[20:23, 140:143] = (200, 40, 40, 255)
    assert report_for(scale=1, specs=[LayerSpec("Flats", flats)]).gaps == {"1x": 0, "2x": 0, "4x": 0, "source": 0}
    assert report_for(scale=1, drop_path=True).gaps["4x"] > 0          # a missing shape still shows at 4x

def test_color_labels_keep_memory_flat_on_big_drawings():
    import tracemalloc
    import numpy as np
    from autoswf.vectorize.metrics import _labels
    palette = np.array([(r, g, b) for r in (.1, .4, .7, .9) for g in (.2, .5, .8) for b in (.15, .6, .95)], np.float32)
    h = w = 2000
    stripe = w // len(palette) + 1
    rgba = np.ones((h, w, 4), np.float32)                         # opaque, so premultiplied = straight
    rgba[..., :3] = np.repeat(palette, stripe, axis=0)[:w][None]  # 36 flat colors side by side
    rgba[:, :10] = 0                                              # and a transparent strip
    tracemalloc.start()
    labels = _labels(rgba, palette)
    peak = tracemalloc.get_traced_memory()[1]
    tracemalloc.stop()
    assert (labels[:, :10] == -1).all() and (labels[:, 10:] == (np.arange(10, w) // stripe)[None]).all()
    assert peak < 64 * 2 ** 20, peak / 2 ** 20
