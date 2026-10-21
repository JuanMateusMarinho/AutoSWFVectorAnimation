"""The project file (spec §14): one `.aswf` zip with the settings (JSON), the parts found (to match them when the
drawing changes), a copy of the drawing and the last built helm; and the re-import that keeps animation, keyframes,
pivots and color slots on the parts that still match (by position, size and color)."""
import hashlib
import io
import json
import math
import os
import re
import zipfile
from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np

from autoswf import __version__
from autoswf.project.settings import HelmSettings

FORMAT = "autoswf-project"
VERSION = 2                       # 2 (Plan 7): "kind" helm or item; item projects hold an opened SWF
MATCH_LIMIT = 1.5


@dataclass(frozen=True)
class PartSignature:
    name: str
    kind: str
    center: tuple[float, float]          # head units
    area: float                          # head units²
    color: tuple[int, int, int]          # the flat color of its largest region


def part_signatures(build) -> list[PartSignature]:
    if build is None or build.parts is None:
        return []
    graph, out = build.parts.graph, []
    for name, part in build.parts.parts.items():
        regions = [graph.regions[r] for r in part.regions]
        area = sum(r.area for r in regions) or 1e-9
        cx = sum(r.center.x * r.area for r in regions) / area
        cy = sum(r.center.y * r.area for r in regions) / area
        largest = max(regions, key=lambda r: r.pixels)
        out.append(PartSignature(name, part.kind, (float(cx), float(cy)), float(area), tuple(int(v) for v in largest.flat[:3])))
    return out


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _file_name(name) -> str | None:
    """A drawing's file name from a project file, or None when it is not a plain name (a crafted project may hold
    "../../x" or "C:/x" to write elsewhere)."""
    base = re.split(r"[\\/]", name)[-1] if isinstance(name, str) else ""
    return None if base in ("", ".", "..") or ":" in base or base != name.strip() else base


def _network(path: str) -> bool:
    """A UNC path: never touched on opening a project (Windows would send the user's credentials to that server)."""
    return path.replace("/", "\\").startswith("\\\\")


def save_project(path: Path, settings: HelmSettings, build, *, signatures: list | None = None,
                 pending: bool = False) -> None:
    """Write the project; nothing is left half-written when it fails (ValueError with the reason). `signatures` are
    the parts the settings were made for (default: the build's); `pending` marks a drawing that changed since and was
    not re-imported, so reopening offers the re-import."""
    path = Path(path)
    source = Path(settings.source)
    try:
        drawing = source.read_bytes()
    except OSError as e:
        raise ValueError("Could not save %s: the drawing %s cannot be read (%s)" % (path.name, source, e.strerror or e))
    try:
        relative = os.path.relpath(source.resolve(), path.parent.resolve())
    except ValueError:                   # another drive
        relative = None
    doc = {"format": FORMAT, "version": VERSION, "kind": "helm", "app_version": __version__,
           "source": {"name": source.name, "path": str(source.resolve()), "relative": relative,
                      "sha256": "" if pending else _sha(drawing)},
           "settings": settings.to_dict(),
           "parts": [asdict(s) for s in (part_signatures(build) if signatures is None else signatures)]}
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("project.json", json.dumps(doc, indent=2, ensure_ascii=False))
        z.writestr("source/" + source.name, drawing)
        if build is not None and build.swf is not None:
            z.writestr("vector/helm.swf", build.swf)
    tmp = path.with_name(path.name + ".part")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_bytes(buffer.getvalue())
        os.replace(tmp, path)
    except OSError as e:
        if tmp.exists():
            tmp.unlink()
        raise ValueError("Could not save %s: %s" % (path.name, e.strerror or e)) from None


@dataclass
class LoadedProject:
    settings: HelmSettings
    signatures: list[PartSignature]
    swf: bytes | None
    source_changed: bool
    notes: list[str] = field(default_factory=list)
    saved_copy: Path | None = None       # the drawing as it was saved, extracted in the cache


