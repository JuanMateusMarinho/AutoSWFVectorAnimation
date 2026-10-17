"""Command line: inspect, demo-helm, render, download-aqw, preview, fidelity, convert and template."""
import argparse
import sys
from pathlib import Path

import numpy as np

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
    try:
        movie = MovieData(args.file)
    except (ValueError, OSError) as e:
        print(e)
        return 1
    char_id = movie.classes.get(args.class_name)
    if char_id is None:
        print("Class '%s' was not found in %s. Classes: %s" % (args.class_name, args.file, ", ".join(sorted(movie.classes))))
        return 1
    obj = instantiate(movie, char_id)
    if obj is None:
        print("Class '%s' in %s cannot be drawn (it is not a MovieClip or shape)" % (args.class_name, args.file))
        return 1
    _qt_app()
    colors = None if args.drawn_colors else PlayerColors()
    ctx = ScriptContext(colors)
    run_pending_actions(obj, ctx)
    for _ in range(args.frame):
        tick(obj, ctx)
    image = render_fitted(obj, args.scale, colors)
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    image.save(str(args.out))
    print("Wrote %s (%d x %d)" % (args.out, image.width(), image.height()))
    return 0


def _cmd_download(args) -> int:
    from autoswf.aqw.assets import AqwCache, DownloadError, default_cache_dir, download_reference_files
    cache = AqwCache(default_cache_dir())
    try:
        download_reference_files(cache, armor=args.armor, samples=args.samples, refresh=args.refresh,
                                 base_url=args.base_url, progress=print)
    except DownloadError as e:
        print("Download failed: %s" % e)
        return 1
    print("Done. AQW files are in %s. They are only used for the local preview and are never shared."
          % (Path(cache.root) / "aqw"))
    return 0


def _cmd_preview(args) -> int:
    from autoswf.aqw.assets import AqwCache, default_cache_dir
    from autoswf.preview.scene import MissingReferenceFiles, PreviewScene
    helm_path = Path(args.helm) if args.helm else None
    try:
        width, height = (int(v) for v in args.size.lower().split("x"))
    except ValueError:
        print("Size must look like 800x600")
        return 1
    if not args.snapshot:
        from autoswf.preview.window import run_preview
        return run_preview(helm_path, link=args.link, label=args.label, armor=args.armor)
    _qt_app()
    try:
        scene = PreviewScene.from_cache(AqwCache(default_cache_dir()), helm_path, link=args.link, armor=args.armor)
        scene.set_label(args.label)
    except (MissingReferenceFiles, ValueError) as e:
        print(e)
        return 1
    except OSError as e:
        print("Could not open %s: %s" % (helm_path, e.strerror or e))
        return 1
    for _ in range(args.frames):
        scene.tick()
    Path(args.snapshot).parent.mkdir(parents=True, exist_ok=True)
    scene.snapshot(width, height).save(str(args.snapshot))
    print("Wrote %s" % args.snapshot)
    return 0


def _cmd_fidelity(args) -> int:
    import os
    from autoswf.aqw.assets import AqwCache, default_cache_dir
    from autoswf.render.fidelity import default_targets, public_classes, run_fidelity
    from autoswf.swf.decode import MovieData
    ffdec = args.ffdec or os.environ.get("AUTOSWF_FFDEC")
    if not ffdec:
        print("Tell AutoSWF where FFDec is: --ffdec FOLDER or the AUTOSWF_FFDEC environment variable.")
        return 1
    _qt_app()
    cache = AqwCache(default_cache_dir())
    targets = default_targets(cache) + [(Path(f), n) for f in args.files for n in public_classes(MovieData(f))]
    if not targets:
        print("Nothing to compare: run python -m autoswf download-aqw --samples, or pass SWF files.")
        return 1
    out = Path(args.out) if args.out else Path(cache.root) / "fidelity"
    rows = run_fidelity(targets, Path(ffdec), out, zoom=args.zoom)
    for r in rows:
        if r.result is None:
            print("ERROR  %s  %s  %s" % (r.file, r.class_name, r.error))
        else:
            state = "PASS " if r.passed else ("KNOWN" if r.known else "FAIL ")
            print("%s  %s  %s  IoU %.3f  error %.1f" % (state, r.file, r.class_name, r.result.iou, r.result.mean_error))
    failed = [r for r in rows if not r.passed and not r.known]
    print("%d of %d classes match FFDec. Report: %s" % (len(rows) - len(failed), len(rows), out / "report.html"))
    return 1 if failed else 0


BACKGROUND_NAMES = ("paper", "papel", "background", "bg", "fundo", "用紙")


