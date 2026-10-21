"""A surgical, lossless edit of an AQW item SWF (Open SWF mode): drop the placements of chosen sub-pieces, optionally
the definitions nothing uses any more, optionally rename the link — every other tag is copied byte for byte."""
import lzma
import struct
import zlib
from dataclasses import dataclass, field
from typing import Iterable

from autoswf.abc.code import u30
from autoswf.aqw.contract import check_link
from autoswf.items.structure import ItemStructure, PieceRef
from autoswf.swf.reader import R, decompress

SPRITE, SYMBOL_CLASS, EXPORT_ASSETS, SCALING_GRID, DO_ABC, DO_ABC_OLD = 39, 76, 56, 78, 82, 72
PLACE_TAGS, REMOVE_TAGS = (4, 26, 70), (5, 28)
PRUNABLE = (2, 22, 32, 83, 46, 84, 39)          # shapes, morph shapes, sprites
BUTTONS = (7, 34)
SHAPE_TAGS = (2, 22, 32, 83)


@dataclass
class EditResult:
    data: bytes
    removed_placements: int = 0
    removed_characters: list[int] = field(default_factory=list)
    renamed: dict[str, str] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)
    replaced_shapes: int = 0


@dataclass
class _Tag:
    code: int
    header: bytes
    body: bytes

    def encode(self) -> bytes:
        return self.header + self.body


def _split(data: bytes, pos: int, end: int) -> list[_Tag]:
    out = []
    while pos < end:
        cl = struct.unpack_from("<H", data, pos)[0]
        code, length, size = cl >> 6, cl & 0x3F, 2
        if length == 0x3F:
            length, size = struct.unpack_from("<I", data, pos + 2)[0], 6
        out.append(_Tag(code, data[pos:pos + size], data[pos + size:pos + size + length]))
        pos += size + length
        if code == 0:
            break
    return out


def _header(code: int, length: int, long: bool) -> bytes:
    if long or length >= 0x3F:
        return struct.pack("<HI", (code << 6) | 0x3F, length)
    return struct.pack("<H", (code << 6) | length)


def _depth(tag: _Tag) -> int | None:
    b = tag.body
    if tag.code in (4, 5, 70):
        return struct.unpack_from("<H", b, 2)[0]
    if tag.code == 26:
        return struct.unpack_from("<H", b, 1)[0]
    if tag.code == 28:
        return struct.unpack_from("<H", b, 0)[0]
    return None


def _char(tag: _Tag) -> int | None:
    """The character a place tag puts on the timeline (None for a move)."""
    b = tag.body
    if tag.code == 4:
        return struct.unpack_from("<H", b, 0)[0]
    if tag.code == 26:
        return struct.unpack_from("<H", b, 3)[0] if b[0] & 0x02 else None
    if tag.code == 70:
        flags, flags2, pos = b[0], b[1], 4
        if flags2 & 0x08 or (flags2 & 0x10 and flags & 0x02):
            pos = b.index(b"\0", pos) + 1
        return struct.unpack_from("<H", b, pos)[0] if flags & 0x02 else None
    return None


def _filter(tags: list[_Tag], depths: set[int]) -> tuple[list[_Tag], dict[int, int]]:
    """The tags without the place/remove tags at `depths`, and how many placements each depth lost."""
    kept, removed = [], {}
    for tag in tags:
        if tag.code in PLACE_TAGS + REMOVE_TAGS and _depth(tag) in depths:
            if tag.code in PLACE_TAGS and _char(tag) is not None:
                removed[_depth(tag)] = removed.get(_depth(tag), 0) + 1
            continue
        kept.append(tag)
    return kept, removed


def _symbols(tag: _Tag) -> list[tuple[int, str]]:
    r = R(tag.body, 0)
    return [(r.u16(), r.string()) for _ in range(r.u16())]


def _symbol_tag(entries: list[tuple[int, str]], long: bool) -> _Tag:
    body = struct.pack("<H", len(entries)) + b"".join(struct.pack("<H", cid) + name.encode("utf-8") + b"\0"
                                                      for cid, name in entries)
    return _Tag(SYMBOL_CLASS, _header(SYMBOL_CLASS, len(body), long), body)


def _read_u30(data: bytes, pos: int) -> tuple[int, int]:
    value = shift = 0
    for _ in range(5):
        b = data[pos]
        pos += 1
        value |= (b & 0x7F) << shift
        if not b & 0x80:
            break
        shift += 7
    return value, pos


