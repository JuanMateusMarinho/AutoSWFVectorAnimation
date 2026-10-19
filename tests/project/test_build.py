# tests/project/test_build.py
import pytest
from PySide6.QtGui import QImage

from autoswf.cli import main
from autoswf.parts.model import Assign
from autoswf.project import build as build_module
from autoswf.project.build import BuildCancelled, HelmBuilder
from autoswf.project.settings import HelmSettings


def settings_for(psd, **kw) -> HelmSettings:
    return HelmSettings(source=str(psd.path), align=psd.align, **kw)


def test_builder_writes_what_convert_writes(helm_psd, tmp_path):
    out = tmp_path / "SyntheticHelm.swf"
    assert main(["convert", str(helm_psd.path), "-o", str(out), "--align", helm_psd.align]) == 0
    s = settings_for(helm_psd)
    s.export.link = "SyntheticHelm"
    b = HelmBuilder(suggest=True).build(s)
    assert b.error is None and b.swf == out.read_bytes()


def test_only_the_stages_a_change_needs_run_again(helm_psd, monkeypatch):
    calls = []
    for name in ("detect_parts", "split_passes", "vectorize", "assemble_helm"):
        real = getattr(build_module, name)
        monkeypatch.setattr(build_module, name, lambda *a, _r=real, _n=name, **k: (calls.append(_n), _r(*a, **k))[1])
    builder, s = HelmBuilder(), settings_for(helm_psd)
    builder.build(s)
    calls.clear()
    s.animation.parts["Ear L"] = ("Twitch", {})
    builder.build(s)
    assert calls == []
    s.corrections.colors["Helm"] = "Base"
    b = builder.build(s)
    assert calls == ["assemble_helm"] and any(c[:2] == ("Helm", "Base") for c in b.helm.colorable)
    calls.clear()
    x, y = b.parts.label_point("Lock 2")
    s.corrections.assign.append(Assign((x, y), "Helm"))
    b = builder.build(s)
    assert calls == ["detect_parts", "split_passes", "vectorize", "assemble_helm"]
    assert b.parts.part_of[b.parts.region_at(x, y).id] == "Helm"


def test_errors_stop_the_build_with_the_stage_and_message(qapp, tmp_path):
    b = HelmBuilder().build(HelmSettings(source=str(tmp_path / "missing.psd")))
    assert b.failed_stage == "read" and "missing.psd" in b.error and b.swf is None
    empty = tmp_path / "empty.png"
    image = QImage(8, 8, QImage.Format.Format_ARGB32)
    image.fill(0)
    image.save(str(empty))
    b = HelmBuilder().build(HelmSettings(source=str(empty)))
    assert b.failed_stage == "passes" and "Nothing to vectorize" in b.error


def test_a_build_can_be_cancelled_between_stages(helm_psd):
    seen = []
    with pytest.raises(BuildCancelled):
        HelmBuilder().build(settings_for(helm_psd, detail=41), progress=seen.append, cancelled=lambda: len(seen) >= 2)
    assert seen[:2] == ["Reading the drawing", "Sorting the layers"]


def test_the_app_builder_waits_for_accepted_suggestions(helm_psd):
    s = settings_for(helm_psd)
    assert HelmBuilder().build(s).timeline.clips == {}
    assert set(HelmBuilder(suggest=True).build(s).timeline.clips) >= {"Eye L", "Eye R", "Lock 1"}
    s.animation.parts["Eye L"] = ("Blink", {})
    assert list(HelmBuilder().build(s).timeline.clips) == ["Eye L"]


def test_pivots_move_the_turn_point_without_touching_the_cache(helm_psd):
    builder, s = HelmBuilder(), settings_for(helm_psd)
    s.animation.parts["Lock 1"] = ("Sway", {})
    before = builder.build(s).rigs["Lock 1"].pivot
    s.pivots["Lock 1"] = (before.x + 3, before.y)
    assert builder.build(s).rigs["Lock 1"].pivot.x == pytest.approx(before.x + 3)
    s.pivots.clear()
    assert builder.build(s).rigs["Lock 1"].pivot == before
