import numpy as np
import pytest
from helm_render import at, near, render_helm
from autoswf.anim.bake import bake
from autoswf.anim.presets import (BlinkParams, PulseParams, SwayParams, TwitchParams, blink_clip, pulse_clip,
                                  twitch_clip)
from autoswf.anim.sway import sway_clip
from autoswf.anim.timeline import Timeline
from autoswf.aqw.helm import export_helm
from autoswf.aqw.validate import validate_helm_swf
from autoswf.model.document import Symbol
from autoswf.model.geometry import Matrix, Point
from autoswf.model.shape import MorphShape
from autoswf.render.colors import PlayerColors

MOVING = {"eyeL", "eyeR", "lock1", "lock2", "lock3", "lock4", "lock5", "lock6", "earL", "accessory1"}
rgb = lambda v: ((v >> 16) & 255, (v >> 8) & 255, v & 255)


def animated(c, rigs, which=("blink", "sway", "twitch", "pulse")):
    timeline = Timeline()
    if "blink" in which:
        for eye in ("Eye L", "Eye R"):
            timeline.put(blink_clip(rigs[eye], BlinkParams()))
    if "sway" in which:
        for k in range(1, 7):
            timeline.put(sway_clip(rigs["Lock %d" % k], SwayParams(), rank=k - 1))
    if "twitch" in which:
        timeline.put(twitch_clip(rigs["Ear L"], TwitchParams()))
    if "pulse" in which:
        timeline.put(pulse_clip(rigs["Accessory 1"], PulseParams()))
    return bake(c.helm, timeline, rigs)


def test_baked_structure_moves_wrappers_and_keeps_colorable_clips_still(converted_parts_helm, part_rigs):
    c = converted_parts_helm
    out = animated(c, part_rigs)
    assert validate_helm_swf(export_helm(out.item), "PartsHelm") == []
    top = {p.name: p for p in out.item.root.frames[0].placements}
    assert list(top) == [p.name for p in c.helm.item.root.frames[0].placements]
    assert [len(top[n].item.frames) for n in ("eyeL", "lock3", "earL", "accessory1", "face")] == [87, 48, 72, 48, 1]
    art = top["lock3"].item.frames[0].placements[0].item
    assert art.name == "Lock 3" and len(art.frames) == 48
    assert any(isinstance(p.item, MorphShape) and p.ratio is not None for p in art.frames[5].placements)
    for frame in art.frames:
        for p in frame.placements:
            if isinstance(p.item, Symbol):
                assert p.item.color_custom is not None and p.matrix == Matrix() and p.color is None
                assert len(p.item.frames) == 48 and isinstance(p.item.frames[7].placements[0].item, MorphShape)
    assert len(c.helm.wrappers["Eye L"].frames) == 1 and len(c.helm.wrappers["Lock 3"].frames) == 1   # input untouched


def test_roots_stay_attached(converted_parts_helm, part_rigs):
    c = converted_parts_helm
    out = animated(c, part_rigs, ("sway", "twitch"))
    for layer in ("Lock 1", "Lock 6", "Ear L"):
        rig, motion = part_rigs[layer], out.wrappers[layer + " motion"]
        local = Point(rig.pivot.x - out.placements[layer].matrix.tx, rig.pivot.y - out.placements[layer].matrix.ty)
        for frame in motion.frames:
            p = frame.placements[0].matrix.apply(local)
            assert abs(p.x - local.x) < 1e-6 and abs(p.y - local.y) < 1e-6, layer


def test_closed_eyes_show_skin_and_a_lowered_lid(converted_parts_helm, part_rigs):
    c, t = converted_parts_helm, converted_parts_helm.t
    swf = export_helm(animated(c, part_rigs, ("blink",)).item)
    colors = PlayerColors(skin=0x80C0FF)
    still, closed, after = (render_helm(swf, "PartsHelm", t, colors, f) for f in (0, 10, 16))
    assert near(at(still, t, -26, 14), (255, 255, 255)) and near(at(closed, t, -26, 14), rgb(colors.skin))
    s, (ox, oy) = t.alignment.scale, t.alignment.origin                      # x -25: left of the iris and pupil
    column = lambda img: np.nonzero(img[int(oy + 8 * s):int(oy + 20 * s), int(ox - 25 * s), :3].max(axis=1) < 80)[0]
    assert np.median(column(closed)) >= np.median(column(still)) + 5 * s      # the lid line came down
    static = render_helm(c.swf, "PartsHelm", t, colors)
    assert np.abs(after - static).max() <= 2                                 # back at rest after the blink


def test_bent_locks_keep_player_colors_aligned(converted_parts_helm, part_rigs):
    c, t = converted_parts_helm, converted_parts_helm.t
    swf = export_helm(animated(c, part_rigs, ("sway",)).item)
    colors = PlayerColors(hair=0x20E040)
    drawn = lambda img: (np.abs(img[..., :3] - (120, 70, 40)).max(axis=2) <= 30) & (img[..., 3] > 200)
    rest = drawn(render_helm(c.swf, "PartsHelm", t, colors)).sum()
    moved = []
    for f in (0, 12, 24, 36):
        img = render_helm(swf, "PartsHelm", t, colors, f)
        assert drawn(img).sum() <= 1.5 * rest + 10, f                    # no drawn brown showing through the green
        for k in range(1, 7):
            rx, ry = t.roots["Lock %d" % k]
            assert near(at(img, t, rx, ry + 1.5), rgb(colors.hair), 6), (f, k)
        moved.append(img)
    assert (np.abs(moved[0] - moved[2]).max(axis=2) > 60).sum() >= 200    # the locks really move


