"""Check an exported helm SWF against the AQW contract (spec §4, §13), and an edited AQW item (Open SWF) against
what AQW needs from any item: its classes, valid character references and color scripts in a form AQW runs."""
import struct
import zlib
from dataclasses import dataclass, field
from typing import Collection

from autoswf.abc.disasm import disassemble
from autoswf.abc.movieclip_classes import SETCOLOR_FORMS, expected_setcolor_ops
from autoswf.abc.reader import ABC
from autoswf.aqw.contract import BITMAP_TAGS, FPS, LOCATIONS, SHADES
from autoswf.swf.reader import SWF, TAG_NAMES

MOVED_COLORABLE = ("Colorable clip '%s' is moved or recolored by its parent's timeline; AQW ignores that once "
                   "mcSetColor runs, so animate its wrapper instead.")


def _setcolor_problem(a: ABC, class_name: str, method: int) -> str | None:
    ops = [(i.op, i.args) for i in disassemble(a, a.bodies[method])]
    if ("callpropvoid", ("mcSetColor", "3")) not in ops:
        return None
    pushed = [args[0][1:-1] for op, args in ops if op == "pushstring"]
    raw = [(i.op, i.args) for i in disassemble(a, a.bodies[method], raw=True)]
    if (len(pushed) == 2 and pushed[0] in LOCATIONS and pushed[1] in SHADES
            and raw == expected_setcolor_ops(class_name, pushed[0], pushed[1], raw=True)):
        return None
    return "Color-custom script in '%s' is not in the format AQW expects." % class_name


def setcolor_form(a: ABC, method: int, class_name: str) -> tuple[str, str, str] | None:
    """(form, location, shade) when the method is an mcSetColor frame script in one of AQW's official forms
    (SETCOLOR_FORMS); None when it calls mcSetColor any other way (or does not call it)."""
    instrs = disassemble(a, a.bodies[method])
    ops = [(i.op, i.args) for i in instrs]
    if ("callpropvoid", ("mcSetColor", "3")) not in ops:
        return None
    pushed = [args[0][1:-1] for op, args in ops if op == "pushstring"]
    if len(pushed) != 2 or pushed[0] not in LOCATIONS or pushed[1] not in SHADES:
        return None
    location, shade = pushed
    raw = [(i.op, i.args) for i in disassemble(a, a.bodies[method], raw=True)]
    if raw == expected_setcolor_ops(class_name, location, shade, raw=True):
        return "plain", location, shade
    jumps = [i for i in instrs if i.op == "jump"]
    normalized = [(op, ("->end",) if op == "jump" else args) for op, args in ops]
    for form in SETCOLOR_FORMS[1:]:
        if (normalized == expected_setcolor_ops(class_name, location, shade, form=form) and len(jumps) == 1
                and jumps[0].args[0] == "->%d" % instrs[-1].offset):
            return form, location, shade
    return None


def _moved_colorable_clips(data: bytes) -> list[str]:
    """Colorable clips (a class whose first frame calls mcSetColor) that a timeline moves or recolors after placing
    them: the client marks them script-transformed, so those changes never show in the game."""
    from autoswf.render.scripts import SetColor, class_frame_actions
    from autoswf.swf.decode import MovieData, PlaceCommand, RemoveCommand, SpriteDef
    movie = MovieData(data)
    colorable = {cid: name for name, cid in movie.classes.items()
                 if any(isinstance(a, SetColor) for a in class_frame_actions(movie.abcs, name).get(0, []))}
    if not colorable:
        return []
    moved = []
    for cid in [0] + movie.character_ids():
        sprite = movie.character(cid)
        if not isinstance(sprite, SpriteDef):
            continue
        at_depth: dict[int, int] = {}
        for commands in sprite.frames:
            for cmd in commands:
                if isinstance(cmd, RemoveCommand):
                    at_depth.pop(cmd.depth, None)
                elif isinstance(cmd, PlaceCommand):
                    current = at_depth.get(cmd.depth)
                    if cmd.move and current is not None and cmd.char_id in (None, current):
                        if current in colorable and (cmd.matrix is not None or cmd.color is not None):
                            if colorable[current] not in moved:
                                moved.append(colorable[current])
                    elif cmd.char_id is not None:
                        at_depth[cmd.depth] = cmd.char_id
    return [MOVED_COLORABLE % name for name in moved]


