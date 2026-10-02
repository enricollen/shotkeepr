"""Neutral palettes keep the surrounding UI from distorting photo perception."""

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

from shotkeepr.desktop.api_client.models import Theme


def apply_theme(app: QApplication, theme: Theme) -> None:
    dark = theme == Theme.DARK
    palette = QPalette()
    colors = {
        QPalette.ColorRole.Window: "#292929" if dark else "#eeeeee",
        QPalette.ColorRole.WindowText: "#eeeeee" if dark else "#202020",
        QPalette.ColorRole.Base: "#353535" if dark else "#ffffff",
        QPalette.ColorRole.AlternateBase: "#404040" if dark else "#e0e0e0",
        QPalette.ColorRole.Text: "#eeeeee" if dark else "#202020",
        QPalette.ColorRole.Button: "#353535" if dark else "#e0e0e0",
        QPalette.ColorRole.ButtonText: "#eeeeee" if dark else "#202020",
        QPalette.ColorRole.ToolTipBase: "#353535" if dark else "#ffffff",
        QPalette.ColorRole.ToolTipText: "#eeeeee" if dark else "#202020",
        QPalette.ColorRole.Highlight: "#606060",
        QPalette.ColorRole.HighlightedText: "#ffffff",
    }
    for role, color in colors.items():
        palette.setColor(role, QColor(color))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text, QColor("#808080"))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText, QColor("#808080"))
    app.setPalette(palette)
