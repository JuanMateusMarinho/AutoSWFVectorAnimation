# tests/render/test_fidelity.py
import os
from pathlib import Path
import pytest
from PySide6.QtGui import QColor, QImage, QPainter
from autoswf.render.fidelity import compare_images, default_targets, run_fidelity

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

@pytest.mark.aqw
def test_official_items_match_ffdec(qapp, aqw_cache, tmp_path):
    ffdec = os.environ.get("AUTOSWF_FFDEC")
    if not ffdec:
        pytest.skip("set AUTOSWF_FFDEC to the FFDec folder")
    rows = run_fidelity(default_targets(aqw_cache), Path(ffdec), tmp_path)
    assert rows and all(r.passed or r.known for r in rows), [(r.file, r.class_name, r.result, r.error) for r in rows if not r.passed]
