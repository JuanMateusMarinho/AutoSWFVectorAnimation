"""The app's dark theme (spec §6): Qt's Fusion style with a dark palette, close to Animate's."""
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

WINDOW, BASE, ALTERNATE, TEXT, DIM = (QColor(45, 45, 48), QColor(30, 30, 32), QColor(38, 38, 41), QColor(222, 222, 222),
                                      QColor(130, 130, 135))
ACCENT = QColor(64, 132, 214)


def apply_dark_theme(app: QApplication) -> None:
    app.setStyle("Fusion")
    p = QPalette()
    for role, color in ((QPalette.ColorRole.Window, WINDOW), (QPalette.ColorRole.WindowText, TEXT),
                        (QPalette.ColorRole.Base, BASE), (QPalette.ColorRole.AlternateBase, ALTERNATE),
                        (QPalette.ColorRole.ToolTipBase, BASE), (QPalette.ColorRole.ToolTipText, TEXT),
                        (QPalette.ColorRole.Text, TEXT), (QPalette.ColorRole.Button, WINDOW),
                        (QPalette.ColorRole.ButtonText, TEXT), (QPalette.ColorRole.BrightText, QColor(255, 90, 90)),
                        (QPalette.ColorRole.Link, ACCENT), (QPalette.ColorRole.Highlight, ACCENT),
                        (QPalette.ColorRole.HighlightedText, QColor(255, 255, 255)),
                        (QPalette.ColorRole.PlaceholderText, DIM)):
        p.setColor(role, color)
    for role in (QPalette.ColorRole.WindowText, QPalette.ColorRole.Text, QPalette.ColorRole.ButtonText):
        p.setColor(QPalette.ColorGroup.Disabled, role, DIM)
    app.setPalette(p)
    app.setStyleSheet("QToolTip { color: #dedede; background-color: #1e1e20; border: 1px solid #555; }")
