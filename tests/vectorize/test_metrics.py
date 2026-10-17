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

def report_for(alignment_for_export=None, drop_path=False):
    from autoswf.vectorize.metrics import quality_report
    d = drawing_from_specs(W, H, SPECS)
    passes = extract_passes(d, assign_roles(d))
    art = vectorize(passes, Alignment(4, (80, 80)))
    if alignment_for_export:
        art = vectorize(passes, alignment_for_export); art.alignment = Alignment(4, (80, 80))
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
