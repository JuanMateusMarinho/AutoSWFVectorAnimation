# tests/project/test_settings.py
import json

import pytest

from autoswf.anim.settings import AnimationSettings
from autoswf.parts.model import Assign, Corrections
from autoswf.project.settings import Adjust, ExportSettings, HelmSettings, Variant


def sample() -> HelmSettings:
    return HelmSettings(source="C:/art/My Helm.psd", roles={"Layer 1": "line"}, align="10,1110,1115,0", detail=60,
                        gradient=["Light"], corrections=Corrections([Assign((5.0, 6.0), "Lock 2")], [], {"Helm": "Base"}),
                        animation=AnimationSettings.from_dict({"parts": {"Ear L": "Twitch"},
                                                               "keys": [{"part": "Eye L", "frame": 12, "y": 3}]}),
                        pivots={"Lock 1": (3.5, -20.0)},
                        export=ExportSettings(link="MyHelm", morph=True, variants=True,
                                              genders={"M": Variant("a.swf", "MyHelmM", Adjust(1, 2, 1.1),
                                                                    {"Lock 1": Adjust(0, 1)}),
                                                       "F": Variant("b.swf", "MyHelmF")}),
                        colors={"Hair": 0xC02030}, dismissed=["no-skin"])


def test_settings_round_trip_through_json():
    s = sample()
    assert HelmSettings.from_dict(json.loads(json.dumps(s.to_dict()))).to_dict() == s.to_dict()


def test_copy_is_independent():
    s = sample()
    c = s.copy()
    c.corrections.colors["Helm"] = "Trim"
    c.export.genders["M"].helm.x = 9
    assert s.corrections.colors["Helm"] == "Base" and s.export.genders["M"].helm.x == 1


def test_default_export_names_come_from_the_drawing():
    s = HelmSettings(source="C:/art/My Helm.psd")
    assert s.export_file().name == "My Helm.swf" and s.export_link() == "MyHelm"


@pytest.mark.parametrize("patch, message", [
    ({"detail": 101}, "detail must be a whole number from 0 to 100"),
    ({"roles": {"L": "lines"}}, "Unknown role 'lines'"),
    ({"pivots": {"Lock 1": [1]}}, 'pivot of "Lock 1"'),
    ({"colors": {"Hiar": "FF0000"}}, "Unknown color location 'Hiar'"),
    ({"align": "1,2"}, "Alignment must look like"),
    ({"export": {"genders": {"X": {"file": "a.swf", "link": "A"}}}}, "Unknown gender 'X'"),
])
def test_bad_settings_name_the_field(patch, message):
    with pytest.raises(ValueError, match="project: .*" + message.replace("(", r"\(").replace(")", r"\)")):
        HelmSettings.from_dict({**sample().to_dict(), **patch})
