"""Display list runtime: shape and MovieClip instances, timelines with Flash's place/move/remove rules,
rewinds that keep persistent children, and the frame-script effects AQW content uses."""
from dataclasses import dataclass, field, replace
from typing import Callable

from autoswf.model.geometry import ColorTransform, Matrix
from autoswf.render.colors import PlayerColors, player_color_transform
from autoswf.render.scripts import (CallSelf, FrameAction, GotoAndPlay, GotoAndStop, Play, SetColor, Stop,
                                    class_frame_actions)
from autoswf.swf.decode import MorphShapeDef, MovieData, PlaceCommand, RemoveCommand, ShapeDef, SpriteDef

MAX_GOTOS = 8          # per clip and per call of run_pending_actions (guards goto loops)


@dataclass(eq=False)
class DisplayObject:
    movie: MovieData
    char_id: int
    depth: int | None = None            # None = added by script
    name: str | None = None
    matrix: Matrix = Matrix()
    color: ColorTransform | None = None
    ratio: int = 0
    clip_depth: int | None = None
    filters: tuple = ()
    blend: str | None = None
    visible: bool = True
    place_frame: int = 0
    script_transformed: bool = False    # the timeline no longer moves or recolors it (set by mcSetColor)
    color_custom: tuple[str, str] | None = None


@dataclass(eq=False)
class ShapeInstance(DisplayObject):
    shape: ShapeDef | MorphShapeDef | None = None


@dataclass(frozen=True)
class _Slot:
    """What the timeline says about one depth at some frame."""
    char_id: int
    place_frame: int
    matrix: Matrix | None = None
    color: ColorTransform | None = None
    ratio: int | None = None
    name: str | None = None
    clip_depth: int | None = None
    filters: tuple | None = None
    blend: str | None = None
    visible: bool | None = None


def _merge(slot: _Slot, cmd: PlaceCommand) -> _Slot:
    changes = {k: getattr(cmd, k) for k in ("matrix", "color", "ratio", "name", "clip_depth", "filters", "blend", "visible")
               if getattr(cmd, k) is not None}
    return replace(slot, **changes) if changes else slot


def _replay(state: dict[int, _Slot], commands, frame: int) -> None:
    for cmd in commands:
        if isinstance(cmd, RemoveCommand):
            state.pop(cmd.depth, None)
            continue
        old = state.get(cmd.depth)
        if cmd.char_id is not None and (old is None or not cmd.move or old.char_id != cmd.char_id):
            base = old if old is not None and cmd.move else _Slot(cmd.char_id, frame)
            state[cmd.depth] = _merge(replace(base, char_id=cmd.char_id, place_frame=frame), cmd)
        elif old is not None and cmd.move:
            state[cmd.depth] = _merge(old, cmd)


def _apply(obj: DisplayObject, slot: _Slot) -> None:
    if not obj.script_transformed:
        obj.matrix = slot.matrix or Matrix()
        obj.color = slot.color
    obj.ratio = slot.ratio or 0
    obj.name = slot.name
    obj.clip_depth = slot.clip_depth
    obj.filters = slot.filters or ()
    obj.blend = slot.blend
    if slot.visible is not None:
        obj.visible = slot.visible


