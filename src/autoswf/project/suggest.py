"""The AI suggestions panel's content (spec §6): what the detection found that the user may want animated, and what it
could not find (to fix by hand). The app applies nothing by itself: Accept, Fix or Skip."""
from dataclasses import dataclass

from autoswf.parts.detect import NO_HAIR_NOTE, NO_SKIN_NOTE


@dataclass(frozen=True)
class Suggestion:
    key: str                     # stable name ("blink", "sway-locks", "no-skin"…), used by Skip for notes
    text: str
    parts: tuple[str, ...] = ()
    preset: str | None = None    # what Accept sets on `parts`; None: nothing to accept (fix or skip)
    stage: str = "Parts"         # where Fix goes


def _names(parts: list[str]) -> str:
    """"Lock 1 to Lock 6" for a consecutive run of numbered parts, else a list."""
    numbers = [p.rpartition(" ")[2] for p in parts]
    if len(parts) > 2 and all(n.isdigit() for n in numbers):
        values = [int(n) for n in numbers]
        if values == list(range(values[0], values[0] + len(values))):
            return "%s to %s" % (parts[0], parts[-1])
    return ", ".join(parts)


def suggestions(build, settings) -> list[Suggestion]:
    if build is None or settings is None:
        return []
    out = []
    decided = settings.animation.parts
    rigs = build.rigs or {}

    def undecided(test) -> list[str]:
        return [n for n, rig in rigs.items() if n not in decided and test(rig)]
    eyes = undecided(lambda r: r.kind == "eye" and r.eye is not None)
    if eyes:
        out.append(Suggestion("blink", "Eyes found (%s). Make them blink?" % _names(eyes), tuple(eyes), "Blink"))
    locks = undecided(lambda r: r.kind == "lock" and r.mask is not None)
    if locks:
        out.append(Suggestion("sway-locks", "%d hair lock%s found (%s). Make %s sway?"
                              % (len(locks), "" if len(locks) == 1 else "s", _names(locks),
                                 "it" if len(locks) == 1 else "them"), tuple(locks), "Sway"))
    back = undecided(lambda r: r.kind == "back_hair" and r.mask is not None)
    if back:
        out.append(Suggestion("sway-back-hair", "Back hair found. Let it sway?", tuple(back), "Sway"))
    ears = undecided(lambda r: r.kind == "ear")
    if ears:
        out.append(Suggestion("twitch-ears", "Ears found (%s). Make %s twitch now and then?"
                              % (_names(ears), "it" if len(ears) == 1 else "them"), tuple(ears), "Twitch"))
    notes = build.parts.notes if build.parts is not None else []
    if NO_SKIN_NOTE in notes and "no-skin" not in settings.dismissed:
        out.append(Suggestion("no-skin", NO_SKIN_NOTE + ". Click the face and pick Face."))
    if NO_HAIR_NOTE in notes and "no-hair" not in settings.dismissed:
        out.append(Suggestion("no-hair", NO_HAIR_NOTE + ". Click the hair and pick Hair."))
    if build.no_flats and "no-parts" not in settings.dismissed:
        out.append(Suggestion("no-parts", "No parts were found (the drawing has no flat colors): the helm is one still "
                                          "shape set. Check the layer roles.", stage="Import"))
    return out
