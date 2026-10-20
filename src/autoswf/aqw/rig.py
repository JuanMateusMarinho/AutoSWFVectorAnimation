"""The AQW avatar, rebuilt the way the client's AvatarMC builds it (hideOptionalParts, loadArmorPieces,
onLoadHelmComplete) and animated by the mcSkel labels the way its frame scripts play them."""
from autoswf.model.geometry import ColorTransform
from autoswf.render.colors import PlayerColors
from autoswf.render.display import ClipInstance, DisplayObject, ScriptContext, advance, instantiate, run_pending_actions
from autoswf.render.scripts import GotoAndPlay, GotoAndStop, Stop
from autoswf.swf.decode import MovieData

BLACK_TINT = ColorTransform((0.0, 0.0, 0.0, 1.0), (0, 0, 0, 0))
ARMOR_SLOTS = {"Chest": ("chest",), "Hip": ("hip",), "FootIdle": ("idlefoot",), "Foot": ("frontfoot", "backfoot"),
               "Shoulder": ("frontshoulder", "backshoulder"), "Hand": ("fronthand", "backhand"),
               "Thigh": ("frontthigh", "backthigh"), "Shin": ("frontshin", "backshin"), "Robe": ("robe",),
               "RobeBack": ("backrobe",)}
OPTIONAL_SLOTS = ("cape", "backhair", "robe", "backrobe", "pvpFlag", "weapon", "weaponOff", "weaponFist",
                  "weaponFistOff", "shield")
MAX_JUMPS = 4


def _new(movie: MovieData | None, class_name: str) -> DisplayObject | None:
    char_id = movie.classes.get(class_name) if movie is not None else None
    return instantiate(movie, char_id) if char_id is not None else None


def _replace_first(slot: ClipInstance, obj: DisplayObject, index: int | None = None) -> None:
    if slot.children:
        slot.remove_child_at(0)
    slot.add_child(obj, index)


