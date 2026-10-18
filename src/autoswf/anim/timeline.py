"""The editable timeline (spec §11): one self-looping clip per animated part, one track per layer it moves, keyframes
that hold or tween (Flash's classic tween), and keys edited by hand kept apart from the ones presets make, so running a
preset again can ask before replacing them. Frames are 0-based here; everything shown to the user is 1-based."""
import math
from dataclasses import dataclass, field, fields, replace

from autoswf.model.geometry import ColorTransform, Matrix, Point


@dataclass(frozen=True)
class Pose:
    x: float = 0.0               # head units, added to the target's rest position
    y: float = 0.0
    rotation: float = 0.0        # degrees, clockwise on screen (Flash's rotation)
    scale_x: float = 1.0
    scale_y: float = 1.0
    alpha: float = 1.0
    brightness: float = 0.0      # -1 (black) .. 1 (white), Flash's Brightness
    bend: float | None = None    # morph ratio 0..1 of a target that bends


REST = Pose()
POSE_FIELDS = tuple(f.name for f in fields(Pose))


@dataclass(frozen=True)
class Key:
    pose: Pose
    tween: bool = False          # interpolate toward the next key; else hold until it
    manual: bool = False         # edited by hand


def _lerp_pose(a: Pose, b: Pose, t: float) -> Pose:
    values = {}
    for name in POSE_FIELDS:
        u, v = getattr(a, name), getattr(b, name)
        values[name] = u if u is None or v is None else u + (v - u) * t
    return Pose(**values)


@dataclass
class Track:
    target: str                  # the layer this track moves ("Lock 3", "Eye L ball")
    keys: dict[int, Key]

    def __post_init__(self) -> None:
        if 0 not in self.keys:
            self.keys[0] = Key(REST)

    def pose(self, frame: int) -> Pose:
        frames = sorted(self.keys)
        start = max(f for f in frames if f <= frame)
        key = self.keys[start]
        later = [f for f in frames if f > start]
        if not key.tween or not later:
            return key.pose
        end = later[0]
        return _lerp_pose(key.pose, self.keys[end].pose, (frame - start) / (end - start))


@dataclass(eq=False)
class Clip:
    part: str
    preset: object | None        # the preset settings that made it (None: made by hand)
    length: int                  # frames in the loop
    tracks: dict[str, Track]
    bends: dict[str, object] = field(default_factory=dict)      # target -> sway.Bend

    def pose(self, target: str, frame: int) -> Pose:
        return self.tracks[target].pose(frame)

    def poses(self, target: str) -> list[Pose]:
        track = self.tracks[target]
        return [track.pose(f) for f in range(self.length)]

    def set_key(self, target: str, frame: int, pose: Pose, tween: bool = False) -> None:
        """A keyframe edited by hand."""
        if target not in self.tracks:
            raise ValueError("'%s' is not animated by '%s'" % (target, self.part))
        if not 0 <= frame < self.length:
            raise ValueError("frame %d is past the end of the %d-frame loop" % (frame + 1, self.length))
        self.tracks[target].keys[frame] = Key(pose, tween, manual=True)

    def manual_keys(self) -> list[tuple[str, int]]:
        return [(target, f) for target, track in self.tracks.items() for f in sorted(track.keys)
                if track.keys[f].manual]


class ManualEditsError(Exception):
    """Replacing a clip would drop keyframes edited by hand (Plan 6 asks the user first)."""

    def __init__(self, part: str, keys: list[tuple[str, int]]):
        self.part, self.keys = part, keys
        n = len(keys)
        super().__init__("'%s' has %d keyframe%s edited by hand; running the preset again replaces %s"
                         % (part, n, "" if n == 1 else "s", "it" if n == 1 else "them"))


@dataclass
class Timeline:
    clips: dict[str, Clip] = field(default_factory=dict)

    def _check(self, part: str, replace_edits: bool) -> None:
        old = self.clips.get(part)
        if old is not None and not replace_edits and old.manual_keys():
            raise ManualEditsError(part, old.manual_keys())

    def put(self, clip: Clip, *, replace_edits: bool = False) -> None:
        self._check(clip.part, replace_edits)
        self.clips[clip.part] = clip

    def remove(self, part: str, *, replace_edits: bool = False) -> None:
        self._check(part, replace_edits)
        self.clips.pop(part, None)


def pose_matrix(rest: Matrix, pose: Pose, origin: Point = Point(0, 0)) -> Matrix:
    """The target's placement matrix for a pose: its rest placement moved by (x, y), turned and scaled about `origin`
    (in the target's own coordinates)."""
    turn = (Matrix.translate(origin.x, origin.y) @ Matrix.rotate(math.radians(pose.rotation))
            @ Matrix.scale(pose.scale_x, pose.scale_y) @ Matrix.translate(-origin.x, -origin.y))
    return (Matrix.translate(rest.tx + pose.x, rest.ty + pose.y) @ turn
            @ Matrix(rest.a, rest.b, rest.c, rest.d))


def pose_color(pose: Pose) -> ColorTransform | None:
    if pose.alpha == 1 and pose.brightness == 0:
        return None
    b = pose.brightness
    m, k = (1 - b, round(255 * b)) if b >= 0 else (1 + b, 0)
    return ColorTransform((m, m, m, pose.alpha), (k, k, k, 0))


def with_fields(pose: Pose, values: dict) -> Pose:
    """The pose with some fields replaced (hand-made keys over a generated pose)."""
    return replace(pose, **values)
