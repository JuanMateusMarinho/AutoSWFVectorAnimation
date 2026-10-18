"""Check an exported helm SWF against the AQW contract (spec §4, §13)."""
from autoswf.abc.disasm import disassemble
from autoswf.abc.movieclip_classes import expected_setcolor_ops
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