def _rename_abc(abc: bytes, rename) -> bytes:
    """The ABC with its string pool rewritten by `rename(str) -> str`; everything after the pool is copied."""
    pos = 4
    for width in ("int", "uint", "double"):
        count, pos = _read_u30(abc, pos)
        for _ in range(max(0, count - 1)):
            if width == "double":
                pos += 8
            else:
                _, pos = _read_u30(abc, pos)
    start = pos
    count, pos = _read_u30(abc, pos)
    strings = []
    for _ in range(max(0, count - 1)):
        length, pos = _read_u30(abc, pos)
        strings.append(abc[pos:pos + length].decode("utf-8", "surrogateescape"))
        pos += length
    pool = bytearray(u30(count))
    for s in strings:
        data = rename(s).encode("utf-8", "surrogateescape")
        pool += u30(len(data)) + data
    return abc[:start] + bytes(pool) + abc[pos:]


def _sprite_children(tag: _Tag) -> set[int]:
    return {c for t in _split(tag.body, 4, len(tag.body)) if t.code in PLACE_TAGS and (c := _char(t)) is not None}


def edit_swf(data: bytes, remove: Iterable[PieceRef] = (), *, prune: bool = True,
             rename: str | None = None, replace_shapes: dict[int, "Shape"] | None = None) -> EditResult:
    """`replace_shapes` (the editor's drawings, char id -> Shape) rewrites those DefineShape tags as DefineShape4 at
    the same place, under the same id."""
    remove = list(dict.fromkeys(remove))
    replace_shapes = dict(replace_shapes or {})
    if not remove and rename is None and not replace_shapes:
        raise ValueError("Nothing to change: no pieces chosen and no new link")
    sig, version, length, body = decompress(bytes(data))
    r = R(body, 0)
    r.rect()
    r.align()
    prefix_end = r.p + 4
    tags = _split(body, prefix_end, len(body))
    result = EditResult(b"")
    if sig == "ZWS":
        result.notes.append("The file was LZMA-compressed (ZWS); it is saved zlib-compressed (CWS).")

    by_sprite: dict[int, set[int]] = {}
    for ref in remove:
        by_sprite.setdefault(ref.sprite, set()).add(ref.depth)
    sprite_ids = {struct.unpack_from("<H", t.body, 0)[0] for t in tags if t.code == SPRITE}
    for sprite in by_sprite:
        if sprite != 0 and sprite not in sprite_ids:
            raise ValueError("Piece %d/%d is not in the file" % (sprite, min(by_sprite[sprite])))
    removed: dict[int, dict[int, int]] = {}
    out: list[_Tag] = []
    root_depths = by_sprite.get(0, set())
    if root_depths:
        tags, removed[0] = _filter(tags, root_depths)
    for tag in tags:
        if tag.code == SPRITE and struct.unpack_from("<H", tag.body, 0)[0] in by_sprite:
            sprite = struct.unpack_from("<H", tag.body, 0)[0]
            inner, removed[sprite] = _filter(_split(tag.body, 4, len(tag.body)), by_sprite[sprite])
            new_body = tag.body[:4] + b"".join(t.encode() for t in inner)
            tag = _Tag(SPRITE, _header(SPRITE, len(new_body), len(tag.header) == 6), new_body)
        out.append(tag)
    for ref in remove:
        if not removed.get(ref.sprite, {}).get(ref.depth):
            raise ValueError("Piece %d/%d is not in the file" % (ref.sprite, ref.depth))
    result.removed_placements = sum(sum(v.values()) for v in removed.values())
    if replace_shapes:
        out = _replace_shapes(out, replace_shapes)
        result.replaced_shapes = len(replace_shapes)

    if prune and remove:
        if any(t.code in BUTTONS for t in out):
            result.notes.append("Unused shapes were kept: the file has buttons")
        else:
            out, result.removed_characters = _prune(out)
    if rename is not None:
        out, result.renamed = _rename(out, rename, data)
    new_body = body[:prefix_end] + b"".join(t.encode() for t in out)
    header_length = struct.pack("<I", 8 + len(new_body))
    if sig == "FWS":
        result.data = b"FWS" + bytes([version]) + header_length + new_body
    else:
        result.data = b"CWS" + bytes([version]) + header_length + zlib.compress(new_body, 9)
    return result


def _replace_shapes(tags: list[_Tag], shapes: dict) -> list[_Tag]:
    from autoswf.swf.shape_encoder import encode_define_shape4
    out, done = [], set()
    for tag in tags:
        if tag.code in SHAPE_TAGS:
            cid = struct.unpack_from("<H", tag.body, 0)[0]
            if cid in shapes:
                body = encode_define_shape4(shapes[cid], cid)
                tag = _Tag(83, _header(83, len(body), True), body)
                done.add(cid)
        out.append(tag)
    missing = sorted(set(shapes) - done)
    if missing:
        raise ValueError("Shape %d is not in the file" % missing[0])
    return out


