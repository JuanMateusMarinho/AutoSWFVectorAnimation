import re

import numpy as np
import pytest
from PIL import Image

from editor_fixtures import (face_like_png, face_with_strip, green_patch_png, hair_colored_png, three_color_disc)
from autoswf.edit.layer import NEW_FIXED_COLOR, Tone, ToneRef
from autoswf.edit.trace_png import (EMPTY, OPAQUE, new_layer_tones, placement, read_png, replace_layer,
                                    suggest_binding, trace_png)
from autoswf.model.geometry import Matrix


def pairs(layer, edit):
    shapes = {d.key: d.shape for d in layer.drawings}
    return [(shape, shapes[key]) for key, shape in edit.shapes.items()]


def test_a_png_traces_into_one_area_per_color():
    assert len(trace_png(three_color_disc()).colors) == 3


def test_replace_maps_colors_onto_the_layer_tones():
    layer = face_with_strip()
    edit = replace_layer(layer, trace_png(face_like_png()), Matrix())
    assert edit.shapes and edit.notes == []
    assert all(len(s.fills) == len(orig.fills) for s, orig in pairs(layer, edit))   # no new fills: every color matched
    after = layer.applied(edit)
    assert after.tone_at(150, 100) == ToneRef("skin", 0) and after.tone_at(60, 140) == ToneRef("shadow", 0)
    assert after.tone_at(285, 100) is None                                          # the strip is gone


def test_an_unmatched_color_becomes_a_fixed_tone_with_a_note():
    edit = replace_layer(face_with_strip(), trace_png(green_patch_png()), Matrix())
    assert NEW_FIXED_COLOR % "#00FF00" in edit.notes


def test_same_canvas_size_lands_in_the_same_spot():
    m = Matrix(0.5, 0, 0, 0.5, -120, -120)
    assert placement((480, 480), source_size=(480, 480), source_matrix=m) == m


def test_other_sizes_fit_the_layer_bounds():
    assert placement((200, 100), target_bounds=(0, 400, 0, 400)) == Matrix(2, 0, 0, 2, 0, 100)
    assert placement((200, 100)) == Matrix.translate(-100, -50)


def test_opaque_or_empty_pngs_are_refused(tmp_path):
    Image.new("RGBA", (10, 10), (9, 9, 9, 255)).save(tmp_path / "opaque.png")
    Image.new("RGBA", (10, 10), (0, 0, 0, 0)).save(tmp_path / "empty.png")
    with pytest.raises(ValueError, match=re.escape(OPAQUE)):
        read_png(tmp_path / "opaque.png")
    with pytest.raises(ValueError, match=re.escape(EMPTY)):
        read_png(tmp_path / "empty.png")
    Image.fromarray(three_color_disc()).save(tmp_path / "ok.png")
    assert read_png(tmp_path / "ok.png").shape == (120, 120, 4)


def test_new_layer_binding_is_suggested_from_matching_item_colors():
    bound = [Tone(ToneRef("h", 0), (110, 60, 30, 255), ("Hair", "None")),
             Tone(ToneRef("s", 0), (242, 201, 160, 255), ("Skin", "None"))]
    traced = trace_png(hair_colored_png())
    assert suggest_binding(traced.colors[0], bound) == ("Hair", "None")
    assert suggest_binding((0, 255, 0, 255), bound) is None
    tones = new_layer_tones(traced, Matrix.translate(100, 100), bound)
    assert [b for _, b in tones] == [("Hair", "None")] and tones[0][0].paths
