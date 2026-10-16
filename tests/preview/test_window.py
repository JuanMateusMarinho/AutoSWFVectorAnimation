# tests/preview/test_window.py
from aqw_fakes import helm, mini_armor, mini_client
from autoswf.aqw.assets import AqwCache
from autoswf.preview.scene import PreviewScene
from autoswf.preview.window import LOCATION_ORDER, PreviewWindow, download_question
from autoswf.swf.decode import MovieData

def test_window_controls_drive_the_scene(qapp, tmp_path):
    sc = PreviewScene(MovieData(mini_client()), {g: MovieData(mini_armor(g)) for g in "MF"}, "TestArmor", helm=MovieData(helm("Kit")), helm_link="Kit")
    w = PreviewWindow(sc, cache=AqwCache(tmp_path))
    assert [w.label_box.itemText(i) for i in range(w.label_box.count())] == ["Ready", "Idle", "Walk"]
    assert w.label_box.currentText() == "Idle" and tuple(w.color_buttons) == LOCATION_ORDER
    w.set_player_color("Hair", 0x00FF00)
    assert w.scene.colors.hair == 0x00FF00
    w.label_box.setCurrentText("Walk")
    assert w.scene.label == "Walk" and w.download_button.isHidden()
    w.close()

def test_window_without_reference_files_offers_the_download(qapp, tmp_path):
    w = PreviewWindow(None, cache=AqwCache(tmp_path))
    assert not w.download_button.isHidden()
    assert str(tmp_path) in download_question(AqwCache(tmp_path)) and "never shared" in download_question(AqwCache(tmp_path))
    w.close()
