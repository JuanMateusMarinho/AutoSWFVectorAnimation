"""The Ruffle test stage's compiled code: the ABC built from stage/*.as on the developer's machine
(tools/build_ruffle_stage.py, with FFDec) and the record of which sources it was built from."""
import hashlib
import json
from pathlib import Path

STAGE_DIR = Path(__file__).with_name("stage")
ABC_FILE = Path(__file__).with_name("stage.abc")
RECORD_FILE = Path(__file__).with_name("stage.abc.json")


def sources_digest() -> str:
    """sha256 over the stage's .as files (names and text, line endings ignored)."""
    h = hashlib.sha256()
    for path in sorted(STAGE_DIR.glob("*.as")):
        h.update(path.name.encode("utf-8") + b"\0")
        h.update(path.read_bytes().replace(b"\r\n", b"\n") + b"\0")
    return h.hexdigest()


def built_digest() -> str | None:
    """The sources digest stage.abc was built from, or None when it was never built."""
    if not RECORD_FILE.exists():
        return None
    return json.loads(RECORD_FILE.read_text(encoding="utf-8")).get("sources")


def stage_abc() -> bytes:
    return ABC_FILE.read_bytes()