def validate_helm_swf(data: bytes, link: str) -> list[str]:
    problems = []
    swf = SWF(data)
    exported = set(swf.symbols.values())
    if link not in exported:
        problems.append("Class '%s' is missing; AQW loads the helm by this name." % link)

    defined = {}
    for _, block in swf.abcs:
        a = ABC(block)
        for inst in a.instances:
            defined[a.mname(inst["name"])] = (a, inst)
    for name in sorted(exported):
        if name not in defined:
            problems.append("Class '%s' has no ActionScript definition." % name)
            continue
        a, inst = defined[name]
        if a.mname(inst["super"]) != "flash.display.MovieClip" or inst["flags"] != 0x08:
            problems.append("Class '%s' must be a dynamic subclass of flash.display.MovieClip." % name)
    for name, (a, inst) in sorted(defined.items()):
        for t in inst["traits"]:
            if "method" in t:
                problem = _setcolor_problem(a, name, t["method"])
                if problem:
                    problems.append(problem)

    if any(swf.tagcount.get(TAG_NAMES[code]) for code in BITMAP_TAGS):
        problems.append("The file contains bitmap images; AQW items must be pure vector.")
    problems += _moved_colorable_clips(data)
    if swf.fps != FPS:
        problems.append("Frame rate is %g fps; AQW items use 24 fps." % swf.fps)
    return problems


@dataclass
class ItemReport:
    problems: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.problems


def _item_findings(data: bytes, expected_classes: Collection[str]) -> tuple[list[str], list[str]]:
    from autoswf.swf.decode import MovieData, PlaceCommand, SpriteDef
    try:
        movie = MovieData(data)              # checks the file and names the reason
        swf = SWF(data)
    except (ValueError, IndexError, KeyError, struct.error, zlib.error, EOFError) as e:
        return ["The file is not a valid SWF: %s" % e], []
    problems, notes = [], []
    exported = set(swf.symbols.values())
    for name in expected_classes:
        if name not in exported:
            problems.append("Class '%s' is missing; AQW loads this part by this name." % name)
    defined = set(swf.chars)
    for cid, name in sorted(swf.symbols.items(), key=lambda kv: kv[1]):
        if cid != 0 and cid not in defined:
            problems.append("Class '%s' points to character %d, which is not in the file." % (name, cid))
    for cid in [0] + movie.character_ids():
        sprite = movie.character(cid)
        if not isinstance(sprite, SpriteDef):
            continue
        missing = sorted({c.char_id for frame in sprite.frames for c in frame
                          if isinstance(c, PlaceCommand) and c.char_id is not None and c.char_id not in defined})
        for char in missing:
            problems.append("Character %d places character %d, which is not in the file." % (cid, char))
    classes = {}
    for _, block in swf.abcs:
        a = ABC(block)
        for inst in a.instances:
            classes[a.mname(inst["name"])] = (a, inst)
    for name in sorted(exported):
        if name not in classes:
            problems.append("Class '%s' has no ActionScript definition." % name)
            continue
        a, inst = classes[name]
        if a.mname(inst["super"]) != "flash.display.MovieClip" or inst["flags"] != 0x08:
            problems.append("Class '%s' must be a dynamic subclass of flash.display.MovieClip." % name)
    for name, (a, inst) in sorted(classes.items()):
        for t in inst["traits"]:
            if "method" not in t:
                continue
            ops = [(i.op, i.args) for i in disassemble(a, a.bodies.get(t["method"], b""))]
            if ("callpropvoid", ("mcSetColor", "3")) in ops and setcolor_form(a, t["method"], name) is None:
                problems.append("Color-custom script in '%s' is not in a form AQW runs." % name)
    if any(swf.tagcount.get(TAG_NAMES[code]) for code in BITMAP_TAGS):
        notes.append("The file contains bitmap images.")
    if swf.fps != FPS:
        notes.append("The file says %g fps; AQW plays items at 24 fps whatever the file says." % swf.fps)
    notes += _moved_colorable_clips(data)
    return problems, notes


def validate_item_swf(data: bytes, expected_classes: Collection[str] = (), original: bytes | None = None) -> ItemReport:
    """Problems that keep AQW from using an edited item, and notes; a problem the `original` file already had is a
    note ("Already in the original: …")."""
    problems, notes = _item_findings(data, expected_classes)
    if original is not None:
        before = set(_item_findings(original, expected_classes)[0])
        notes = ["Already in the original: " + p for p in problems if p in before] + notes
        problems = [p for p in problems if p not in before]
    return ItemReport(problems, notes)
