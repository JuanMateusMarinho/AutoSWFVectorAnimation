# tests/parts/test_parts_acceptance.py
import pytest
from drawings import synthetic_parts_helm
from autoswf.aqw.helm import export_helm
from autoswf.aqw.validate import validate_helm_swf
from autoswf.drawing.passes import extract_passes
from autoswf.drawing.readers import read_drawing
from autoswf.drawing.roles import assign_roles
from autoswf.drawing.writers import write_clip, write_psd
from autoswf.parts.assemble import assemble_helm
from autoswf.parts.detect import detect_parts
from autoswf.parts.hidden import layered_passes, split_passes
from autoswf.vectorize.art import vectorize
from autoswf.vectorize.metrics import QUALITY_BARS, quality_report

def exported_segments(symbol, seen=None) -> int:
    """Segments of every shape the helm's SWF holds (each shape once)."""
    from autoswf.model.shape import Shape
    seen = set() if seen is None else seen
    total = 0
    for frame in symbol.frames:
        for p in frame.placements:
            if id(p.item) in seen:
                continue
            seen.add(id(p.item))
            total += sum(len(path.segments) for path in p.item.paths) if isinstance(p.item, Shape)                 else exported_segments(p.item, seen)
    return total


def convert(path, alignment):
    d = read_drawing(path)
    passes = extract_passes(d, assign_roles(d))
    pm = detect_parts(passes, alignment)
    layers = split_passes(passes, pm)
    art = vectorize(layered_passes(passes, layers), alignment)
    helm = assemble_helm(art, layers, "Accept")
    swf = export_helm(helm.item)
    assert validate_helm_swf(swf, "Accept") == []
    convert.segments = exported_segments(helm.item.root)
    return passes, pm, art, swf

@pytest.mark.parametrize("suffix, writer", [(".psd", write_psd), (".clip", write_clip)])
def test_parts_helm_meets_the_quality_bar(tmp_path, qapp, suffix, writer):
    t = synthetic_parts_helm()
    writer(tmp_path / ("helm" + suffix), t.width, t.height, t.layers)
    passes, pm, art, swf = convert(tmp_path / ("helm" + suffix), t.alignment)
    report = quality_report(passes, art, swf, "Accept")
    assert report.problems() == [], report.format()
    assert report.bytes < 80_000

@pytest.mark.aqw
@pytest.mark.parametrize("rel, class_name", [("items/helms/ArtixHead.swf", "ArtixHead"),
                                              ("items/helms/GoldLeppy2018HatM.swf", "GoldLeppy2018HatM"),
                                              (None, "mcHeadM"), (None, "mcHeadF"), ("morph", "CrystallisOnsenMMorph4")])
def test_official_helms_with_parts(tmp_path, qapp, aqw_cache, request, rel, class_name):
    from official_drawings import official_drawing, official_segment_count
    from autoswf.swf.decode import MovieData
    path = request.getfixturevalue("reference_morph") if rel == "morph" else (
        aqw_cache.file_path(rel) if rel else aqw_cache.client_path())
    movie = MovieData(path)
    t = official_drawing(movie, class_name)
    write_psd(tmp_path / "o.psd", t.width, t.height, t.layers)
    passes, pm, art, swf = convert(tmp_path / "o.psd", t.alignment)
    report = quality_report(passes, art, swf, "Accept")
    assert report.problems(dict(QUALITY_BARS, color_shift=0.01)) == [], report.format()
    assert convert.segments <= 6 * official_segment_count(movie, class_name) and report.bytes < 20_000

@pytest.mark.aqw
def test_morph_check_in_convert(tmp_path, capsys, qapp, aqw_cache):
    from official_drawings import official_drawing
    from autoswf.cli import main
    from autoswf.swf.decode import MovieData
    t = official_drawing(MovieData(aqw_cache.client_path()), "mcHeadM")       # drawn as a morph of the male head
    write_psd(tmp_path / "m.psd", t.width, t.height, t.layers)
    assert main(["convert", str(tmp_path / "m.psd"), "--align", str(t.alignment), "--morph"]) == 0
    line = next(l for l in capsys.readouterr().out.splitlines() if l.startswith("Morph check"))
    assert "female: " in line and "— male" not in line          # the female head is wider than the male one
