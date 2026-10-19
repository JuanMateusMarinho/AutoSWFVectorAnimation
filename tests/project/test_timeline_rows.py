# tests/project/test_timeline_rows.py
from autoswf.anim.settings import ManualKey
from autoswf.project.build import HelmBuilder
from autoswf.project.settings import HelmSettings
from autoswf.project.timeline_rows import timeline_rows


def test_rows_show_loops_and_key_kinds(helm_psd):
    s = HelmSettings(source=str(helm_psd.path), align=helm_psd.align)
    s.animation.parts.update({"Eye L": ("Blink", {}), "Lock 1": ("Sway", {"length": 24})})
    s.animation.keys.append(ManualKey("Eye L", "Eye L lid", 12, {"y": 9.0}))
    rows = timeline_rows(HelmBuilder().build(s))
    assert [(r.part, r.target) for r in rows][:2] == [("Eye L", None), ("Eye L", "Eye L ball")]
    lid = next(r for r in rows if r.target == "Eye L lid")
    assert lid.length == 87 and lid.keys[11] == "manual" and lid.keys[10] == "generated"
    lock = next(r for r in rows if r.target == "Lock 1")
    assert lock.length == 24 and len(lock.keys) == 24 and lock.preset == "Sway"
