# tests/preview/test_scene.py
import struct

import pytest
from aqw_fakes import blob_helm, helm, mini_armor, mini_client, write_mini_cache
from autoswf.aqw.assets import AqwCache
from autoswf.preview.scene import MissingReferenceFiles, PreviewScene, find_helm_link
from autoswf.render.colors import PlayerColors
from autoswf.swf.decode import MovieData

def scene(helm_bytes=None):
    return PreviewScene(MovieData(mini_client()), {g: MovieData(mini_armor(g)) for g in "MF"}, "TestArmor",
                        helm=MovieData(helm_bytes) if helm_bytes else None, helm_link="Kit" if helm_bytes else None)

def count(img, rgb, x0, x1):
    want, n = ((rgb >> 16) & 255, (rgb >> 8) & 255, rgb & 255), 0
    for y in range(img.height()):
        for x in range(x0, x1):
            c = img.pixelColor(x, y)
            n += (c.red(), c.green(), c.blue()) == want
    return n

def test_both_bodies_render_and_follow_player_colors(qapp):
    sc = scene(helm("Kit"))
    img = sc.snapshot(400, 300)
    hair = PlayerColors().hair
    assert count(img, hair, 0, 200) > 20 and count(img, hair, 200, 400) > 20
    sc.set_color("Hair", 0x00FF00)
    img = sc.snapshot(400, 300)
    assert count(img, 0x00FF00, 0, 400) > 40 and count(img, hair, 0, 400) == 0

def test_labels_and_ticks(qapp):
    sc = scene()
    assert sc.labels == ["Ready", "Idle", "Walk"] and sc.label == "Idle"
    sc.set_label("Walk"); sc.tick()
    assert [r.skel.frame for r in sc.rigs.values()] == [4, 4]

def test_morph_check_counts_uncovered_base_head(qapp):
    assert scene(blob_helm("Kit", 5)).uncovered_head_pixels("M") > 100
    assert scene(blob_helm("Kit", 200)).uncovered_head_pixels("F") == 0

def test_find_helm_link():
    assert find_helm_link(MovieData(helm("Kit"))) == "Kit"
    with pytest.raises(ValueError, match="pass --link NAME"):
        find_helm_link(MovieData(mini_armor("M")), "armor.swf")

def test_from_cache_explains_missing_files(tmp_path):
    with pytest.raises(MissingReferenceFiles, match="download-aqw --armor TestArmor"):
        PreviewScene.from_cache(AqwCache(tmp_path), None, armor="TestArmor")

def test_preview_snapshot_command(tmp_path, qapp, monkeypatch, capsys):
    from PySide6.QtGui import QImage
    from autoswf.cli import main
    kit, out = tmp_path / "kit.swf", tmp_path / "shot.png"
    kit.write_bytes(helm("Kit"))
    monkeypatch.setenv("AUTOSWF_CACHE", str(tmp_path / "empty"))
    assert main(["preview", str(kit), "--armor", "TestArmor", "--snapshot", str(out)]) == 1
    assert "download-aqw" in capsys.readouterr().out
    write_mini_cache(tmp_path / "cache"); monkeypatch.setenv("AUTOSWF_CACHE", str(tmp_path / "cache"))
    assert main(["preview", str(kit), "--armor", "TestArmor", "--snapshot", str(out), "--label", "Walk", "--frames", "2"]) == 0
    assert QImage(str(out)).size().toTuple() == (800, 600)


def root_class_helm() -> bytes:
    """A helm whose class is the main timeline (SymbolClass id 0), plus a class bound to nothing drawable."""
    from swf_builders import place2, shape_tag, swf, symbol_class
    disc = {"fill1": 1, "start": (-20, -20), "edges": [(20, -20), (20, 20), (-20, 20), (-20, -20)]}
    return swf([shape_tag(1, 3, fills=[("solid", (0, 0, 0, 255))], lines=[], paths=[disc]), place2(1, cid=1),
                symbol_class({0: "Kit", 7: "Ghost"})])


def test_root_class_and_corrupt_helms_in_the_cli(tmp_path, qapp, monkeypatch, capsys):
    from autoswf.cli import main
    write_mini_cache(tmp_path / "cache"); monkeypatch.setenv("AUTOSWF_CACHE", str(tmp_path / "cache"))
    root, bad, out = tmp_path / "root.swf", tmp_path / "bad.swf", tmp_path / "shot.png"
    root.write_bytes(root_class_helm())
    bad.write_bytes(b"CWS\x0f" + struct.pack("<I", 500) + b"junk")
    assert main(["preview", str(root), "--armor", "TestArmor", "--snapshot", str(out)]) == 0
    assert main(["render", str(root), "--class", "Kit", "--out", str(out)]) == 0
    capsys.readouterr()
    assert main(["preview", str(bad), "--armor", "TestArmor", "--snapshot", str(out)]) == 1
    assert "bad.swf is not a valid SWF file" in capsys.readouterr().out
    assert main(["render", str(bad), "--class", "Kit", "--out", str(out)]) == 1
    assert main(["render", str(root), "--class", "Ghost", "--out", str(out)]) == 1
    assert "cannot be drawn" in capsys.readouterr().out


def test_morph_check_reports_both_genders(qapp):
    from autoswf.preview.scene import MORPH_TOLERANCE_PX
    small, big = scene(blob_helm("Kit", 5)).morph_check(), scene(blob_helm("Kit", 200)).morph_check()
    assert set(small) == {"M", "F"} and min(small.values()) > MORPH_TOLERANCE_PX and big == {"M": 0, "F": 0}


def test_a_male_only_armor_file_shows_one_body(qapp, tmp_path):
    from aqw_fakes import mini_armor_with_pieces, write_mini_cache
    from autoswf.render.effects import qimage_to_array
    cache = write_mini_cache(tmp_path)
    sc = PreviewScene.from_cache(cache, None, armor_data=mini_armor_with_pieces("M"))
    assert tuple(sc.rigs) == ("M",) and sc.armor_link == "TestArmor"
    body = qimage_to_array(sc.snapshot(400, 300, background=(0, 0, 0, 0)))[..., 3]
    assert body[:, 140:260].max() > 0 and body[:, :60].max() == 0           # one body, in the middle
    assert sc.morph_check().keys() == {"M"}


def test_an_animated_armor_is_framed_wider(qapp, tmp_path):
    from aqw_fakes import animated_armor_swf, mini_armor_with_pieces, write_mini_cache
    cache = write_mini_cache(tmp_path)
    plain = PreviewScene.from_cache(cache, None, armor_data=mini_armor_with_pieces("M"))
    animated = PreviewScene.from_cache(cache, None, armor_data=animated_armor_swf())
    assert animated.animated is not None and animated.default_zoom(600) < plain.default_zoom(600) / 2


def test_scene_plays_an_armors_own_motions():
    from aqw_fakes import listener_armor_swf
    sc = PreviewScene(MovieData(mini_client()), {"M": MovieData(listener_armor_swf())}, "TestBind", genders=("M",))
    assert sc.motions == ["Portrait", "Idle", "Walk", "Slash"]
    sc.play_motion("Walk")
    assert sc.rigs["M"].head().child_by_name("face").frame == 2
