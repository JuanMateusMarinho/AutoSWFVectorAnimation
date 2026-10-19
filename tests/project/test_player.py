# tests/project/test_player.py
import numpy as np

from autoswf.model.geometry import Matrix
from autoswf.project.build import HelmBuilder
from autoswf.project.player import HelmPlayer
from autoswf.project.settings import HelmSettings
from autoswf.render.effects import qimage_to_array
from autoswf.render.painter import Renderer


def animated(helm_psd):
    s = HelmSettings(source=str(helm_psd.path), align=helm_psd.align)
    s.animation.parts.update({"Eye L": ("Blink", {}), "Lock 1": ("Sway", {"length": 48})})
    return HelmBuilder().build(s)


def pixels(obj):
    return qimage_to_array(Renderer().render_image(obj, 160, 160, Matrix.translate(80, 80), None))


def test_player_plays_every_loop_on_its_own(qapp, helm_psd):
    b = animated(helm_psd)
    p = HelmPlayer(b.swf, b.link)
    assert p.length == 87
    rest, closed = pixels(p.at(0)), pixels(p.at(10))
    assert np.abs(rest - closed).max() > 0.5                              # the eye closes on frame 11
    assert np.allclose(pixels(HelmPlayer(b.swf, b.link).at(87 * 48)), rest)   # both loops back at their start


def test_player_rewinds(qapp, helm_psd):
    b = animated(helm_psd)
    p = HelmPlayer(b.swf, b.link)
    p.at(30)
    assert np.allclose(pixels(p.at(5)), pixels(HelmPlayer(b.swf, b.link).at(5)))
