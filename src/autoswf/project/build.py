"""The convert pipeline as cached stages (the app and `convert` share it): a change re-runs only the stages that read
what changed — a color slot re-assembles the helm, an animation setting only re-bakes it."""
import copy
import json
import os
from collections import OrderedDict
from dataclasses import dataclass, field, replace
from typing import Callable

import numpy as np

from autoswf.anim.bake import bake
from autoswf.anim.rig import rig_parts
from autoswf.anim.settings import build_timeline
from autoswf.anim.timeline import Timeline
from autoswf.aqw.helm import export_helm
from autoswf.aqw.template import Alignment, choose_alignment
from autoswf.drawing.layers import DrawingError
from autoswf.drawing.passes import extract_passes
from autoswf.drawing.readers import read_drawing
from autoswf.drawing.roles import TONE_ROLES, assign_roles, layer_keys
from autoswf.model.geometry import Point
from autoswf.parts.assemble import AssembledHelm, assemble_helm
from autoswf.parts.detect import apply_color_slots, detect_parts
from autoswf.parts.hidden import layered_passes, split_passes, with_locations
from autoswf.parts.model import Corrections
from autoswf.project.settings import HelmSettings
from autoswf.vectorize.art import VectorizeSettings, helm_from_art, vectorize

STAGES = ("read", "passes", "parts", "split", "art", "helm", "animation", "swf")
STAGE_LABELS = {"read": "Reading the drawing", "passes": "Sorting the layers", "parts": "Finding the parts",
                "split": "Filling behind moving parts", "art": "Vectorizing", "helm": "Building the helm",
                "animation": "Animating", "swf": "Writing the SWF"}
CACHE_SIZE = 3


class BuildCancelled(Exception):
    pass


@dataclass(eq=False)
class Build:
    settings: HelmSettings
    link: str = ""
    drawing: object = None
    roles: dict | None = None
    passes: object = None
    alignment: Alignment | None = None
    alignment_reason: str = ""
    parts: object = None                  # PartMap with the color slots applied, or None (no parts)
    no_flats: bool = False                # parts were wanted but the drawing has no flat colors
    layers: list = field(default_factory=list)
    art: object = None
    helm: AssembledHelm | None = None
    rigs: dict = field(default_factory=dict)
    timeline: Timeline | None = None
    animation_notes: list[str] = field(default_factory=list)
    settings_notes: list[str] = field(default_factory=list)      # choices that name layers the drawing lost
    still: bytes | None = None
    swf: bytes | None = None
    error: str | None = None
    failed_stage: str | None = None

    @property
    def notes(self) -> list[str]:
        out = list(self.settings_notes) + (list(self.art.notes) if self.art is not None else [])
        if self.parts is not None:
            out += self.parts.notes
        return out + self.animation_notes

    @property
    def complete(self) -> bool:
        return self.swf is not None


class _Lru:
    def __init__(self, size: int = CACHE_SIZE):
        self.size, self.items = size, OrderedDict()

    def get(self, key):
        if key in self.items:
            self.items.move_to_end(key)
            return self.items[key]
        return None

    def put(self, key, value):
        self.items[key] = value
        self.items.move_to_end(key)
        while len(self.items) > self.size:
            self.items.popitem(last=False)
        return value


def _json(value) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False)


