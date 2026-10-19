"""AQW item format constants and naming rules (spec §4, §13)."""
import unicodedata
from dataclasses import dataclass
from typing import Collection

LOCATIONS = ("Skin", "Hair", "Eye", "Base", "Trim", "Accessory")
SHADES = ("None", "Light", "Dark", "Darker")
FPS = 24.0
BITMAP_TAGS = frozenset({6, 20, 21, 35, 36, 90})


def sanitize_link(name: str) -> str:
    """Turn an item name into a valid AS3 class name ("Chapéu 2" -> "Chapeu2", "4ever" -> "_4ever")."""
    ascii_only = unicodedata.normalize("NFKD", name)
    s = "".join(ch for ch in ascii_only if ch.isascii() and (ch.isalnum() or ch == "_"))
    if not s:
        raise ValueError("Link name is empty after removing invalid characters")
    return "_" + s if s[0].isdigit() else s


def internal_class_name(link: str, symbol_name: str, n: int) -> str:
    try:
        slug = sanitize_link(symbol_name)
    except ValueError:
        slug = "Symbol"
    return "%s_fla.%s_%d" % (link, slug, n)


SIZE_WARNING_BYTES = 200 * 1024
AS3_RESERVED = frozenset(
    "as break case catch class const continue default delete do dynamic each else extends false final finally for "
    "function get if implements import in include instanceof interface internal is namespace native new null "
    "override package private protected public return set static super switch this throw to true try typeof use "
    "var void while with".split())
FLASH_NAMES = frozenset(
    "Object String Number int uint Boolean Array Function Class Error Math Date RegExp XML XMLList Namespace QName "
    "JSON Vector MovieClip Sprite Shape Stage DisplayObject Bitmap Loader".split())
AQW_CLIENT_NAMES = frozenset("Game World AvatarMC mcSkel mcHeadM mcHeadF Main".split())


@dataclass(frozen=True)
class LinkCheck:
    link: str                    # the name the class will have ("" when nothing usable is left)
    error: str | None = None
    warning: str | None = None


def check_link(text: str, client_classes: Collection[str] = ()) -> LinkCheck:
    """An item's link (class) name checked for AQW: sanitized, never a reserved word, a Flash class or a class of the
    game client (the game would find its own class first)."""
    try:
        link = sanitize_link(text)
    except ValueError:
        return LinkCheck("", "The link name is empty; use letters, digits and _")
    warning = None if link == text else "Class names use only letters, digits and _: the link will be '%s'" % link
    if link in AS3_RESERVED:
        return LinkCheck(link, "'%s' is an ActionScript reserved word" % link, warning)
    if link in AQW_CLIENT_NAMES or link in client_classes:
        return LinkCheck(link, "'%s' is a class of the AQW game client; the game would use its own class instead of "
                               "the helm" % link, warning)
    if link in FLASH_NAMES:
        return LinkCheck(link, "'%s' is a Flash class name; choose another" % link, warning)
    return LinkCheck(link, None, warning)


def client_class_names(client) -> frozenset[str]:
    """The class names of the AQW game client (a MovieData): exported symbols and ActionScript classes, without
    a package."""
    names = {n for n in client.classes if "." not in n}
    for abc in client.abcs:
        for inst in abc.instances:
            name = abc.mname(inst["name"])
            if "." not in name:
                names.add(name)
    return frozenset(names)
