"""Animation settings (spec §11): the suggested presets (eyes blink, locks and back hair sway), the `<drawing>.anim.json`
file that overrides them and holds hand-made keyframes, and the timeline built from both. Frames in the file are
1-based, as in Animate."""
import json
import math
from dataclasses import dataclass, field
from pathlib import Path

from autoswf.anim.presets import (BlinkParams, PulseParams, SwayParams, TwitchParams, blink_clip, blink_frames,
                                  check_preset, parse_params, preset_name, pulse_clip, twitch_clip, TWITCH_AT)
from autoswf.anim.sway import sway_clip, sway_ranks
from autoswf.anim.timeline import POSE_FIELDS, Timeline, with_fields
from autoswf.parts.model import PartName

KEY_FIELDS = POSE_FIELDS + ("tween",)
FIELD_RANGES = {"x": (-500, 500), "y": (-500, 500), "rotation": (-360, 360), "scale_x": (-20, 20),
                "scale_y": (-20, 20), "alpha": (0, 1), "brightness": (-1, 1), "bend": (0, 1)}
FILE_KEYS = ("presets", "parts", "keys")


@dataclass(frozen=True)
class ManualKey:
    part: str
    target: str
    frame: int                   # 1-based
    fields: dict                 # Pose fields this key sets
    tween: bool = False