def _prune(tags: list[_Tag]) -> tuple[list[_Tag], list[int]]:
    defined = {struct.unpack_from("<H", t.body, 0)[0]: t for t in tags if t.code in PRUNABLE}
    roots = set()
    for t in tags:
        if t.code == SYMBOL_CLASS:
            roots |= {cid for cid, name in _symbols(t) if "." not in name}
        elif t.code == EXPORT_ASSETS:
            roots |= {cid for cid, _ in _symbols(t)}
        elif t.code in PLACE_TAGS and (c := _char(t)) is not None:
            roots.add(c)
    reachable, todo = set(), list(roots)
    while todo:
        cid = todo.pop()
        if cid in reachable:
            continue
        reachable.add(cid)
        tag = defined.get(cid)
        if tag is not None and tag.code == SPRITE:
            todo += list(_sprite_children(tag))
    dropped = sorted(cid for cid in defined if cid not in reachable)
    if not dropped:
        return tags, []
    gone = set(dropped)
    out = []
    for t in tags:
        if t.code in PRUNABLE and struct.unpack_from("<H", t.body, 0)[0] in gone:
            continue
        if t.code == SCALING_GRID and struct.unpack_from("<H", t.body, 0)[0] in gone:
            continue
        if t.code == SYMBOL_CLASS:
            entries = _symbols(t)
            kept = [(cid, name) for cid, name in entries if cid not in gone]
            if len(kept) != len(entries):
                t = _symbol_tag(kept, len(t.header) == 6)
        out.append(t)
    return out, dropped


def _rename(tags: list[_Tag], new_text: str, original: bytes) -> tuple[list[_Tag], dict[str, str]]:
    from autoswf.items.structure import read_structure
    from autoswf.swf.decode import MovieData
    check = check_link(new_text)
    if check.error:
        raise ValueError(check.error)
    new = check.link
    old = read_structure(MovieData(original)).link
    if old is None:
        raise ValueError("This file has no link to rename")
    if new == old:
        raise ValueError("The new link is the same as the old one")
    renamed: dict[str, str] = {}
    out = []
    for t in tags:
        if t.code == SYMBOL_CLASS:
            entries = []
            for cid, name in _symbols(t):
                if name.startswith(old):
                    renamed[name] = new + name[len(old):]
                entries.append((cid, renamed.get(name, name)))
            t = _symbol_tag(entries, len(t.header) == 6)
        out.append(t)
    exact = {k: v for k, v in renamed.items() if "." not in k}
    fla_old, fla_new = old + "_fla", new + "_fla"

    def rename(s: str) -> str:
        if s in exact:
            return exact[s]
        if s == fla_old:
            return fla_new
        if s.startswith(fla_old + ":") or s.startswith(fla_old + "."):
            return fla_new + s[len(fla_old):]
        return s
    final = []
    for t in out:
        if t.code == DO_ABC:
            name_end = t.body.index(b"\0", 4) + 1
            body = t.body[:name_end] + _rename_abc(t.body[name_end:], rename)
            t = _Tag(DO_ABC, _header(DO_ABC, len(body), len(t.header) == 6), body)
        elif t.code == DO_ABC_OLD:
            body = _rename_abc(t.body, rename)
            t = _Tag(DO_ABC_OLD, _header(DO_ABC_OLD, len(body), len(t.header) == 6), body)
        final.append(t)
    return final, renamed


def parse_piece_path(structure: ItemStructure, path: str) -> PieceRef:
    """A piece's path as `edit-swf --list` prints it ("MChest/39"), with the full class name instead of the key
    ("KindOfBraveMChest/39"), or, in a one-gender file, the part's name ("Chest/39")."""
    first, sep, rest = path.strip().strip("/").partition("/")
    keys = {p.key for p in structure.parts}
    if first not in keys:
        by_class = {p.class_name: p.key for p in structure.parts if p.class_name}
        if first in by_class:
            first = by_class[first]
        elif len(structure.genders) == 1 and structure.genders[0] + first in keys:
            first = structure.genders[0] + first
    try:
        return structure.piece(first + sep + rest).ref
    except KeyError:
        raise ValueError("No piece '%s' in this file; run edit-swf FILE --list to see the pieces" % path) from None
