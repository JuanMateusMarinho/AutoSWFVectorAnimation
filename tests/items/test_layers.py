from editor_fixtures import (LINE_RGBA, depth_is_top, part_by_key, rect_area, setcolor_of, shape_of,
                             strip_face_armor, unchanged_tags_identical)
from autoswf.aqw.validate import validate_item_swf
from autoswf.items.edit import edit_swf
from autoswf.items.layers import NewLayer
from autoswf.items.structure import read_structure
from autoswf.swf.decode import MovieData

SCAR = shape_of({0: rect_area(100, 100, 140, 104)}, [(200, 60, 60, 255)])
OUTLINE = shape_of({0: rect_area(98, 98, 142, 99)}, [LINE_RGBA])


def test_a_new_layer_lands_on_top_of_the_part_with_its_color_clips():
    armor = strip_face_armor()
    structure = read_structure(MovieData(armor))
    head = part_by_key(structure, "MHead")
    out = edit_swf(armor, add_layers=[NewLayer(head.char_id, "Scar", [(SCAR, ("Skin", "Dark")), (OUTLINE, None)])])
    movie = MovieData(out.data)
    after = read_structure(movie)
    piece = part_by_key(after, "MHead").pieces[-1]
    assert depth_is_top(movie, part_by_key(after, "MHead"), piece)
    assert any(c.color == ("Skin", "Dark") for c in piece.children)
    assert out.added_layers == [(head.char_id, piece.ref.depth)]
    assert validate_item_swf(out.data, structure.public_classes(), original=armor).ok
    assert unchanged_tags_identical(armor, out.data, allowed={"DefineSprite": [head.char_id]})


def test_new_layer_class_names_never_collide():
    armor = strip_face_armor()
    head = part_by_key(read_structure(MovieData(armor)), "MHead")
    once = edit_swf(armor, add_layers=[NewLayer(head.char_id, "Scar", [(SCAR, ("Skin", "Dark"))])]).data
    twice = edit_swf(once, add_layers=[NewLayer(head.char_id, "Scar 2", [(SCAR, ("Skin", "Dark"))])]).data
    names = set(MovieData(twice).classes)
    assert {"StripHero_fla.AutoSWFLayer1_SkinDark", "StripHero_fla.AutoSWFLayer2_SkinDark"} <= names


def test_rebinding_a_color_clip_in_an_opened_swf():
    armor = strip_face_armor()
    out = edit_swf(armor, rebind={"StripHero_fla.Shadow_2": ("Hair", "Dark")})
    movie = MovieData(out.data)
    abc = next(block for block in movie._abc_blocks)
    assert setcolor_of(abc, "StripHero_fla.Shadow_2") == ("Hair", "Dark")
    assert setcolor_of(abc, "StripHero_fla.Skin_1") == ("Skin", "None")
    assert validate_item_swf(out.data, read_structure(MovieData(armor)).public_classes(), original=armor).ok
