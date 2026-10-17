# tests/vectorize/test_planar.py
import numpy as np
from scipy import ndimage
from autoswf.aqw.helm import HelmItem, export_helm
from autoswf.model.document import Frame, Placement, Symbol
from autoswf.model.geometry import Matrix
from autoswf.model.shape import SolidFill
from autoswf.render.display import ScriptContext, instantiate, run_pending_actions
from autoswf.render.effects import qimage_to_array
from autoswf.render.painter import Renderer
from autoswf.render.paths import fill_paths
from autoswf.swf.decode import MovieData
from autoswf.vectorize.fit import FitSettings
from autoswf.vectorize.planar import trace_shape

COLORS = [(220, 40, 40, 255), (40, 180, 60, 255), (240, 220, 80, 255)]

def labels():
    yy, xx = np.mgrid[0:120, 0:160]
    lab = np.full((120, 160), -1)
    lab[(xx - 60) ** 2 + (yy - 60) ** 2 < 45 ** 2] = 0
    lab[(xx > 70) & (xx < 140) & (yy > 20) & (yy < 100)] = 1
    lab[(abs(xx - 100) + abs(yy - 60) < 12)] = 2                      # a diamond inside region 1
    lab[(abs(yy - 0.25 * xx - 85) < 1 + xx / 60) & (xx > 10) & (xx < 150)] = 2   # a thin tapered stroke across everything
    return lab

def render(shape, w, h, scale):
    md = MovieData(export_helm(HelmItem("T", Symbol("T", [Frame([Placement(shape, 1)])]))))
    obj = instantiate(md, md.classes["T"]); run_pending_actions(obj, ScriptContext(None))
    return md, qimage_to_array(Renderer().render_image(obj, w, h, Matrix.scale(scale, scale), None))

def test_traced_regions_render_without_holes_and_match_the_labels(qapp):
    lab = labels()
    shape = trace_shape(lab, [SolidFill(c) for c in COLORS], FitSettings(), Matrix.scale(0.1, 0.1))
    md, img = render(shape, 160, 120, 10.0)
    inside = ndimage.binary_erosion(lab >= 0, iterations=2)
    assert (img[..., 3][inside] >= 0.99).all()
    traced = img[..., 3] >= 0.5
    assert (traced & (lab >= 0)).sum() / (traced | (lab >= 0)).sum() >= 0.97
    sharp = ndimage.binary_erosion(lab == 1, iterations=3)
    assert np.allclose(img[sharp][:, :3], np.array(COLORS[1][:3]) / 255, atol=1 / 255)

def test_every_fill_contour_closes_after_twips_rounding(qapp):
    shape = trace_shape(labels(), [SolidFill(c) for c in COLORS], FitSettings(), Matrix(0.137, 0, 0, 0.137, -3.3, 7.1))
    md, _ = render(shape, 10, 10, 1.0)
    (sid,) = [cid for cid in range(1, 10) if type(md.character(cid)).__name__ == "ShapeDef"]
    for fp in fill_paths(md.character(sid)):
        for contour in fp.contours:
            assert contour[0][0] == contour[-1][2]