@dataclass(eq=False)
class ClipInstance(DisplayObject):
    sprite: SpriteDef | None = None
    class_name: str | None = None
    frame: int = 0
    playing: bool = True
    driven: bool = False                # playhead moved from outside: own stop/play/goto actions are ignored
    children: list[DisplayObject] = field(default_factory=list)
    pending: bool = True                # entered a frame whose actions have not run yet

    def child_at_depth(self, depth: int) -> DisplayObject | None:
        return next((c for c in self.children if c.depth == depth), None)

    def child_by_name(self, name: str) -> DisplayObject | None:
        return next((c for c in self.children if c.name == name), None)

    def add_child(self, obj: DisplayObject, index: int | None = None) -> None:
        obj.depth = None
        if index is None:
            self.children.append(obj)
        else:
            self.children.insert(index, obj)

    def remove_child_at(self, index: int) -> DisplayObject:
        return self.children.pop(index)

    def frame_actions(self, frame: int) -> list[FrameAction]:
        if not self.class_name:
            return []
        key = ("frame_actions", self.class_name)
        actions = self.movie.cache.get(key)
        if actions is None:
            actions = self.movie.cache[key] = class_frame_actions(self.movie.abcs, self.class_name)
        return actions.get(frame, [])

    def goto(self, frame: int) -> None:
        frame = max(0, min(frame, self.sprite.frame_count - 1))
        if frame == self.frame and not self.pending:
            return
        if frame == self.frame + 1:
            self._step(frame)
        else:
            self._reconcile(frame)
        self.frame = frame
        self.pending = True

    def goto_label(self, label: str) -> bool:
        frame = self.sprite.labels.get(label)
        if frame is None:
            return False
        self.goto(frame)
        return True

    def timeline_state(self, frame: int) -> dict[int, _Slot]:
        cache = self.sprite._states
        if frame not in cache:
            start = max((k for k in cache if k <= frame), default=-1)
            state = dict(cache[start]) if start >= 0 else {}
            for n in range(start + 1, frame + 1):
                _replay(state, self.sprite.frames[n], n)
            cache[frame] = state
        return cache[frame]

    def _insert(self, obj: DisplayObject, index: int | None = None) -> None:
        if index is None:
            index = next((i for i, c in enumerate(self.children) if c.depth is not None and c.depth > obj.depth),
                         len(self.children))
        self.children.insert(index, obj)

    def _create(self, depth: int, slot: _Slot) -> DisplayObject | None:
        obj = instantiate(self.movie, slot.char_id)
        if obj is not None:
            obj.depth, obj.place_frame = depth, slot.place_frame
            _apply(obj, slot)
        return obj

    def _step(self, frame: int) -> None:
        for cmd in self.sprite.frames[frame]:
            old = self.child_at_depth(cmd.depth)
            if isinstance(cmd, RemoveCommand):
                if old is not None:
                    self.children.remove(old)
                continue
            if cmd.char_id is not None and (old is None or not cmd.move or old.char_id != cmd.char_id):
                base = _Slot(cmd.char_id, frame)
                if old is not None and cmd.move:
                    base = _Slot(cmd.char_id, frame, old.matrix, old.color, old.ratio, old.name, old.clip_depth,
                                 old.filters, old.blend, old.visible)
                index = None
                if old is not None:
                    index = self.children.index(old)
                    self.children.remove(old)
                obj = self._create(cmd.depth, _merge(base, cmd))
                if obj is not None:
                    self._insert(obj, index)
            elif old is not None and cmd.move:
                if cmd.matrix is not None and not old.script_transformed:
                    old.matrix = cmd.matrix
                if cmd.color is not None and not old.script_transformed:
                    old.color = cmd.color
                for key in ("ratio", "name", "clip_depth", "filters", "blend", "visible"):
                    value = getattr(cmd, key)
                    if value is not None:
                        setattr(old, key, value)

    def _reconcile(self, frame: int) -> None:
        state = self.timeline_state(frame)
        old = {c.depth: c for c in self.children if c.depth is not None}
        scripted = [(i, c) for i, c in enumerate(self.children) if c.depth is None]
        children = []
        for depth in sorted(state):
            slot, kept = state[depth], old.get(depth)
            if kept is not None and kept.char_id == slot.char_id and kept.place_frame == slot.place_frame:
                _apply(kept, slot)
                children.append(kept)
            else:
                obj = self._create(depth, slot)
                if obj is not None:
                    children.append(obj)
        for i, c in scripted:
            children.insert(min(i, len(children)), c)
        self.children = children


@dataclass
class ScriptContext:
    colors: PlayerColors | None = None
    on_call: Callable[[ClipInstance, str], None] | None = None
    on_frame: Callable[[ClipInstance, int], None] | None = None     # before a clip's frame actions run


def instantiate(movie: MovieData, char_id: int) -> ShapeInstance | ClipInstance | None:
    char = movie.character(char_id)
    if isinstance(char, (ShapeDef, MorphShapeDef)):
        return ShapeInstance(movie, char_id, shape=char)
    if isinstance(char, SpriteDef):
        clip = ClipInstance(movie, char_id, sprite=char, class_name=movie.class_name(char_id))
        clip._reconcile(0)
        return clip
    return None


def advance(obj: DisplayObject) -> None:
    """One tick of every playhead in the tree (children that exist before the parent moves)."""
    if not isinstance(obj, ClipInstance):
        return
    existing = list(obj.children)
    if obj.playing and not obj.driven and obj.sprite.frame_count > 1:
        nxt = obj.frame + 1
        obj.goto(nxt if nxt < obj.sprite.frame_count else 0)
    alive = {id(c) for c in obj.children}
    for c in existing:
        if id(c) in alive:
            advance(c)


def run_pending_actions(obj: DisplayObject, ctx: ScriptContext) -> None:
    if not isinstance(obj, ClipInstance):
        return
    gotos = 0
    while obj.pending:
        obj.pending = False
        if ctx.on_frame is not None:
            ctx.on_frame(obj, obj.frame)
        for action in obj.frame_actions(obj.frame):
            if action.conditional:
                continue
            if isinstance(action, SetColor):
                obj.color_custom = (action.location, action.shade)
                obj.script_transformed = True
            elif isinstance(action, CallSelf):
                if ctx.on_call is not None:
                    ctx.on_call(obj, action.method)
            elif obj.driven:
                continue
            elif isinstance(action, Stop):
                obj.playing = False
            elif isinstance(action, Play):
                obj.playing = True
            elif isinstance(action, (GotoAndPlay, GotoAndStop)):
                target = obj.sprite.labels.get(action.target) if isinstance(action.target, str) else action.target
                if target is None:
                    continue
                obj.playing = isinstance(action, GotoAndPlay)
                if gotos < MAX_GOTOS and target != obj.frame:
                    gotos += 1
                    obj.goto(target)
    for c in list(obj.children):
        run_pending_actions(c, ctx)


def tick(obj: DisplayObject, ctx: ScriptContext) -> None:
    advance(obj)
    run_pending_actions(obj, ctx)


def effective_color(obj: DisplayObject, colors: PlayerColors | None) -> ColorTransform | None:
    if obj.color_custom is not None and colors is not None:
        return player_color_transform(obj.color_custom[0], obj.color_custom[1], colors)
    return obj.color
