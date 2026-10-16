"""Color transform math and AQW color custom, exactly as the client's AvatarMC.changeColor (spec §4.3)."""
import dataclasses
from dataclasses import dataclass

from autoswf.model.geometry import ColorTransform

RGBA = tuple[int, int, int, int]
LOCATION_FIELDS = {"Skin": "skin", "Hair": "hair", "Eye": "eye", "Base": "base", "Trim": "trim", "Accessory": "accessory"}


def concat(outer: ColorTransform, inner: ColorTransform) -> ColorTransform:
    """The transform of `inner` followed by `outer` (runtime adds may be floats outside ±255)."""
    mult = tuple(o * i for o, i in zip(outer.mult, inner.mult))
    add = tuple(oa + om * ia for oa, om, ia in zip(outer.add, outer.mult, inner.add))
    return ColorTransform(mult, add)


def apply(ct: ColorTransform, rgba: RGBA) -> RGBA:
    return tuple(max(0, min(255, round(c * m + a))) for c, m, a in zip(rgba, ct.mult, ct.add))


@dataclass(frozen=True)
class PlayerColors:
    """The player's custom colors, 0xRRGGBB (defaults are AutoSWF's choice)."""
    skin: int = 0xF2C9A0
    hair: int = 0x6B4423
    eye: int = 0x2F7FD1
    base: int = 0x3F5A8C
    trim: int = 0xC9A445
    accessory: int = 0x8C2F39

    def get(self, location: str) -> int:
        """Unknown locations give black, as the client's Number(undefined) does."""
        field_name = LOCATION_FIELDS.get(location)
        return getattr(self, field_name) if field_name else 0

    def replace(self, location: str, rgb: int) -> "PlayerColors":
        if location not in LOCATION_FIELDS:
            raise ValueError("Unknown color location '%s'" % location)
        return dataclasses.replace(self, **{LOCATION_FIELDS[location]: rgb})


def player_color_transform(location: str, shade: str, colors: PlayerColors) -> ColorTransform:
    rgb = colors.get(location)
    shade = shade.upper()
    if shade == "LIGHT":
        offsets = (100, 100, 100)
    elif shade == "DARK":
        offsets = (-25 if location == "Skin" else -50, -50, -50)
    elif shade == "DARKER":
        offsets = (-125, -125, -125)
    else:
        offsets = (0, 0, 0)
    r, g, b = (rgb >> 16) & 255, (rgb >> 8) & 255, rgb & 255
    return ColorTransform((0.0, 0.0, 0.0, 1.0), (r + offsets[0], g + offsets[1], b + offsets[2], 0))
