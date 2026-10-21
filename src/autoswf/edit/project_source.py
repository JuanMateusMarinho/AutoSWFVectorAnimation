"""Helm projects as edit layers (Plan 7, spec §8.6): a part's traced layers (fills, details, lines), bottom to top, in
the helm's own space, with the AQW color each face takes when the helm is assembled; and the extra layers drawn by
hand. The edited shapes go back into the project's ArtEdits."""
from autoswf.edit.layer import Drawing, EditLayer, Tone, ToneRef
from autoswf.edit.regions import stroke_width_px
from autoswf.model.geometry import Matrix
from autoswf.model.shape import SolidFill
from autoswf.parts.assemble import face_location, face_shade
from autoswf.render.colors import PlayerColors, player_color_transform


def _colors(build) -> PlayerColors:
    colors = PlayerColors()
    for location, rgb in build.settings.colors.items():
        colors = colors.replace(location, rgb)
    return colors


def _shown(binding, color, colors: PlayerColors):
    if binding is None:
        return tuple(color)
    ct = player_color_transform(binding[0], binding[1], colors)
    return tuple(max(0, min(255, int(v))) for v in ct.add[:3]) + (255,)


def _with_line(layer: EditLayer, line_ref) -> EditLayer:
    visible = layer.visible_areas()
    if line_ref is None or line_ref not in visible:
        return layer
    return EditLayer(layer.name, layer.drawings, layer.tones, line_ref, max(1.0, stroke_width_px(visible[line_ref])))


def project_layer(build, part: str) -> EditLayer:
    """The part as an EditLayer (an eye holds its ball and lid); drawing keys are traced layer names."""
    by_name = {layer.name: layer for layer in build.layers}
    parts = {part} | {name for name, layer in by_name.items() if layer.parent == part}
    colors = _colors(build)
    drawings, tones, line = [], [], None
    for t in build.art.layers:
        if t.part not in parts:
            continue
        drawings.append(Drawing(t.name, t.shape, Matrix(), False))
        part_layer = by_name.get(t.part)
        for i, style in enumerate(t.styles):
            location = face_location(style, part_layer) if t.role == "fills" and part_layer is not None else None
            binding = (location, face_shade(style, part_layer.soft_roles)) if location else None
            tones.append(Tone(ToneRef(t.name, i), _shown(binding, style.color, colors), binding))
        if t.role == "line" and line is None and t.styles:
            line = ToneRef(t.name, 0)
    return _with_line(EditLayer(part, drawings, tones, line, 1.0), line)


def extra_layer(build, name: str) -> EditLayer:
    """A hand-made layer: one drawing per tone, keyed "tone<k>"."""
    extra = next(e for e in build.settings.edits.extras if e.name == name)
    colors = _colors(build)
    drawings, tones, fixed = [], [], []
    for k, (shape, location, shade) in enumerate(extra.tones):
        key = "tone%d" % k
        binding = (location, shade) if location else None
        drawings.append(Drawing(key, shape, Matrix(), binding is not None))
        for i, fill in enumerate(shape.fills):
            color = fill.color if isinstance(fill, SolidFill) else fill.stops[0].color
            tone = Tone(ToneRef(key, i), _shown(binding, color, colors), binding)
            tones.append(tone)
            if binding is None:
                fixed.append(tone)
    line = min(fixed, key=lambda t: sum(t.color[:3])).ref if fixed else None
    return _with_line(EditLayer(name, drawings, tones, line, 1.0), line)
