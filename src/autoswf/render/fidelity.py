"""Fidelity check: render official classes with AutoSWF and with JPEXS FFDec (an independent renderer on the
user's computer) and compare them. FFDec does not run ActionScript, so both sides use the drawn colors."""
import html
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PySide6.QtGui import QImage

from autoswf.aqw.assets import DEFAULT_ARMOR, SAMPLE_FILES, AqwCache
from autoswf.render.display import instantiate
from autoswf.render.effects import qimage_to_array
from autoswf.render.painter import render_fitted
from autoswf.swf.decode import MovieData

IOU_MIN = 0.97
ERROR_MAX = 8.0
KNOWN_FFDEC_DIFFERENCES: dict[tuple[str, str], str] = {}


@dataclass(frozen=True)
class FidelityResult:
    iou: float
    mean_error: float
    shift: tuple[int, int]


@dataclass(frozen=True)
class FidelityRow:
    file: str
    class_name: str
    result: FidelityResult | None
    error: str | None
    passed: bool
    known: str | None


def _straight(img: QImage) -> np.ndarray:
    """H x W x 4, unpremultiplied RGB 0..255 and alpha 0..1."""
    arr = qimage_to_array(img)
    alpha = arr[..., 3:4]
    rgb = np.divide(arr[..., :3], alpha, out=np.zeros_like(arr[..., :3]), where=alpha > 0) * 255
    return np.concatenate([rgb, alpha], axis=-1)


def _crop(arr: np.ndarray) -> np.ndarray:
    ys, xs = np.nonzero(arr[..., 3] >= 0.5)
    if len(ys) == 0:
        return arr[:0, :0]
    return arr[ys.min():ys.max() + 1, xs.min():xs.max() + 1]


def compare_images(ours: QImage, ref: QImage, max_shift: int = 2) -> FidelityResult:
    a, b = _crop(_straight(ours)), _crop(_straight(ref))
    if a.size == 0 or b.size == 0:
        return FidelityResult(1.0, 0.0, (0, 0)) if a.size == b.size else FidelityResult(0.0, 255.0, (0, 0))
    h, w = max(a.shape[0], b.shape[0]) + 2 * max_shift, max(a.shape[1], b.shape[1]) + 2 * max_shift
    base = np.zeros((h, w, 4), np.float32)
    base[max_shift:max_shift + a.shape[0], max_shift:max_shift + a.shape[1]] = a
    mask_a = base[..., 3] >= 0.5
    shifts = sorted(((dx, dy) for dy in range(-max_shift, max_shift + 1) for dx in range(-max_shift, max_shift + 1)),
                    key=lambda s: abs(s[0]) + abs(s[1]))
    best = None
    for dx, dy in shifts:
        other = np.zeros_like(base)
        y, x = max_shift + dy, max_shift + dx
        other[y:y + b.shape[0], x:x + b.shape[1]] = b
        mask_b = other[..., 3] >= 0.5
        both = mask_a & mask_b
        iou = float(both.sum() / (mask_a | mask_b).sum())
        if best is None or iou > best[0]:
            error = float(np.abs(base[..., :3][both] - other[..., :3][both]).mean()) if both.any() else 255.0
            best = (iou, error, (dx, dy))
    return FidelityResult(*best)


def public_classes(movie: MovieData) -> list[str]:
    return sorted(n for n, cid in movie.classes.items() if cid and "_fla." not in n)