@dataclass
class AnimationSettings:
    presets: dict[str, dict] = field(default_factory=dict)                  # preset -> its settings for every part
    parts: dict[str, tuple[str | None, dict]] = field(default_factory=dict) # part -> (preset or None, own settings)
    keys: list[ManualKey] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data, source: str = "animation file") -> "AnimationSettings":
        try:
            return cls._from_dict(data)
        except ValueError as e:
            raise ValueError("%s: %s" % (source, e)) from None

    @classmethod
    def _from_dict(cls, data) -> "AnimationSettings":
        if not isinstance(data, dict):
            raise ValueError("the file must hold a JSON object with %s" % ", ".join(FILE_KEYS))
        for key in data:
            if key not in FILE_KEYS:
                raise ValueError("Unknown key '%s'; keys are %s" % (key, ", ".join(FILE_KEYS)))
        out = cls()
        for name, values in _mapping(data.get("presets", {}), "presets").items():
            try:
                canonical = preset_name(name)
                if canonical is None:
                    raise ValueError("'none' has no settings")
                values = dict(_mapping(values, "preset %s" % canonical))
                parse_params(canonical, values)
            except ValueError as e:
                raise ValueError("preset \"%s\": %s" % (name, e)) from None
            out.presets[canonical] = values
        for part, entry in _mapping(data.get("parts", {}), "parts").items():
            try:
                part = PartName.parse(str(part)).name
                if isinstance(entry, dict):
                    values = {k: v for k, v in entry.items() if k != "preset"}
                    if "preset" not in entry:
                        raise ValueError("it needs a \"preset\"")
                    name = preset_name(entry["preset"])
                    if name is None and values:
                        raise ValueError("'none' has no settings")
                else:
                    name, values = preset_name(entry), {}
                if name is not None:
                    parse_params(name, values)
            except ValueError as e:
                raise ValueError("part \"%s\": %s" % (part, e)) from None
            out.parts[part] = (name, values)
        keys = data.get("keys", [])
        if not isinstance(keys, list):
            raise ValueError("\"keys\" must be a list")
        for n, entry in enumerate(keys, start=1):
            try:
                out.keys.append(_manual_key(entry))
            except ValueError as e:
                raise ValueError("entry %d of \"keys\": %s" % (n, e)) from None
        return out

    def to_dict(self) -> dict:
        data = {}
        if self.presets:
            data["presets"] = {name: dict(values) for name, values in self.presets.items()}
        if self.parts:
            data["parts"] = {part: ("none" if name is None else ({"preset": name, **values} if values else name))
                             for part, (name, values) in self.parts.items()}
        if self.keys:
            data["keys"] = [{"part": k.part, "target": k.target, "frame": k.frame, **k.fields,
                             **({"tween": True} if k.tween else {})} for k in self.keys]
        return data

    @classmethod
    def load(cls, path) -> "AnimationSettings":
        path = Path(path)
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as e:
            raise ValueError("Could not read %s: %s" % (path.name, getattr(e, "strerror", None) or e)) from None
        try:
            data = json.loads(text)
        except json.JSONDecodeError as e:
            raise ValueError("%s is not valid JSON (line %d, column %d)" % (path.name, e.lineno, e.colno)) from None
        return cls.from_dict(data, path.name)

    def save(self, path) -> None:
        Path(path).write_text(json.dumps(self.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")


def _mapping(value, what: str) -> dict:
    if not isinstance(value, dict):
        raise ValueError("\"%s\" must be a JSON object" % what)
    return value


def _manual_key(entry) -> ManualKey:
    if not isinstance(entry, dict):
        raise ValueError("a keyframe must be a JSON object")
    part = entry.get("part")
    if not isinstance(part, str) or not part.strip():
        raise ValueError("a keyframe needs its \"part\"")
    part = PartName.parse(part).name
    frame = entry.get("frame")
    if isinstance(frame, bool) or not isinstance(frame, (int, float)) or frame != int(frame) or frame < 1:
        raise ValueError("frame must be a whole number from 1 (got %s)" % json.dumps(frame))
    target = entry.get("target", part)
    values, tween = {}, False
    for key, value in entry.items():
        if key in ("part", "target", "frame"):
            continue
        if key not in KEY_FIELDS:
            raise ValueError("Unknown keyframe field '%s'; fields are %s" % (key, ", ".join(KEY_FIELDS)))
        if key == "tween":
            if not isinstance(value, bool):
                raise ValueError("tween must be true or false (got %s)" % json.dumps(value))
            tween = value
            continue
        low, high = FIELD_RANGES[key]
        if (isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value)
                or not low <= value <= high):
            raise ValueError("%s must be a number from %g to %g (got %s)" % (key, low, high, json.dumps(value)))
        values[key] = float(value)
    return ManualKey(part, str(target), int(frame), values, tween)


def suggest_presets(rigs: dict) -> dict:
    """What the app suggests: Blink for every eye with a ball, Sway for every lock and back-hair part."""
    out = {}
    for name, rig in rigs.items():
        if rig.kind == "eye" and rig.eye is not None:
            out[name] = BlinkParams()
        elif rig.kind in ("lock", "back_hair") and rig.mask is not None:
            out[name] = SwayParams()
    return out


def build_timeline(rigs: dict, settings: AnimationSettings, *, suggest: bool = True) -> tuple[Timeline, list[str]]:
    notes = []
    chosen = {name: spec.name for name, spec in suggest_presets(rigs).items()} if suggest else {}
    own: dict[str, dict] = {}
    for part, (name, values) in settings.parts.items():
        if part not in rigs:
            notes.append("Animation for '%s' skipped: there is no such part" % part)
            continue
        if name is None:
            chosen.pop(part, None)
            continue
        check_preset(name, part, rigs[part].kind)
        chosen[part] = name
        own[part] = values
    specs = {}
    for part in rigs:
        if part in chosen:
            try:
                specs[part] = parse_params(chosen[part], {**settings.presets.get(chosen[part], {}), **own.get(part, {})})
            except ValueError as e:
                raise ValueError("Animation for '%s': %s" % (part, e)) from None
    ranks = sway_ranks(rigs, [p for p, s in specs.items() if isinstance(s, SwayParams)])
    timeline = Timeline()
    for part, spec in specs.items():
        rig = rigs[part]
        if isinstance(spec, BlinkParams):
            clip = blink_clip(rig, spec)
        elif isinstance(spec, SwayParams):
            clip = sway_clip(rig, spec, ranks[part])
        elif isinstance(spec, TwitchParams):
            clip = twitch_clip(rig, spec)
        else:
            clip = pulse_clip(rig, spec)
        timeline.put(clip)
    for key in settings.keys:
        clip = timeline.clips.get(key.part)
        if clip is None:
            notes.append("Keyframe for '%s' skipped: it has no animation" % key.part)
        elif key.target not in clip.tracks:
            notes.append("Keyframe for '%s' in '%s' skipped: '%s' does not move it" % (key.target, key.part, key.part))
        elif key.frame > clip.length:
            notes.append("Keyframe at frame %d of '%s' skipped: its loop has %d frames"
                         % (key.frame, key.part, clip.length))
        else:
            fields = dict(key.fields)
            if "bend" in fields and key.target not in clip.bends:
                notes.append("Keyframe at frame %d of '%s' sets a bend, but '%s' does not bend; the bend is left out"
                             % (key.frame, key.part, key.target))
                del fields["bend"]
            base = clip.pose(key.target, key.frame - 1)
            clip.set_key(key.target, key.frame - 1, with_fields(base, fields), key.tween)
    return timeline, notes


def clip_summary(clip) -> str:
    spec = clip.preset
    if isinstance(spec, BlinkParams):
        starts = [s + 1 for s in blink_frames(spec)[0]]
        detail = "blinks at frame %d" % starts[0] if len(starts) == 1 else "blinks at frames %d and %d" % tuple(starts)
    elif isinstance(spec, SwayParams):
        links = clip.details.get("links", 1)
        detail = "%d link%s" % (links, "" if links == 1 else "s")
    elif isinstance(spec, TwitchParams):
        detail = "twitches at frame %d" % (round(TWITCH_AT * spec.every) + 1)
    else:
        detail = ""
    frames = "%d frames" % clip.length + (", " + detail if detail else "")
    return "%-12s  %-6s  %s" % (clip.part, spec.name if spec is not None else "Custom", frames)
