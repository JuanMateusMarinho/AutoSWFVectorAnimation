"""A helm with parts (spec §4.2-4.3, §10): one wrapper symbol per part, placed at its pivot (its registration point,
as in Flash), holding a plain baked shape, then one colorable child clip per (location, shade) on top with exactly
the same edges, then details and line art. Animation (Plan 5) goes on the wrappers, never on the colorable clips."""
import re
from dataclasses import dataclass

import numpy as np
from scipy import ndimage

from autoswf.aqw.contract import LOCATIONS, SHADES
from autoswf.aqw.helm import HelmItem
from autoswf.model.document import ColorCustom, Frame, Placement, Symbol
from autoswf.model.geometry import Matrix
from autoswf.model.shape import Shape, SolidFill, translated
from autoswf.parts.hidden import PartLayer
from autoswf.vectorize.art import FaceStyle, TracedLayer, VectorArt, recolored, split_tones
from autoswf.vectorize.planar import trace_shape

# The client's mcSkel in Idle (both genders, 2026-10-16): the head slot and the back-hair slot.
IDLE_HEAD = Matrix(0.23516845703125, 0.025909423828125, -0.025909423828125, 0.23516845703125, 7.6, -100.25)
IDLE_BACKHAIR = Matrix(0.89178466796875, 0.1094207763671875, -0.1094207763671875, 0.89178466796875, 4.0, -114.15)
LOCATION_MATCH = 16                                # max channel difference between a face's flat and a region's
UNDERLAP_UNITS = 1.5                               # head units a lower group of faces reaches under the groups above
EDGE_MARGIN = 2                                    # px: and never closer than this to the part's edge


def head_to_backhair() -> Matrix:
    """Head-local space into the back-hair slot's space, so back hair shows in Idle where it was drawn."""
    return IDLE_BACKHAIR.inverse() @ IDLE_HEAD


