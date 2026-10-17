# tests/drawing/test_passes.py
import numpy as np
import pytest
from drawings import disc, drawing_from_specs, rect
from autoswf.drawing.composite import blend
from autoswf.drawing.layers import DrawingError
from autoswf.drawing.passes import extract_passes, is_soft
from autoswf.drawing.roles import assign_roles
from autoswf.drawing.writers import LayerSpec

W = H = 60
RED, BLUE, INK, GOLD = (200, 40, 40, 255), (120, 110, 210, 255), (25, 15, 35, 255), (250, 220, 90, 255)

def helm_specs():
    return [LayerSpec("Flats", rect(W, H, RED, 10, 10, 50, 50)),
            LayerSpec("Shadow", rect(W, H, BLUE, 30, 0, 60, 60), blend="multiply", clipping=True),
            LayerSpec("Light", disc(W, H, (255, 255, 255, 255), 20, 20, 8, soft=True), blend="screen", clipping=True),
            LayerSpec("Details", disc(W, H, GOLD, 40, 40, 3)),
            LayerSpec("Line", rect(W, H, INK, 10, 10, 50, 13))]

def passes_of(specs, overrides=None):
    d = drawing_from_specs(W, H, specs)
    return extract_passes(d, assign_roles(d, overrides))

def test_roles_become_passes_and_tones_are_clipped():
    p = passes_of(helm_specs())
    (part,) = p.parts
    assert part.part is None and part.order == ["fills", "details", "line"] and not p.flattened
    ox, oy = part.origin
    at = lambda arr, x, y: arr[y - oy, x - ox]
    assert [t.role for t in part.tones] == ["shadow", "light"]
    shadow, light = part.tones
    assert at(shadow.alpha, 40, 30) == pytest.approx(1) and at(shadow.alpha, 55, 30) == 0
    assert not shadow.soft and light.soft
    expected = blend("multiply", np.array(RED[:3]) / 255, np.array(BLUE[:3]) / 255)
    assert at(part.fills, 40, 30)[:3] == pytest.approx(expected, abs=1 / 255)
    assert at(part.lines, 30, 11)[3] == 1 and at(part.lines, 30, 30)[3] == 0
    assert at(part.details, 40, 40)[3] == 1 and at(part.details, 30, 30)[3] == 0
    assert p.full.shape == (H, W, 4)

def test_part_folders_become_parts():
    specs = [LayerSpec("Face", children=[LayerSpec("Flats", rect(W, H, RED, 0, 30, 60, 60))]),
             LayerSpec("Hair", children=[LayerSpec("Flats", rect(W, H, BLUE, 0, 0, 60, 35)), LayerSpec("Line", rect(W, H, INK, 0, 33, 60, 35))])]
    p = passes_of(specs)
    assert [(q.part, q.origin) for q in p.parts] == [("Face", (0, 30)), ("Hair", (0, 0))]

def test_no_role_names_vectorize_the_whole_drawing_as_flats():
    p = passes_of([LayerSpec("Paper", rect(W, H, (255, 255, 255, 255), 0, 0, W, H)), LayerSpec("Layer 1", rect(W, H, RED, 5, 5, 20, 20))])
    assert p.flattened and len(p.parts) == 1 and p.parts[0].flats[10 - p.parts[0].origin[1], 10 - p.parts[0].origin[0], 3] == 1
    assert "No layer name matches a painting pass" in " ".join(p.notes) and "--role" in " ".join(p.notes)

def test_nothing_visible_is_an_error():
    with pytest.raises(DrawingError, match="Nothing to vectorize: every layer is empty, hidden or ignored"):
        passes_of([LayerSpec("Paper", rect(W, H, (255, 255, 255, 255), 0, 0, W, H)), LayerSpec("Line", rect(W, H, INK, 0, 0, 5, 5), visible=False)])

def test_tone_above_the_lines_is_noted():
    specs = helm_specs(); specs.append(specs.pop(2))       # Light moved above Line
    p = passes_of(specs)
    assert p.parts[0].tone_above_lines and any("above the line art" in n for n in p.notes)

def test_soft_detection():
    hard = disc(W, H, (0, 0, 0, 255), 30, 30, 20)[..., 3] / 255
    soft = disc(W, H, (0, 0, 0, 255), 30, 30, 20, soft=True)[..., 3] / 255
    assert not is_soft(hard) and is_soft(soft)

def test_used_layers_that_draw_nothing_are_an_error():
    with pytest.raises(DrawingError, match="Nothing to vectorize"):
        passes_of([LayerSpec("Line", rect(W, H, INK, 5, 5, 50, 50), opacity=0.0)])
    with pytest.raises(DrawingError, match="Nothing to vectorize"):
        passes_of([LayerSpec("Flats", rect(W, H, (0, 0, 0, 0), 0, 0, W, H)),
                   LayerSpec("Line", rect(W, H, INK, 5, 5, 50, 50), clipping=True)])

def test_empty_role_layers_get_a_note():
    p = passes_of([LayerSpec("Flats", rect(W, H, RED, 5, 5, 50, 50)), LayerSpec("Line", rect(W, H, (0, 0, 0, 0), 0, 0, W, H))])
    note = " ".join(p.notes)
    assert "Layer 'Line' (line) is empty" in note and "Rasterize" in note
