"""Write AutoSWF's layered test drawings into cache/test-drawings (never committed) to open in Clip Studio Paint or
convert by hand:

    .venv/Scripts/python tools/make_test_drawings.py [--morph PATH.swf]

synthetic.psd / synthetic.clip and synthetic_parts.psd / .clip are drawn by the test suite's synthetic helms; the official ones are AQW items from the
local cache (python -m autoswf download-aqw --samples) split into painting passes."""
import argparse
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tests"))

from drawings import synthetic_helm, synthetic_parts_helm      # noqa: E402
from official_drawings import official_drawing                 # noqa: E402
from autoswf.aqw.assets import AqwCache, default_cache_dir      # noqa: E402
from autoswf.drawing.writers import write_clip, write_psd      # noqa: E402
from autoswf.swf.decode import MovieData                       # noqa: E402

OFFICIAL = (("items/helms/ArtixHead.swf", "ArtixHead"), ("items/helms/GoldLeppy2018HatM.swf", "GoldLeppy2018HatM"))


def anim_strip(t):
    """The drawing converted with the default animation presets, frames 1, 11, 13, 25 and 37 side by side."""
    import numpy as np
    from PIL import Image
    from drawings import drawing_from_specs
    from helm_render import render_helm
    from autoswf.anim.bake import bake
    from autoswf.anim.rig import rig_parts
    from autoswf.anim.settings import AnimationSettings, build_timeline
    from autoswf.aqw.helm import export_helm
    from autoswf.drawing.passes import extract_passes
    from autoswf.drawing.roles import assign_roles
    from autoswf.parts.assemble import assemble_helm
    from autoswf.parts.detect import detect_parts
    from autoswf.parts.hidden import layered_passes, split_passes
    from autoswf.render.colors import PlayerColors
    from autoswf.vectorize.art import vectorize
    d = drawing_from_specs(t.width, t.height, t.layers)
    passes = extract_passes(d, assign_roles(d))
    parts = detect_parts(passes, t.alignment)
    layers = split_passes(passes, parts)
    helm = assemble_helm(vectorize(layered_passes(passes, layers), t.alignment), layers, "Strip")
    rigs = rig_parts(parts, helm, layers)
    timeline, _ = build_timeline(rigs, AnimationSettings())
    swf = export_helm(bake(helm, timeline, rigs).item)
    frames = []
    for f in (0, 10, 12, 24, 36):
        img = render_helm(swf, "Strip", t, PlayerColors(), f)
        a = img[..., 3:4] / 255
        frames.append((img[..., :3] * a + 51 * (1 - a)).astype(np.uint8))
    return Image.fromarray(np.hstack(frames))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--morph", help="also split this helm SWF (all of its public helm classes)")
    parser.add_argument("--size", type=int, default=480, help="synthetic drawing size in px")
    parser.add_argument("--parts", action="store_true", help="also write NAME_parts.png: the parts AutoSWF finds")
    parser.add_argument("--anim", action="store_true",
                        help="also write NAME.anim.png: frames 1, 11, 13, 25 and 37 of the animated helm side by side")
    args = parser.parse_args()
    cache = AqwCache(default_cache_dir())
    out = Path(cache.root) / "test-drawings"
    out.mkdir(parents=True, exist_ok=True)

    def save(name, t, clip=False):
        path = out / (name + ".psd")
        write_psd(path, t.width, t.height, t.layers)
        print("Wrote %s  (--align %s)" % (path, t.alignment))
        if args.parts:
            from drawings import drawing_from_specs
            from autoswf.drawing.passes import extract_passes
            from autoswf.drawing.roles import assign_roles
            from autoswf.parts.detect import detect_parts
            from autoswf.parts.overview import parts_image
            d = drawing_from_specs(t.width, t.height, t.layers)
            passes = extract_passes(d, assign_roles(d))
            parts_image(passes, detect_parts(passes, t.alignment)).save(out / (name + "_parts.png"))
            print("Wrote %s" % (out / (name + "_parts.png")))
        if args.anim:
            anim_strip(t).save(out / (name + ".anim.png"))
            print("Wrote %s" % (out / (name + ".anim.png")))
        if clip:
            write_clip(out / (name + ".clip"), t.width, t.height, t.layers)
            print("Wrote %s" % (out / (name + ".clip")))

    save("synthetic", synthetic_helm(args.size), clip=True)
    save("synthetic_parts", synthetic_parts_helm(), clip=True)
    targets = [(cache.file_path(rel), cls) for rel, cls in OFFICIAL if cache.file_path(rel).exists()]
    client = cache.client_path()
    if client is not None and client.exists():
        targets += [(client, "mcHeadM"), (client, "mcHeadF")]
    if args.morph:
        movie = MovieData(args.morph)
        targets += [(Path(args.morph), n) for n in movie.classes if "." not in n and not n.endswith("_backhair")]
    for path, cls in targets:
        save(cls, official_drawing(MovieData(path), cls))
    return 0


if __name__ == "__main__":
    sys.exit(main())
