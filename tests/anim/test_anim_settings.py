import json
import re
import pytest
from autoswf.anim.presets import BlinkParams, SwayParams, TwitchParams
from autoswf.anim.settings import AnimationSettings, ManualKey, build_timeline, clip_summary, suggest_presets


def test_eyes_blink_and_locks_sway_by_default(part_rigs):
    s = suggest_presets(part_rigs)
    assert s == {"Eye L": BlinkParams(), "Eye R": BlinkParams(), **{"Lock %d" % k: SwayParams() for k in range(1, 7)}}
    timeline, notes = build_timeline(part_rigs, AnimationSettings())
    assert notes == [] and clip_summary(timeline.clips["Eye L"]) == "%-12s  %-6s  %s" % ("Eye L", "Blink",
                                                                                      "87 frames, blinks at frame 11")
    assert clip_summary(timeline.clips["Lock 6"]) == "%-12s  %-6s  %s" % ("Lock 6", "Sway", "48 frames, 6 links")


def test_settings_override_presets_and_parts(part_rigs):
    s = AnimationSettings(presets={"Sway": {"amplitude": 20}},
                          parts={"Ear L": ("Twitch", {}), "Lock 2": (None, {}), "Lock 3": ("Sway", {"length": 72})})
    timeline, notes = build_timeline(part_rigs, s)
    assert "Lock 2" not in timeline.clips and timeline.clips["Ear L"].preset == TwitchParams()
    assert timeline.clips["Lock 3"].length == 72 and timeline.clips["Lock 1"].preset.amplitude == 20 and notes == []


def test_hand_made_keys_go_on_top_and_stale_ones_are_notes(part_rigs):
    keys = [ManualKey("Lock 3", "Lock 3", 12, {"rotation": 6.0}), ManualKey("Lock 9", "Lock 9", 1, {"alpha": 0.5}),
            ManualKey("Lock 3", "Lock 3", 60, {"rotation": 1.0}), ManualKey("Lock 3", "Eye L ball", 3, {"alpha": 0.0})]
    timeline, notes = build_timeline(part_rigs, AnimationSettings(keys=keys))
    clip = timeline.clips["Lock 3"]
    assert clip.pose("Lock 3", 11).rotation == 6.0 and clip.manual_keys() == [("Lock 3", 11)]
    generated, _ = build_timeline(part_rigs, AnimationSettings())
    assert clip.pose("Lock 3", 11).bend == generated.clips["Lock 3"].pose("Lock 3", 11).bend   # other fields kept
    assert notes == ["Keyframe for 'Lock 9' skipped: it has no animation",
                     "Keyframe at frame 60 of 'Lock 3' skipped: its loop has 48 frames",
                     "Keyframe for 'Eye L ball' in 'Lock 3' skipped: 'Lock 3' does not move it"]


def test_presets_on_the_wrong_part_are_errors_and_unknown_parts_notes(part_rigs):
    with pytest.raises(ValueError, match=re.escape("only locks, ears, accessories and back hair have their hidden "
                                                   "areas filled ('Hair' is not one of them)")):
        build_timeline(part_rigs, AnimationSettings(parts={"Hair": ("Sway", {})}))
    _, notes = build_timeline(part_rigs, AnimationSettings(parts={"Lock 9": ("Sway", {})}))
    assert notes == ["Animation for 'Lock 9' skipped: there is no such part"]


def test_settings_file_round_trip(tmp_path):
    s = AnimationSettings({"Sway": {"amplitude": 20.0}}, {"Ear L": ("Twitch", {}), "Lock 2": (None, {}),
                                                         "Lock 3": ("Sway", {"length": 72})},
                          [ManualKey("Lock 3", "Lock 3", 12, {"rotation": 6.0}, tween=True)])
    s.save(tmp_path / "h.anim.json")
    assert AnimationSettings.load(tmp_path / "h.anim.json") == s
    (tmp_path / "e.anim.json").write_text("{}")
    assert AnimationSettings.load(tmp_path / "e.anim.json") == AnimationSettings()


@pytest.mark.parametrize("data, message", [
    ({"parts": {"Lock 1": "Wave"}}, "Unknown preset 'Wave'"),
    ({"presets": {"Sway": {"amp": 1}}}, "Unknown Sway setting 'amp'"),
    ({"parts": {"Lock 1": {"preset": "Sway", "length": 5}}}, "Sway length must be a whole number from 12 to 240"),
    ({"keys": [{"part": "Lock 1", "frame": 1}, {"part": "Lock 1", "frame": 0}]},
     "entry 2 of \"keys\": frame must be a whole number from 1"),
    ({"keys": [{"part": "Lock 1", "frame": 2, "spin": 3}]},
     "Unknown keyframe field 'spin'; fields are x, y, rotation, scale_x, scale_y, alpha, brightness, bend, tween"),
    ({"moves": []}, "Unknown key 'moves'"),
])
def test_bad_settings_are_clear_errors(tmp_path, data, message):
    (tmp_path / "x.anim.json").write_text(json.dumps(data))
    with pytest.raises(ValueError, match="x.anim.json: .*" + re.escape(message)):
        AnimationSettings.load(tmp_path / "x.anim.json")
    (tmp_path / "y.anim.json").write_text("{nope")
    with pytest.raises(ValueError, match=r"y.anim.json is not valid JSON \(line 1"):
        AnimationSettings.load(tmp_path / "y.anim.json")
