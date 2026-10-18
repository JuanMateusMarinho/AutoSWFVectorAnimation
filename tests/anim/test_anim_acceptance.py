import pytest
from autoswf.anim.bake import bake
from autoswf.anim.rig import rig_parts
from autoswf.anim.settings import AnimationSettings, build_timeline
from autoswf.aqw.helm import export_helm
from autoswf.aqw.validate import validate_helm_swf
from autoswf.drawing.passes import extract_passes
from autoswf.drawing.readers import read_drawing
from autoswf.drawing.roles import assign_roles
from autoswf.drawing.writers import write_psd
from autoswf.parts.assemble import assemble_helm
from autoswf.parts.detect import detect_parts
from autoswf.parts.hidden import layered_passes, split_passes
from autoswf.swf.decode import MovieData, SpriteDef
from autoswf.vectorize.art import vectorize


def animate(path, alignment, link="Accept"):
    d = read_drawing(path)
    passes = extract_passes(d, assign_roles(d))
    pm = detect_parts(passes, alignment)
    layers = split_passes(passes, pm)
    helm = assemble_helm(vectorize(layered_passes(passes, layers), alignment), layers, link)
    rigs = rig_parts(pm, helm, layers)
    timeline, notes = build_timeline(rigs, AnimationSettings())
    swf = export_helm(bake(helm, timeline, rigs).item)
    assert validate_helm_swf(swf, link) == []
    return pm, timeline, swf


def eye_clips(swf):
    movie = MovieData(swf)
    return movie, [c for c in movie.character_ids() if isinstance(movie.character(c), SpriteDef)
                   and movie.character(c).frame_count == 87]


@pytest.mark.aqw
def test_blink_matches_the_default_heads_eye_clip(aqw_cache, converted_parts_helm, part_rigs):
    """Our ball moves on exactly the official frames with the official alpha and scale values."""
    from autoswf.anim.presets import BlinkParams, blink_clip
    from autoswf.anim.timeline import Timeline
    client = MovieData(aqw_cache.client_path())
    head = client.character(client.classes["mcHeadM"])
    official = next(s for s in (client.character(c.char_id) for cmds in head.frames for c in cmds if c.char_id)
                    if isinstance(s, SpriteDef) and s.frame_count == 87)          # mcHeadM's eye clip
    timeline = Timeline()
    timeline.put(blink_clip(part_rigs["Eye L"], BlinkParams()))
    movie, (eye,) = eye_clips(export_helm(bake(converted_parts_helm.helm, timeline, part_rigs).item))
    ours = movie.character(eye)
    ball_moves = lambda sprite, depth: [(f, c.matrix and (round(c.matrix.a, 4), round(c.matrix.d, 4)),
                                         c.color and c.color.mult[3])
                                        for f, cmds in enumerate(sprite.frames) for c in cmds
                                        if c.depth == depth and c.move]
    assert ball_moves(ours, 1) == ball_moves(official, 1)
    assert [f for f, cmds in enumerate(ours.frames) if cmds] == [0, 10, 11, 12, 13, 14, 15]


def test_synthetic_helm_animates_small_and_valid(tmp_path, qapp):
    from drawings import synthetic_parts_helm
    t = synthetic_parts_helm()
    write_psd(tmp_path / "h.psd", t.width, t.height, t.layers)
    pm, timeline, swf = animate(tmp_path / "h.psd", t.alignment)
    assert sorted(timeline.clips) == sorted(["Eye L", "Eye R"] + ["Lock %d" % k for k in range(1, 7)])
    assert len(swf) < 30_000 and len(eye_clips(swf)[1]) == 2


@pytest.mark.aqw
@pytest.mark.parametrize("rel, class_name", [("items/helms/ArtixHead.swf", "ArtixHead"),
                                              ("items/helms/GoldLeppy2018HatM.swf", "GoldLeppy2018HatM"),
                                              (None, "mcHeadM"), ("morph", "CrystallisOnsenMMorph4")])
def test_official_derived_helms_animate(tmp_path, qapp, aqw_cache, request, rel, class_name):
    from official_drawings import official_drawing
    path = request.getfixturevalue("reference_morph") if rel == "morph" else (
        aqw_cache.file_path(rel) if rel else aqw_cache.client_path())
    t = official_drawing(MovieData(path), class_name)
    write_psd(tmp_path / "o.psd", t.width, t.height, t.layers)
    pm, timeline, swf = animate(tmp_path / "o.psd", t.alignment)
    eyes = [n for n in pm.parts if n.startswith("Eye")]
    locks = [n for n in pm.parts if n.startswith("Lock")]
    assert set(eyes + locks) == set(timeline.clips) and len(swf) < 60_000
    if class_name == "CrystallisOnsenMMorph4":
        assert len(locks) >= 6 and {"Eye L", "Eye R"} <= set(timeline.clips)


def test_preview_plays_the_helms_own_loops(tmp_path, qapp, converted_parts_helm, part_rigs):
    from aqw_fakes import write_mini_cache
    from autoswf.aqw.assets import AqwCache
    from autoswf.preview.scene import PreviewScene
    from autoswf.render.effects import qimage_to_array
    write_mini_cache(tmp_path / "cache")
    timeline, _ = build_timeline(part_rigs, AnimationSettings())
    (tmp_path / "a.swf").write_bytes(export_helm(bake(converted_parts_helm.helm, timeline, part_rigs).item))
    scene = PreviewScene.from_cache(AqwCache(tmp_path / "cache"), tmp_path / "a.swf", armor="TestArmor")
    for _ in range(10):
        scene.tick()
        assert qimage_to_array(scene.snapshot(400, 300))[..., 3].max() > 0      # morphs and motion clips paint
    for rig in scene.rigs.values():                                             # both bodies play the helm's loops
        helm = rig.head().child_by_name("helm").children[0]
        assert {c.frame for c in helm.children if c.sprite.frame_count in (87, 48)} == {10}
