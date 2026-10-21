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

    def to_dict(self) -> dict:
        from autoswf.project.edits import shape_to_json
        return {"removed": [[r.sprite, r.depth] for r in self.removed],
                "shapes": {str(cid): shape_to_json(s) for cid, s in self.shapes.items()},
                "layers": [{"part": l.part_char, "name": l.name,
                            "tones": [{"shape": shape_to_json(s), "color": list(b) if b else None} for s, b in l.tones]}
                           for l in self.layers],
                "rebinds": {name: list(b) for name, b in self.rebinds.items()}}

    @classmethod
    def from_dict(cls, data) -> "ItemEdits":
        from autoswf.project.edits import shape_from_json
        if not isinstance(data, dict):
            raise ValueError("edits must be a JSON object")
        try:
            return cls([PieceRef(int(s), int(d)) for s, d in data.get("removed", [])],
                       {int(cid): shape_from_json(s) for cid, s in data.get("shapes", {}).items()},
                       [NewLayer(int(l["part"]), str(l["name"]),
                                 [(shape_from_json(t["shape"]), tuple(t["color"]) if t.get("color") else None)
                                  for t in l.get("tones", [])]) for l in data.get("layers", [])],
                       {str(name): tuple(b) for name, b in data.get("rebinds", {}).items()})
        except (KeyError, TypeError, ValueError, IndexError) as e:
            raise ValueError("the edits are incomplete (%s)" % e) from None

    def apply(self, original: bytes, *, prune: bool = False, rename: str | None = None) -> bytes:
        if self.empty and rename is None:
            return original
        from autoswf.items.edit import edit_swf
        return edit_swf(original, sorted(self.removed, key=lambda r: (r.sprite, r.depth)), prune=prune, rename=rename,
                        replace_shapes=self.shapes, add_layers=self.layers, rebind=self.rebinds).data
