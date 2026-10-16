# tests/preview/test_scene.py
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