def test_no_holes_open_while_parts_move(converted_parts_helm, part_rigs):
    c, t = converted_parts_helm, converted_parts_helm.t
    swf = export_helm(animated(c, part_rigs).item)
    under = render_helm(c.swf, "PartsHelm", t, PlayerColors(), 0, hide=MOVING)[..., 3]
    for f in range(0, 96, 4):
        assert (render_helm(swf, "PartsHelm", t, PlayerColors(), f)[..., 3] >= under - 3).all(), f


def test_one_part_in_two_layers_moves_as_one(converted_parts_helm, part_rigs):
    from dataclasses import replace
    c = converted_parts_helm
    rig = replace(part_rigs["Lock 3"], layers=["Lock 3", "Lock 4"])
    timeline = Timeline()
    timeline.put(sway_clip(rig, SwayParams(), rank=0))
    out = bake(c.helm, timeline, {"Lock 3": rig})
    a, b = out.wrappers["Lock 3 motion"], out.wrappers["Lock 4 motion"]
    assert [f.placements[0].matrix.b for f in a.frames] == pytest.approx([f.placements[0].matrix.b for f in b.frames])


def test_back_hair_sways_in_its_own_class(qapp):
    from drawings import disc, drawing_from_specs, rect
    from autoswf.anim.rig import rig_parts
    from autoswf.aqw.template import Alignment
    from autoswf.drawing.passes import extract_passes
    from autoswf.drawing.roles import assign_roles
    from autoswf.drawing.writers import LayerSpec
    from autoswf.parts.assemble import assemble_helm
    from autoswf.parts.detect import detect_parts
    from autoswf.parts.hidden import layered_passes, split_passes
    from autoswf.vectorize.art import vectorize
    W = H = 240
    specs = [LayerSpec("Back hair", children=[LayerSpec("Flats", rect(W, H, (120, 70, 40, 255), 60, 120, 180, 230))]),
             LayerSpec("Flats", disc(W, H, (240, 200, 160, 255), 120, 110, 70))]
    d = drawing_from_specs(W, H, specs)
    passes = extract_passes(d, assign_roles(d))
    alignment = Alignment(2.4, (120, 120))
    pm = detect_parts(passes, alignment)
    layers = split_passes(passes, pm)
    helm = assemble_helm(vectorize(layered_passes(passes, layers), alignment), layers, "BH")
    rigs = rig_parts(pm, helm, layers)
    assert rigs["Back hair"].pivot.y < helm.placements["Back hair"].matrix.ty     # turns about its top, not its middle
    timeline = Timeline()
    timeline.put(sway_clip(rigs["Back hair"], SwayParams(), rank=0))
    out = bake(helm, timeline, rigs)
    inner = out.item.backhair.frames[0].placements[0].item
    assert len(inner.frames[0].placements[0].item.frames) == 48
    assert validate_helm_swf(export_helm(out.item), "BH") == []


def test_the_lash_hides_and_squashes_about_the_ball(qapp):
    """An eye drawn with an outline all round: its lower half (the lash) goes with the ball, squashed about its center."""
    from drawings import disc, drawing_from_specs, ring
    from autoswf.anim.rig import rig_parts
    from autoswf.aqw.template import Alignment
    from autoswf.drawing.passes import extract_passes
    from autoswf.drawing.roles import assign_roles
    from autoswf.drawing.writers import LayerSpec
    from autoswf.parts.assemble import assemble_helm
    from autoswf.parts.detect import detect_parts
    from autoswf.parts.hidden import layered_passes, split_passes
    from autoswf.vectorize.art import vectorize
    W = H = 240
    flats = disc(W, H, (242, 201, 160, 255), 120, 130, 90)
    for layer in (disc(W, H, (10, 10, 10, 255), 100, 140, 28), disc(W, H, (255, 255, 255, 255), 100, 140, 24),
                  disc(W, H, (40, 120, 220, 255), 100, 136, 12)):
        flats = np.where(layer[..., 3:4] > 0, layer, flats)
    d = drawing_from_specs(W, H, [LayerSpec("Flats", flats)])
    passes = extract_passes(d, assign_roles(d))
    alignment = Alignment(4.0, (120, 120))
    pm = detect_parts(passes, alignment)
    layers = split_passes(passes, pm)
    helm = assemble_helm(vectorize(layered_passes(passes, layers), alignment), layers, "E")
    rigs = rig_parts(pm, helm, layers)
    assert rigs["Eye L"].eye.lash == "Eye L lash"
    timeline = Timeline()
    timeline.put(blink_clip(rigs["Eye L"], BlinkParams()))
    eye = bake(helm, timeline, rigs).wrappers["Eye L"]
    lash = lambda f: next(p for p in eye.frames[f].placements if p.name == "eyeLLash")
    assert lash(10).color.mult[3] == 0 and lash(12).color is None
    m = lash(12).matrix                                       # squashed about the ball's center (the clip's origin)
    center = m.apply(Point(-lash(0).matrix.tx, -lash(0).matrix.ty))
    assert abs(center.x) < 1e-6 and abs(center.y) < 1e-6 and m.d == pytest.approx(0.6431884765625)
