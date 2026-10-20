# tests/preview/test_window.py
import struct
import threading
import time

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


def test_open_helm_failure_keeps_the_current_helm(qapp, tmp_path):
    sc = PreviewScene(MovieData(mini_client()), {g: MovieData(mini_armor(g)) for g in "MF"}, "TestArmor", helm=MovieData(helm("Kit")), helm_link="Kit")
    w = PreviewWindow(sc, cache=AqwCache(tmp_path))
    title, current = w.windowTitle(), sc.helm
    bad = tmp_path / "bad.swf"
    bad.write_bytes(b"CWS\x0f" + struct.pack("<I", 500) + b"junk")
    assert "not a valid SWF file" in w.open_helm(bad)
    assert w.windowTitle() == title and w.scene.helm is current and w.scene.helm_link == "Kit"
    good = tmp_path / "kit2.swf"
    good.write_bytes(helm("Kit2"))
    assert w.open_helm(good) is None and w.scene.helm_link == "Kit2" and "kit2.swf" in w.windowTitle()
    w.close()


def test_download_worker_always_reports_and_closing_does_not_wait(qapp, tmp_path, monkeypatch):
    from autoswf.preview import window as win
    release, messages = threading.Event(), []

    def slow_download(*args, **kwargs):
        release.wait(10)
        raise RuntimeError("boom")
    monkeypatch.setattr(win, "download_reference_files", slow_download)
    monkeypatch.setattr(win.QMessageBox, "question", lambda *a, **k: win.QMessageBox.StandardButton.Yes)
    monkeypatch.setattr(win.QMessageBox, "warning", lambda *a, **k: messages.append(a[2]))
    w = PreviewWindow(None, cache=AqwCache(tmp_path))
    w._on_download()
    start = time.time()
    w.close()
    elapsed = time.time() - start
    release.set()
    deadline = time.time() + 5
    while not messages and time.time() < deadline:
        qapp.processEvents(); time.sleep(0.01)
    assert elapsed < 1.0 and messages and "boom" in messages[0]


def test_preview_takes_a_helm_from_memory(qapp, tmp_path):
    sc = PreviewScene(MovieData(mini_client()), {g: MovieData(mini_armor(g)) for g in "MF"}, "TestArmor")
    w = PreviewWindow(sc, cache=AqwCache(tmp_path))
    assert w.set_helm_data(helm("Kit3"), "Kit3") is None and w.scene.helm_link == "Kit3"
    assert "not a valid SWF file" in w.set_helm_data(b"junk", "X") and w.scene.helm_link == "Kit3"
    w.close()


def test_the_label_box_offers_an_animated_armors_motions(qapp, tmp_path):
    from aqw_fakes import listener_armor_swf
    sc = PreviewScene(MovieData(mini_client()), {"M": MovieData(listener_armor_swf())}, "TestBind", genders=("M",))
    w = PreviewWindow(sc, cache=AqwCache(tmp_path))
    items = [w.label_box.itemText(i) for i in range(w.label_box.count())]
    assert "Armor: Slash" in items and "Idle" in items
    w.label_box.setCurrentText("Armor: Slash")
    assert sc.rigs["M"].head().child_by_name("face").frame == 3
    w.close()
