# tests/app/test_swf_editor.py
from PySide6.QtCore import Qt

from app_helpers import window
from aqw_fakes import mini_armor_with_pieces, write_mini_cache
from autoswf.app.swf_editor import SwfEditor
from autoswf.aqw.assets import AqwCache
from autoswf.items.structure import read_structure
from autoswf.swf.decode import MovieData


def editor(tmp_path, data=None, cache=None):
    tmp_path.mkdir(parents=True, exist_ok=True)
    path = tmp_path / "Armor.swf"
    path.write_bytes(data or mini_armor_with_pieces("M"))
    e = SwfEditor(cache or AqwCache(tmp_path / "none"))
    assert e.open(path) is None
    return e


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
