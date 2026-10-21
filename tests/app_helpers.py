"""Helpers shared by the app tests: a main window with its settings kept in the test's folder, and menu lookups."""
from PySide6.QtCore import QSettings

from autoswf.app.controller import ProjectController
from autoswf.app.window import MainWindow


def window(cache, tmp_path, threaded=False):
    """A main window whose unsaved-changes question answers "discard" (tests replace `ask_save` to try others)."""
    w = MainWindow(ProjectController(cache, threaded=threaded), cache,
                   settings_store=QSettings(str(tmp_path / "ui.ini"), QSettings.Format.IniFormat))
    w.ask_save = lambda: "discard"
    w.ask_discard_edits = lambda: True
    return w


def find_action(menu, text):
    for action in menu.actions():
        if action.text() == text:
            return action
        if action.menu() is not None and (found := find_action(action.menu(), text)) is not None:
            return found
    return None
