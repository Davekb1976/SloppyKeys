"""Animated hover/selection glow.

QSS :hover swaps colours instantly, which feels static. This attaches a coloured
drop-shadow and animates its blur on enter/leave (and on demand for a selected
state), giving buttons and cards a smooth glow. One effect per widget (Qt allows
a single graphics effect per widget), so use sparingly on key surfaces.
"""

from __future__ import annotations

from PySide6.QtCore import (
    QEasingCurve,
    QEvent,
    QObject,
    QPropertyAnimation,
    QRectF,
    Qt,
    QTimer,
)
from PySide6.QtGui import QColor, QConicalGradient, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QGraphicsDropShadowEffect, QWidget


class HoverGlow(QObject):
    def __init__(self, widget: QWidget, color: str, radius: int = 26) -> None:
        super().__init__(widget)
        self._radius = radius
        self._selected = False

        self._effect = QGraphicsDropShadowEffect(widget)
        self._effect.setColor(QColor(color))
        self._effect.setOffset(0, 0)
        self._effect.setBlurRadius(0)
        widget.setGraphicsEffect(self._effect)

        self._anim = QPropertyAnimation(self._effect, b"blurRadius", self)
        self._anim.setDuration(170)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)

        widget.installEventFilter(self)

    def _to(self, value: float) -> None:
        self._anim.stop()
        self._anim.setEndValue(value)
        self._anim.start()

    def set_color(self, color: str) -> None:
        self._effect.setColor(QColor(color))

    def set_selected(self, selected: bool) -> None:
        self._selected = selected
        self._to(self._radius if selected else 0)

    def eventFilter(self, _obj: QObject, event: QEvent) -> bool:
        if event.type() == QEvent.Type.Enter and not self._selected:
            self._to(self._radius * 0.6)
        elif event.type() == QEvent.Type.Leave and not self._selected:
            self._to(0)
        return False


# TrailBorder draw modes.
MODE_OFF = "off"
MODE_TRAIL = "trail"      # one bright segment travelling around the border
MODE_OUTLINE = "outline"  # the whole border lit, static


class TrailBorder(QObject):
    """A bright segment that travels around a widget's rounded border.

    For pointing at something the user hasn't noticed yet — the Run strip's
    selectors when a gamemode has just been picked. It paints *over* the widget
    after its own paintEvent, so QSS styling is untouched and nothing needs to
    become a custom widget.

    Deliberately not a QGraphicsEffect: a widget can only have one, and the glow
    above already claims that slot on the surfaces we care about.
    """

    def __init__(
        self,
        widget: QWidget,
        color: str,
        radius: int = 10,
        thickness: int = 2,
        interval_ms: int = 33,
        arc_span: int = 70,
    ) -> None:
        super().__init__(widget)
        self._widget = widget
        self._color = QColor(color)
        self._radius = radius
        self._thickness = thickness
        self._span = max(10, arc_span)
        self._angle = 0.0
        self._mode = MODE_OFF

        self._timer = QTimer(self)
        self._timer.setInterval(max(16, interval_ms))
        self._timer.timeout.connect(self._advance)
        widget.installEventFilter(self)

    def set_color(self, color: str) -> None:
        self._color = QColor(color)

    def set_active(self, active: bool) -> None:
        """Start or stop the moving segment. Stopping repaints once so it clears."""
        self._set_mode(MODE_TRAIL if active else MODE_OFF)

    def set_outline(self, lit: bool) -> None:
        """Freeze into a solid full border instead of a travelling segment.

        The trail says "look here, something is missing"; the outline says "this is
        set". Same border, no animation and no timer, so a completed selection stays
        marked without anything moving on screen.
        """
        self._set_mode(MODE_OUTLINE if lit else MODE_OFF)

    def _set_mode(self, mode: str) -> None:
        if mode == self._mode:
            return
        self._mode = mode
        if mode == MODE_TRAIL:
            self._angle = 0.0
            self._timer.start()
        else:
            self._timer.stop()
        self._widget.update()

    @property
    def active(self) -> bool:
        """True while anything is being drawn — trail or static outline."""
        return self._mode != MODE_OFF

    def _advance(self) -> None:
        # 16 degrees per tick at ~30fps: one lap in roughly 0.75s. Fast enough to
        # read as motion, slow enough not to look like an error state.
        self._angle = (self._angle + 16.0) % 360.0
        self._widget.update()

    def eventFilter(self, _obj: QObject, event: QEvent) -> bool:
        if event.type() != QEvent.Type.Paint or self._mode == MODE_OFF:
            return False
        # Let the widget draw itself first, then overpaint the trail.
        self._widget.event(event)
        self._paint()
        return True  # handled: the widget must not paint twice

    def _paint(self) -> None:
        rect = QRectF(self._widget.rect()).adjusted(
            self._thickness / 2, self._thickness / 2, -self._thickness / 2, -self._thickness / 2
        )
        if rect.width() <= 0 or rect.height() <= 0:
            return

        path = QPainterPath()
        path.addRoundedRect(rect, self._radius, self._radius)

        if self._mode == MODE_OUTLINE:
            brush: QColor | QConicalGradient = QColor(self._color)
        else:
            # A conical gradient turns the border into one moving bright segment:
            # the colour is opaque over `span` degrees and transparent elsewhere,
            # and the whole gradient rotates.
            gradient = QConicalGradient(rect.center(), -self._angle)
            head = QColor(self._color)
            tail = QColor(self._color)
            tail.setAlpha(0)
            fraction = self._span / 360.0
            gradient.setColorAt(0.0, head)
            gradient.setColorAt(fraction, tail)
            gradient.setColorAt(1.0, head)
            brush = gradient

        painter = QPainter(self._widget)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        pen = QPen(brush, self._thickness)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(path)
        painter.end()
