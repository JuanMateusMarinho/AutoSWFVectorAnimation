"""Write AutoSWF's layered test drawings into cache/test-drawings (never committed) to open in Clip Studio Paint or
convert by hand:

    .venv/Scripts/python tools/make_test_drawings.py [--morph PATH.swf]

synthetic.psd / synthetic.clip are drawn by the test suite's synthetic helm; the official ones are AQW items from the
local cache (python -m autoswf download-aqw --samples) split into painting passes."""
import argparse
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tests"))

from drawings import synthetic_helm                            # noqa: E402
from official_drawings import official_drawing                 # noqa: E402
from autoswf.aqw.assets import AqwCache, default_cache_dir      # noqa: E402
from autoswf.drawing.writers import write_clip, write_psd      # noqa: E402
from autoswf.swf.decode import MovieData                       # noqa: E402

OFFICIAL = (("items/helms/ArtixHead.swf", "ArtixHead"), ("items/helms/GoldLeppy2018HatM.swf", "GoldLeppy2018HatM"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--morph", help="also split this helm SWF (all of its public helm classes)")
    parser.add_argument("--size", type=int, default=480, help="synthetic drawing size in px")
    args = parser.parse_args()
    cache = AqwCache(default_cache_dir())
    out = Path(cache.root) / "test-drawings"
    out.mkdir(parents=True, exist_ok=True)

    def save(name, t, clip=False):
        path = out / (name + ".psd")
        write_psd(path, t.width, t.height, t.layers)
        print("Wrote %s  (--align %s)" % (path, t.alignment))
        if clip:
            write_clip(out / (name + ".clip"), t.width, t.height, t.layers)
            print("Wrote %s" % (out / (name + ".clip")))

    save("synthetic", synthetic_helm(args.size), clip=True)
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
