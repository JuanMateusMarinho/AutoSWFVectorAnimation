"""Click-to-fix (spec §9.2: every mistake fixable in at most two actions): the parts a clicked region can be given,
in the menu's order, and the region under a click."""
from dataclasses import dataclass

import numpy as np

from autoswf.parts.model import EYE_PIECES, KIND_NAMES


@dataclass(frozen=True)
class Choice:
    label: str
    part: str
    piece: str | None = None
    group: str | None = None        # the submenu it sits in ("Eye L", "Lock", "Accessory")


def new_part_name(parts, kind: str) -> str:
    """The next free numbered part: "Lock 7", "Accessory 2"."""
    numbers = [p.index for p in parts.parts.values() if p.kind == kind and p.index is not None]
    return "%s %d" % (KIND_NAMES[kind], max(numbers, default=0) + 1)


def part_choices(parts) -> list[Choice]:
    out = [Choice("Face", "Face"), Choice("Ear L", "Ear L"), Choice("Ear R", "Ear R"), Choice("Nose", "Nose"),
           Choice("Mouth", "Mouth"), Choice("Brow L", "Brow L"), Choice("Brow R", "Brow R")]
    for eye in ("Eye L", "Eye R"):
        out += [Choice(piece.capitalize(), eye, piece, eye) for piece in EYE_PIECES]
    out.append(Choice("Hair", "Hair"))
    locks = sorted((p for p in parts.parts.values() if p.kind == "lock"), key=lambda p: p.index or 0)
    out += [Choice(p.name, p.name, None, "Lock") for p in locks]
    out.append(Choice("New lock", new_part_name(parts, "lock"), None, "Lock"))
    out += [Choice("Back hair", "Back hair"), Choice("Horn L", "Horn L"), Choice("Horn R", "Horn R"),
            Choice("Helm", "Helm")]
    accessories = sorted((p for p in parts.parts.values() if p.kind == "accessory"), key=lambda p: p.index or 0)
    out += [Choice(p.name, p.name, None, "Accessory") for p in accessories]
    out.append(Choice("New accessory", new_part_name(parts, "accessory"), None, "Accessory"))
    return out


def region_mask(parts, x: float, y: float) -> tuple[int, np.ndarray] | None:
    """The region under a drawing pixel and its drawing-sized mask, or None outside every region."""
    region = parts.region_at(x, y)
    if region is None:
        return None
    return region.id, parts.graph.canvas_mask(region.id)
