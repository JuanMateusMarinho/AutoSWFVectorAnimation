# tests/app/test_swf_editor.py
from pathlib import Path

from PySide6.QtCore import Qt

from app_helpers import window
from aqw_fakes import mini_armor_with_pieces, write_mini_cache
from autoswf.app.swf_editor import SwfEditor
from autoswf.aqw.assets import AqwCache
from autoswf.items.structure import read_structure
from autoswf.swf.decode import MovieData


def editor(tmp_path, data=None, cache=None, settings_store=None):
    tmp_path.mkdir(parents=True, exist_ok=True)
    path = tmp_path / "Armor.swf"
    path.write_bytes(data or mini_armor_with_pieces("M"))
    e = SwfEditor(cache or AqwCache(tmp_path / "none"), settings_store=settings_store)
    assert e.open(path) is None
    return e


class FakeRuffle:
    """What launch_ruffle returns: a process whose log the editor reads."""
    def __init__(self, lines=()):
        self.stdout = iter(lines)


def ruffle_editor(tmp_path, monkeypatch, cache, data=None, found=True, log=()):
    """An editor on release_armor_swf with Ruffle faked: `launched` lists the test SWFs it was started on."""
    from PySide6.QtCore import QSettings
    from aqw_fakes import release_armor_swf
    from autoswf.ruffle import launch
    tmp_path.mkdir(parents=True, exist_ok=True)
    store = QSettings(str(tmp_path / "ui.ini"), QSettings.Format.IniFormat)
    exe = tmp_path / "ruffle.exe"
    exe.write_bytes(b"")
    from PySide6.QtWidgets import QMessageBox
    launched = []
    monkeypatch.setattr(launch, "find_ruffle", lambda saved, dirs=None: Path(saved) if saved else (exe if found else None))
    monkeypatch.setattr(launch, "launch_ruffle",
                        lambda ruffle, swf, **kw: launched.append(swf) or FakeRuffle(log))
    # the mini cache has no Training Dummy: the offer to download it is declined unless a test says otherwise
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.No)
    return editor(tmp_path / "e", data or release_armor_swf(), cache, store), launched, exe


def test_open_in_ruffle_uses_the_edited_armor(qapp, tmp_path, app_cache, monkeypatch):
    from autoswf.ruffle.testswf import read_test_swf
    e, launched, _ = ruffle_editor(tmp_path, monkeypatch, app_cache)
    e.set_removed(e.structure.piece("MHead/1").ref, True)               # an edit not exported
    swf = e.open_in_ruffle()
    settings, armor = read_test_swf(swf.read_bytes())
    assert armor == e.current_data() and armor != e.original and launched == [swf]
    assert settings["link"] == "TestRelease" and settings["genders"] == ["M"]


def test_the_ruffle_button_shows_only_for_animated_armors(qapp, tmp_path, app_cache):
    from aqw_fakes import animated_armor_swf, release_armor_swf
    assert not editor(tmp_path / "a", release_armor_swf(), app_cache).ruffle_button.isHidden()
    assert not editor(tmp_path / "b", animated_armor_swf(), app_cache).ruffle_button.isHidden()
    assert editor(tmp_path / "c", mini_armor_with_pieces("M"), app_cache).ruffle_button.isHidden()


def test_without_ruffle_it_asks_once_and_remembers(qapp, tmp_path, app_cache, monkeypatch):
    from PySide6.QtWidgets import QFileDialog, QMessageBox
    e, launched, exe = ruffle_editor(tmp_path, monkeypatch, app_cache, found=False)
    asked = []
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *a, **k: asked.append(1) or (str(exe), ""))
    e.open_in_ruffle()
    e.open_in_ruffle()
    assert asked == [1] and len(launched) == 2 and e.settings_store.value("ruffle/path") == str(exe)


