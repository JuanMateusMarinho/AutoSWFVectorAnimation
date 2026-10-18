import numpy as np
import pytest
from autoswf.anim.presets import SwayParams
from autoswf.anim.rig import PartRig, RigMask
from autoswf.anim.sway import bend_points, place_chain, solve_chain, sway_clip
from autoswf.model.geometry import Point


def l_lock(scale=4.0):
    """A lock 4 units wide hanging from (0, 0): down to y 24, then right to x 16 along y 20..24 (head units)."""
    px = np.zeros((int(26 * scale), int(20 * scale)), bool)
    px[:int(24 * scale), :int(4 * scale)] = True
    px[int(20 * scale):int(24 * scale), :int(18 * scale)] = True
    return RigMask(px, Point(-2, 0), scale)


def test_the_chain_follows_a_bent_lock():
    m = l_lock()
    chain = place_chain(m, Point(0, 0))
    assert 26 <= chain.length <= 38 and len(chain.nodes) == 7                # 6 links of about 5 units
    assert chain.nodes[-1].x > 12 and 20 <= chain.nodes[-1].y <= 24
    for p in chain.nodes:                                                     # every node lies inside the lock
        i = min(int((p.y - m.origin.y) * m.scale), m.pixels.shape[0] - 1)
        j = min(int((p.x - m.origin.x) * m.scale), m.pixels.shape[1] - 1)
        assert m.pixels[i, j], p
    u = chain.u(np.array([0.0, 0.0, 15.0]), np.array([1.0, 22.0, 22.0]))
    assert u[0] < 0.1 and 0.5 < u[1] < 0.8 and u[2] > 0.9


def test_the_loop_is_seamless_and_the_tip_lags():
    th = solve_chain(links=5, length=48, stiffness=0.2, wind=0.3, phase=0.0)
    assert th.shape == (48, 5)
    steps = np.abs(np.diff(np.vstack([th, th[:1]]), axis=0))
    assert steps[-1].max() <= 1.05 * steps[:-1].max()                         # the wrap is like any other step
    first = lambda a: np.angle(np.fft.rfft(a)[1])
    assert (first(th[:, 0]) - first(th[:, -1])) % (2 * np.pi) > np.radians(30)


def test_bending_keeps_the_root_and_turns_the_tip():
    chain = place_chain(l_lock(), Point(0, 0))
    angles = np.zeros(len(chain.nodes) - 1)
    angles[-1] = np.radians(10)                                               # only the last link turns
    xs, ys = np.array([0.0, chain.nodes[-1].x]), np.array([0.5, chain.nodes[-1].y])
    bx, by = bend_points(chain, angles, xs, ys)
    assert (bx[0], by[0]) == pytest.approx((0.0, 0.5))
    j = chain.nodes[-2]
    r = np.hypot(xs[1] - j.x, ys[1] - j.y)
    assert np.hypot(bx[1] - xs[1], by[1] - ys[1]) == pytest.approx(2 * r * np.sin(np.radians(5)), rel=0.05)


def test_a_long_lock_turns_and_bends_like_the_simulation(part_rigs):
    clip = sway_clip(part_rigs["Lock 6"], SwayParams(), rank=0)
    bend = clip.bends["Lock 6"]
    assert np.degrees(np.abs(bend.angles[:, -1]).max()) == pytest.approx(12.0)
    assert bend.error <= 0.03 * bend.chain.length
    poses = clip.poses("Lock 6")
    assert min(p.bend for p in poses) == pytest.approx(0) and max(p.bend for p in poses) == pytest.approx(1)
    assert [p.rotation for p in poses] == pytest.approx(list(np.degrees(bend.angles[:, 0])))


def test_neighbouring_locks_lag_by_the_delay(part_rigs):
    a = np.array([p.rotation for p in sway_clip(part_rigs["Lock 3"], SwayParams(), 0).poses("Lock 3")])
    b = np.array([p.rotation for p in sway_clip(part_rigs["Lock 4"], SwayParams(), 1).poses("Lock 4")])
    assert max(range(48), key=lambda s: float(np.dot(a, np.roll(b, -s)))) == 4


def test_short_locks_only_turn_and_zero_amplitude_rests(part_rigs):
    short = PartRig("Lock 9", "lock", ["Lock 9"], Point(0, 0), mask=RigMask(np.ones((12, 8), bool), Point(-1, 0), 4.0))
    clip = sway_clip(short, SwayParams(), rank=0)
    assert clip.bends == {} and max(abs(p.rotation) for p in clip.poses("Lock 9")) == pytest.approx(12.0)
    still = sway_clip(part_rigs["Lock 6"], SwayParams(amplitude=0), rank=0)
    assert still.bends == {} and all(p.rotation == 0 for p in still.poses("Lock 6"))
    for stiffness in (0.0, 1.0):                                              # extreme but legal settings
        loop = sway_clip(part_rigs["Lock 6"], SwayParams(stiffness=stiffness, amplitude=45, length=12), rank=3)
        assert loop.length == 12 and np.isfinite([p.rotation for p in loop.poses("Lock 6")]).all()


def test_back_hair_hangs_from_its_top_edge():
    """A wide back-hair mass sways like a curtain: its top edge stays attached and its bottom edge stays level."""
    rig = PartRig("Back hair", "back_hair", ["Back hair"], Point(0, 0),
                  mask=RigMask(np.ones((46 * 4, 50 * 4), bool), Point(-25, 0), 4.0))
    clip = sway_clip(rig, SwayParams(), rank=0)
    assert all(p.rotation == 0 for p in clip.poses("Back hair"))
    xs, ys = np.array([-24.5, 24.5, -24.5, 24.5, 0.0]), np.array([0.2, 0.2, 45.8, 45.8, 45.8])
    for ends in clip.bends["Back hair"].morph_points(xs, ys):
        assert np.abs(ends[:2] - np.stack([xs[:2], ys[:2]], axis=1)).max() < 0.1      # the top edge stays
        assert np.abs(ends[2:, 1] - ys[2:]).max() < 0.1                               # the bottom edge stays level
    start, end = clip.bends["Back hair"].morph_points(xs, ys)
    assert abs(start[4, 0] - end[4, 0]) > 2.0                                        # and it swings


def test_big_parts_bend_from_a_bounded_sample():
    from autoswf.anim.sway import MAX_BEND_SAMPLES
    rig = PartRig("Back hair", "back_hair", ["Back hair"], Point(0, 0),
                  mask=RigMask(np.ones((120 * 4, 60 * 4), bool), Point(-30, 0), 4.0))
    bend = sway_clip(rig, SwayParams(length=240), rank=0).bends["Back hair"]
    assert bend.samples <= MAX_BEND_SAMPLES and len(bend.ratios) == 240
