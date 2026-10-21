# tests/items/test_edit.py
import lzma
import struct

import numpy as np
import pytest

from aqw_fakes import mini_armor_with_pieces, root_weapon_swf
from autoswf.aqw.validate import validate_item_swf
from autoswf.items.edit import edit_swf, parse_piece_path
from autoswf.items.structure import PieceRef, read_structure
from autoswf.swf.decode import MovieData
from autoswf.swf.reader import R, decompress, iter_tags

SHAPE_CODES = (2, 22, 32, 83)


def tags(data):
    _, _, _, body = decompress(data)
    r = R(body, 0)
    r.rect()
    r.align()
    return [(code, body[pos:pos + ln]) for code, pos, ln in iter_tags(body, r.p + 4, len(body))]


def char_id(body: bytes) -> int:
    return struct.unpack_from("<H", body, 0)[0]


def walk(st):
    return list(st.walk())


def to_zws(data: bytes) -> bytes:
    """The same SWF, LZMA-compressed (ZWS header: compressed length, then the 5 LZMA property bytes)."""
    _, version, length, body = decompress(data)
    packed = lzma.compress(body, format=lzma.FORMAT_ALONE)
    props, stream = packed[:5], packed[13:]
    return b"ZWS" + bytes([version]) + struct.pack("<I", length) + struct.pack("<I", len(stream)) + props + stream


def render_class(data: bytes, class_name: str, hide_depth: int | None = None) -> np.ndarray:
    from autoswf.model.geometry import Matrix
    from autoswf.render.colors import PlayerColors
    from autoswf.render.display import ScriptContext, instantiate, run_pending_actions
    from autoswf.render.effects import qimage_to_array
    from autoswf.render.painter import Renderer
    movie = MovieData(data)
    obj = instantiate(movie, movie.classes[class_name])
    run_pending_actions(obj, ScriptContext(PlayerColors()))
    if hide_depth is not None:
        obj.child_at_depth(hide_depth).visible = False
    return qimage_to_array(Renderer().render_image(obj, 300, 300, Matrix.translate(150, 150) @ Matrix.scale(2, 2),
                                                   PlayerColors()))


def test_removing_a_piece_changes_only_its_sprite():
    data = mini_armor_with_pieces("M")
    st = read_structure(MovieData(data))
    strap = st.piece("MChest/5").ref
    result = edit_swf(data, [strap], prune=False)
    before, after = tags(data), tags(result.data)
    changed = [i for i, (a, b) in enumerate(zip(before, after)) if a != b]
    assert len(before) == len(after) and len(changed) == 1 and before[changed[0]][0] == 39
    assert result.removed_placements == 1
    st2 = read_structure(MovieData(result.data))
    assert [c.label for c in st2.parts[0].pieces] == ["Skin (None)", "Vest"]


def test_unused_definitions_are_pruned_and_shared_ones_kept():
    data = mini_armor_with_pieces("M")
    st = read_structure(MovieData(data))
    result = edit_swf(data, [st.piece("MChest/5").ref, st.piece("MRobeBack/1").ref])
    gone = {st.piece(p).char_id for p in ("MChest/5", "MRobeBack/1", "MRobeBack/1/1", "MRobeBack/1/2", "MRobeBack/1/2/1")}
    assert set(result.removed_characters) == gone
    movie = MovieData(result.data)
    assert movie.character(st.piece("MChest/3/2").char_id) is not None    # the Stud stays: Vest and Shoulder still use it
    assert validate_item_swf(result.data, st.public_classes(), data).ok


def test_shared_and_multi_frame_pieces_are_removed_cleanly():
    data = mini_armor_with_pieces("M")
    st = read_structure(MovieData(data))
    gem = st.piece("MShoulder/3/1").ref                                      # inside the shared Stud: gone from all 3 places
    blinker_shape = st.piece("MHead/3/2").ref                                # placed, moved and removed over 3 frames
    out = edit_swf(data, [gem, blinker_shape])
    after = read_structure(MovieData(out.data))
    assert all(after.piece(p).children == [] for p in ("MChest/3/2", "MChest/5/1", "MShoulder/3"))
    sprite = MovieData(out.data).character(blinker_shape.sprite)
    assert all(cmd.depth != 2 for frame in sprite.frames for cmd in frame) and sprite.frame_count == 3
    assert [c.ref.depth for c in after.piece("MHead/3").children] == [1]


