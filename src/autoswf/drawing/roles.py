"""Which painting pass each layer is (spec §5): from layer and folder names in English, Portuguese and Japanese,
from the layer it is clipped to, or from the user's overrides."""
import unicodedata
from dataclasses import dataclass
from typing import Literal

from autoswf.drawing.layers import Drawing, LayerNode

ROLES = ("line", "flat", "shadow", "occlusion", "light", "details")
TONE_ROLES = ("shadow", "occlusion", "light")
IGNORE = "ignore"
GUIDE_PREFIX = "AQW Guide"

# Checked in this order: the first role with a matching word or phrase wins.
VOCABULARY = (
    (IGNORE, ("paper", "papel", "background", "bg", "fundo", "sketch", "sketches", "rough", "rascunho", "esboco",
              "draft", "reference", "ref", "referencia", "用紙", "下書き", "ラフ")),
    ("occlusion", ("occlusion", "ambient occlusion", "ao", "oclusao", "deep shadow", "dark shadow", "2nd shadow",
                   "second shadow", "shadow 2", "sombra 2", "sombra escura")),
    ("shadow", ("shadow", "shadows", "shade", "shading", "sombra", "sombras", "影")),
    ("light", ("light", "lights", "highlight", "highlights", "luz", "luzes", "brilho", "brilhos", "rim light", "glow",
               "ハイライト")),
    ("line", ("line", "lines", "lineart", "line art", "linework", "ink", "inks", "outline", "linha", "linhas",
              "contorno", "traco", "tracos", "線画", "主線")),
    ("details", ("detail", "details", "detalhe", "detalhes", "extra", "extras", "deco")),
    ("flat", ("flat", "flats", "flat color", "flat colors", "flat colour", "flat colours", "base", "base color",
              "base colors", "color", "colors", "colour", "colours", "fill", "fills", "cor", "cores", "cores chapadas",
              "cor base", "chapado", "chapadas", "preenchimento", "下塗り", "ベタ")),
)


@dataclass(frozen=True)
class LayerRole:
    role: str | None                     # a role, "ignore", or None (not used)
    part: str | None                     # part hint: the outermost folder that is not named after a pass
    source: Literal["name", "folder", "clipped", "override", "hidden", "guide"]


def _fold(text: str) -> str:
    """Accents and width variants dropped (Oclusão -> oclusao, ﾍﾞﾀ -> ヘタ), case folded."""
    return "".join(ch for ch in unicodedata.normalize("NFKD", text) if not unicodedata.combining(ch)).casefold()


def _words(text: str) -> list[str]:
    return "".join(ch if ch.isalnum() else " " for ch in _fold(text)).split()


# Folded like the names they are matched against (ベタ loses its dakuten in a name, so it must here too).
_FOLDED_VOCABULARY = tuple((role, tuple(_fold(p) for p in phrases)) for role, phrases in VOCABULARY)


def _matches(words: list[str], phrase: str) -> bool:
    if not phrase.isascii():                         # Japanese names have no spaces between words
        return any(phrase in w for w in words)
    p = phrase.split()
    return any(words[i:i + len(p)] == p for i in range(len(words) - len(p) + 1))


def detect_role(name: str) -> str | None:
    if name.strip().casefold().startswith(GUIDE_PREFIX.casefold()):
        return IGNORE
    words = _words(name)
    for role, phrases in _FOLDED_VOCABULARY:
        if any(_matches(words, phrase) for phrase in phrases):
            return role
    return None


def _layers(drawing: Drawing) -> list[tuple[LayerNode, tuple[LayerNode, ...]]]:
    return [(n, anc) for n, anc in drawing.walk() if n.kind != "group"]


def _check_overrides(drawing: Drawing, overrides: dict[str, str]) -> None:
    layers = _layers(drawing)
    names = list(dict.fromkeys(n.name for n, _ in layers))
    paths = {"/".join([a.name for a in anc] + [n.name]) for n, anc in layers}
    for key, role in overrides.items():
        if role not in ROLES + (IGNORE,):
            raise ValueError("Unknown role '%s'; use one of: %s" % (role, ", ".join(ROLES + (IGNORE,))))
        if key not in names and key not in paths:
            raise ValueError("No layer named '%s'. Layers: %s" % (key, ", ".join(names)))


def _clipping_base(node: LayerNode, siblings: list[LayerNode]) -> LayerNode | None:
    for other in reversed(siblings[:siblings.index(node)]):
        if not other.clipping:
            return other
    return None


def assign_roles(drawing: Drawing, overrides: dict[str, str] | None = None) -> dict[LayerNode, LayerRole]:
    overrides = overrides or {}
    _check_overrides(drawing, overrides)
    roles: dict[LayerNode, LayerRole] = {}
    for node, ancestors in _layers(drawing):
        part = next((a.name for a in ancestors if detect_role(a.name) is None), None)
        path = "/".join([a.name for a in ancestors] + [node.name])
        siblings = ancestors[-1].children if ancestors else drawing.layers
        if not node.visible or not all(a.visible for a in ancestors):
            role = LayerRole(IGNORE, part, "hidden")
        elif node.name.strip().casefold().startswith(GUIDE_PREFIX.casefold()):
            role = LayerRole(IGNORE, part, "guide")
        elif path in overrides or node.name in overrides:
            role = LayerRole(overrides.get(path, overrides.get(node.name)), part, "override")
        elif detect_role(node.name) is not None:
            role = LayerRole(detect_role(node.name), part, "name")
        elif (folder := next((detect_role(a.name) for a in reversed(ancestors) if detect_role(a.name)), None)):
            role = LayerRole(folder, part, "folder")
        elif node.clipping and (base := _clipping_base(node, siblings)) is not None and base in roles \
                and roles[base].role not in (None, IGNORE):
            role = LayerRole(roles[base].role, part, "clipped")
        else:
            role = LayerRole(None, part, "name")
        roles[node] = role
    return roles


BACKGROUND_NAMES = ("paper", "papel", "background", "bg", "fundo", "用紙")


def role_reason(node: LayerNode, ancestors, role: LayerRole, siblings) -> str:
    """Why a layer got its role, in the words `convert` prints and the app's layer list shows."""
    if role.source == "hidden":
        return "hidden"
    if role.source == "guide":
        return "ignored: guide"
    if role.source == "override":
        return "--role"
    if role.source == "folder":
        folder = next(a.name for a in reversed(ancestors) if detect_role(a.name))
        return "folder '%s'" % folder
    if role.source == "clipped":
        base = next(s for s in reversed(siblings[:siblings.index(node)]) if not s.clipping)
        return "clipped to '%s'" % base.name
    if role.role == IGNORE:
        words = node.name.casefold().split()
        return "ignored: background" if any(w in BACKGROUND_NAMES for w in words) else "ignored: sketch or reference"
    if role.role is None:
        return 'no role in its name; pass --role "%s=line"' % node.name
    return "name"
