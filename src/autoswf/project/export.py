"""Export the helm (spec §13): link names checked for AQW, Helm or Helm morph (with the coverage check), back hair or
not, one file or male and female versions with their own adjustments, each file written safely and validated."""
import copy
import os
from dataclasses import dataclass, field
from pathlib import Path

from autoswf.anim.bake import bake
from autoswf.anim.rig import part_of_layer
from autoswf.anim.settings import suggest_presets
from autoswf.aqw.assets import AqwCache
from autoswf.aqw.contract import SIZE_WARNING_BYTES, check_link, client_class_names
from autoswf.aqw.helm import export_helm
from autoswf.aqw.validate import validate_helm_swf
from autoswf.model.document import Placement
from autoswf.model.geometry import Matrix, Point
from autoswf.parts.assemble import AssembledHelm
from autoswf.project.settings import Adjust, HelmSettings, Variant

GENDER_NAMES = {"M": "male", "F": "female"}


@dataclass
class ExportResult:
    path: Path
    link: str
    gender: str | None
    size: int = 0
    problems: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.problems

    def summary(self) -> str:
        if self.problems:
            return "Could not export %s: %s" % (self.path.name, "; ".join(self.problems))
        return "Wrote %s (%.1f KB, class %s) — valid" % (self.path.name, self.size / 1024, self.link)


def default_variant(settings: HelmSettings, gender: str) -> Variant:
    """`<Name>M` / `<Name>F` next to the single file (spec §13, my call)."""
    file = settings.export_file()
    try:
        link = settings.export_link() + gender
    except ValueError:
        link = ""
    return Variant(str(file.with_name(file.stem + gender + file.suffix)), link)


def outputs(settings: HelmSettings) -> list[tuple[str | None, Path, str]]:
    """(gender or None, file, link) of every file the export writes."""
    if settings.export.variants:
        return [(g, Path(v.file), v.link) for g in ("M", "F")
                for v in [settings.export.genders.get(g) or default_variant(settings, g)]]
    try:
        link = settings.export_link()
    except ValueError:
        link = ""
    return [(None, settings.export_file(), link)]


def export_problems(settings: HelmSettings, client_classes=()) -> list[str]:
    problems = []
    found = outputs(settings)
    for gender, path, link in found:
        prefix = "%s version: " % GENDER_NAMES[gender].capitalize() if gender else ""
        check = check_link(link, client_classes)
        if check.error:
            problems.append(prefix + check.error)
        elif check.link != link:
            problems.append(prefix + check.warning)
        if path.suffix.lower() != ".swf":
            problems.append(prefix + "The output must be a .swf file (got %s)" % path.name)
        try:
            same = path.resolve() == Path(settings.source).resolve()
        except OSError:
            same = False
        if same:
            problems.append(prefix + "The output %s would overwrite the drawing; choose another name" % path.name)
    if len(found) == 2:
        (_, a, la), (_, b, lb) = found
        if a.resolve() == b.resolve():
            problems.append("The male and female versions need different files")
        if la == lb:
            problems.append("The male and female versions need different links")
    return problems


def adjust_targets(helm: AssembledHelm, layers) -> dict[str, list[Placement]]:
    """Each part's top-level placements: its layers' wrappers (or motion clips), or an eye's parent."""
    out: dict[str, list[Placement]] = {}
    for layer in layers:
        name = layer.parent or layer.name
        placement = helm.placements.get(name)
        if placement is None:
            continue
        part = layer.parent or part_of_layer(layer)
        if all(p is not placement for p in out.get(part, [])):
            out.setdefault(part, []).append(placement)
    return out


def adjust_matrix(adjust: Adjust, pivot: Point) -> Matrix:
    """Move by (x, y) and scale about `pivot` (head units)."""
    return (Matrix.translate(pivot.x + adjust.x, pivot.y + adjust.y) @ Matrix.scale(adjust.scale, adjust.scale)
            @ Matrix.translate(-pivot.x, -pivot.y))