class AvatarRig:
    def __init__(self, client: MovieData, gender: str, *, armor: MovieData | None = None, armor_link: str = "",
                 helm: MovieData | None = None, helm_link: str | None = None, colors: PlayerColors | None = None,
                 world: dict | None = None):
        skel_id = client.classes.get("mcSkel")
        if skel_id is None:
            raise ValueError("The AQW client has no mcSkel class")
        self.client, self.gender, self.colors = client, gender, colors
        self.world = dict(world) if world is not None else {"bitWalk": True}     # as in normal play
        self.anim_events: dict[str, list[tuple[str, bool]]] = {}
        self._skeleton_request: str | None = None
        self.animated = None
        self._armor = armor
        self._scripts = None                       # the animated head's running class (HeadScripts)
        self._scripts_clip: ClipInstance | None = None
        self._motion: tuple[int, int] | None = None
        if armor is not None and armor_link:
            from autoswf.items.animated import read_animated_armor
            found = read_animated_armor(armor, gender)
            if found is not None and found.class_name == "%s%sHead" % (armor_link, gender):
                self.animated = found
        self.skel: ClipInstance = instantiate(client, skel_id)
        self.skel.driven = True
        labels = self.skel.sprite.labels
        self.labels = sorted(labels, key=labels.get)
        self.label, self._start, self._end, self._hold = "", 0, 1, False
        for name in OPTIONAL_SLOTS:
            slot = self._slot(name)
            if slot is not None:
                slot.visible = False
        self._load_face(armor, armor_link)
        self._load_armor(armor, armor_link)
        self._load_helm(helm, helm_link)
        self.set_label("Idle" if "Idle" in labels else self.labels[0] if self.labels else "")

    # ------------------------------------------------------------ construction (mirrors the client)

    def _slot(self, name: str) -> ClipInstance | None:
        slot = self.skel.child_by_name(name)
        return slot if isinstance(slot, ClipInstance) else None

    def head(self) -> ClipInstance:
        return self._slot("head")

    def _load_face(self, armor: MovieData | None = None, armor_link: str = "") -> None:
        """The armor's <Link><G>Head when it has one, else the client's mcHead<G> (as the client does)."""
        head = self.head()
        face = _new(armor, "%s%sHead" % (armor_link, self.gender)) if armor is not None and armor_link else None
        if face is None:
            face = _new(self.client, "mcHead" + self.gender)
        if head is None or face is None:
            return
        old = head.child_by_name("face")
        if old is not None:
            head.children.remove(old)
        face.name = "face"
        head.add_child(face, 0)

    def _load_armor(self, armor: MovieData | None, link: str) -> None:
        if armor is None:
            return
        for part, slots in ARMOR_SLOTS.items():
            class_name = "%s%s%s" % (link, self.gender, part)
            if class_name not in armor.classes:
                continue
            for name in slots:
                slot, obj = self._slot(name), _new(armor, class_name)
                if slot is None or obj is None:
                    continue
                _replace_first(slot, obj, 0 if part == "Hand" else None)
                if name == "backhand":
                    obj.color, obj.script_transformed = BLACK_TINT, True
            if part == "Foot" and self._slot("frontfoot") is not None:
                self._slot("frontfoot").visible = False
            if part in ("Robe", "RobeBack") and self._slot(slots[0]) is not None:
                self._slot(slots[0]).visible = True

    def _load_helm(self, helm: MovieData | None, link: str | None) -> None:
        if helm is None or not link:
            return
        if link not in helm.classes:
            raise ValueError("Class '%s' was not found in the helm file" % link)
        helm_item = _new(helm, link)
        if helm_item is None:
            raise ValueError("Class '%s' in the helm file cannot be drawn (it is not a MovieClip or shape)" % link)
        head = self.head()
        helm_slot, hair, back = head.child_by_name("helm"), head.child_by_name("hair"), self._slot("backhair")
        if helm_slot.children:
            helm_slot.remove_child_at(0)
        helm_slot.visible = True
        if hair is not None:
            hair.visible = False
        if back is not None:
            back.visible = False
            back_item = _new(helm, link + "_backhair")
            if back_item is not None:
                _replace_first(back, back_item)
                back.visible = True
        helm_slot.add_child(helm_item)

    # ------------------------------------------------------------ playback

    def set_label(self, label: str) -> None:
        labels = self.skel.sprite.labels
        if label not in labels:
            raise ValueError("Unknown animation label '%s'" % label)
        start = labels[label]
        later = [f for f in labels.values() if f > start]
        self.label, self._start, self._end, self._hold = label, start, min(later, default=self.skel.sprite.frame_count), False
        self._enter(start)
        self._run()

    def tick(self) -> None:
        existing = list(self.skel.children)
        if not self._hold:
            nxt = self.skel.frame + 1
            self._enter(nxt if nxt < self._end else self._start)
        alive = {id(c) for c in self.skel.children}
        for c in existing:
            if id(c) in alive:
                advance(c)
        self._enter_frame()
        self._run()

    def _targets_label(self, action) -> bool:
        return isinstance(action, (GotoAndPlay, GotoAndStop)) and action.target in (self.label, self._start)

    def _enter(self, frame: int) -> None:
        """Jump the skeleton; a goto back to the current label is a loop point (never shown); an unconditional
        stop holds the playhead until the next label."""
        self.skel.goto(frame)
        self.skel.pending = True
        for _ in range(MAX_JUMPS):
            if self.skel.frame != self._start and any(map(self._targets_label, self.skel.frame_actions(self.skel.frame))):
                self.skel.goto(self._start)
                continue
            break
        self._hold = any(isinstance(a, Stop) and not a.conditional for a in self.skel.frame_actions(self.skel.frame))

    def _on_call(self, clip: ClipInstance, method: str) -> None:
        front, idle = self._slot("frontfoot"), self._slot("idlefoot")
        if clip is not self.skel or front is None or idle is None:
            return
        if method == "showIdleFoot":
            front.visible, idle.visible = False, True
        elif method == "showFrontFoot":
            front.visible, idle.visible = True, False

    def _run(self) -> None:
        run_pending_actions(self.skel, ScriptContext(self.colors, self._on_call, self._on_frame))
        if self._skeleton_request is not None:
            label, self._skeleton_request = self._skeleton_request, None
            if label in self.skel.sprite.labels or label in self.anim_events:
                self.play(label)

    # ------------------------------------------------------------ animated armors (spec §15)

    def _armor_head(self) -> ClipInstance | None:
        head = self.head()
        face = head.child_by_name("face") if head is not None else None
        if self.animated is None or not isinstance(face, ClipInstance) or face.movie is not self._armor:
            return None
        return face

    def _on_frame(self, clip: ClipInstance, frame: int) -> None:
        """The animated head's frame scripts (listeners register, the skeleton may be sent to another label); a new
        head is constructed and added to the stage first."""
        if clip is not self._armor_head():
            return
        self._ensure_scripts(clip)
        self._apply(self._scripts.frame(frame), frame_script=True)

    def _ensure_scripts(self, clip: ClipInstance) -> None:
        if self._scripts_clip is clip:
            return
        from autoswf.items.animated import HeadScripts
        self._scripts_clip = clip
        self._scripts = HeadScripts(self.animated.head, _RigHost(self))
        self._apply(self._scripts.construct())
        self._apply(self._scripts.dispatch("addedToStage"))

    def _enter_frame(self) -> None:
        """ENTER_FRAME on the animated head (after the playheads moved): an armor animation played by name loops, then
        the head's own handlers run."""
        head = self._armor_head()
        if head is None:
            return
        if self._motion is not None and not self._motion[0] <= head.frame < self._motion[1]:
            head.goto(self._motion[0])
        self._ensure_scripts(head)
        self._apply(self._scripts.dispatch("enterFrame"))

    def _apply(self, effects: list, frame_script: bool = False) -> None:
        """What the head's code did. A frame script's own goto/stop/play are run by the display list already."""
        from autoswf.items.animated import Anchor, Goto, Listen, PlayClip, SetVisible, SkeletonPlay, StopClip
        head = self._armor_head()
        for e in effects:
            if isinstance(e, Listen):
                entry = (e.handler, e.block)
                if entry not in self.anim_events.setdefault(e.game_label, []):
                    self.anim_events[e.game_label].append(entry)
            elif isinstance(e, SkeletonPlay):
                self._skeleton_request = e.label
            elif isinstance(e, SetVisible):
                obj = self._resolve(e.place)
                if obj is not None:
                    obj.visible = e.visible
            elif isinstance(e, Anchor):
                if head is not None and self.head() is not None:
                    head.matrix, head.script_transformed = self.head().matrix.inverse(), True
            elif frame_script or head is None:
                continue
            elif isinstance(e, Goto):
                self._motion = None
                if isinstance(e.target, str):
                    head.goto_label(e.target)
                else:
                    head.goto(e.target)
                head.playing = e.play
            elif isinstance(e, StopClip):
                head.playing = False
            elif isinstance(e, PlayClip):
                head.playing = True

    def _resolve(self, place: tuple) -> DisplayObject | None:
        """The clip at a place around the animated head (items.animated.locate): the head, its slot, the skeleton,
        then children by name. The avatar above the skeleton is not a clip here."""
        ups, downs = place
        chain = [self._armor_head(), self.head(), self.skel]
        if ups >= len(chain):
            return None
        obj = chain[ups]
        for name in downs:
            obj = obj.child_by_name(name) if isinstance(obj, ClipInstance) else None
        return obj

    def play_motion(self, label: str) -> None:
        """Play one of the animated armor's own animations by name: its head goes there and plays it in a loop (a
        one-frame animation holds), until a game label's handler sends it elsewhere."""
        head = self._armor_head()
        if head is None or label not in head.sprite.labels:
            raise ValueError("Unknown armor animation '%s'" % label)
        labels = head.sprite.labels
        start = labels[label]
        end = min((f for f in labels.values() if f > start), default=head.sprite.frame_count)
        self._motion = (start, end)
        head.goto(start)
        head.playing = end - start > 1
        self._run()

    def play(self, label: str) -> None:
        """The client's mcSkel.gotoAndPlay(label): an armor listener for the label runs first (only the first one) and
        keeps the body from playing it when its flag is set (never for Idle); a label the skeleton does not have
        changes nothing when a listener took it."""
        events = self.anim_events.get(label)
        if events:
            handler, flag = events[0]
            self._call_handler(handler)
            if flag and label != "Idle":
                self._run()
                return
        if label in self.skel.sprite.labels:
            self.set_label(label)
        elif events:
            self._run()
        else:
            raise ValueError("Unknown animation label '%s'" % label)

    def _call_handler(self, handler: str) -> None:
        head = self._armor_head()
        if head is None:
            return
        self._ensure_scripts(head)
        self._apply(self._scripts.call(handler))


