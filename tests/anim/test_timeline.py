import pytest
from autoswf.anim.timeline import (REST, Clip, Key, ManualEditsError, Pose, Timeline, Track, pose_color,
                                   pose_matrix)
from autoswf.model.geometry import ColorTransform, Matrix, Point


def lock_clip():
    return Clip("Lock 3", None, 48, {"Lock 3": Track("Lock 3", {})})


def test_keys_hold_or_tween():
    track = Track("Lock 3", {4: Key(Pose(rotation=10, bend=0.2), tween=True), 8: Key(Pose(rotation=-10, bend=0.6))})
    assert track.keys[0] == Key(REST)
    assert [track.pose(f).rotation for f in (0, 3, 4, 6, 8, 11)] == [0, 0, 10, 0, -10, -10]
    assert track.pose(6).bend == pytest.approx(0.4) and track.pose(2).bend is None


def test_pose_matrix_and_color():
    m = pose_matrix(Matrix.translate(2, 3), Pose(x=1, y=-1, rotation=90, scale_x=2, scale_y=0.5))
    assert (m.a, m.b, m.c, m.d) == pytest.approx((0, 2, -0.5, 0), abs=1e-9) and (m.tx, m.ty) == pytest.approx((3, 2))
    root = pose_matrix(Matrix(), Pose(rotation=90), origin=Point(0, -10)).apply(Point(0, -10))   # turning about it
    assert abs(root.x) < 1e-9 and abs(root.y + 10) < 1e-9
    assert pose_color(REST) is None
    assert pose_color(Pose(alpha=0)) == ColorTransform((1, 1, 1, 0), (0, 0, 0, 0))
    assert pose_color(Pose(brightness=0.5)) == ColorTransform((0.5, 0.5, 0.5, 1), (128, 128, 128, 0))
    assert pose_color(Pose(brightness=-0.25)) == ColorTransform((0.75, 0.75, 0.75, 1), (0, 0, 0, 0))


def test_hand_edits_are_kept_apart_and_protected():
    clip, timeline = lock_clip(), Timeline()
    timeline.put(clip)
    clip.set_key("Lock 3", 12, Pose(rotation=6))
    assert clip.manual_keys() == [("Lock 3", 12)] and clip.pose("Lock 3", 20).rotation == 6
    assert len(clip.poses("Lock 3")) == 48
    with pytest.raises(ManualEditsError, match="'Lock 3' has 1 keyframe edited by hand; running the preset again "
                                               "replaces it"):
        timeline.put(lock_clip())
    fresh = lock_clip()
    timeline.put(fresh, replace_edits=True)
    assert timeline.clips["Lock 3"] is fresh


def test_keys_must_fit_the_clip():
    clip = lock_clip()
    with pytest.raises(ValueError, match="frame 49 is past the end of the 48-frame loop"):
        clip.set_key("Lock 3", 48, REST)
    with pytest.raises(ValueError, match="'Eye L ball' is not animated by 'Lock 3'"):
        clip.set_key("Eye L ball", 3, REST)