def adjust_helm(helm: AssembledHelm, layers, helm_adjust: Adjust, parts: dict[str, Adjust], rigs: dict) -> None:
    """Apply a gender's adjustments in place (on a baked copy): parts about their pivots, then the whole helm about the
    head origin (the back hair inside its own placement)."""
    targets = adjust_targets(helm, layers)
    for part, adjust in parts.items():
        placements = targets.get(part, [])
        if not placements:
            continue
        rig = rigs.get(part)
        pivot = rig.pivot if rig is not None else Point(placements[0].matrix.tx, placements[0].matrix.ty)
        m = adjust_matrix(adjust, pivot)
        for p in placements:
            p.matrix = m @ p.matrix
    whole = adjust_matrix(helm_adjust, Point(0, 0))
    for frame in helm.item.root.frames:
        for p in frame.placements:
            p.matrix = whole @ p.matrix
    if helm.item.backhair is not None:
        for frame in helm.item.backhair.frames:
            for p in frame.placements:
                p.matrix = p.matrix @ whole


def _write(path: Path, data: bytes) -> str | None:
    tmp = path.with_name(path.name + ".part")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_bytes(data)
        os.replace(tmp, path)
    except OSError as e:
        try:
            if tmp.exists():
                tmp.unlink()
        except OSError:
            pass
        return "Could not write %s: %s" % (path, e.strerror or e)
    return None


def _morph_notes(cache: AqwCache, data: bytes, link: str, genders: tuple[str, ...]) -> list[str]:
    from autoswf.preview.scene import MORPH_TOLERANCE_PX, PreviewScene
    from autoswf.swf.decode import MovieData
    client = cache.client_path()
    if client is None:
        return ["Morph check skipped: AQW reference files are missing. Use Help ▸ Download AQW files."]
    # only the base heads matter: no armor is needed
    scene = PreviewScene(MovieData(client), {g: None for g in genders}, "", helm=MovieData(data), helm_link=link)
    counts = {g: scene.uncovered_head_pixels(g) for g in genders}
    shown = [(g, n) for g, n in counts.items() if n > MORPH_TOLERANCE_PX]
    if not shown:
        heads = " and ".join(GENDER_NAMES[g] for g in genders)
        return ["Morph check: the helm covers the %s base head%s" % (heads, "s" if len(genders) > 1 else "")]
    return ["Morph check: the base head shows around the helm — %s"
            % ", ".join("%s: %d px" % (GENDER_NAMES[g], n) for g, n in shown)]


def pending_animation(build, settings: HelmSettings) -> list[str]:
    """Parts with a suggested animation the user has not accepted or skipped yet."""
    return [p for p in suggest_presets(build.rigs) if p not in settings.animation.parts] if build.rigs else []


def export_files(builder, build, settings: HelmSettings, cache: AqwCache) -> list[ExportResult]:
    found = outputs(settings)
    if not build.complete:
        return [ExportResult(path, link, g, problems=[build.error or "The helm is not built yet"]) for g, path, link in found]
    client = cache.client_path()
    names = ()
    if client is not None:
        from autoswf.swf.decode import MovieData
        try:
            names = client_class_names(MovieData(client))
        except ValueError:
            names = ()
    problems = export_problems(settings, names)
    if problems:
        return [ExportResult(path, link, g, problems=list(problems)) for g, path, link in found]
    pending = pending_animation(build, settings)
    results = []
    for gender, path, link in found:
        helm, rigs, timeline = builder.helm_for(build, link)
        baked = bake(helm, timeline, rigs) if timeline is not None and timeline.clips else copy.deepcopy(helm)
        if not settings.export.back_hair:
            baked.item.backhair = None
        if gender is not None:
            variant = settings.export.genders.get(gender) or default_variant(settings, gender)
            adjust_helm(baked, build.layers, variant.helm, variant.parts, rigs)
        data = export_helm(baked.item)
        result = ExportResult(path, link, gender, len(data))
        error = _write(path, data)
        if error:
            result.problems.append(error)
            results.append(result)
            continue
        result.problems += validate_helm_swf(data, link)
        if len(data) > SIZE_WARNING_BYTES:
            result.notes.append("%s is larger than 200 KB; official helms are usually a few KB. Try a lower detail."
                                % path.name)
        if settings.export.morph:
            result.notes += _morph_notes(cache, data, link, (gender,) if gender else ("M", "F"))
        if pending:
            result.notes.append("Not animated yet: %s (see AI suggestions)" % ", ".join(pending))
        results.append(result)
    return results