def _role_reason(node, ancestors, role, siblings) -> str:
    from autoswf.drawing.roles import IGNORE, detect_role
    if role.source == "hidden":
        return "hidden"
    if role.source == "guide":
        return "ignored: guide"
    if role.source == "override":
        return "--role"
    if role.source == "folder":
        folder = next(a.name for a in reversed(ancestors) if detect_role(a.name))
        return "folder '%s'" % folder
    if role.source == "clipped":
        base = next(s for s in reversed(siblings[:siblings.index(node)]) if not s.clipping)
        return "clipped to '%s'" % base.name
    if role.role == IGNORE:
        words = node.name.casefold().split()
        return "ignored: background" if any(w in BACKGROUND_NAMES for w in words) else "ignored: sketch or reference"
    if role.role is None:
        return 'no role in its name; pass --role "%s=line"' % node.name
    return "name"


def _parse_roles(items: list[str]) -> dict[str, str]:
    roles = {}
    for item in items:
        layer, sep, role = item.rpartition("=")
        if not sep or not layer:
            raise ValueError('Roles look like "LAYER=ROLE", for example --role "Layer 1=line"')
        roles[layer] = role.strip()
    return roles


def _cmd_convert(args) -> int:
    from autoswf.aqw.template import Alignment, choose_alignment
    from autoswf.drawing.layers import DrawingError
    from autoswf.drawing.passes import extract_passes
    from autoswf.drawing.readers import read_drawing
    from autoswf.drawing.roles import IGNORE, assign_roles
    from autoswf.vectorize.art import VectorizeSettings, helm_from_art, vectorize
    from autoswf.vectorize.metrics import quality_report
    out = Path(args.out) if args.out else Path(args.drawing).with_suffix(".swf")
    if out.resolve() == Path(args.drawing).resolve():
        print("The output %s would overwrite the drawing; choose another name" % out.name)
        return 1
    if out.suffix.lower() != ".swf":
        print("The output must be a .swf file (got %s)" % out.name)
        return 1
    try:
        overrides = _parse_roles(args.role)
        override = Alignment.parse(args.align) if args.align else None
        link = sanitize_link(args.link or out.stem)
        drawing = read_drawing(args.drawing)
        roles = assign_roles(drawing, overrides)
    except (DrawingError, ValueError) as e:
        print(e)
        return 1
    layers = [(n, a) for n, a in drawing.walk() if n.kind != "group"]
    print("Opened %s (%d x %d, %d layers)" % (Path(args.drawing).name, drawing.width, drawing.height, len(layers)))
    for node, ancestors in layers:
        role = roles[node]
        siblings = ancestors[-1].children if ancestors else drawing.layers
        shown = role.role if role.role not in (None, IGNORE) else "not used"
        path = "/".join([a.name for a in ancestors] + [node.name])
        print("  %s  %s  (%s)" % (path, shown, _role_reason(node, ancestors, role, siblings)))
    if args.list:
        return 0
    try:
        passes = extract_passes(drawing, roles, gradient_layers=frozenset(args.gradient))
        ys, xs = np.nonzero(passes.full[..., 3] > 0)
        alignment, reason = choose_alignment(drawing, (xs.min(), xs.max() + 1, ys.min(), ys.max() + 1), override)
        art = vectorize(passes, alignment, VectorizeSettings(detail=args.detail))
    except (DrawingError, ValueError) as e:
        print(e)
        return 1
    for note in art.notes:
        print(note)
    print("Alignment: %s: --align %s" % (reason, alignment))
    for layer in art.layers:
        segments = sum(len(p.segments) for p in layer.shape.paths)
        print("%s: %d region%s, %d segments" % (layer.name, len(layer.styles), "" if len(layer.styles) == 1 else "s", segments))
    data = export_helm(helm_from_art(art, link, separate_tones=args.separate_tones))
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(data)
    if len(data) > SIZE_WARNING_BYTES:
        print("Warning: %s is larger than 200 KB; official helms are usually a few KB. Try a lower --detail." % out)
    problems = validate_helm_swf(data, link)
    for p in problems:
        print("Problem: " + p)
    if problems:
        return 1
    print("Wrote %s (%.1f KB, class %s) — valid" % (out, len(data) / 1024, link))
    if args.report:
        print(quality_report(passes, art, data, link).format())
    return 0


