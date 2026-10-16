"""Command line: `python -m autoswf inspect FILE` and `python -m autoswf demo-helm OUT.swf`."""
import argparse
import sys
from pathlib import Path

from autoswf.aqw.contract import sanitize_link
from autoswf.aqw.helm import HelmItem, export_helm
from autoswf.aqw.validate import validate_helm_swf
from autoswf.model.document import ColorCustom, Frame, Placement, Symbol
from autoswf.model.geometry import Matrix
from autoswf.model.shape import Shape, SolidFill, ellipse
from autoswf.swf.inspect_format import format_report
from autoswf.swf.reader import SWF

SIZE_WARNING_BYTES = 200 * 1024
BLACK, WHITE, SKIN, HAIR, IRIS = (17, 17, 17, 255), (255, 255, 255, 255), (242, 201, 160, 255), (123, 75, 214, 255), (36, 179, 194, 255)


def _blob(color, cx, cy, rx, ry) -> Shape:
    return Shape([SolidFill(color)], [ellipse(0, cx, cy, rx, ry)])


def _colorable(name, location, shade, color, cx, cy, rx, ry) -> Symbol:
    return Symbol(name, [Frame([Placement(_blob(color, cx, cy, rx, ry), 1)])], color_custom=ColorCustom(location, shade))


def demo_helm(link: str) -> HelmItem:
    """A tiny morph helm: face, two blink-ready eyes and hair, all wired to AQW color custom."""
    iris = _colorable("Iris", "Eye", "None", IRIS, 1, 2, 6, 8)
    eye = Symbol("Eye", [Frame([Placement(_blob(BLACK, 0, 0, 11, 13), 1), Placement(_blob(WHITE, 0, 0, 9.5, 11.5), 2),
                                Placement(iris, 3), Placement(_blob(BLACK, 1, 3, 3, 3), 4),
                                Placement(_blob(WHITE, -2, -2, 1.8, 1.8), 5)])])
    root = Symbol("Head", [Frame([
        Placement(_blob(BLACK, 0, 0, 48, 53), 1),
        Placement(_colorable("Face", "Skin", "None", SKIN, 0, 0, 45, 50), 2),
        Placement(_colorable("FaceShade", "Skin", "Dark", SKIN, 8, 20, 30, 22), 3),
        Placement(eye, 4, Matrix.translate(-18, 5)),
        Placement(eye, 5, Matrix(-0.6, 0, 0, 1, 22, 5)),
        Placement(_blob(BLACK, 0, -30, 50, 30), 6),
        Placement(_colorable("Hair", "Hair", "None", HAIR, 0, -30, 47, 27), 7),
        Placement(_colorable("HairShade", "Hair", "Dark", HAIR, 10, -22, 30, 14), 8),
    ])])
    return HelmItem(link, root)


def _cmd_inspect(args) -> int:
    print(format_report(SWF(args.file), tree=args.tree, abc=args.abc, strings=args.strings, shapes=args.shapes,
                        maxdepth=args.maxdepth, title=args.file))
    return 0


def _cmd_demo_helm(args) -> int:
    link = sanitize_link(args.link)
    data = export_helm(demo_helm(link))
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(data)
    problems = validate_helm_swf(data, link)
    if len(data) > SIZE_WARNING_BYTES:
        print("Warning: %s is larger than 200 KB; official helms are usually a few KB." % out)
    if problems:
        for p in problems:
            print("Problem: " + p)
        return 1
    print("Wrote %s (%d bytes, %d classes) — valid" % (out, len(data), len(SWF(data).symbols)))
    return 0


def _qt_app():
    from PySide6.QtGui import QGuiApplication
    return QGuiApplication.instance() or QGuiApplication([])


def _cmd_render(args) -> int:
    from autoswf.render.colors import PlayerColors
    from autoswf.render.display import ScriptContext, instantiate, run_pending_actions, tick
    from autoswf.render.painter import render_fitted
    from autoswf.swf.decode import MovieData
    movie = MovieData(args.file)
    char_id = movie.classes.get(args.class_name)
    if char_id is None:
        print("Class '%s' was not found in %s. Classes: %s" % (args.class_name, args.file, ", ".join(sorted(movie.classes))))
        return 1
    _qt_app()
    colors = None if args.drawn_colors else PlayerColors()
    ctx = ScriptContext(colors)
    obj = instantiate(movie, char_id)
    run_pending_actions(obj, ctx)
    for _ in range(args.frame):
        tick(obj, ctx)
    image = render_fitted(obj, args.scale, colors)
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    image.save(str(args.out))
    print("Wrote %s (%d x %d)" % (args.out, image.width(), image.height()))
    return 0


def main(argv: list[str] | None = None) -> int:
    reconfigure = getattr(sys.stdout, "reconfigure", None)
    if reconfigure:
        reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(prog="autoswf", description="AutoSWF command line tools")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("inspect", help="describe the structure of a SWF file")
    p.add_argument("file")
    p.add_argument("--tree", action="store_true", help="show the display tree of every exported class")
    p.add_argument("--abc", action="store_true", help="list ActionScript classes")
    p.add_argument("--strings", action="store_true", help="list ActionScript strings")
    p.add_argument("--shapes", action="store_true", help="summarize fills and edges")
    p.add_argument("--maxdepth", type=int, default=6)
    p.set_defaults(run=_cmd_inspect)
    p = sub.add_parser("demo-helm", help="write a small demo morph helm with color custom")
    p.add_argument("out")
    p.add_argument("--link", default="AutoSwfDemoMorph", help="class name AQW uses to load the helm")
    p.set_defaults(run=_cmd_demo_helm)
    p = sub.add_parser("render", help="render one class of a SWF to a PNG image")
    p.add_argument("file")
    p.add_argument("--class", dest="class_name", required=True, help="exported class to render")
    p.add_argument("--out", required=True, help="PNG file to write")
    p.add_argument("--scale", type=float, default=4.0)
    p.add_argument("--frame", type=int, default=0, help="frames to play (24 fps) before rendering")
    p.add_argument("--drawn-colors", action="store_true", help="keep the drawn colors instead of player colors")
    p.set_defaults(run=_cmd_render)
    args = parser.parse_args(argv)
    return args.run(args)
