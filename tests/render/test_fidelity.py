# tests/render/test_fidelity.py
import os
from pathlib import Path
import subprocess
import pytest
from PySide6.QtGui import QColor, QImage, QPainter
from autoswf.abc.movieclip_classes import ClassSpec, build_abc
from autoswf.render import fidelity
from autoswf.render.display import instantiate
from autoswf.render.fidelity import compare_images, default_targets, run_fidelity
from autoswf.render.painter import render_fitted
from autoswf.swf.decode import MovieData
from autoswf.swf.movie import build_swf
from aqw_fakes import _disc, _holder

def disc(size, x, y, color=(200, 50, 50)):
    img = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied); img.fill(0)
    p = QPainter(img); p.setRenderHint(QPainter.RenderHint.Antialiasing); p.setBrush(QColor(*color)); p.setPen(QColor(*color))
    p.drawEllipse(x, y, 20, 20); p.end()
    return img

def test_identical_images_match(qapp):
    r = compare_images(disc(40, 10, 10), disc(40, 10, 10))
    assert (r.iou, r.mean_error, r.shift) == (1.0, 0.0, (0, 0))

def test_small_offsets_and_canvas_sizes_are_tolerated(qapp):
    r = compare_images(disc(40, 10, 10), disc(50, 12, 13))
    assert r.iou == 1.0 and r.mean_error == 0.0

def test_color_difference_is_measured(qapp):
    r = compare_images(disc(40, 10, 10), disc(40, 10, 10, color=(250, 50, 50)))
    assert r.iou == 1.0 and 45 <= r.mean_error * 3 <= 55      # mean over R, G, B: a +50 red gap averages ~16.7

def one_class_swf(class_name, radius):
    part = _holder("Part", _disc((90, 110, 140, 255), radius))
    return build_swf([part], {id(part): class_name}, build_abc([ClassSpec(class_name)]))

def fake_ffdec(command, **kwargs):
    """Stands in for FFDec: renders each selected character with AutoSWF into DefineSprite_<id>_<class>/1.png."""
    ids = [int(c) for c in command[command.index("-selectid") + 1].split(",")]
    zoom, out, swf = float(command[command.index("-zoom") + 1]), command[-2], command[-1]
    movie = MovieData(swf)
    names = {cid: n for n, cid in movie.classes.items()}
    for cid in ids:
        folder = Path(out) / ("DefineSprite_%d_%s" % (cid, names[cid]))
        folder.mkdir(parents=True, exist_ok=True)
        render_fitted(instantiate(movie, cid), zoom, None).save(str(folder / "1.png"))
    return subprocess.CompletedProcess(command, 0, "", "")

def test_same_named_files_in_different_folders_keep_their_own_references(qapp, tmp_path, monkeypatch):
    (tmp_path / "tool").mkdir(); (tmp_path / "tool" / "ffdec-cli.jar").write_bytes(b"")
    swfs = {}
    for gender, part, radius in (("M", "Shin", 8), ("F", "Robe", 30)):
        swfs[gender] = tmp_path / "classes" / gender / "Item.swf"
        swfs[gender].parent.mkdir(parents=True)
        swfs[gender].write_bytes(one_class_swf("Item%s%s" % (gender, part), radius))
    assert len({tuple(MovieData(p).classes.values()) for p in swfs.values()}) == 1     # same character id, other art
    monkeypatch.setattr(fidelity.subprocess, "run", fake_ffdec)
    targets = [(swfs["M"], "ItemMShin"), (swfs["F"], "ItemFRobe")]
    for _ in range(2):                                                                  # a reused report folder too
        rows = run_fidelity(targets, tmp_path / "tool", tmp_path / "report")
        assert [(r.class_name, r.passed) for r in rows] == [("ItemMShin", True), ("ItemFRobe", True)], rows

@pytest.mark.aqw
def test_official_items_match_ffdec(qapp, aqw_cache, tmp_path):
    ffdec = os.environ.get("AUTOSWF_FFDEC")
    if not ffdec:
        pytest.skip("set AUTOSWF_FFDEC to the FFDec folder")
    rows = run_fidelity(default_targets(aqw_cache), Path(ffdec), tmp_path)
    assert rows and all(r.passed or r.known for r in rows), [(r.file, r.class_name, r.result, r.error) for r in rows if not r.passed]