class HelmBuilder:
    """`suggest`: animate the suggested parts by default (the CLI; the app waits for the user to accept them).
    `use_parts`: find parts (False = one static shape set). `animate`: bake the animation (False = a still helm)."""

    def __init__(self, suggest: bool = False, use_parts: bool = True, animate: bool = True):
        self.suggest, self.use_parts, self.animate = suggest, use_parts, animate
        self._caches = {name: _Lru() for name in ("read", "passes", "parts", "split", "art", "helm")}

    # ------------------------------------------------------------ stages

    def build(self, settings: HelmSettings, *, until: str = "swf", progress: Callable[[str], None] | None = None,
              cancelled: Callable[[], bool] | None = None) -> Build:
        settings = copy.deepcopy(settings)
        b = Build(settings)
        last = STAGES.index(until)
        self._progress, self._cancelled = progress, cancelled
        stage = "read"
        try:
            for stage in STAGES[:last + 1]:
                getattr(self, "_" + stage)(b)
        except (DrawingError, ValueError) as e:
            b.error, b.failed_stage = str(e), stage
        return b

    def _run(self, stage: str, cache: str, key, make):
        found = self._caches[cache].get(key)
        if found is not None:
            return found
        if self._cancelled is not None and self._cancelled():
            raise BuildCancelled()
        if self._progress is not None:
            self._progress(STAGE_LABELS[stage])
        return self._caches[cache].put(key, make())

    def _read(self, b: Build) -> None:
        source = b.settings.source
        try:
            st = os.stat(source)
            stamp = (st.st_mtime_ns, st.st_size)
        except OSError:
            stamp = None
        b._read_key = (source, stamp)
        b.drawing = self._run("read", "read", b._read_key, lambda: read_drawing(source))

    def _passes(self, b: Build) -> None:
        s = b.settings
        b._passes_key = (b._read_key, _json(s.roles), tuple(s.gradient))

        keys = layer_keys(b.drawing)
        overrides = {k: v for k, v in s.roles.items() if k in keys}
        b.settings_notes = ["There is no layer '%s' in the drawing (chosen as %s); that choice is not used" % (k, v)
                            for k, v in s.roles.items() if k not in keys]

        def make():
            roles = assign_roles(b.drawing, overrides)
            tones = {n.name for n, r in roles.items() if r.role in TONE_ROLES}
            gradient = frozenset(g for g in s.gradient if g in tones)
            return roles, extract_passes(b.drawing, roles, gradient_layers=gradient)
        b.roles, b.passes = self._run("passes", "passes", b._passes_key, make)
        tones = {n.name for n, r in b.roles.items() if r.role in TONE_ROLES}
        b.settings_notes += ["'%s' is not a shadow, occlusion or light layer (any more); it is drawn without a gradient"
                             % g for g in s.gradient if g not in tones]
        ys, xs = np.nonzero(b.passes.full[..., 3] > 0)
        override = Alignment.parse(s.align) if s.align else None
        b.alignment, b.alignment_reason = choose_alignment(b.drawing, (xs.min(), xs.max() + 1, ys.min(), ys.max() + 1),
                                                           override)

    def _parts(self, b: Build) -> None:
        s = b.settings
        c = s.corrections.to_dict()
        b._parts_key = (b._passes_key, b.alignment, s.detail, _json(c["assign"]), _json(c["cuts"]), self.use_parts)
        if not self.use_parts:
            return
        base = self._run("parts", "parts", b._parts_key, lambda: detect_parts(
            b.passes, b.alignment, Corrections(list(s.corrections.assign), list(s.corrections.cuts), {}), s.detail))
        if not base.parts:                 # line art alone: nothing to split, one static shape set
            b.no_flats = True
            return
        b.parts = apply_color_slots(base, s.corrections.colors)

    def _split(self, b: Build) -> None:
        if b.parts is None:
            return
        base = self._run("split", "split", b._parts_key, lambda: split_passes(b.passes, b.parts))
        b.layers = with_locations(base, b.parts)

    def _art(self, b: Build) -> None:
        settings = VectorizeSettings(detail=b.settings.detail)
        if b.parts is None:
            b._art_key = ("whole", b._parts_key)
            b.art = self._run("art", "art", b._art_key, lambda: vectorize(b.passes, b.alignment, settings))
        else:
            b._art_key = ("parts", b._parts_key)
            b.art = self._run("art", "art", b._art_key,
                              lambda: vectorize(layered_passes(b.passes, b.layers), b.alignment, settings))

    def _helm(self, b: Build) -> None:
        s = b.settings
        b.link = s.export_link()
        key = (b._art_key, _json(s.corrections.colors), b.link, s.separate_tones)
        b._helm_key = key

        def make():
            helm = self._assemble(b, b.link)
            rigs = rig_parts(b.parts, helm, b.layers) if b.parts is not None else {}
            return helm, rigs, export_helm(helm.item)
        b.helm, rigs, b.still = self._run("helm", "helm", key, make)
        b.rigs = self._with_pivots(rigs, s.pivots)

    def _animation(self, b: Build) -> None:
        if not self.animate or b.parts is None:
            return
        b.timeline, b.animation_notes = build_timeline(b.rigs, b.settings.animation, suggest=self.suggest)

    def _swf(self, b: Build) -> None:
        if b.timeline is None or not b.timeline.clips:
            b.swf = b.still
        else:
            b.swf = export_helm(bake(b.helm, b.timeline, b.rigs).item)

    # ------------------------------------------------------------ helpers

    def _assemble(self, b: Build, link: str) -> AssembledHelm:
        if b.parts is None:
            item = helm_from_art(b.art, link, separate_tones=b.settings.separate_tones)
            return AssembledHelm(item, {}, {}, [])
        return assemble_helm(b.art, b.layers, link, separate_tones=b.settings.separate_tones)

    @staticmethod
    def _with_pivots(rigs: dict, pivots: dict) -> dict:
        return {name: replace(rig, pivot=Point(*pivots[name])) if name in pivots else rig for name, rig in rigs.items()}

    def helm_for(self, b: Build, link: str) -> tuple[AssembledHelm, dict, Timeline | None]:
        """The built helm assembled again for another link (export names), with its rigs and timeline."""
        if b.art is None:
            raise ValueError("The helm is not built yet")
        if link == b.link and b.helm is not None:
            return b.helm, b.rigs, b.timeline
        helm = self._assemble(b, link)
        rigs = self._with_pivots(rig_parts(b.parts, helm, b.layers), b.settings.pivots) if b.parts is not None else {}
        timeline = None
        if self.animate and b.parts is not None:
            timeline, _ = build_timeline(rigs, b.settings.animation, suggest=self.suggest)
        return helm, rigs, timeline
