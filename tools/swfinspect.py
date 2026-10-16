"""Kept for the research workflow: same as `python -m autoswf inspect FILE [options]`."""
import sys

from autoswf.cli import main

if __name__ == "__main__":
    raise SystemExit(main(["inspect", *sys.argv[1:]]))
