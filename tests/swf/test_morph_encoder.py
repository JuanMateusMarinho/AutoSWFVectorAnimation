import numpy as np
import pytest
from autoswf.aqw.helm import HelmItem, export_helm
from autoswf.aqw.validate import validate_helm_swf
from autoswf.model.document import Frame, Placement, Symbol
from autoswf.model.geometry import Matrix, Point
from autoswf.model.shape import LineTo, MorphShape, QuadTo, Shape, SolidFill, closed_contour
from autoswf.swf.decode import MorphShapeDef, MovieData


def square(size, curved=False):
    first = QuadTo(size / 2, -1, size, 0) if curved else LineTo(size, 0)
    return Shape([SolidFill((200, 30, 30, 255))],
                 [closed_contour(0, Point(0, 0), [first, LineTo(size, size), LineTo(0, size), LineTo(0, 0)])])


def grow_helm(ratios=(0.0, 0.5, 1.0)):
    morph = MorphShape(square(10, True), square(30, True))
    clip = Symbol("Grow", [Frame([Placement(morph, 1, ratio=r)]) for r in ratios])
    return export_helm(HelmItem("G", Symbol("G", [Frame([Placement(clip, 1)])])))


def test_morph_shapes_and_ratios_round_trip():
    data = grow_helm()
    movie = MovieData(data)
    clip = movie.character(movie.character(movie.classes["G"]).frames[0][0].char_id)
    first, *moves = [cmds[0] for cmds in clip.frames]
    morph = movie.character(first.char_id)
    assert isinstance(morph, MorphShapeDef)
    assert morph.start.bounds[1] == pytest.approx(10) and morph.end.bounds[1] == pytest.approx(30)
    assert len(morph.start.edges) == len(morph.end.edges) == 4 and morph.end.edges[0].control is not None
    assert [first.ratio] + [m.ratio for m in moves] == [0, 32768, 65535]
    assert all(m.move and m.char_id is None and m.matrix is None for m in moves)
    assert validate_helm_swf(data, "G") == []


def test_a_morph_renders_between_its_shapes(qapp):
    from autoswf.render.display import ScriptContext, instantiate, run_pending_actions, tick
    from autoswf.render.effects import qimage_to_array
    from autoswf.render.painter import Renderer
    movie = MovieData(grow_helm())
    obj, ctx = instantiate(movie, movie.classes["G"]), ScriptContext()
    run_pending_actions(obj, ctx)
    tick(obj, ctx)                                                       # frame 2: ratio 0.5, a 20 x 20 square
    alpha = qimage_to_array(Renderer(cache_bytes=0).render_image(obj, 40, 40, Matrix(), None))[..., 3]
    ys, xs = np.nonzero(alpha > 0.5)
    assert (xs.min(), xs.max(), ys.max()) == (0, 19, 19)


def test_a_morph_that_replaces_a_clip_keeps_its_ratio():
    morph = MorphShape(square(10, True), square(30, True))
    dot = Symbol("Dot", [Frame([Placement(square(4), 1)])])
    clip = Symbol("Swap", [Frame([Placement(dot, 1)]), Frame([Placement(morph, 1, ratio=0.5)])])
    data = export_helm(HelmItem("S", Symbol("S", [Frame([Placement(clip, 1)])])))
    movie = MovieData(data)
    swap = movie.character(movie.character(movie.classes["S"]).frames[0][0].char_id)
    remove, place = swap.frames[1]
    assert isinstance(movie.character(place.char_id), MorphShapeDef) and place.ratio == 32768
    assert validate_helm_swf(data, "S") == []


def test_mismatched_morphs_and_stray_ratios_are_errors():
    bad = MorphShape(square(10), Shape([SolidFill((0, 0, 0, 255))], []))
    with pytest.raises(ValueError, match="same fills, paths and segment kinds"):
        export_helm(HelmItem("B", Symbol("B", [Frame([Placement(bad, 1)])])))
    with pytest.raises(ValueError, match="Only morph shapes take a ratio"):
        export_helm(HelmItem("B", Symbol("B", [Frame([Placement(square(10), 1, ratio=0.5)])])))
