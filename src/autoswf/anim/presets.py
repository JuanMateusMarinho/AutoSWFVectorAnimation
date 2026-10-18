"""Animation presets (spec §11) and their settings: Blink reproduces the official AQW eye clip frame for frame, Twitch
turns a part quickly and lets it settle, Pulse loops its brightness and alpha. Sway lives in `sway`."""
import math
from dataclasses import dataclass, fields
from typing import ClassVar, Mapping

from autoswf.anim.timeline import REST, Clip, Key, Pose, Track
from autoswf.parts.model import KINDS


@dataclass(frozen=True)
class BlinkParams:
    name: ClassVar[str] = "Blink"
    interval: int = 87           # loop length (frames)
    speed: float = 1.0           # 1 = the official 6-frame blink
    double: bool = False         # blink again 2 frames after the first ends


@dataclass(frozen=True)
class SwayParams:
    name: ClassVar[str] = "Sway"
    stiffness: float = 0.5       # 0 floppy (the tip lags far behind) .. 1 stiff
    amplitude: float = 12.0      # degrees: the tip link's largest angle
    wind: float = 0.3            # gusts at twice the loop's frequency, stronger toward the tip
    delay: int = 4               # frames between neighbouring swaying parts
    length: int = 48             # loop length (frames)


@dataclass(frozen=True)
class TwitchParams:
    name: ClassVar[str] = "Twitch"
    angle: float = 10.0          # degrees of the quick turn
    every: int = 72              # loop length (frames)
    settle: int = 12             # frames it takes to come back to rest


@dataclass(frozen=True)
class PulseParams:
    name: ClassVar[str] = "Pulse"
    length: int = 48             # loop length (frames)
    brightness: float = 0.35     # brightness at the peak (-1..1)
    alpha: float = 1.0           # alpha at the peak


PresetSpec = BlinkParams | SwayParams | TwitchParams | PulseParams
PRESETS = {"Blink": BlinkParams, "Sway": SwayParams, "Twitch": TwitchParams, "Pulse": PulseParams}
RANGES = {("Blink", "interval"): (16, 480), ("Blink", "speed"): (0.5, 2), ("Sway", "stiffness"): (0, 1),
          ("Sway", "amplitude"): (0, 45), ("Sway", "wind"): (0, 1), ("Sway", "delay"): (0, 48),
          ("Sway", "length"): (12, 240), ("Twitch", "angle"): (-45, 45), ("Twitch", "every"): (24, 480),
          ("Twitch", "settle"): (4, 48), ("Pulse", "length"): (12, 240), ("Pulse", "brightness"): (-1, 1),
          ("Pulse", "alpha"): (0, 1)}
MOVES = {"Blink": {"eye"}, "Sway": {"lock", "ear", "accessory", "back_hair"}, "Twitch": {"lock", "ear", "accessory"},
         "Pulse": set(KINDS)}
TRUE, FALSE = {"on", "true", "yes", "1"}, {"off", "false", "no", "0"}

# The official eye clip (client mcHeadM/mcHeadF, the user's reference morph), 0-based frames 10..15: ball alpha, ball
# scale x and y, then the default head's lid offset from rest (it closes OFFICIAL_DROP units).
OFFICIAL_BLINK = ((0.0, 1.0, 1.0, -0.2, 7.2),
                  (0.0, 1.0, 1.0, 1.15, 6.65),
                  (1.0, 1.236114501953125, 0.6431884765625, 2.45, 6.1),
                  (1.0, 1.10491943359375, 0.841400146484375, 1.1, 2.7),
                  (1.0, 1.0261993408203125, 0.9603424072265625, 0.25, 0.7),
                  (1.0, 1.0, 1.0, 0.0, 0.0))
OFFICIAL_DROP = 7.2
FAR_EYE_SCALE = -0.553           # the client places the far eye's clip mirrored and narrowed (mcHeadM: x-scale -0.553)
BLINK_START = 10
TWITCH_AT = 0.4                  # the twitch starts 40 % into its loop


def preset_name(text: str) -> str | None:
    """"sway" -> "Sway", "none" -> None."""
    t = str(text).strip().casefold()
    if t == "none":
        return None
    for name in PRESETS:
        if name.casefold() == t:
            return name
    raise ValueError("Unknown preset '%s'; presets are Blink, Sway, Twitch, Pulse or none" % str(text).strip())


def _value(name: str, key: str, kind: type, raw: object):
    if kind is bool:
        word = str(raw).strip().casefold() if not isinstance(raw, bool) else ("on" if raw else "off")
        if word in TRUE or word in FALSE:
            return word in TRUE
        raise ValueError("%s %s must be on or off (got '%s')" % (name, key, raw))
    low, high = RANGES[(name, key)]
    whole = kind is int
    try:
        if isinstance(raw, bool):
            raise ValueError
        number = float(raw)
        if not math.isfinite(number) or not low <= number <= high or (whole and number != int(number)):
            raise ValueError
    except (TypeError, ValueError):
        raise ValueError("%s %s must be %s from %g to %g (got '%s')"
                         % (name, key, "a whole number" if whole else "a number", low, high, raw)) from None
    return int(number) if whole else number


