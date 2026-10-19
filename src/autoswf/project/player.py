"""Frame-accurate playback of a built helm SWF (the canvas and the timeline): every child clip loops on its own, as in
the game, so frame f shows each clip at its own f modulo its length."""
from autoswf.render.colors import PlayerColors
from autoswf.render.display import ClipInstance, ScriptContext, instantiate, run_pending_actions, tick
from autoswf.swf.decode import MovieData, PlaceCommand, SpriteDef


class HelmPlayer:
    def __init__(self, swf: bytes, link: str, colors: PlayerColors | None = None):
        self.movie = MovieData(swf)
        if link not in self.movie.classes:
            raise ValueError("Class '%s' was not found in the helm" % link)
        self.link, self.colors = link, colors or PlayerColors()
        back = link + "_backhair"
        self._roots = [self.movie.classes[link]] + ([self.movie.classes[back]] if back in self.movie.classes else [])
        self.length = self._longest()
        self._helm: ClipInstance | None = None
        self._back: ClipInstance | None = None
        self._frame = -1

    def _longest(self) -> int:
        longest, seen, todo = 1, set(), list(self._roots)
        while todo:
            cid = todo.pop()
            if cid in seen:
                continue
            seen.add(cid)
            char = self.movie.character(cid)
            if isinstance(char, SpriteDef):
                longest = max(longest, char.frame_count)
                todo += [cmd.char_id for frame in char.frames for cmd in frame
                         if isinstance(cmd, PlaceCommand) and cmd.char_id is not None]
        return longest

    def set_colors(self, colors: PlayerColors) -> None:
        self.colors = colors

    def _fresh(self) -> None:
        self._ctx = ScriptContext(self.colors)
        objs = [instantiate(self.movie, cid) for cid in self._roots]
        for obj in objs:
            run_pending_actions(obj, self._ctx)
        self._helm = objs[0]
        self._back = objs[1] if len(objs) > 1 else None
        self._frame = 0

    def _goto(self, frame: int) -> None:
        if self._helm is None or frame < self._frame:
            self._fresh()
        while self._frame < frame:
            for obj in (self._helm, self._back):
                if obj is not None:
                    tick(obj, self._ctx)
            self._frame += 1

    def at(self, frame: int) -> ClipInstance:
        """The helm showing `frame` (0-based): ticks forward from the last frame asked, starts again to go back."""
        self._goto(max(0, frame))
        return self._helm

    def back_at(self, frame: int) -> ClipInstance | None:
        self._goto(max(0, frame))
        return self._back
