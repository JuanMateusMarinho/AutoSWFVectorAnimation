from autoswf.anim.rig import part_of_layer


def test_rigs_of_the_synthetic_helm(converted_parts_helm, part_rigs):
    c, rigs = converted_parts_helm, part_rigs
    assert list(rigs) == [n for n in c.parts.parts if n in rigs] and "Lock 6" in rigs
    eye = rigs["Eye L"]
    assert eye.layers == ["Eye L"] and eye.eye.ball == "Eye L ball" and eye.eye.lid == "Eye L lid"
    assert 6.0 <= eye.eye.drop <= 9.0                  # white bottom y 19, lid line bottom near y 9.2: 0.766 x ~10
    lock = rigs["Lock 3"]
    assert lock.layers == ["Lock 3"] and lock.tip is not None and lock.mask.scale == 4.0
    assert rigs["Lock 6"].mask.pixels.sum() > 2 * lock.mask.pixels.sum()
    assert abs(lock.pivot.x - c.t.roots["Lock 3"][0]) <= 1.5


def test_layers_belong_to_their_part():
    from types import SimpleNamespace as L
    assert [part_of_layer(L(name=n, parent=p)) for n, p in (("Lock 3 (Bangs)", None), ("Eye L lid", "Eye L"),
                                                              ("Hair", None))] == ["Lock 3", "Eye L", "Hair"]


def test_the_right_eye_is_the_far_eye(part_rigs):
    assert part_rigs["Eye L"].eye.far is False and part_rigs["Eye R"].eye.far is True
