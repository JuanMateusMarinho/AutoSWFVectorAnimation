# tests/project/test_fixes.py
from autoswf.project.fixes import new_part_name, part_choices, region_mask


def test_choices_list_every_part_and_new_ones(converted_parts_helm):
    choices = part_choices(converted_parts_helm.parts)
    labels = [c.label for c in choices]
    assert labels[:2] == ["Face", "Ear L"] and "New lock" in labels and "New accessory" in labels
    new_lock = next(c for c in choices if c.label == "New lock")
    assert new_lock.part == "Lock 7" and new_lock.group == "Lock"
    assert [c.piece for c in choices if c.group == "Eye L"] == ["white", "iris", "pupil", "highlight", "lid"]
    assert new_part_name(converted_parts_helm.parts, "accessory") == "Accessory 2"


def test_region_mask_finds_the_region_under_a_point(converted_parts_helm):
    parts = converted_parts_helm.parts
    x, y = parts.label_point("Lock 2")
    rid, mask = region_mask(parts, x, y)
    assert parts.part_of[rid] == "Lock 2" and mask[int(y), int(x)]
    assert region_mask(parts, -10, -10) is None