def load_project(path: Path, cache_root: Path) -> LoadedProject:
    path = Path(path)
    try:
        with zipfile.ZipFile(path) as z:
            doc = json.loads(z.read("project.json").decode("utf-8"))
            names = set(z.namelist())
            source = doc.get("source", {}) if isinstance(doc, dict) else {}
            name = source.get("name", "") if isinstance(source, dict) else ""
            safe = _file_name(name)
            saved = z.read("source/" + name) if safe and "source/" + name in names else None
            swf = z.read("vector/helm.swf") if "vector/helm.swf" in names else None
    except (zipfile.BadZipFile, KeyError, ValueError, OSError, UnicodeDecodeError):
        raise ValueError("%s is not an AutoSWF project" % path.name) from None
    if not isinstance(doc, dict) or doc.get("format") != FORMAT:
        raise ValueError("%s is not an AutoSWF project" % path.name)
    if doc.get("kind", "helm") != "helm":
        raise ValueError("%s is a project of an opened SWF, not of a drawing" % path.name)
    version = doc.get("version")
    if not isinstance(version, int) or version > VERSION:
        raise ValueError("%s was made by a newer AutoSWF (project version %s)" % (path.name, version))
    settings = HelmSettings.from_dict(doc.get("settings", {}), path.name)
    signatures = []
    for entry in doc.get("parts", []):
        try:
            signatures.append(PartSignature(entry["name"], entry["kind"], tuple(entry["center"]), float(entry["area"]),
                                            tuple(entry["color"])))
        except (KeyError, TypeError, ValueError):
            continue
    saved_copy = None
    if saved is not None:
        saved_copy = Path(cache_root) / "projects" / _sha(saved) / safe
        if not saved_copy.exists():
            saved_copy.parent.mkdir(parents=True, exist_ok=True)
            saved_copy.write_bytes(saved)
    stored = source.get("path") if isinstance(source.get("path"), str) else ""
    absolute = Path(stored)
    relative = path.parent / source["relative"] if isinstance(source.get("relative"), str) else None
    found = None
    if stored and not _network(stored) and absolute.exists():
        found = absolute
    elif relative is not None and not _network(str(relative)) and relative.exists():
        found = relative
    notes, changed = [], False
    if found is not None:
        settings.source = str(found)
        changed = _sha(found.read_bytes()) != source.get("sha256")
    elif saved_copy is not None:
        settings.source = str(saved_copy)
        notes.append("The drawing was not found at %s; using the copy saved in the project." % source.get("path"))
    else:
        notes.append("The drawing was not found at %s and the project holds no copy of it." % source.get("path"))
    return LoadedProject(settings, signatures, swf, changed, notes, saved_copy)


