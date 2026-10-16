from autoswf.model.document import Frame, Placement, Symbol
from autoswf.model.geometry import Matrix
from autoswf.model.shape import Shape, SolidFill
from autoswf.swf.movie import build_swf
from autoswf.swf.reader import SWF


def test_header_tag_order_and_shared_child():
    eye = Symbol("Eye", [Frame([Placement(Shape([SolidFill((0, 0, 0, 255))], []), 1)])])
    head = Symbol("Head", [Frame([Placement(eye, 1, Matrix.translate(18.1, 26.9)),
                                  Placement(eye, 3, Matrix(-0.28, -0.03, -0.05, 0.48, 34.6, 28.6))])])
    data = build_swf([head], {id(head): "Demo"}, abc=b"")
    assert data[:4] == b"CWS\x0f"
    swf = SWF(data)
    assert (swf.size, swf.fps, swf.frames, swf.attrs) == ((0.0, 550.0, 0.0, 400.0), 24.0, 1, 0x08)
    assert list(swf.symbols.values()) == ["Demo"]
    kinds = [c["kind"] for c in swf.chars.values()]
    assert kinds.count("sprite") == 2 and kinds.count("shape4") == 1      # Eye defined once, placed twice
    assert swf.root["frames"] == [[]]                                      # root timeline places nothing
