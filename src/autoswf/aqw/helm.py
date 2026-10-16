"""Export a helm (normal or morph) as an AQW-ready SWF (spec §4.2, §13)."""
from dataclasses import dataclass

from autoswf.abc.movieclip_classes import ClassSpec, build_abc
from autoswf.aqw.contract import LOCATIONS, SHADES, internal_class_name, sanitize_link
from autoswf.model.document import SetColorScript, Symbol
from autoswf.swf.movie import build_swf


@dataclass(eq=False)
class HelmItem:
    link: str
    root: Symbol
    backhair: Symbol | None = None


def _walk(symbol: Symbol, seen: set[int], out: list[Symbol]) -> None:
    if id(symbol) in seen:
        return
    seen.add(id(symbol))
    out.append(symbol)
    for frame in symbol.frames:
        for p in frame.placements:
            if isinstance(p.item, Symbol):
                _walk(p.item, seen, out)


def _frame_scripts(symbol: Symbol) -> tuple:
    scripts = dict(symbol.scripts)
    cc = symbol.color_custom
    if cc is not None:
        if cc.location not in LOCATIONS:
            raise ValueError("Invalid color-custom location '%s' on '%s'; use one of: %s"
                             % (cc.location, symbol.name, ", ".join(LOCATIONS)))
        if cc.shade not in SHADES:
            raise ValueError("Invalid color-custom shade '%s' on '%s'; use one of: %s"
                             % (cc.shade, symbol.name, ", ".join(SHADES)))
        if 0 in scripts:
            raise ValueError("'%s' is colorable, so its first frame cannot have another script" % symbol.name)
        scripts[0] = SetColorScript(cc.location, cc.shade)
    return tuple(sorted(scripts.items(), key=lambda s: s[0]))


def export_helm(item: HelmItem) -> bytes:
    if sanitize_link(item.link) != item.link:
        raise ValueError("Link name '%s' is not a valid class name; use '%s'" % (item.link, sanitize_link(item.link)))
    tops = [item.root] + ([item.backhair] if item.backhair is not None else [])
    ordered, seen = [], set()
    for top in tops:
        _walk(top, seen, ordered)

    class_names = {id(item.root): item.link}
    if item.backhair is not None:
        class_names[id(item.backhair)] = item.link + "_backhair"
    specs, n = [], 0
    for symbol in ordered:
        scripts = _frame_scripts(symbol)
        if id(symbol) not in class_names:
            if not scripts:
                continue
            n += 1
            class_names[id(symbol)] = internal_class_name(item.link, symbol.name, n)
        specs.append(ClassSpec(class_names[id(symbol)], scripts))
    return build_swf(tops, class_names, build_abc(specs))
