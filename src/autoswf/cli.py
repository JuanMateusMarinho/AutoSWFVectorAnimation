"""Command line: inspect, demo-helm, render, download-aqw, preview, fidelity, convert, template and app."""
import argparse
import sys
from pathlib import Path

from autoswf.aqw.contract import SIZE_WARNING_BYTES, sanitize_link
from autoswf.aqw.helm import HelmItem, export_helm
from autoswf.aqw.validate import validate_helm_swf
from autoswf.model.document import ColorCustom, Frame, Placement, Symbol
from autoswf.model.geometry import Matrix
from autoswf.model.shape import Shape, SolidFill, ellipse
from autoswf.swf.inspect_format import format_report
from autoswf.swf.reader import SWF

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


def _parse_player_colors(items: list[str]) -> dict[str, int]:
    from autoswf.render.colors import LOCATION_FIELDS
    locations = {loc.casefold(): loc for loc in LOCATION_FIELDS}
    colors = {}
    for item in items:
        location, sep, value = item.partition("=")
        value = value.strip().lstrip("#")
        if (not sep or location.strip().casefold() not in locations or len(value) != 6
                or any(c not in "0123456789abcdefABCDEF" for c in value)):
            raise ValueError("Player colors look like Hair=FF0000 (locations: %s)" % ", ".join(LOCATION_FIELDS))
        colors[locations[location.strip().casefold()]] = int(value, 16)
    return colors


def _cmd_preview(args) -> int:
    from autoswf.aqw.assets import AqwCache, default_cache_dir
    from autoswf.preview.scene import MissingReferenceFiles, PreviewScene
    helm_path = Path(args.helm) if args.helm else None
    try:
        width, height = (int(v) for v in args.size.lower().split("x"))
    except ValueError:
        print("Size must look like 800x600")
        return 1
    try:
        colors = _parse_player_colors(args.player_color)
    except ValueError as e:
        print(e)
        return 1
    if not args.snapshot:
        from autoswf.preview.window import run_preview
        return run_preview(helm_path, link=args.link, label=args.label, armor=args.armor, colors=colors)
    _qt_app()
    try:
        scene = PreviewScene.from_cache(AqwCache(default_cache_dir()), helm_path, link=args.link, armor=args.armor)
        scene.set_label(args.label)
        for location, rgb in colors.items():
            scene.set_color(location, rgb)
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


def _parse_roles(items: list[str]) -> dict[str, str]:
    roles = {}
    for item in items:
        layer, sep, role = item.rpartition("=")
        if not sep or not layer:
            raise ValueError('Roles look like "LAYER=ROLE", for example --role "Layer 1=line"')
        roles[layer] = role.strip()
    return roles