def test_no_export_has_dangling_references():
    data = mini_armor_with_pieces("M")
    st = read_structure(MovieData(data))
    for piece in walk(st):
        assert validate_item_swf(edit_swf(data, [piece.ref]).data, st.public_classes()).ok, piece.path


def test_rename_changes_class_names_and_their_strings_only():
    data = mini_armor_with_pieces("M")
    out = edit_swf(data, rename="NewArmor")
    movie = MovieData(out.data)
    assert "NewArmorMChest" in movie.classes and "NewArmor_fla.Skin_1" in movie.classes
    assert not any(n.startswith("TestArmor") for n in movie.classes)
    assert validate_item_swf(out.data, ["NewArmorM" + p for p in ("Chest", "Hip")]).ok
    strings = movie.abcs[0].strings
    assert "NewArmor_fla:Skin_1" in strings and "TestArmor_fla" not in strings and "mcSetColor" in strings
    assert out.renamed["TestArmorMChest"] == "NewArmorMChest"
    with pytest.raises(ValueError, match="reserved word"):
        edit_swf(data, rename="class")
    with pytest.raises(ValueError, match="Nothing to change"):
        edit_swf(data)
    with pytest.raises(ValueError, match="is not in the file"):
        edit_swf(data, [PieceRef(999, 1)])


def test_root_timeline_and_compression_variants():
    weapon = root_weapon_swf()                                               # FWS
    st = read_structure(MovieData(weapon))
    out = edit_swf(weapon, [st.parts[0].pieces[0].ref])
    assert out.data[:3] == b"FWS" and len(MovieData(out.data).root.frames[0]) == 1
    zws = to_zws(mini_armor_with_pieces("M"))
    renamed = edit_swf(zws, rename="Z")
    assert renamed.data[:3] == b"CWS" and "ZWS" in renamed.notes[0] and "ZMChest" in MovieData(renamed.data).classes


def test_piece_paths_accept_class_names_and_single_gender_names():
    st = read_structure(MovieData(mini_armor_with_pieces("M")))
    ref = st.piece("MChest/5").ref
    assert parse_piece_path(st, "MChest/5") == ref == parse_piece_path(st, "TestArmorMChest/5") == \
        parse_piece_path(st, "Chest/5")
    with pytest.raises(ValueError, match="No piece"):
        parse_piece_path(st, "Chest/77")


@pytest.mark.real
def test_kind_of_brave_without_the_quiver_and_the_strap(kind_of_brave, qapp):
    data = kind_of_brave.read_bytes()
    out = edit_swf(data, [PieceRef(31, 1), PieceRef(110, 39)])
    assert validate_item_swf(out.data, read_structure(MovieData(data)).public_classes(), data).ok
    assert len(out.data) < len(data) and out.removed_placements == 2
    kept_before = {(c, b) for c, b in tags(data)
                   if c not in (39, 76) and not (c in SHAPE_CODES and char_id(b) in out.removed_characters)}
    assert kept_before <= set(tags(out.data))                                # every other tag byte-identical
    assert np.allclose(render_class(out.data, "KindOfBraveMChest"),
                       render_class(data, "KindOfBraveMChest", hide_depth=39), atol=1 / 255)


def test_replacing_a_shape_changes_only_that_tag():
    from editor_fixtures import changed_tag_indexes, index_of_shape, rect_area, shape_of
    data = mini_armor_with_pieces()
    structure = read_structure(MovieData(data))
    cid = structure.piece("MShoulder/1").char_id
    classes = structure.public_classes()
    new_shape = shape_of({0: rect_area(-5, -5, 5, 5)}, [(1, 2, 3, 255)])
    out = edit_swf(data, replace_shapes={cid: new_shape})
    assert changed_tag_indexes(data, out.data) == [index_of_shape(data, cid)]
    assert validate_item_swf(out.data, classes, original=data).ok and out.replaced_shapes == 1
    assert MovieData(out.data).character(cid).bounds == (-5.0, 5.0, -5.0, 5.0)


def test_replacing_a_shape_that_is_not_in_the_file_is_refused():
    with pytest.raises(ValueError, match="Shape 9999 is not in the file"):
        edit_swf(mini_armor_with_pieces(), replace_shapes={9999: None})
