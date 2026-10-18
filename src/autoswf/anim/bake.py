"""Bake a timeline into a helm's SWF timelines (spec §11, §4.3): an eye's clip is its parent wrapper moving its ball and
lid, any other part gets a motion clip in its wrapper's place that moves the wrapper, and bends become morph shapes
whose ratio changes per frame. Colorable clips stay where Plan 4 placed them; only their own morph shape changes."""
import copy
from dataclasses import replace

from autoswf.anim.timeline import Timeline, pose_color, pose_matrix
from autoswf.model.document import Frame, Placement, Symbol
from autoswf.model.geometry import Matrix, Point
from autoswf.model.shape import Shape


def _bake_eye(helm, clip, rig) -> None:
    container = helm.wrappers[rig.name]
    base = list(container.frames[0].placements)
    targets = {id(helm.wrappers[t]): t for t in clip.tracks if t in helm.wrappers}
    frames = []
    for f in range(clip.length):
        placements = []
        for p in base:
            target = targets.get(id(p.item))
            if target is None:
                placements.append(replace(p))
                continue
            pose = clip.pose(target, f)
            placements.append(replace(p, matrix=pose_matrix(p.matrix, pose), color=pose_color(pose)))
        frames.append(Frame(placements))
    container.frames = frames


def _bake_layer(helm, clip, rig, layer: str) -> None:
    placement = helm.placements[layer]
    wrapper = placement.item
    origin = Point(rig.pivot.x - placement.matrix.tx, rig.pivot.y - placement.matrix.ty)
    frames = []
    for f in range(clip.length):
        pose = clip.pose(layer, f)
        frames.append(Frame([Placement(wrapper, 1, pose_matrix(Matrix(), pose, origin), pose_color(pose), name="art")]))
    motion = Symbol(layer + " motion", frames)
    placement.item = motion
    helm.wrappers[motion.name] = motion


def _bake_bend(helm, clip, layer: str, bend) -> None:
    wrapper = helm.wrappers[layer]
    m = helm.placements[layer].matrix
    offset = Point(m.tx, m.ty)                     # the wrapper's pivot in head units
    ratios = [clip.pose(layer, f).bend or 0.0 for f in range(clip.length)]
    morphs = {}

    def morph_of(shape: Shape):
        if id(shape) not in morphs:
            morphs[id(shape)] = bend.morph(shape, offset)
        return morphs[id(shape)]

    base = list(wrapper.frames[0].placements)
    for p in base:
        if isinstance(p.item, Symbol):             # a colorable clip: its own timeline changes its shape's ratio
            inner = list(p.item.frames[0].placements)
            p.item.frames = [Frame([replace(q, item=morph_of(q.item), ratio=r) if isinstance(q.item, Shape)
                                    else replace(q) for q in inner]) for r in ratios]
    wrapper.frames = [Frame([replace(p, item=morph_of(p.item), ratio=r) if isinstance(p.item, Shape) else replace(p)
                             for p in base]) for r in ratios]


def bake(helm, timeline: Timeline, rigs: dict):
    """A copy of the AssembledHelm `helm` with every clip of `timeline` baked in (`helm` itself is left as it is)."""
    out = copy.deepcopy(helm)
    for part, clip in timeline.clips.items():
        rig = rigs[part]
        if rig.eye is not None:
            _bake_eye(out, clip, rig)
            continue
        for layer in rig.layers:
            if layer in clip.tracks:
                _bake_layer(out, clip, rig, layer)
        for layer, bend in clip.bends.items():
            _bake_bend(out, clip, layer, bend)
    return out