def face_shade(style: FaceStyle, soft_roles: frozenset[str], steps: int = 3) -> str:
    """The game shade of a face: Light over Darker over Dark over None; soft tones count from their middle level."""
    levels = dict(style.tones)

    def present(role: str) -> bool:
        return levels.get(role, 0) >= ((steps + 1) // 2 if role in soft_roles else 1)
    if present("light"):
        return "Light"
    if present("occlusion"):
        return "Darker"
    if present("shadow"):
        return "Dark"
    return "None"


def instance_name(name: str) -> str:
    """"Lock 3" -> "lock3", "Eye L ball" -> "eyeLBall", "Back hair" -> "backHair", "Hair (Bangs)" -> "hairBangs"."""
    words = re.findall(r"[A-Za-z0-9]+", name) or ["part"]
    return words[0].lower() + "".join(w[:1].upper() + w[1:] for w in words[1:])


@dataclass(eq=False)
class AssembledHelm:
    item: HelmItem
    wrappers: dict[str, Symbol]                    # by layer name, plus the eyes' parent wrappers ("Eye L")
    placements: dict[str, Placement]
    colorable: list[tuple[str, str, str]]          # (layer name, location, shade) in placement order


def _location(style: FaceStyle, layer: PartLayer) -> str | None:
    if style.flat is None:
        return None
    for color, location in layer.locations:
        if max(abs(int(a) - int(b)) for a, b in zip(style.flat[:3], color[:3])) <= LOCATION_MATCH:
            return location
    return None


def _stack(traced: TracedLayer, groups: list[tuple[list[int], list[FaceStyle]]]) -> list[Shape]:
    """One shape per group of faces (bottom to top), each traced from the face map with its own faces plus an underlap
    of UNDERLAP_UNITS under the faces of the groups above it that stops EDGE_MARGIN px inside the part: a lower group
    never reaches the part's edge under another one, so an upper group's anti-aliased edge never blends with a lower
    group's color, and neighbors overlap by a full pixel even at one pixel per head unit."""
    labels = traced.labels
    m = traced.matrix
    reach = max(EDGE_MARGIN, int(np.ceil(UNDERLAP_UNITS / max(np.hypot(m.a, m.b), 1e-9))))
    inside = ndimage.distance_transform_edt(np.pad(labels >= 0, 1))[1:-1, 1:-1] > EDGE_MARGIN
    shapes = []
    for k, (faces, styles) in enumerate(groups):
        own = np.isin(labels, faces)
        if not own.any():
            shapes.append(Shape([], []))
            continue
        above = np.isin(labels, [f for later, _ in groups[k + 1:] for f in later])
        out = np.full(labels.shape, -1, np.int32)
        palette, index = [], {}
        lookup = np.full(int(labels.max()) + 2, -1, np.int32)
        for face, style in zip(faces, styles):
            if style not in index:
                index[style] = len(palette)
                palette.append(style)
            lookup[face] = index[style]
        out[own] = lookup[labels[own]]
        if above.any():
            dist, (iy, ix) = ndimage.distance_transform_edt(~own, return_indices=True)
            under = above & (dist <= reach) & inside
            out[under] = out[iy[under], ix[under]]
        hidden = above if traced.hidden is None else above | traced.hidden      # covered at rest
        shapes.append(trace_shape(out, [SolidFill(s.color) for s in palette], traced.fit, traced.matrix, hidden))
    return shapes


def _shape_items(traced: TracedLayer, layer: PartLayer, separate_tones: bool, colorable: list) -> list:
    """The plain shape(s) of a fills layer and its colorable clips, in drawing order."""
    if traced.role != "fills":
        return [traced.shape]
    locations = [_location(s, layer) for s in traced.styles]
    shades = [face_shade(s, layer.soft_roles) for s in traced.styles]
    if any(locations) and traced.labels is not None and not separate_tones:
        return _layered_items(traced, layer, locations, shades, colorable)
    flat = [FaceStyle(s.flat, s.flat) if s.flat is not None else None for s in traced.styles]
    plain = recolored(traced, traced.name, [f if loc else s for s, f, loc in zip(traced.styles, flat, locations)])
    items = [t.shape for t in (split_tones(plain) if separate_tones else [plain])]
    for location in LOCATIONS:
        if location not in locations:
            continue
        has_dark = any(loc == location and sh == "Dark" for loc, sh in zip(locations, shades))
        wanted = {"None": lambda shade: True,                      # Dark continues under Darker only where
                  "Dark": lambda shade: shade == "Dark" or (has_dark and shade == "Darker"),   # both exist
                  "Darker": lambda shade: shade == "Darker", "Light": lambda shade: shade == "Light"}
        for shade in ("None", "Dark", "Darker", "Light"):
            mapping = []
            for s, f, loc, sh in zip(traced.styles, flat, locations, shades):
                take = loc == location and wanted[shade](sh)
                mapping.append((f if shade == "None" else s) if take else None)
            if not any(mapping):
                continue
            clip = recolored(traced, "%s %s %s" % (layer.name, location, shade), mapping)
            if not clip.shape.paths:
                continue
            items.append(Symbol(clip.name, [Frame([Placement(clip.shape, 1)])], color_custom=ColorCustom(location, shade)))
            colorable.append((layer.name, location, shade))
    return items


def _layered_items(traced: TracedLayer, layer: PartLayer, locations: list, shades: list, colorable: list) -> list:
    """Plain faces, then per location its None, Dark, Darker and Light faces, each group traced on its own (_stack)."""
    plain = [i for i, loc in enumerate(locations) if not loc]
    groups = [(plain, [traced.styles[i] for i in plain])]
    names = [None]
    for location in LOCATIONS:
        for shade in ("None", "Dark", "Darker", "Light"):
            faces = [i for i, (loc, sh) in enumerate(zip(locations, shades)) if loc == location and sh == shade]
            if not faces:
                continue
            styles = [FaceStyle(traced.styles[i].flat, traced.styles[i].flat) if shade == "None" else traced.styles[i]
                      for i in faces]
            groups.append((faces, styles))
            names.append((location, shade))
    items = []
    for name, shape in zip(names, _stack(traced, groups)):
        if not shape.paths:
            continue
        if name is None:
            items.append(shape)
            continue
        location, shade = name
        items.append(Symbol("%s %s %s" % (layer.name, location, shade), [Frame([Placement(shape, 1)])],
                            color_custom=ColorCustom(location, shade)))
        colorable.append((layer.name, location, shade))
    return items


def _wrapper(layer: PartLayer, traced: list[TracedLayer], separate_tones: bool, colorable: list) -> Symbol | None:
    items = []
    for t in traced:
        items += _shape_items(t, layer, separate_tones, colorable)
    placements = []
    for item in items:
        if isinstance(item, Shape):
            if not item.paths:
                continue
            item = translated(item, -layer.pivot.x, -layer.pivot.y)
        else:
            shape = item.frames[0].placements[0].item
            item.frames[0].placements[0].item = translated(shape, -layer.pivot.x, -layer.pivot.y)
        placements.append(Placement(item, len(placements) + 1))
    return Symbol(layer.name, [Frame(placements)]) if placements else None


def assemble_helm(art: VectorArt, layers: list[PartLayer], link: str, *, separate_tones: bool = False) -> AssembledHelm:
    traced: dict[str, list[TracedLayer]] = {}
    for t in art.layers:
        traced.setdefault(t.part, []).append(t)
    wrappers: dict[str, Symbol] = {}
    placements: dict[str, Placement] = {}
    colorable: list[tuple[str, str, str]] = []
    root_frame, back_frame = Frame(), Frame()
    parents: dict[str, tuple[Symbol, object]] = {}
    taken: set[str] = set()

    def unique(name: str) -> str:                  # folder names may spell alike ("Hair (髪)" -> "hair")
        base, k = instance_name(name), 2
        out = base
        while out in taken:
            out, k = "%s%d" % (base, k), k + 1
        taken.add(out)
        return out
    for layer in layers:
        symbol = _wrapper(layer, traced.get(layer.name, []), separate_tones, colorable)
        if symbol is None:
            continue
        wrappers[layer.name] = symbol
        if layer.parent is None:
            frame = back_frame if layer.back_hair else root_frame
            p = Placement(symbol, len(frame.placements) + 1, Matrix.translate(layer.pivot.x, layer.pivot.y),
                          name=unique(layer.name))
            frame.placements.append(p)
            placements[layer.name] = p
            continue
        if layer.parent not in parents:
            pivot = next((l.pivot for l in layers if l.parent == layer.parent and l.name.endswith(" ball")), layer.pivot)
            parent = Symbol(layer.parent, [Frame()])
            p = Placement(parent, len(root_frame.placements) + 1, Matrix.translate(pivot.x, pivot.y),
                          name=unique(layer.parent))
            root_frame.placements.append(p)
            parents[layer.parent] = (parent, pivot)
            wrappers[layer.parent] = parent
            placements[layer.parent] = p
        parent, pivot = parents[layer.parent]
        frame = parent.frames[0]
        p = Placement(symbol, len(frame.placements) + 1,
                      Matrix.translate(layer.pivot.x - pivot.x, layer.pivot.y - pivot.y), name=instance_name(layer.name))
        frame.placements.append(p)
        placements[layer.name] = p
    root = Symbol(link, [root_frame])
    backhair = None
    if back_frame.placements:
        inner = Symbol("Back hair art", [back_frame])
        backhair = Symbol(link + "_backhair", [Frame([Placement(inner, 1, head_to_backhair())])])
    return AssembledHelm(HelmItem(link, root, backhair), wrappers, placements, colorable)


def colorable_summary(helm: AssembledHelm) -> str:
    pairs = {(loc, shade) for _, loc, shade in helm.colorable}
    ordered = [(loc, shade) for loc in LOCATIONS for shade in SHADES if (loc, shade) in pairs]
    if not ordered:
        return "Color custom: none (every part keeps its drawn colors)"
    return "Color custom: %s (%d clip%s)" % (", ".join("%s %s" % p for p in ordered), len(helm.colorable),
                                             "" if len(helm.colorable) == 1 else "s")
