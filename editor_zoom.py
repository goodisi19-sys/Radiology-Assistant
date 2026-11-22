"""View-only editor scale: document fonts, HTML and undo history stay intact."""
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QTextEdit


class ReportEditor(QTextEdit):
    scaleChanged = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.scale_percent = 100
        # Keep the layout's non-owning paint-device reference alive with the editor.
        self._scale_device = QImage(1, 1, QImage.Format.Format_ARGB32)

    def set_scale(self, percent):
        percent = max(75, min(250, int(percent)))
        cursor = self.textCursor()
        modified = self.document().isModified()
        self.scale_percent = percent
        self._scale_device.setDotsPerMeterX(round(self.logicalDpiX() * percent / 100 / 0.0254))
        self._scale_device.setDotsPerMeterY(round(self.logicalDpiY() * percent / 100 / 0.0254))
        self.document().documentLayout().setPaintDevice(self._scale_device)
        self.document().markContentsDirty(0, self.document().characterCount())
        self.document().setModified(modified)
        self.setTextCursor(cursor)
        self.ensureCursorVisible()
        self.viewport().update()
        self.scaleChanged.emit(percent)

    def wheelEvent(self, event):
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            delta = event.angleDelta().y()
            if delta:
                self.set_scale(self.scale_percent + (25 if delta > 0 else -25))
            event.accept()
            return
        super().wheelEvent(event)
