import os

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