def _cmd_convert(args) -> int:
    from autoswf.aqw.template import Alignment
    from autoswf.drawing.roles import IGNORE, assign_roles, role_reason
    from autoswf.project.build import HelmBuilder
    from autoswf.project.settings import HelmSettings
    from autoswf.vectorize.metrics import quality_report
    out = Path(args.out) if args.out else Path(args.drawing).with_suffix(".swf")
    if out.resolve() == Path(args.drawing).resolve():
        print("The output %s would overwrite the drawing; choose another name" % out.name)
        return 1
    if out.suffix.lower() != ".swf":
        print("The output must be a .swf file (got %s)" % out.name)
        return 1
    animation_flags = [flag for flag, value in (("--anim", args.anim), ("--animate", args.animate),
                                                ("--blink", args.blink), ("--sway", args.sway),
                                                ("--twitch", args.twitch), ("--pulse", args.pulse)) if value]
    part_flags = [flag for flag, value in (("--parts", args.parts), ("--color", args.color),
                                           ("--parts-image", args.parts_image)) if value] + animation_flags
    for off, needed, flags in (("--no-parts", "parts", part_flags if args.no_parts else []),
                               ("--no-animate", "animation", animation_flags if args.no_animate else [])):
        if flags:                                  # options that only mean something with parts / animation
            one = len(flags) == 1
            names = flags[0] if one else "%s and %s" % (", ".join(flags[:-1]), flags[-1])
            print("%s need%s %s; %s cannot be used with %s"
                  % (names, "s" if one else "", needed, "it" if one else "they", off))
            return 1
    try:
        overrides = _parse_roles(args.role)
        if args.align:
            Alignment.parse(args.align)
        link = sanitize_link(args.link or out.stem)
        corrections, corrections_file = _corrections(args)
        animation, animation_file = _animation_settings(args)
    except ValueError as e:
        print(e)
        return 1
    settings = HelmSettings(source=str(args.drawing), roles=overrides, align=args.align or None, detail=args.detail,
                            gradient=list(args.gradient), separate_tones=args.separate_tones, corrections=corrections,
                            animation=animation)
    settings.export.link = link
    builder = HelmBuilder(suggest=True, use_parts=not args.no_parts, animate=not args.no_animate)
    build = builder.build(settings, until="read")
    if build.error:
        print(build.error)
        return 1
    drawing = build.drawing
    try:
        roles = assign_roles(drawing, overrides)
    except ValueError as e:
        print(e)
        return 1
    layers = [(n, a) for n, a in drawing.walk() if n.kind != "group"]
    print("Opened %s (%d x %d, %d layers)" % (Path(args.drawing).name, drawing.width, drawing.height, len(layers)))
    for node, ancestors in layers:
        role = roles[node]
        siblings = ancestors[-1].children if ancestors else drawing.layers
        shown = role.role if role.role not in (None, IGNORE) else "not used"
        path = "/".join([a.name for a in ancestors] + [node.name])
        print("  %s  %s  (%s)" % (path, shown, role_reason(node, ancestors, role, siblings)))
    if args.list:
        return 0
    if corrections_file is not None:
        print("Using part corrections from %s" % corrections_file.name)
    if animation_file is not None:
        print("Using animation settings from %s" % animation_file.name)
    build = builder.build(settings)
    if build.no_flats:
        print("Parts: none (there are no flat colors to find parts in); writing one static shape set")
    if build.failed_stage in ("read", "passes", "parts", "split", "art"):
        print(build.error)
        return 1
    passes, art, parts = build.passes, build.art, build.parts
    for note in art.notes + (parts.notes if parts is not None else []):
        print(note)
    print("Alignment: %s: --align %s" % (build.alignment_reason, build.alignment))
    if parts is None:
        for layer in art.layers:
            segments = sum(len(p.segments) for p in layer.shape.paths)
            print("%s: %d region%s, %d segments" % (layer.name, len(layer.styles), "" if len(layer.styles) == 1 else "s",
                                                   segments))
    else:
        from autoswf.parts.assemble import colorable_summary
        helm = build.helm
        _print_parts(parts)
        print(colorable_summary(helm))
        if any(shade != "None" for _, _, shade in helm.colorable):
            print("In colorable areas the game draws shadows and lights with its own fixed tones (Dark, Darker, "
                  "Light), not the colors you painted.")
        if args.parts_image:
            from autoswf.parts.overview import parts_image
            Path(args.parts_image).parent.mkdir(parents=True, exist_ok=True)
            parts_image(passes, parts).save(args.parts_image)
            print("Wrote %s (the parts found; drawing pixels, for corrections)" % args.parts_image)
        if build.error:
            print(build.error)
            return 1
        if not args.no_animate:
            _print_animation(build)
    if build.error:
        print(build.error)
        return 1
    data, still = build.swf, build.still
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
    if args.report:                                # the drawing's rest pose: the helm before animation
        print(quality_report(passes, art, still, link).format())
    if args.morph:
        _morph_check(out, link)
    return 0


def _corrections(args):
    """The part corrections: --parts FILE, else DRAWING.parts.json next to the drawing when it exists, plus --color
    (none with --no-parts)."""
    from autoswf.parts.model import Corrections, check_color
    path = Path(args.parts) if args.parts else Path(args.drawing).with_name(Path(args.drawing).stem + ".parts.json")
    if args.no_parts:
        return Corrections(), None
    if args.parts or path.exists():
        corrections = Corrections.load(path)
    else:
        corrections, path = Corrections(), None
    for item in args.color:
        part, sep, location = item.rpartition("=")
        if not sep or not part:
            raise ValueError('Colors look like "PART=LOCATION", for example --color "Helm=Base"')
        name, location = check_color(part, location)
        corrections.colors[name] = location
    return corrections, path


PRESET_OPTIONS = (("blink", "Blink"), ("sway", "Sway"), ("twitch", "Twitch"), ("pulse", "Pulse"))


def _animation_settings(args):
    """The animation settings: --anim FILE, else DRAWING.anim.json next to the drawing when it exists, plus --animate and
    the preset options (none with --no-parts or --no-animate)."""
    from autoswf.anim.presets import parse_params, preset_name
    from autoswf.anim.settings import AnimationSettings
    from autoswf.parts.model import PartName
    path = Path(args.anim) if args.anim else Path(args.drawing).with_name(Path(args.drawing).stem + ".anim.json")
    if args.no_parts or args.no_animate:
        return AnimationSettings(), None
    if args.anim or path.exists():
        settings = AnimationSettings.load(path)
    else:
        settings, path = AnimationSettings(), None
    for item in args.animate:
        part, sep, preset = item.rpartition("=")
        if not sep or not part.strip():
            raise ValueError('Animations look like "PART=PRESET", for example --animate "Ear L=Twitch"')
        settings.parts[PartName.parse(part).name] = (preset_name(preset), {})
    for option, name in PRESET_OPTIONS:
        for item in getattr(args, option):
            key, sep, value = item.partition("=")
            if not sep or not key.strip():
                raise ValueError("Preset settings look like KEY=VALUE, for example --sway amplitude=20")
            values = {**settings.presets.get(name, {}), key.strip(): value.strip()}
            parse_params(name, values)
            settings.presets[name] = values
    return settings, path


