"""Symbols (MovieClips) with timelines, AQW color-custom marks and frame scripts."""
from dataclasses import dataclass, field

from autoswf.model.geometry import ColorTransform, Matrix
from autoswf.model.shape import Shape


@dataclass(frozen=True)
class ColorCustom:
    location: str        # Skin, Hair, Eye, Base, Trim, Accessory
    shade: str           # None, Light, Dark, Darker


@dataclass(frozen=True)
class SetColorScript:
    location: str
    shade: str


@dataclass(frozen=True)
class StopScript:
    pass


@dataclass(frozen=True)
class GotoAndPlayScript:
    label: str


FrameScript = SetColorScript | StopScript | GotoAndPlayScript


@dataclass
class Placement:
    item: "Shape | Symbol"
    depth: int
    matrix: Matrix = Matrix()
    color: ColorTransform | None = None
    name: str | None = None


@dataclass
class Frame:
    placements: list[Placement] = field(default_factory=list)
    label: str | None = None


@dataclass(eq=False)
class Symbol:
    name: str
    frames: list[Frame]
    color_custom: ColorCustom | None = None
    scripts: dict[int, FrameScript] = field(default_factory=dict)   # 0-based frame index -> script