def _cmd_template(args) -> int:
    from autoswf.aqw.assets import AqwCache, default_cache_dir
    from autoswf.aqw.template import TEMPLATE_ORIGIN, TEMPLATE_SCALE, TEMPLATE_SIZE, write_template
    from autoswf.swf.decode import MovieData
    client = AqwCache(default_cache_dir()).client_path()
    if client is None or not client.exists():
        print("AQW reference files are missing: the game client. Run: python -m autoswf download-aqw")
        return 1
    clip = Path(args.clip) if args.clip else None
    for path in (Path(args.out), clip):
        if path is not None:
            path.parent.mkdir(parents=True, exist_ok=True)
    write_template(MovieData(client), Path(args.out), clip=clip)
    print("Wrote %s (%d x %d, head origin at %g,%g, %g px per head unit)"
          % (args.out, *TEMPLATE_SIZE, *TEMPLATE_ORIGIN, TEMPLATE_SCALE))
    if clip is not None:
        print("Wrote %s (experimental: if Clip Studio Paint cannot open it, use the .psd)" % clip)
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
    from autoswf.aqw.assets import DEFAULT_ARMOR, GAME_BASE_URL
    p = sub.add_parser("download-aqw", help="download the AQW game client and an armor for the preview (local only)")
    p.add_argument("--armor", default=DEFAULT_ARMOR, help="armor file shown on the preview body (default: %(default)s)")
    p.add_argument("--samples", action="store_true", help="also download official items used for fidelity checks")
    p.add_argument("--refresh", action="store_true", help="download again even if the files are already cached")
    p.add_argument("--base-url", default=GAME_BASE_URL, help=argparse.SUPPRESS)
    p.set_defaults(run=_cmd_download)
    p = sub.add_parser("preview", help="show a helm on the AQW male and female bodies")
    p.add_argument("helm", nargs="?", help="helm SWF to show")
    p.add_argument("--link", help="helm class name (found automatically when the file has one)")
    p.add_argument("--label", default="Idle", help="game animation to play (default: %(default)s)")
    p.add_argument("--armor", default=DEFAULT_ARMOR, help="armor worn by the preview bodies (default: %(default)s)")
    p.add_argument("--snapshot", help="save one image instead of opening the window")
    p.add_argument("--frames", type=int, default=0, help="frames to play (24 fps) before the snapshot")
    p.add_argument("--size", default="800x600", help="snapshot size, WIDTHxHEIGHT")
    p.set_defaults(run=_cmd_preview)
    p = sub.add_parser("fidelity", help="compare the renderer with JPEXS FFDec on official items")
    p.add_argument("files", nargs="*", help="extra SWF files to compare (all their exported classes)")
    p.add_argument("--ffdec", help="FFDec folder (default: the AUTOSWF_FFDEC environment variable)")
    p.add_argument("--out", help="report folder (default: <cache>/fidelity)")
    p.add_argument("--zoom", type=float, default=4.0)
    p.set_defaults(run=_cmd_fidelity)
    p = sub.add_parser("convert", help="turn a layered drawing (.clip, .psd or .png) into a vector helm SWF")
    p.add_argument("drawing")
    p.add_argument("-o", "--out", help="SWF to write (default: next to the drawing, with .swf)")
    p.add_argument("--link", help="helm class name AQW loads (default: from the output file name)")
    p.add_argument("--detail", type=int, default=50, help="0 = simplest shapes, 100 = most faithful (default: %(default)s)")
    p.add_argument("--role", action="append", default=[], metavar="LAYER=ROLE",
                   help="set a layer's role: line, flat, shadow, occlusion, light, details or ignore (repeatable)")
    p.add_argument("--align", metavar="SCALE,X,Y[,DEG]",
                   help="drawing pixels per head unit, the pixel of the head origin, and an optional rotation: DEG "
                        "turns the drawing clockwise onto the head (a drawing that is turned clockwise needs a "
                        "negative DEG)")
    p.add_argument("--gradient", action="append", default=[], metavar="LAYER",
                   help="draw this soft shadow/occlusion/light layer as an SWF gradient instead of flat steps")
    p.add_argument("--separate-tones", action="store_true",
                   help="draw shadow, occlusion and light as separate shapes over the flat colors")
    p.add_argument("--report", action="store_true", help="measure the result against the drawing")
    p.add_argument("--list", action="store_true", help="only list the layers and the role of each")
    p.set_defaults(run=_cmd_convert)
    p = sub.add_parser("template", help="write a drawing template with the AQW heads as guide layers")
    p.add_argument("out", help="PSD file to write")
    p.add_argument("--clip", help="also write a Clip Studio Paint .clip (experimental)")
    p.set_defaults(run=_cmd_template)
    args = parser.parse_args(argv)
    return args.run(args)