def _print_animation(build) -> None:
    """The animation notes and clips of a build (the helm itself is baked by the builder)."""
    from autoswf.anim.settings import clip_summary, suggest_presets
    for note in build.animation_notes:
        print(note)
    clips = build.timeline.clips if build.timeline is not None else {}
    if not clips:
        if suggest_presets(build.rigs):            # there were eyes or locks, and the settings switched them off
            print("Animation: none (every part that would animate is set to none)")
        else:
            print("Animation: none (no eyes or locks found; add one with --animate PART=PRESET)")
        return
    print("Animation (%d clip%s):" % (len(clips), "" if len(clips) == 1 else "s"))
    for clip in clips.values():
        print("  " + clip_summary(clip))


def _print_parts(parts) -> None:
    from autoswf.aqw.contract import LOCATIONS
    print("Parts (%d):" % len(parts.parts))
    for name, part in parts.parts.items():
        found = {parts.location_of.get(r) for r in part.regions}
        text = [loc for loc in LOCATIONS if loc in found] + (["drawn colors"] if None in found else [])
        x, y = parts.label_point(name)
        print("  %-12s  %-22s  at %d,%d" % (name, ", ".join(text), x, y))


def _morph_check(out: Path, link: str) -> None:
    from autoswf.aqw.assets import DEFAULT_ARMOR, AqwCache, default_cache_dir
    from autoswf.preview.scene import MORPH_TOLERANCE_PX, PreviewScene
    cache = AqwCache(default_cache_dir())
    if cache.missing(DEFAULT_ARMOR):
        print("Morph check skipped: AQW reference files are missing. Run: python -m autoswf download-aqw")
        return
    _qt_app()
    counts = PreviewScene.from_cache(cache, out, link=link).morph_check()
    names = {"M": "male", "F": "female"}
    shown = [(g, counts[g]) for g in ("M", "F") if counts[g] > MORPH_TOLERANCE_PX]
    if not shown:
        print("Morph check: the helm covers the male and female base heads")
    else:
        print("Morph check: the base head shows around the helm — %s"
              % ", ".join("%s: %d px" % (names[g], n) for g, n in shown))


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


def _cmd_app(args) -> int:
    from autoswf.app.main import run_app
    return run_app([args.file] if args.file else [])


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
    p.add_argument("--player-color", action="append", default=[], metavar="LOCATION=RRGGBB",
                   help="a player color, e.g. Hair=FF0000 (Skin, Hair, Eye, Base, Trim, Accessory; repeatable)")
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
    p.add_argument("--parts", metavar="FILE",
                   help="part corrections (default: DRAWING.parts.json next to the drawing, when it exists)")
    p.add_argument("--no-parts", action="store_true", help="one static shape set: no parts and no color custom")
    p.add_argument("--color", action="append", default=[], metavar="PART=LOCATION",
                   help="the AQW color a part follows: Skin, Hair, Eye, Base, Trim, Accessory or none (repeatable)")
    p.add_argument("--parts-image", metavar="FILE.png", help="write an image of the parts found")
    p.add_argument("--morph", action="store_true",
                   help="check that the helm covers the male and female base heads (needs the AQW files)")
    p.add_argument("--no-animate", action="store_true",
                   help="a still helm: no blinking, swaying or other animation")
    p.add_argument("--anim", metavar="FILE",
                   help="animation settings (default: DRAWING.anim.json next to the drawing, when it exists)")
    p.add_argument("--animate", action="append", default=[], metavar="PART=PRESET",
                   help="animate a part: Blink, Sway, Twitch, Pulse or none (repeatable; eyes blink and locks sway "
                        "by default)")
    for option, name in PRESET_OPTIONS:
        p.add_argument("--" + option, action="append", default=[], metavar="KEY=VALUE",
                       help="a %s setting for every part that uses it (repeatable)" % name)
    p.set_defaults(run=_cmd_convert)
    p = sub.add_parser("template", help="write a drawing template with the AQW heads as guide layers")
    p.add_argument("out", help="PSD file to write")
    p.add_argument("--clip", help="also write a Clip Studio Paint .clip (experimental)")
    p.set_defaults(run=_cmd_template)
    p = sub.add_parser("app", help="open the AutoSWF app")
    p.add_argument("file", nargs="?", help="a drawing, an AutoSWF project (.aswf) or a SWF to open")
    p.set_defaults(run=_cmd_app)
    args = parser.parse_args(argv)
    return args.run(args)