def test_a_missing_training_dummy_is_downloaded_when_the_user_agrees(qapp, tmp_path, app_cache, monkeypatch):
    # caches downloaded before Plan 8 have no Training Dummy: Open in Ruffle offers it (5 KB from game.aq.com)
    from PySide6.QtWidgets import QMessageBox
    from autoswf.app import swf_editor
    from autoswf.ruffle.testswf import embedded_dummy
    e, launched, _ = ruffle_editor(tmp_path, monkeypatch, app_cache)
    asked, fetched = [], []

    def download(cache, **kw):
        fetched.append(1)
        cache.dummy_path().parent.mkdir(parents=True, exist_ok=True)
        cache.dummy_path().write_bytes(b"FWS dummy")
    monkeypatch.setattr(swf_editor, "download_dummy", download)
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: asked.append(1) or QMessageBox.StandardButton.No)
    assert embedded_dummy(e.open_in_ruffle().read_bytes()) is None and fetched == []      # declined: drawn dummy
    e.open_in_ruffle()
    assert asked == [1]                                                                     # asked once a session
    e2, _, _ = ruffle_editor(tmp_path / "2", monkeypatch, app_cache)
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes)
    assert embedded_dummy(e2.open_in_ruffle().read_bytes()) == b"FWS dummy" and fetched == [1]


def test_missing_aqw_files_give_a_message(qapp, tmp_path, monkeypatch):
    from autoswf.aqw.assets import AqwCache
    e, launched, _ = ruffle_editor(tmp_path, monkeypatch, AqwCache(tmp_path / "empty"))
    assert e.open_in_ruffle() is None and launched == []
    assert e.message.text().startswith("AQW reference files are missing")


def test_errors_ruffle_logs_for_the_armor_show_in_the_editor(qapp, tmp_path, app_cache, monkeypatch):
    import time
    from PySide6.QtWidgets import QApplication
    line = ('ERROR ruffle_core::avm2::events: Error dispatching event EventObject { type: "addedToStage" } to handler '
            'FunctionObject(FunctionObject { ptr: 0x2, name: "TestReleaseMHead/onAdded()" }) : ArgumentError: Oops\n')
    e, _, _ = ruffle_editor(tmp_path, monkeypatch, app_cache, log=[line])
    e.open_in_ruffle()
    end = time.time() + 5
    while time.time() < end and "Oops" not in e.message.text():
        QApplication.processEvents()
        time.sleep(0.02)
    assert e.message.text() == ("The armor's code stopped in Ruffle: TestReleaseMHead/onAdded(): "
                                "ArgumentError: Oops")


def test_tree_shows_parts_and_pieces_with_thumbnails(qapp, tmp_path):
    e = editor(tmp_path)
    chest = e.tree.topLevelItem(0)
    assert chest.text(0) == "Chest (male)"
    assert [chest.child(i).text(0) for i in range(chest.childCount())] == ["Skin (None)", "Vest", "Strap"]
    e.tree.expandItem(chest)
    assert not chest.child(1).icon(0).isNull()


def test_unchecking_removes_and_undo_restores(qapp, tmp_path):
    e = editor(tmp_path)
    strap = e.structure.piece("MChest/5").ref
    e.tree_item("MChest/5").setCheckState(0, Qt.CheckState.Unchecked)
    assert e.removed == {strap}
    assert [c.label for c in read_structure(MovieData(e.edited)).parts[0].pieces] == ["Skin (None)", "Vest"]
    e.undo_stack.undo()
    assert e.removed == set() and e.tree_item("MChest/5").checkState(0) == Qt.CheckState.Checked


def test_a_shared_piece_goes_everywhere_and_says_so(qapp, tmp_path):
    e = editor(tmp_path)
    e.select("MChest/5/1/1")                                                 # the Gem inside the shared Stud
    assert "Also used in: Chest (male), Shoulder (male)" in e.info.text()
    e.tree_item("MChest/5/1/1").setCheckState(0, Qt.CheckState.Unchecked)
    assert all(e.tree_item(p).checkState(0) == Qt.CheckState.Unchecked for p in ("MChest/3/2/1", "MShoulder/3/1"))
    assert e.undo_stack.count() == 1


def test_named_pieces_warn(qapp, tmp_path):
    e = editor(tmp_path)
    e.select("MHead/1")
    assert "named 'Face'" in e.info.text()


def test_export_writes_a_valid_edited_file(qapp, tmp_path):
    e = editor(tmp_path)
    e.set_removed(e.structure.piece("MRobeBack/1").ref, True)
    d = e.export_dialog()
    d.file_edit.setText(str(tmp_path / "Armor.swf"))
    assert not d.export_button.isEnabled() and "overwrite" in d.file_message.text()
    d.file_edit.setText(str(tmp_path / "Out.swf"))
    d.rename_box.setChecked(True)
    d.link_edit.setText("Fresh")
    assert d.export_button.isEnabled()
    d.export_button.click()
    assert "valid" in d.report.toPlainText() and "FreshMChest" in MovieData(tmp_path / "Out.swf").classes


