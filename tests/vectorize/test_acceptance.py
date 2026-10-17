# tests/vectorize/test_acceptance.py
import pytest
from drawings import synthetic_helm
from autoswf.aqw.helm import export_helm
from autoswf.aqw.validate import validate_helm_swf
from autoswf.drawing.passes import extract_passes
from autoswf.drawing.readers import read_drawing
from autoswf.drawing.roles import assign_roles
from autoswf.drawing.writers import write_clip, write_psd
from autoswf.vectorize.art import helm_from_art, segment_count, vectorize
from autoswf.vectorize.metrics import QUALITY_BARS, quality_report

def convert(path, alignment):
    d = read_drawing(path)
    passes = extract_passes(d, assign_roles(d))
    art = vectorize(passes, alignment)
    swf = export_helm(helm_from_art(art, "Accept"))
    assert validate_helm_swf(swf, "Accept") == []
    return passes, art, swf

@pytest.mark.parametrize("suffix, writer", [(".psd", write_psd), (".clip", write_clip)])
def test_synthetic_helm_meets_the_quality_bar(tmp_path, qapp, suffix, writer):
    t = synthetic_helm()
    writer(tmp_path / ("helm" + suffix), t.width, t.height, t.layers)
    passes, art, swf = convert(tmp_path / ("helm" + suffix), t.alignment)
    report = quality_report(passes, art, swf, "Accept")
    assert report.problems() == [], report.format()
    assert [l.name for l in art.layers] == ["Fills", "Details", "Line"] and report.bytes < 60_000

@pytest.mark.aqw
@pytest.mark.parametrize("rel, class_name", [("items/helms/ArtixHead.swf", "ArtixHead"),
                                              ("items/helms/GoldLeppy2018HatM.swf", "GoldLeppy2018HatM"),
                                              (None, "mcHeadM"), (None, "mcHeadF")])
def test_official_helms_meet_the_quality_bar(tmp_path, qapp, aqw_cache, rel, class_name):
    from official_drawings import official_drawing, official_segment_count
    from autoswf.swf.decode import MovieData
    movie = MovieData(aqw_cache.file_path(rel) if rel else aqw_cache.client_path())
    t = official_drawing(movie, class_name)
    write_psd(tmp_path / "o.psd", t.width, t.height, t.layers)
    passes, art, swf = convert(tmp_path / "o.psd", t.alignment)
    report = quality_report(passes, art, swf, "Accept")
    assert report.problems(dict(QUALITY_BARS, color_shift=0.01)) == [], report.format()
    assert segment_count(art) <= 2.5 * official_segment_count(movie, class_name)

@pytest.mark.parametrize("size, detail", [(2000, 50), (480, 0)])
def test_template_size_and_lowest_detail_meet_the_bar(qapp, size, detail):
    from drawings import drawing_from_specs
    from autoswf.vectorize.art import VectorizeSettings
    t = synthetic_helm(size)
    d = drawing_from_specs(t.width, t.height, t.layers)
    passes = extract_passes(d, assign_roles(d))
    art = vectorize(passes, t.alignment, VectorizeSettings(detail=detail))
    swf = export_helm(helm_from_art(art, "Accept"))
    report = quality_report(passes, art, swf, "Accept")
    bars = dict(QUALITY_BARS) if detail == 50 else dict(QUALITY_BARS, edge_p95=2.5, edge_p99=4.0, color_shift=0.02)
    assert report.problems(bars) == [], report.format()