class _RigHost:
    """The animated head's surroundings in this rig: the static avatar (items.animated.Host) plus its real clips —
    whether one exists, its frame and visibility."""

    def __init__(self, rig: AvatarRig):
        from autoswf.items.animated import Host
        self.rig, self.static = rig, Host(rig.world)

    def value(self, path: tuple):
        from autoswf.items.animated import SCALARS, locate
        known = self.static.value(path)
        if known is not None or not path or path[-1] not in SCALARS:
            return known
        place = locate(path[:-1])
        obj = self.rig._resolve(place) if place is not None and place[0] < 3 else None
        if obj is None:
            return None
        name = path[-1]
        if name == "visible":
            return ("bool", obj.visible)
        if name == "name":
            return ("str", obj.name or "")
        if isinstance(obj, ClipInstance) and name in ("currentFrame", "totalFrames", "numChildren"):
            return ("int", {"currentFrame": obj.frame + 1, "totalFrames": obj.sprite.frame_count,
                            "numChildren": len(obj.children)}[name])
        return None

    def exists(self, path: tuple):
        from autoswf.items.animated import locate
        place = locate(path)
        if place is None or place[0] >= 3:
            return self.static.exists(path)
        return self.rig._resolve(place) is not None

    def has(self, path: tuple, name: str):
        return self.static.has(path, name)

    def contains(self, path: tuple, other: tuple):
        return self.static.contains(path, other)
