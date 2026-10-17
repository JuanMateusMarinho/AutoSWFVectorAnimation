# tests/vectorize/test_gradient.py
import numpy as np
import pytest
from drawings import disc, drawing_from_specs, rect
from autoswf.aqw.template import Alignment
from autoswf.drawing.passes import extract_passes
from autoswf.drawing.roles import assign_roles
from autoswf.drawing.writers import LayerSpec
from autoswf.model.shape import GradientFill
from autoswf.vectorize.art import VectorizeSettings, vectorize
from autoswf.vectorize.gradient import fit_gradient

def test_radial_blob_and_linear_ramp():
    yy, xx = np.mgrid[0:80, 0:80]
    blob = np.clip(1 - np.hypot(xx - 30, yy - 40) / 25, 0, 1)
    g, err = fit_gradient((255, 255, 255), blob)
    assert g.kind == "radial" and err <= 0.04
    assert (g.matrix.tx, g.matrix.ty) == (pytest.approx(30, abs=1.5), pytest.approx(40, abs=1.5))
    assert g.stops[0].color[3] > g.stops[-1].color[3]
    ramp = np.tile(np.linspace(1, 0, 80), (80, 1))
    g, err = fit_gradient((255, 200, 0), ramp)
    assert g.kind == "linear" and err <= 0.04

def test_gradient_layer_becomes_an_overlay():
    W = H = 100
    specs = [LayerSpec("Flats", rect(W, H, (200, 40, 40, 255), 0, 0, W, H)),
             LayerSpec("Light", disc(W, H, (255, 255, 255, 255), 50, 50, 30, soft=True), clipping=True)]
    d = drawing_from_specs(W, H, specs)
    passes = extract_passes(d, assign_roles(d))
    art = vectorize(passes, Alignment(1, (0, 0)), VectorizeSettings(gradient_layers=frozenset({"Light"})))
    assert [l.name for l in art.layers] == ["Fills", "Light (gradient)"]
    assert all(not s.tones for s in art.layers[0].styles)
    assert isinstance(art.layers[1].shape.fills[0], GradientFill)
    with pytest.raises(ValueError, match="No tone layer named 'Glow' to draw with gradients"):
        vectorize(passes, Alignment(1, (0, 0)), VectorizeSettings(gradient_layers=frozenset({"Glow"})))
