# tests/items/test_thumbs.py
from aqw_fakes import mini_armor_with_pieces
from autoswf.items.structure import read_structure
from autoswf.items.thumbs import piece_image
from autoswf.render.colors import PlayerColors
from autoswf.swf.decode import MovieData


def test_piece_images_are_fitted_and_colored(qapp):
    movie = MovieData(mini_armor_with_pieces("M"))
    st = read_structure(movie)
    img = piece_image(movie, st.piece("MChest/1").char_id, 48, PlayerColors(skin=0x00FF00))
    assert (img.width(), img.height()) == (48, 48)
    colors = {img.pixelColor(x, y).rgb() & 0xFFFFFF for x in range(48) for y in range(48)
              if img.pixelColor(x, y).alpha() == 255}
    assert 0x00FF00 in colors
