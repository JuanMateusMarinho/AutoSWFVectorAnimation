"""AQW reference files: the local cache layout and the downloader. Downloads only happen when the user asks
(the `download-aqw` command or the preview window's button); the files never leave the user's computer."""
import http.client
import json
import lzma
import os
import re
import struct
import tempfile
import urllib.error
import urllib.request
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from autoswf.swf.reader import decompress

GAME_BASE_URL = "https://game.aq.com/game"
DEFAULT_ARMOR = "PalidanRevamp"
SAMPLE_FILES = ("items/helms/ArtixHead.swf", "items/helms/GoldLeppy2018HatM.swf", "hair/M/Normal.swf",
                "classes/M/VoidKnightStar.swf", "items/capes/redcape.swf")
USER_AGENT = "AutoSWF/0.1"
CLIENT_NAME = re.compile(r"^[A-Za-z0-9_.-]+\.swf$")
ARMOR_NAME = re.compile(r"^[A-Za-z0-9_.-]+$")
SWF_SIGNATURES = (b"FWS", b"CWS", b"ZWS")


class DownloadError(Exception):
    pass


def default_cache_dir() -> Path:
    """AUTOSWF_CACHE, else <repo>/cache in a source checkout, else %LOCALAPPDATA%/AutoSWF/cache."""
    env = os.environ.get("AUTOSWF_CACHE")
    if env:
        return Path(env)
    repo = Path(__file__).resolve().parents[3]
    if (repo / "pyproject.toml").exists():
        return repo / "cache"
    return Path(os.environ.get("LOCALAPPDATA", Path.home())) / "AutoSWF" / "cache"


@dataclass(frozen=True)
class AqwCache:
    root: Path

    def version_file(self) -> Path:
        return Path(self.root) / "aqw" / "version.json"

    def file_path(self, rel: str) -> Path:
        return Path(self.root) / "aqw" / "gamefiles" / rel

    def client_name(self) -> str | None:
        try:
            name = json.loads(self.version_file().read_text(encoding="utf-8")).get("sFile")
        except (OSError, ValueError, AttributeError):
            return None
        return name if isinstance(name, str) and CLIENT_NAME.match(name) else None

    def client_path(self) -> Path | None:
        name = self.client_name()
        if name is None:
            return None
        path = self.file_path(name)
        return path if path.exists() else None

    def armor_path(self, gender: str, armor: str) -> Path:
        return self.file_path("classes/%s/%s.swf" % (gender, armor))

    def missing(self, armor: str) -> list[str]:
        """What the preview still needs, in plain words."""
        out = [] if self.client_path() is not None else ["AQW game client"]
        return out + ["armor classes/%s/%s.swf" % (g, armor) for g in "MF" if not self.armor_path(g, armor).exists()]


def _get(url: str, timeout: float) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read()
    except urllib.error.HTTPError as e:
        raise DownloadError("Could not download %s (HTTP %d)" % (url, e.code)) from e
    except (urllib.error.URLError, OSError, http.client.HTTPException, ValueError) as e:
        reason = getattr(e, "reason", None) or str(e) or type(e).__name__
        raise DownloadError("Could not download %s (%s)" % (url, reason)) from e


def _check_swf(url: str, body: bytes) -> None:
    """A complete SWF: known signature, and a body that decompresses to the length its header announces."""
    if body[:3] not in SWF_SIGNATURES:
        raise DownloadError("%s is not a SWF file" % url)
    try:
        _, _, length, data = decompress(body)
    except (ValueError, zlib.error, lzma.LZMAError, EOFError, struct.error) as e:
        raise DownloadError("%s is not a complete SWF file" % url) from e
    if len(data) + 8 < length:
        raise DownloadError("%s is not a complete SWF file" % url)


def _save(path: Path, data: bytes) -> None:
    """Write next to the target and move into place, so a failure never leaves a partial file."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".part")
    except OSError as e:
        raise DownloadError("Could not save %s (%s)" % (path, e.strerror or e)) from e
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        os.replace(tmp, path)
    except OSError as e:
        raise DownloadError("Could not save %s (%s)" % (path, e.strerror or e)) from e
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


def download_reference_files(cache: AqwCache, *, armor: str = DEFAULT_ARMOR, samples: bool = False,
                             refresh: bool = False, base_url: str = GAME_BASE_URL,
                             progress: Callable[[str], None] = print, timeout: float = 30.0) -> list[Path]:
    """Fetch the current client, the armor for both genders and optionally the fidelity samples.
    Files already in the cache are kept unless `refresh`; returns the paths written."""
    base = base_url.rstrip("/")
    answer = _get(base + "/api/data/gameversion", timeout)
    try:
        client = json.loads(answer)["sFile"]
    except (ValueError, KeyError, TypeError) as e:
        raise DownloadError("AQW returned an unexpected game version answer") from e
    if not isinstance(client, str) or not CLIENT_NAME.match(client):
        raise DownloadError("AQW returned an unexpected client name '%s'" % client)
    if not ARMOR_NAME.match(armor):
        raise DownloadError("'%s' is not a valid armor file name" % armor)

    wanted = [client] + ["classes/%s/%s.swf" % (g, armor) for g in "MF"] + (list(SAMPLE_FILES) if samples else [])
    written = []
    for rel in wanted:
        target = cache.file_path(rel)
        if refresh or not target.exists():
            url = "%s/gamefiles/%s" % (base, rel)
            body = _get(url, timeout)
            _check_swf(url, body)
            _save(target, body)
            written.append(target)
            progress("Downloaded %s (%d KB)" % (rel, max(1, len(body) // 1024)))
        if rel == client:
            _save(cache.version_file(), answer)     # only now: a failed update keeps the previous client usable
    return written
