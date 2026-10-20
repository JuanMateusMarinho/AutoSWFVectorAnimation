import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")      # before any Qt import: tests run headless

import pytest


@pytest.fixture(scope="session")
def qapp():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


@pytest.fixture
def aqw_cache():
    """The real AQW files in the local cache; tests using it skip when they are not downloaded."""
    from autoswf.aqw.assets import DEFAULT_ARMOR, AqwCache, default_cache_dir
    cache = AqwCache(default_cache_dir())
    if cache.missing(DEFAULT_ARMOR):
        pytest.skip("AQW reference files are not downloaded (python -m autoswf download-aqw)")
    return cache


@pytest.fixture
def real_drawing():
    """The user's own drawing (never committed): AUTOSWF_REAL_DRAWING or cache/real/SkySavior.clip; skipped without it."""
    path = Path(os.environ.get("AUTOSWF_REAL_DRAWING") or Path(__file__).resolve().parents[1] / "cache" / "real" / "SkySavior.clip")
    if not path.exists():
        pytest.skip("the user's drawing is not in %s" % path)
    return path


@pytest.fixture
def reference_morph():
    """The user's reference morph helm (never committed): AUTOSWF_REFERENCE_MORPH or cache/real/CrystallisOnsenMMorph4.swf;
    skipped without it."""
    path = Path(os.environ.get("AUTOSWF_REFERENCE_MORPH")
                or Path(__file__).resolve().parents[1] / "cache" / "real" / "CrystallisOnsenMMorph4.swf")
    if not path.exists():
        pytest.skip("the reference morph is not in %s" % path)
    return path


@pytest.fixture(scope="session")
def parts_helm(qapp):
    """The synthetic helm with parts and its ground truth, built once."""
    from drawings import synthetic_parts_helm
    return synthetic_parts_helm()


@pytest.fixture(scope="session")
def converted_parts_helm(parts_helm, qapp):
    """The synthetic parts helm through detect -> split -> vectorize -> assemble -> export, once per session."""
    from types import SimpleNamespace
    from drawings import drawing_from_specs
    from autoswf.aqw.helm import export_helm
    from autoswf.drawing.passes import extract_passes
    from autoswf.drawing.roles import assign_roles
    from autoswf.parts.assemble import assemble_helm
    from autoswf.parts.detect import detect_parts
    from autoswf.parts.hidden import layered_passes, split_passes
    from autoswf.vectorize.art import vectorize
    t = parts_helm
    d = drawing_from_specs(t.width, t.height, t.layers)
    passes = extract_passes(d, assign_roles(d))
    parts = detect_parts(passes, t.alignment)
    layers = split_passes(passes, parts)
    art = vectorize(layered_passes(passes, layers), t.alignment)
    helm = assemble_helm(art, layers, "PartsHelm")
    return SimpleNamespace(t=t, passes=passes, parts=parts, layers=layers, art=art, helm=helm,
                           swf=export_helm(helm.item))


@pytest.fixture(scope="session")
def part_rigs(converted_parts_helm):
    """What the animation presets know about each part of the synthetic parts helm."""
    from autoswf.anim.rig import rig_parts
    c = converted_parts_helm
    return rig_parts(c.parts, c.helm, c.layers)


@pytest.fixture(scope="session")
def helm_psd(tmp_path_factory, qapp):
    """The 480 px synthetic parts helm written as a PSD (the app imports files), with its alignment text."""
    from types import SimpleNamespace
    from drawings import synthetic_parts_helm
    from autoswf.drawing.writers import write_psd
    t = synthetic_parts_helm(480)
    path = tmp_path_factory.mktemp("helm") / "Synthetic Helm.psd"
    write_psd(path, t.width, t.height, t.layers)
    return SimpleNamespace(path=path, align=str(t.alignment), t=t)


@pytest.fixture(scope="session")
def backhair_psd(tmp_path_factory):
    """A tiny helm with back hair, written as a PSD."""
    from types import SimpleNamespace
    from drawings import back_hair_specs
    from autoswf.drawing.writers import write_psd
    w, h, specs, align = back_hair_specs()
    path = tmp_path_factory.mktemp("bh") / "BH.psd"
    write_psd(path, w, h, specs)
    return SimpleNamespace(path=path, align=align)


@pytest.fixture
def app_cache(tmp_path):
    """A mini AQW cache (the fake client and armor of aqw_fakes) for app tests."""
    from aqw_fakes import write_mini_cache
    return write_mini_cache(tmp_path / "aqw-cache")


@pytest.fixture
def kind_of_brave():
    """The user's armor KindOfBrave.swf (AQW art, never committed): AUTOSWF_REFERENCE_ARMOR or cache/real/KindOfBrave.swf."""
    path = Path(os.environ.get("AUTOSWF_REFERENCE_ARMOR")
                or Path(__file__).resolve().parents[1] / "cache" / "real" / "KindOfBrave.swf")
    if not path.exists():
        pytest.skip("the reference armor is not in %s" % path)
    return path


@pytest.fixture
def azrael():
    """The user's animated armor AzraelGuardianArmor.swf (AQW art, never committed): AUTOSWF_ANIMATED_ARMOR or
    cache/real/AzraelGuardianArmor.swf."""
    path = Path(os.environ.get("AUTOSWF_ANIMATED_ARMOR")
                or Path(__file__).resolve().parents[1] / "cache" / "real" / "AzraelGuardianArmor.swf")
    if not path.exists():
        pytest.skip("the animated armor is not in %s" % path)
    return path.read_bytes()
