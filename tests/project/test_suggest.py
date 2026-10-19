# tests/project/test_suggest.py
from autoswf.drawing.writers import write_psd
from autoswf.project.build import HelmBuilder
from autoswf.project.settings import HelmSettings
from autoswf.project.suggest import suggestions


def test_suggestions_for_the_synthetic_helm(helm_psd):
    s = HelmSettings(source=str(helm_psd.path), align=helm_psd.align)
    b = HelmBuilder().build(s)
    got = suggestions(b, s)
    assert [x.key for x in got] == ["blink", "sway-locks", "twitch-ears"]
    assert got[0].text == "Eyes found (Eye L, Eye R). Make them blink?" and got[0].parts == ("Eye L", "Eye R")
    assert got[1].text == "6 hair locks found (Lock 1 to Lock 6). Make them sway?" and got[1].preset == "Sway"
    s.animation.parts.update({"Eye L": ("Blink", {}), "Eye R": (None, {})})
    assert [x.key for x in suggestions(b, s)] == ["sway-locks", "twitch-ears"]


def test_notes_become_fix_suggestions(qapp, tmp_path):
    from drawings import hat_over_hair
    t = hat_over_hair()
    path = tmp_path / "hat.psd"
    write_psd(path, t.width, t.height, t.layers)
    s = HelmSettings(source=str(path), align=str(t.alignment))
    b = HelmBuilder().build(s)
    [no_skin] = [x for x in suggestions(b, s) if x.key == "no-skin"]
    assert no_skin.preset is None and no_skin.stage == "Parts" and "Click the face" in no_skin.text
    s.dismissed.append("no-skin")
    assert "no-skin" not in [x.key for x in suggestions(b, s)]
