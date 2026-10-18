import re
import pytest
from autoswf.anim.presets import (BlinkParams, PulseParams, SwayParams, TwitchParams, blink_clip, check_preset,
                                  parse_params, preset_name, pulse_clip, twitch_clip)
from autoswf.anim.rig import EyeRig, PartRig
from autoswf.anim.timeline import REST
from autoswf.model.geometry import Point


def eye(lid=True, drop=7.2):
    return PartRig("Eye L", "eye", ["Eye L"], Point(-22, 14),
                   eye=EyeRig("Eye L ball", "Eye L lid" if lid else None, "Eye L lash", drop))


def test_blink_is_the_official_eye_clip():
    clip = blink_clip(eye(), BlinkParams())
    assert clip.length == 87 and set(clip.tracks) == {"Eye L ball", "Eye L lid", "Eye L lash"}
    ball, lid = clip.poses("Eye L ball"), clip.poses("Eye L lid")
    assert clip.poses("Eye L lash") == ball                   # lower lines hide and squash with the ball, as in AQW
    assert [p.alpha for p in ball[9:17]] == [1, 0, 0, 1, 1, 1, 1, 1]
    assert [(p.scale_x, p.scale_y) for p in ball[12:16]] == [
        (1.236114501953125, 0.6431884765625), (1.10491943359375, 0.841400146484375),
        (1.0261993408203125, 0.9603424072265625), (1, 1)]
    assert [round(p.y, 2) for p in lid[9:17]] == [0, 7.2, 6.65, 6.1, 2.7, 0.7, 0, 0]
    assert [round(p.x, 2) for p in lid[10:15]] == [-0.2, 1.15, 2.45, 1.1, 0.25]
    assert all(p == REST for p in ball[:10] + ball[16:] + lid[:10] + lid[16:])


def test_blink_options():
    half = blink_clip(eye(drop=3.6), BlinkParams()).poses("Eye L lid")
    assert round(half[10].y, 2) == 3.6                                     # the lid closes as far as this eye needs
    slow = blink_clip(eye(), BlinkParams(speed=0.5)).poses("Eye L ball")   # 11 frames instead of 6
    assert [p.alpha for p in slow[9:22]] == [1, 0, 0, 0, 0.5, 1, 1, 1, 1, 1, 1, 1, 1] and slow[20] == REST
    fast = blink_clip(eye(), BlinkParams(speed=2)).poses("Eye L ball")      # 4 frames
    assert fast[10].alpha == 0 and fast[13] == REST
    double = blink_clip(eye(), BlinkParams(double=True)).poses("Eye L ball")
    assert [p.alpha for p in double[16:21]] == [1, 1, 0, 0, 1]             # again 2 frames after the first ends
    assert set(blink_clip(eye(lid=False), BlinkParams()).tracks) == {"Eye L ball", "Eye L lash"}
    with pytest.raises(ValueError, match="Blink needs a loop of at least 24 frames with these settings \\(got 20\\)"):
        blink_clip(eye(), BlinkParams(interval=20, double=True))


def test_twitch_and_pulse():
    ear = PartRig("Ear L", "ear", ["Ear L"], Point(-30, 10))
    turn = [p.rotation for p in twitch_clip(ear, TwitchParams()).poses("Ear L")]
    assert turn[:29] == [0] * 29 and turn[29] == pytest.approx(6) and turn[30] == pytest.approx(10)
    assert max(map(abs, turn)) == pytest.approx(10) and all(r == 0 for r in turn[42:])
    gem = pulse_clip(PartRig("Accessory 1", "accessory", ["Accessory 1"], Point(0, 0)), PulseParams(alpha=0.5))
    poses = gem.poses("Accessory 1")
    assert poses[0] == REST and poses[24].brightness == pytest.approx(0.35) and poses[24].alpha == pytest.approx(0.5)
    assert poses[47].brightness == pytest.approx(poses[1].brightness)
    assert set(pulse_clip(eye(), PulseParams()).tracks) == {"Eye L ball"}


def test_settings_are_parsed_and_checked():
    assert parse_params("Sway", {"amplitude": "20", "length": "72"}) == SwayParams(amplitude=20.0, length=72)
    assert parse_params("Blink", {"double": "on"}).double is True and parse_params("Twitch", {}) == TwitchParams()
    assert preset_name("sway") == "Sway" and preset_name("None") is None
    for args, message in [
            (("Sway", {"amp": "3"}), "Unknown Sway setting 'amp'; Sway settings: stiffness, amplitude, wind, delay, length"),
            (("Sway", {"amplitude": "big"}), "Sway amplitude must be a number from 0 to 45 (got 'big')"),
            (("Sway", {"stiffness": 2}), "Sway stiffness must be a number from 0 to 1 (got '2')"),
            (("Blink", {"interval": "10"}), "Blink interval must be a whole number from 16 to 480 (got '10')"),
            (("Blink", {"double": "maybe"}), "Blink double must be on or off (got 'maybe')")]:
        with pytest.raises(ValueError, match=re.escape(message)):
            parse_params(*args)
    with pytest.raises(ValueError, match=re.escape("Unknown preset 'Wave'; presets are Blink, Sway, Twitch, Pulse or none")):
        preset_name("Wave")
    with pytest.raises(ValueError, match=re.escape("Sway moves the part, and only locks, ears, accessories and back "
                                                   "hair have their hidden areas filled ('Hair' is not one of them)")):
        check_preset("Sway", "Hair", "hair")
    with pytest.raises(ValueError, match=re.escape("Blink works on eyes ('Mouth' is not an eye)")):
        check_preset("Blink", "Mouth", "mouth")
    check_preset("Pulse", "Helm", "shell")


def test_loops_too_short_are_refused_when_read():
    with pytest.raises(ValueError, match=re.escape("Blink needs a loop of at least 24 frames with these settings (got 20)")):
        parse_params("Blink", {"interval": "20", "double": "on"})
    with pytest.raises(ValueError, match=re.escape("Twitch needs a loop of at least 60 frames with these settings (got 24)")):
        parse_params("Twitch", {"every": 24, "settle": 48})


def test_the_far_eye_mirrors_the_lid_drift():
    """The client places the far eye's clip mirrored (x-scale -0.553), so its lid drifts toward the face, not away."""
    far = PartRig("Eye R", "eye", ["Eye R"], Point(4, 14), eye=EyeRig("Eye R ball", "Eye R lid", None, 7.2, far=True))
    lid = blink_clip(far, BlinkParams()).poses("Eye R lid")
    assert [round(p.x, 3) for p in lid[10:15]] == [round(-0.553 * dx, 3) for dx in (-0.2, 1.15, 2.45, 1.1, 0.25)]
    assert [round(p.y, 2) for p in lid[10:15]] == [7.2, 6.65, 6.1, 2.7, 0.7]