def _ffdec_export(ffdec_dir: Path, swf: Path, char_ids: list[int], zoom: float, out_dir: Path) -> dict[int, Path]:
    """Frame 1 of each character, rendered by FFDec in one run: character id -> PNG path."""
    jar = Path(ffdec_dir) / "ffdec-cli.jar"
    if not jar.exists():
        raise RuntimeError("FFDec was not found in %s (ffdec-cli.jar is missing)" % ffdec_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    ids = ",".join(str(c) for c in char_ids)
    command = ["java", "-jar", str(jar), "-selectid", ids, "-select", ",".join("%d:1" % c for c in char_ids),
               "-zoom", "%g" % zoom, "-format", "sprite:png", "-export", "sprite", str(out_dir), str(swf)]
    try:
        proc = subprocess.run(command, capture_output=True, text=True, timeout=600)
    except FileNotFoundError as e:
        raise RuntimeError("Java was not found; FFDec needs it on the PATH") from e
    paths = {}
    for c in char_ids:
        found = [p for p in out_dir.glob("DefineSprite_%d*/1.png" % c)
                 if re.fullmatch(r"DefineSprite_%d(_.*)?" % c, p.parent.name)]
        if found:
            paths[c] = found[0]
    if not paths:
        raise RuntimeError("FFDec rendered nothing for %s: %s" % (swf.name, (proc.stdout + proc.stderr)[-400:]))
    return paths


def ffdec_render_many(ffdec_dir: Path, swf: Path, char_ids: list[int], zoom: float, out_dir: Path) -> dict[int, QImage]:
    return {c: QImage(str(p)) for c, p in _ffdec_export(ffdec_dir, swf, char_ids, zoom, out_dir).items()}


def ffdec_render(ffdec_dir: Path, swf: Path, char_id: int, zoom: float, out_dir: Path) -> QImage:
    image = ffdec_render_many(ffdec_dir, swf, [char_id], zoom, out_dir).get(char_id)
    if image is None:
        raise RuntimeError("FFDec did not render character %d of %s" % (char_id, swf.name))
    return image


def default_targets(cache: AqwCache) -> list[tuple[Path, str]]:
    targets = []
    client = cache.client_path()
    if client is not None:
        targets += [(client, "mcHeadM"), (client, "mcHeadF")]
    for path in [cache.armor_path(g, DEFAULT_ARMOR) for g in "MF"] + [cache.file_path(rel) for rel in SAMPLE_FILES]:
        if path.exists():
            targets += [(path, name) for name in public_classes(MovieData(path))]
    return targets


def _slug(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", text)


def run_fidelity(targets: list[tuple[Path, str]], ffdec_dir: Path, out_dir: Path, zoom: float = 4.0) -> list[FidelityRow]:
    groups: dict[Path, list[str]] = {}
    for path, name in targets:
        groups.setdefault(Path(path), []).append(name)
    out_dir = Path(out_dir)
    (out_dir / "ours").mkdir(parents=True, exist_ok=True)
    rows, images = [], {}
    for path, names in groups.items():
        movie = MovieData(path)
        ids = {n: movie.classes[n] for n in names if n in movie.classes}
        try:
            refs = _ffdec_export(ffdec_dir, path, sorted(set(ids.values())), zoom, out_dir / "ffdec" / _slug(path.stem))
        except RuntimeError as e:
            rows += [FidelityRow(path.name, n, None, str(e), False, None) for n in names]
            continue
        for name in names:
            if name not in ids or ids[name] not in refs:
                rows.append(FidelityRow(path.name, name, None, "No reference image for this class", False, None))
                continue
            ours = render_fitted(instantiate(movie, ids[name]), zoom, None)
            ours_path = out_dir / "ours" / ("%s_%s.png" % (_slug(path.stem), _slug(name)))
            ours.save(str(ours_path))
            result = compare_images(ours, QImage(str(refs[ids[name]])))
            passed = result.iou >= IOU_MIN and result.mean_error <= ERROR_MAX
            rows.append(FidelityRow(path.name, name, result, None, passed, KNOWN_FFDEC_DIFFERENCES.get((path.name, name))))
            images[(path.name, name)] = (ours_path, refs[ids[name]])
    _write_report(rows, images, out_dir)
    return rows


def _write_report(rows: list[FidelityRow], images: dict, out_dir: Path) -> None:
    lines = ["<!doctype html><meta charset='utf-8'><title>AutoSWF fidelity report</title>",
             "<style>body{font-family:sans-serif;background:#eee}td{padding:6px;vertical-align:top;background:#fff}"
             "img{max-width:360px;background:repeating-conic-gradient(#ddd 0 25%,#fff 0 50%) 0 0/16px 16px}"
             ".fail{color:#b00}.pass{color:#070}</style>",
             "<h1>AutoSWF vs FFDec</h1><p>Thresholds: IoU &ge; %.2f, mean color error &le; %.1f (0-255).</p>" % (IOU_MIN, ERROR_MAX),
             "<table><tr><th>File / class</th><th>AutoSWF</th><th>FFDec</th><th>Result</th></tr>"]
    for r in rows:
        ours, ref = images.get((r.file, r.class_name), (None, None))
        cell = lambda p: "<img src='%s'>" % html.escape(p.relative_to(out_dir).as_posix()) if p else ""
        if r.result is None:
            verdict = "<span class='fail'>error: %s</span>" % html.escape(r.error or "")
        else:
            state = "pass" if r.passed else ("known difference: %s" % html.escape(r.known) if r.known else "fail")
            verdict = "<span class='%s'>%s</span><br>IoU %.3f<br>error %.1f<br>shift %s" % (
                "pass" if r.passed else "fail", state, r.result.iou, r.result.mean_error, r.result.shift)
        lines.append("<tr><td>%s<br><b>%s</b></td><td>%s</td><td>%s</td><td>%s</td></tr>" % (
            html.escape(r.file), html.escape(r.class_name), cell(ours), cell(ref), verdict))
    lines.append("</table>")
    (out_dir / "report.html").write_text("\n".join(lines), encoding="utf-8")
