"""A small transparent speed readout pinned to the top-right corner of the screen.

It is always on top, never takes focus, and mouse clicks pass straight through it to whatever is below.
"""
from PyQt6.QtCore import QRectF, Qt
from PyQt6.QtGui import QColor, QFont, QFontMetrics, QGuiApplication, QPainter
from PyQt6.QtWidgets import QWidget

from ui import BLUE, GREEN, fmt_rate


class Overlay(QWidget):
    MARGIN = 12

    def __init__(self, opacity=1.0):
        super().__init__()
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint |
                            Qt.WindowType.Tool | Qt.WindowType.WindowTransparentForInput |
                            Qt.WindowType.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setWindowOpacity(opacity)
        self.down = self.up = 0.0
        self.text_font = QFont("Segoe UI", 10)
        self.text_font.setBold(True)
        metrics = QFontMetrics(self.text_font)
        self.line_h = metrics.height()
        # fixed size, wide enough for the longest reading, so the box never jitters
        self.setFixedSize(metrics.horizontalAdvance("↓ 999.9 MB/s") + 24, self.line_h * 2 + 16)
        QGuiApplication.primaryScreen().availableGeometryChanged.connect(self.reposition)
        self.reposition()

    def reposition(self, *_):
        area = QGuiApplication.primaryScreen().availableGeometry()  # excludes the taskbar
        self.move(area.right() - self.width() - self.MARGIN + 1, area.top() + self.MARGIN)

    def showEvent(self, event):
        self.reposition()
        super().showEvent(event)

    def set_speeds(self, down, up):
        self.down, self.up = down, up
        if self.isVisible():
            self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(12, 16, 20, 150))  # translucent dark pill keeps the text readable on any background
        p.drawRoundedRect(QRectF(self.rect()), 9, 9)
        p.setFont(self.text_font)
        lines = ((f"↓ {fmt_rate(self.down)}", GREEN), (f"↑ {fmt_rate(self.up)}", BLUE))
        for i, (label, color) in enumerate(lines):
            p.setPen(QColor(color))
            box = QRectF(8, 8 + i * self.line_h, self.width() - 16, self.line_h)
            p.drawText(box, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, label)
        p.end()
