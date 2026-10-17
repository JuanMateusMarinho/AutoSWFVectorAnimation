# tests/drawing/test_roles.py
import pytest
from autoswf.drawing.layers import Drawing, LayerNode
from autoswf.drawing.roles import LayerRole, assign_roles, detect_role

@pytest.mark.parametrize("name, role", [
    ("Line", "line"), ("Lineart 2", "line"), ("Linha", "line"), ("Line color", "line"), ("線画", "line"),
    ("Flats", "flat"), ("Cores chapadas", "flat"), ("Base", "flat"), ("Shadow", "shadow"), ("Sombra", "shadow"),
    ("Occlusion", "occlusion"), ("Oclusão", "occlusion"), ("AO", "occlusion"), ("Sombra 2", "occlusion"),
    ("Details", "details"), ("Detalhes", "details"), ("Light", "light"), ("Luz", "light"), ("Highlight", "light"),
    ("Paper", "ignore"), ("用紙", "ignore"), ("Background", "ignore"), ("Rascunho", "ignore"), ("AQW Guide Head M", "ignore"),
    ("Layer 1", None), ("Camada 3", None), ("Hair", None)])
def test_detect_role(name, role):
    assert detect_role(name) == role

def px(name, **kw):
    return LayerNode(name, "pixel", **kw)

def group(name, children, **kw):
    return LayerNode(name, "group", children=children, **kw)

def test_folders_parts_clipping_overrides_and_hidden_layers():
    layers = [px("Paper"), group("Hair", [px("Flats"), px("Sombra", clipping=True), px("Layer 5", clipping=True)]),
              group("Shadows", [px("Layer 2")]), px("Sketch", visible=False), group("Old", [px("Line")], visible=False),
              px("Layer 9"), px("Line"), px("AQW Guide Head M")]
    d = Drawing(None, 10, 10, layers)
    roles = assign_roles(d, {"Layer 9": "details"})
    r = {tuple(a.name for a in anc) + (n.name,): roles[n] for n, anc in d.walk() if n in roles}
    assert r[("Paper",)] == LayerRole("ignore", None, "name")
    assert r[("Hair", "Flats")] == LayerRole("flat", "Hair", "name")
    assert r[("Hair", "Sombra")] == LayerRole("shadow", "Hair", "name")
    assert r[("Hair", "Layer 5")] == LayerRole("flat", "Hair", "clipped")
    assert r[("Shadows", "Layer 2")] == LayerRole("shadow", None, "folder")
    assert r[("Sketch",)].source == "hidden" and r[("Old", "Line")].source == "hidden"
    assert r[("Layer 9",)] == LayerRole("details", None, "override")
    assert r[("Line",)] == LayerRole("line", None, "name")
    assert r[("AQW Guide Head M",)] == LayerRole("ignore", None, "guide")

def test_override_errors_name_the_choices():
    d = Drawing(None, 10, 10, [px("Layer 1")])
    with pytest.raises(ValueError, match="No layer named 'Nope'. Layers: Layer 1"):
        assign_roles(d, {"Nope": "line"})
    with pytest.raises(ValueError, match="Unknown role 'shiny'; use one of: line, flat, shadow, occlusion, light, details, ignore"):
        assign_roles(d, {"Layer 1": "shiny"})