def parse_params(name: str, values: Mapping[str, object]) -> PresetSpec:
    """A preset's settings from user values (strings from the command line or JSON values), checked."""
    canonical = preset_name(name)
    if canonical is None:
        raise ValueError("'none' has no settings")
    cls = PRESETS[canonical]
    kinds = {f.name: f.type for f in fields(cls)}
    out = {}
    for key, raw in values.items():
        if key not in kinds:
            raise ValueError("Unknown %s setting '%s'; %s settings: %s" % (canonical, key, canonical, ", ".join(kinds)))
        kind = {"int": int, "float": float, "bool": bool}.get(kinds[key], kinds[key])
        out[key] = _value(canonical, key, kind, raw)
    spec = cls(**out)
    _check_loop(spec)
    return spec


def _check_loop(spec) -> None:
    """Blink and Twitch must fit in their loops."""
    if isinstance(spec, BlinkParams):
        starts, n = blink_frames(spec)
        need, got = starts[-1] + n, spec.interval
    elif isinstance(spec, TwitchParams):
        need, got = round(TWITCH_AT * spec.every) + 2 + spec.settle, spec.every
    else:
        return
    if got < need:
        raise ValueError("%s needs a loop of at least %d frames with these settings (got %d)" % (spec.name, need, got))


def check_preset(name: str, part: str, kind: str) -> None:
    """A preset may only move parts that have their hidden areas filled (spec §9.3)."""
    if kind in MOVES[name]:
        return
    if name == "Blink":
        raise ValueError("Blink works on eyes ('%s' is not an eye)" % part)
    kinds = {"Sway": "locks, ears, accessories and back hair", "Twitch": "locks, ears and accessories"}[name]
    raise ValueError("%s moves the part, and only %s have their hidden areas filled ('%s' is not one of them)"
                     % (name, kinds, part))


def _blink_step(x: float) -> tuple:
    k = int(math.floor(x))
    t = x - k
    if t == 0 or k >= len(OFFICIAL_BLINK) - 1:
        return OFFICIAL_BLINK[min(k, len(OFFICIAL_BLINK) - 1)]
    a, b = OFFICIAL_BLINK[k], OFFICIAL_BLINK[k + 1]
    return tuple(u + (v - u) * t for u, v in zip(a, b))


def blink_frames(params: BlinkParams) -> tuple[list[int], int]:
    """First frames of each blink and the frames one blink takes."""
    n = max(4, round(5 / params.speed) + 1)
    return ([BLINK_START] + ([BLINK_START + n + 2] if params.double else [])), n


def blink_clip(rig, params: BlinkParams) -> object:
    if rig.eye is None:
        raise ValueError("'%s' has no eye ball to blink" % rig.name)
    _check_loop(params)
    starts, n = blink_frames(params)
    ratio = rig.eye.drop / OFFICIAL_DROP
    mirror = FAR_EYE_SCALE if rig.eye.far else 1.0
    ball, lid = {}, {}
    for start in starts:
        for i in range(n):
            alpha, sx, sy, dx, dy = _blink_step(i * 5 / (n - 1))
            ball[start + i] = Key(Pose(scale_x=sx, scale_y=sy, alpha=alpha))
            lid[start + i] = Key(Pose(x=dx * ratio * mirror, y=dy * ratio))
    tracks = {rig.eye.ball: Track(rig.eye.ball, ball)}
    if rig.eye.lid:
        tracks[rig.eye.lid] = Track(rig.eye.lid, lid)
    if rig.eye.lash:                               # AQW keeps the lower lines in the ball and iris clips:
        tracks[rig.eye.lash] = Track(rig.eye.lash, dict(ball))      # they hide and squash with the ball
    return Clip(rig.name, params, params.interval, tracks)


def twitch_clip(rig, params: TwitchParams) -> object:
    _check_loop(params)
    start = round(TWITCH_AT * params.every)
    keys = {start: Key(Pose(rotation=0.6 * params.angle)), start + 1: Key(Pose(rotation=params.angle))}
    for k in range(1, params.settle + 1):
        tau = k / params.settle
        angle = params.angle * (1 - tau) ** 2 * math.cos(3 * math.pi * tau)
        keys[start + 1 + k] = Key(Pose(rotation=angle) if k < params.settle else REST)
    return Clip(rig.name, params, params.every, {layer: Track(layer, dict(keys)) for layer in rig.layers})


def pulse_clip(rig, params: PulseParams) -> object:
    keys = {}
    for f in range(params.length):
        s = (1 - math.cos(2 * math.pi * f / params.length)) / 2
        keys[f] = Key(Pose(alpha=1 - (1 - params.alpha) * s, brightness=params.brightness * s))
    targets = [rig.eye.ball] if rig.eye is not None else rig.layers
    return Clip(rig.name, params, params.length, {t: Track(t, dict(keys)) for t in targets})
