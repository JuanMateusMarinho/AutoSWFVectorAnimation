"""Everything the user changed in an opened item SWF (Plan 7): removed pieces, edited drawings, new layers and AQW
color changes — the unit of undo in the Open SWF workspace, applied to the original file in one surgical edit."""
from dataclasses import dataclass, field

from autoswf.items.layers import NewLayer
from autoswf.items.structure import PieceRef
from autoswf.model.shape import Shape


@dataclass
class ItemEdits:
    removed: list[PieceRef] = field(default_factory=list)
    shapes: dict[int, Shape] = field(default_factory=dict)
    layers: list[NewLayer] = field(default_factory=list)
    rebinds: dict[str, tuple[str, str]] = field(default_factory=dict)

    def copy(self) -> "ItemEdits":
        return ItemEdits(list(self.removed), dict(self.shapes), list(self.layers), dict(self.rebinds))

    @property
    def empty(self) -> bool:
        return not (self.removed or self.shapes or self.layers or self.rebinds)

    def structure_key(self) -> tuple:
        """What changes the file's structure (a full rewrite), as opposed to drawings only."""
        return (tuple(sorted(self.removed, key=lambda r: (r.sprite, r.depth))), tuple(id(l) for l in self.layers),
                tuple(sorted(self.rebinds.items())))

    def apply(self, original: bytes, *, prune: bool = False, rename: str | None = None) -> bytes:
        if self.empty and rename is None:
            return original
        from autoswf.items.edit import edit_swf
        return edit_swf(original, sorted(self.removed, key=lambda r: (r.sprite, r.depth)), prune=prune, rename=rename,
                        replace_shapes=self.shapes, add_layers=self.layers, rebind=self.rebinds).data
