# tests/parts/test_regions.py
import numpy as np
from drawings import drawing_from_specs, rect
from autoswf.aqw.template import Alignment
from autoswf.drawing.passes import extract_passes
from autoswf.drawing.roles import assign_roles
from autoswf.drawing.writers import LayerSpec
from autoswf.parts.regions import build_regions

W, H = 100, 60
RED, INK, SKIN = (200, 40, 40, 255), (20, 20, 30, 255), (240, 200, 160, 255)

def graph(specs, cuts=(), alignment=Alignment(10, (0, 0))):
    d = drawing_from_specs(W, H, specs)
    return build_regions(extract_passes(d, assign_roles(d)), alignment, cuts)

def test_a_line_across_a_flat_splits_it():
    g = graph([LayerSpec("Flats", rect(W, H, RED, 0, 0, W, H)), LayerSpec("Line", rect(W, H, INK, 48, 0, 52, H))])
    assert sorted(round(r.area) for r in g.regions) == [30, 30]
    a, b = g.regions
    assert abs(g.adjacency(0)[(a.id, b.id)] - 6.0) < 0.5        # 60 px of shared boundary at 10 px per unit

def test_an_open_line_does_not_split():
    g = graph([LayerSpec("Flats", rect(W, H, RED, 0, 0, W, H)), LayerSpec("Line", rect(W, H, INK, 48, 0, 52, 40))])
    assert len(g.regions) == 1

def test_a_cut_splits_like_a_line():
    g = graph([LayerSpec("Flats", rect(W, H, RED, 0, 0, W, H))], cuts=[[(50, -5), (50, 65)]])
    assert len(g.regions) == 2 and g.region_at(10, 10).id != g.region_at(90, 10).id

def test_regions_have_head_unit_features():
    g = graph([LayerSpec("Flats", rect(W, H, RED, 0, 0, 50, 60))], alignment=Alignment(10, (50, 30)))
    (r,) = g.regions
    assert abs(r.center.x + 2.5) < 0.05 and abs(r.center.y) < 0.05 and r.box == (0, 0, 50, 60)
    assert r.flat == RED and r.pixels == 3000

def test_tiny_enclosed_slivers_join_a_neighbor():
    ring = rect(W, H, INK, 20, 20, 27, 27); ring[22:25, 22:25] = 0
    g = graph([LayerSpec("Flats", rect(W, H, RED, 0, 0, W, H)), LayerSpec("Line", ring)])
    assert min(r.pixels for r in g.regions) >= 12

def test_part_folders_are_separate_groups_and_the_top_one_wins():
    specs = [LayerSpec("Rosto", children=[LayerSpec("Flats", rect(W, H, SKIN, 0, 0, 60, H))]),
             LayerSpec("Cabelo", children=[LayerSpec("Flats", rect(W, H, RED, 40, 0, W, 30))])]
    g = graph(specs)
    assert [grp.hint for grp in g.groups] == ["Rosto", "Cabelo"]
    assert g.region_at(50, 10).flat == RED and g.region_at(50, 50).flat == SKIN and g.region_at(5, 5).group == 0