def _write_zip(path: Path, entries: dict[str, bytes | str]) -> None:
    """Writes the zip atomically; nothing is left half-written when it fails (ValueError with the reason)."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in entries.items():
            z.writestr(name, data)
    tmp = path.with_name(path.name + ".part")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_bytes(buffer.getvalue())
        os.replace(tmp, path)
    except OSError as e:
        if tmp.exists():
            tmp.unlink()
        raise ValueError("Could not save %s: %s" % (path.name, e.strerror or e)) from None


def _read_doc(path: Path):
    try:
        with zipfile.ZipFile(path) as z:
            doc = json.loads(z.read("project.json").decode("utf-8"))
            names = set(z.namelist())
            return doc, names, z
    except (zipfile.BadZipFile, KeyError, ValueError, OSError, UnicodeDecodeError):
        raise ValueError("%s is not an AutoSWF project" % Path(path).name) from None


def project_kind(path: Path) -> str:
    """"helm" (a project made from a drawing; every version 1 file) or "item" (an opened SWF)."""
    doc, _, _ = _read_doc(Path(path))
    if not isinstance(doc, dict) or doc.get("format") != FORMAT:
        raise ValueError("%s is not an AutoSWF project" % Path(path).name)
    return "item" if doc.get("kind") == "item" else "helm"


def save_item_project(path: Path, original: bytes, name: str, edits) -> None:
    """An opened SWF and what the user changed in it: the original bytes and the edits (applied again on open)."""
    path, safe = Path(path), _file_name(name) or "item.swf"
    doc = {"format": FORMAT, "version": VERSION, "kind": "item", "app_version": __version__,
           "item": {"name": safe, "sha256": _sha(original)}, "edits": edits.to_dict()}
    _write_zip(path, {"project.json": json.dumps(doc, indent=1, ensure_ascii=False), "item/" + safe: original})


@dataclass
class LoadedItemProject:
    original: bytes
    name: str
    edits: object                        # ItemEdits
    notes: list[str] = field(default_factory=list)


def load_item_project(path: Path) -> LoadedItemProject:
    from autoswf.items.item_edits import ItemEdits
    path = Path(path)
    try:
        with zipfile.ZipFile(path) as z:
            doc = json.loads(z.read("project.json").decode("utf-8"))
            if not isinstance(doc, dict) or doc.get("format") != FORMAT:
                raise ValueError("%s is not an AutoSWF project" % path.name)
            version = doc.get("version")
            if not isinstance(version, int) or version > VERSION:
                raise ValueError("%s was made by a newer AutoSWF (project version %s)" % (path.name, version))
            if doc.get("kind") != "item":
                raise ValueError("%s is a project of a drawing, not of an opened SWF" % path.name)
            item = doc.get("item", {})
            name = _file_name(item.get("name", "")) or "item.swf"
            original = z.read("item/" + name)
    except (zipfile.BadZipFile, KeyError, OSError, UnicodeDecodeError, json.JSONDecodeError):
        raise ValueError("%s is not an AutoSWF project" % path.name) from None
    notes = []
    if item.get("sha256") and item["sha256"] != _sha(original):
        notes.append("The SWF saved in %s is damaged" % path.name)
    return LoadedItemProject(original, name, ItemEdits.from_dict(doc.get("edits", {})), notes)


def _cost(a: PartSignature, b: PartSignature) -> float:
    distance = math.hypot(a.center[0] - b.center[0], a.center[1] - b.center[1]) / math.sqrt(max(1e-9, min(a.area, b.area)))
    color = max(abs(x - y) for x, y in zip(a.color, b.color)) / 255
    return distance + color + 0.5 * abs(math.log(max(a.area, 1e-9) / max(b.area, 1e-9)))


def match_parts(old: list[PartSignature], new: list[PartSignature]) -> dict[str, str]:
    """Old part name -> new part name, per kind, by the cheapest assignment under MATCH_LIMIT."""
    from scipy.optimize import linear_sum_assignment
    out = {}
    for kind in {s.kind for s in old}:
        a = [s for s in old if s.kind == kind]
        b = [s for s in new if s.kind == kind]
        if not a or not b:
            continue
        cost = np.array([[_cost(x, y) for y in b] for x in a])
        rows, cols = linear_sum_assignment(cost)
        for r, c in zip(rows, cols):
            if cost[r, c] <= MATCH_LIMIT:
                out[a[r].name] = b[c].name
    return out


@dataclass
class ReimportReport:
    renamed: dict[str, str]
    kept: list[str]
    lost: list[str]
    new: list[str]

    def text(self) -> str:
        lines = []
        if self.kept:
            lines.append("Kept: " + ", ".join(self.kept))
        lines += ["Renamed: %s → %s" % kv for kv in self.renamed.items()]
        if self.lost:
            lines.append("Lost (its animation and keyframes were removed): " + ", ".join(self.lost))
        if self.new:
            lines.append("New: " + ", ".join(self.new))
        return "\n".join(lines) or "Nothing changed in the parts."


def reimport(settings: HelmSettings, old: list[PartSignature], build) -> tuple[HelmSettings, ReimportReport]:
    """The settings moved onto the parts of the new build: matched parts keep (renamed) animation, keyframes,
    pivots, color slots and version adjustments; lost parts lose theirs."""
    new = part_signatures(build)
    mapping = match_parts(old, new)
    old_names = {s.name for s in old}
    renamed = {o: n for o, n in mapping.items() if o != n}
    report = ReimportReport(renamed, sorted(o for o, n in mapping.items() if o == n),
                            sorted(o for o in old_names if o not in mapping),
                            sorted(n.name for n in new if n.name not in mapping.values()))

    def move(name: str) -> str | None:
        return mapping.get(name) if name in old_names else name

    out = settings.copy()
    out.animation.parts = {move(p): v for p, v in settings.animation.parts.items() if move(p) is not None}
    keys = []
    for k in settings.animation.keys:
        part = move(k.part)
        if part is None:
            continue
        target = part + k.target[len(k.part):] if k.target == k.part or k.target.startswith(k.part + " ") else k.target
        keys.append(type(k)(part, target, k.frame, dict(k.fields), k.tween))
    out.animation.keys = keys
    out.pivots = {move(p): v for p, v in settings.pivots.items() if move(p) is not None}
    out.corrections.colors = {move(p): v for p, v in settings.corrections.colors.items() if move(p) is not None}
    for variant in out.export.genders.values():
        variant.parts = {move(p): a for p, a in variant.parts.items() if move(p) is not None}
    return out, report