def test_armor_preview_uses_the_edited_file(qapp, tmp_path):
    e = editor(tmp_path, cache=write_mini_cache(tmp_path / "c"))
    e.set_removed(e.structure.piece("MChest/5").ref, True)
    w = e.preview()
    assert tuple(w.scene.rigs) == ("M",) and w.scene.armor_link == "TestArmor"
    assert [c.label for c in read_structure(w.scene.armors["M"]).parts[0].pieces] == ["Skin (None)", "Vest"]
    w.close()


def test_main_window_opens_a_swf_in_the_editor(qapp, tmp_path, app_cache):
    w = window(app_cache, tmp_path)
    path = tmp_path / "Armor.swf"
    path.write_bytes(mini_armor_with_pieces("M"))
    assert w.open_path(path) is None and w.stack.currentWidget() is w.swf_editor and w.stage_bar.isHidden()
    bad = tmp_path / "bad.swf"
    bad.write_bytes(b"CWS\x0f\x00\x00\x00\x00junk")
    assert "not a valid SWF file" in w.open_path(bad)
    w.close()


def test_animated_armors_show_their_animations(qapp, tmp_path):
    from aqw_fakes import animated_armor_swf
    e = editor(tmp_path, animated_armor_swf())
    rows = e.animation_rows()
    assert ("Walk", "Walking", "yes") in rows and ("Idle", "Idleing", "") in rows
    assert not e.animations_view.isHidden()
    plain = editor(tmp_path / "p", mini_armor_with_pieces("M"))
    assert plain.animations_view.isHidden()


def test_an_armor_that_registers_from_methods_shows_its_motions(qapp, tmp_path):
    from aqw_fakes import listener_armor_swf
    e = editor(tmp_path, listener_armor_swf())
    assert ("Walk", "Walk", "yes") in e.animation_rows() and not e.animations_view.isHidden()
    walk = e.structure.parts[-1].pieces[2]
    e.select(walk.path)
    assert e.frame == 2                                                     # the canvas shows the head on its Walk frame
    e.select("MChest")
    assert "draws its whole character in its Head" in e.canvas_message()


def test_removals_not_exported_ask_before_they_are_lost(qapp, tmp_path, app_cache):
    w = window(app_cache, tmp_path)
    path = tmp_path / "Armor.swf"
    path.write_bytes(mini_armor_with_pieces("M"))
    assert w.open_path(path) is None and not w.swf_editor.dirty
    w.swf_editor.set_removed(w.swf_editor.structure.piece("MChest/5").ref, True)
    asked = []
    answers = [False, False, True]
    w.ask_discard_edits = lambda: asked.append(1) or answers.pop(0)
    assert w.open_path(path) is None and w.swf_editor.removed           # the user kept the edits
    assert w.close() is False
    d = w.swf_editor.export_dialog()
    d.file_edit.setText(str(tmp_path / "Out.swf"))
    d.export_button.click()
    assert not w.swf_editor.dirty and len(asked) == 2
    assert w.close() is True and len(asked) == 2                         # exported: nothing to lose


def test_save_and_reopen_an_edited_swf(qapp, tmp_path, app_cache):
    from editor_fixtures import rect_area, strip_face_armor
    w = window(app_cache, tmp_path)
    f = tmp_path / "StripHero.swf"
    f.write_bytes(strip_face_armor())
    assert w.open_path(f) is None
    e = w.swf_editor
    e.select("MHead/1")
    layer = e.edit_tools.layer
    e._on_layer_edit(layer.paint(rect_area(100, 100, 120, 120), layer.line_tone), "Brush")
    e.set_removed(e.structure.piece("MHead/2").ref, True)
    edited = e.current_data()
    assert w._save(tmp_path / "work.aswf")
    w2 = window(app_cache, tmp_path / "again")
    assert w2.open_path(tmp_path / "work.aswf") is None and w2.in_swf_editor()
    assert w2.swf_editor.current_data() == edited and w2.swf_editor.undo_stack.count() == 0
