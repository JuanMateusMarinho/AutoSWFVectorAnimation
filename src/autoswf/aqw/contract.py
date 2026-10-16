"""AQW item format constants and naming rules (spec §4)."""
import unicodedata

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
