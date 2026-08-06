"""Roblox viewport: shows the live Roblox window without owning it.

Roblox stays its own top-level window. The macro window is opaque and always-on-
top; we punch a hole in it over this slot (a region mask) and move Roblox behind
that hole, so Roblox renders through and receives clicks while the rest of the
macro UI stays on top. Roblox is never reparented, so closing the macro can't
affect it. The hole exists only while this widget is visible (the Run page) and
Roblox is attached.
"""

from __future__ import annotations

from typing import Callable

from PySide6.QtCore import QPoint, QRect, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QWidget

from sloppykeys.core.win32 import roblox_window as rbx

from . import icons, theme

SYNC_MS = 500
BORDER_INSET = 6  # gap between the widget edge and the dashed frame / hole


class RobloxViewport(QWidget):
    def __init__(self, on_attach: Callable[[bool], None] | None = None) -> None:
        super().__init__()
        self._on_attach = on_attach
        self._hwnd: int | None = None
        self._attached = False

        # The hole must be exactly VIEWPORT_WIDTH x VIEWPORT_HEIGHT, so the widget
        # is that plus the frame inset on each side.
        self.setFixedSize(
            theme.VIEWPORT_WIDTH + BORDER_INSET * 2,
            theme.VIEWPORT_HEIGHT + BORDER_INSET * 2,
        )

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._sync)
        self._timer.start(SYNC_MS)

    # # Geometry
    def _hole_rect(self) -> QRect:
        return self.rect().adjusted(BORDER_INSET, BORDER_INSET, -BORDER_INSET, -BORDER_INSET)

    def _hole_screen_rect(self) -> tuple[int, int, int, int]:
        hole = self._hole_rect()
        top_left = self.mapToGlobal(hole.topLeft())
        return (top_left.x(), top_left.y(), hole.width(), hole.height())

    def screen_rect(self) -> tuple[int, int, int, int]:
        """The viewport area in screen coordinates (for capture / image search)."""
        return self._hole_screen_rect()

    def attached_hwnd(self) -> int | None:
        return self._hwnd

    def _apply_hole(self) -> None:
        window = self.window()
        offset = self.mapTo(window, self._hole_rect().topLeft())
        hole = QRect(offset, self._hole_rect().size())
        if hasattr(window, "set_roblox_hole"):
            window.set_roblox_hole(hole)

    def _clear_hole(self) -> None:
        window = self.window()
        if hasattr(window, "set_roblox_hole"):
            window.set_roblox_hole(None)

    # # Painting: dashed frame + placeholder (only while Roblox is detached)
    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        rect = self.rect().adjusted(1, 1, -1, -1)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(theme.INK_850))
        painter.drawRoundedRect(rect, 10, 10)

        # Once Roblox is positioned it fills the hole; a dashed frame over it
        # just looks like a border cutting into the game, so only draw the dash
        # and placeholder while detached.
        if not self._attached:
            pen = QPen(QColor(theme.VIOLET))
            pen.setWidth(2)
            pen.setStyle(Qt.PenStyle.CustomDashLine)
            pen.setDashPattern([6, 5])
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(self._hole_rect(), 8, 8)
            self._paint_placeholder(painter)
        painter.end()

    def _paint_placeholder(self, painter: QPainter) -> None:
        center = self.rect().center()

        painter.setPen(QColor(theme.PURPLE))
        painter.setFont(QFont(theme.ICON_FAMILY, 36))
        painter.drawText(
            QRect(center.x() - 40, center.y() - 60, 80, 60),
            Qt.AlignmentFlag.AlignCenter,
            icons.MONITOR,
        )

        painter.setPen(QColor(theme.TEXT_DIM))
        painter.setFont(QFont(theme.FAMILY, 12, QFont.Weight.Bold))
        painter.drawText(
            QRect(center.x() - 150, center.y(), 300, 24),
            Qt.AlignmentFlag.AlignCenter,
            "Roblox Window",
        )

        # Size pill: the exact client size Roblox is resized to.
        text = f"{theme.VIEWPORT_WIDTH} x {theme.VIEWPORT_HEIGHT}"
        painter.setFont(QFont(theme.FAMILY, 10, QFont.Weight.Bold))
        pill = QRect(center.x() - 45, center.y() + 30, 90, 24)
        painter.setPen(QPen(QColor(theme.GOOD), 1))
        painter.setBrush(QColor(theme.INK_700))
        painter.drawRoundedRect(pill, 12, 12)
        painter.setPen(QColor(theme.GOOD))
        painter.drawText(pill, Qt.AlignmentFlag.AlignCenter, text)

    # # State
    def _set_attached(self, attached: bool) -> None:
        if attached == self._attached:
            return
        self._attached = attached
        if attached:
            self._apply_hole()
        else:
            self._clear_hole()
        self.update()
        if self._on_attach is not None:
            self._on_attach(attached)

    # # Sync loop
    def _sync(self) -> None:
        if not self.isVisible() or self.window().isMinimized():
            return

        if self._hwnd is not None and not rbx.is_window(self._hwnd):
            self._hwnd = None

        if self._hwnd is None:
            self._hwnd = rbx.find_roblox_window()
            if self._hwnd is None:
                self._set_attached(False)
                return

        self._set_attached(True)
        self.reposition()

    def reposition(self) -> None:
        if self._hwnd is None or not self._attached or self.window().isMinimized():
            return
        rbx.position_window_to_client_rect(self._hwnd, *self._hole_screen_rect())

    # # Visibility: the hole must only exist while the Run page is showing.
    def showEvent(self, event) -> None:
        super().showEvent(event)
        QTimer.singleShot(0, self._sync)

    def hideEvent(self, event) -> None:
        super().hideEvent(event)
        if self._attached:
            self._clear_hole()
        self._attached = False

    def teardown(self) -> None:
        """Stop syncing and remove the hole. Roblox stays a live top-level window."""
        self._timer.stop()
        if self._attached:
            self._clear_hole()
        self._hwnd = None
