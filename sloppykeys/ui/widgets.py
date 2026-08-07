"""Small reusable widgets."""

from __future__ import annotations

from PySide6.QtCore import Property, QEasingCurve, QPropertyAnimation, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (
    QAbstractButton,
    QAbstractSpinBox,
    QDoubleSpinBox,
    QPlainTextEdit,
    QPushButton,
)

from sloppykeys.config.keybinds import Keybind

from . import theme


class LogView(QPlainTextEdit):
    """Read-only log panel: bounded, and always showing the newest line.

    `setMaximumBlockCount` is Qt's own circular buffer — it drops the oldest block
    as a new one arrives, so a long session can't grow the document. It replaces
    hand-rolled trimming that deleted the first line through a cursor, which moved
    the view to the top and left the panel stuck there instead of following the
    log (and the tester's variant simply wiped the whole panel at the cap).

    Appending pins the scrollbar to the bottom. Qt only auto-scrolls when the bar
    is already at its maximum, which stops being true the moment anything nudges
    it — including the block-count trim.
    """

    def __init__(self, max_lines: int = theme.LOG_MAX_LINES) -> None:
        super().__init__()
        self.setObjectName("log")
        self.setReadOnly(True)
        self.setMaximumBlockCount(max(10, int(max_lines)))

    def append_line(self, text: str) -> None:
        self.appendPlainText(text)
        bar = self.verticalScrollBar()
        bar.setValue(bar.maximum())


class ToggleSwitch(QAbstractButton):
    """iOS-style animated on/off switch."""

    def __init__(self, on_color: str = theme.VIOLET) -> None:
        super().__init__()
        self.setCheckable(True)
        self.setFixedSize(42, 22)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._on_color = QColor(on_color)
        self._margin = 3
        self._pos = float(self._margin)
        self._anim = QPropertyAnimation(self, b"knob", self)
        self._anim.setDuration(150)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.toggled.connect(self._animate)

    def _knob_on(self) -> float:
        return float(self.width() - self.height() + self._margin)

    def _animate(self, checked: bool) -> None:
        self._anim.stop()
        self._anim.setEndValue(self._knob_on() if checked else float(self._margin))
        self._anim.start()

    def get_knob(self) -> float:
        return self._pos

    def set_knob(self, value: float) -> None:
        self._pos = value
        self.update()

    knob = Property(float, get_knob, set_knob)

    def setChecked(self, checked: bool) -> None:  # keep knob in sync when set directly
        super().setChecked(checked)
        self._pos = self._knob_on() if checked else float(self._margin)
        self.update()

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        radius = self.height() / 2

        track = self._on_color if self.isChecked() else QColor(theme.INK_500)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(track)
        p.drawRoundedRect(QRectF(self.rect()), radius, radius)

        knob_d = self.height() - 2 * self._margin
        p.setBrush(QColor("#FFFFFF"))
        p.drawEllipse(QRectF(self._pos, self._margin, knob_d, knob_d))
        p.end()


class SecondsSpin(QDoubleSpinBox):
    """A delay field the user reads in seconds, stored in milliseconds.

    Every timing value on disk is an integer of milliseconds and stays that way — the
    macro sleeps in ms, `settings.json`, `configs/` and `routes.json` all hold ms, and
    changing that would mean migrating every saved file. Only the field is seconds,
    because "2.5" is a number people can judge and "2500" is one they mistype.

    **Two decimals, not one.** Every default and step the app writes is a multiple of
    50ms (a sequence action defaults to 250ms), and at one decimal 0.25s would round to
    0.3 and write 300ms back — the field would retune a delay just by being opened. Two
    decimals resolve 10ms, so a hand-typed 12345ms from the old field does snap to
    12350ms; that is 5ms against a click settle of 200-550ms, and nothing the app itself
    writes is affected.
    """

    def __init__(
        self, max_ms: int, min_ms: int = 0, width: int = 112, arrows: bool = True
    ) -> None:
        super().__init__()
        self.setDecimals(2)
        self.setRange(min_ms / 1000.0, max_ms / 1000.0)
        self.setSingleStep(0.1)
        self.setSuffix(" s")
        self.setFixedWidth(width)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        # `arrows=False` for a field in a narrow row: the step buttons cost ~16px, which
        # is the difference between "60.00 s" fitting and being elided (measured 108px
        # needed against a 96px field in the Units detail card).
        if not arrows:
            self.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)

    def ms(self) -> int:
        """The value in milliseconds, which is what everything downstream wants."""
        return int(round(self.value() * 1000))

    def set_ms(self, value: object) -> None:
        """Show a stored millisecond value. Junk reads as zero rather than raising."""
        try:
            self.setValue(int(value) / 1000.0)
        except (TypeError, ValueError):
            self.setValue(0.0)


def qt_key_to_vk(qt_key: int) -> int | None:
    """Map a Qt key to a Windows virtual-key code for the polled hotkeys.

    Letters and digits share values with their VK codes; F-keys and a few
    specials are mapped explicitly. Unsupported keys return None.
    """
    if Qt.Key.Key_F1 <= qt_key <= Qt.Key.Key_F1 + 23:
        return 0x70 + (qt_key - Qt.Key.Key_F1)
    if Qt.Key.Key_A <= qt_key <= Qt.Key.Key_Z:
        return qt_key  # 0x41..0x5A == VK 'A'..'Z'
    if Qt.Key.Key_0 <= qt_key <= Qt.Key.Key_9:
        return qt_key  # 0x30..0x39 == VK '0'..'9'
    specials = {
        Qt.Key.Key_Space: 0x20,
        Qt.Key.Key_Return: 0x0D,
        Qt.Key.Key_Enter: 0x0D,
        Qt.Key.Key_Tab: 0x09,
        Qt.Key.Key_Insert: 0x2D,
        Qt.Key.Key_Delete: 0x2E,
        Qt.Key.Key_Home: 0x24,
        Qt.Key.Key_End: 0x23,
        Qt.Key.Key_PageUp: 0x21,
        Qt.Key.Key_PageDown: 0x22,
    }
    return specials.get(qt_key)


class KeyCaptureButton(QPushButton):
    """Click to arm, then press a key combo to rebind. Emits the new Keybind."""

    captured = Signal(object)  # Keybind

    def __init__(self, keybind: Keybind) -> None:
        super().__init__()
        self._keybind = keybind
        self._listening = False
        self.setFixedWidth(160)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.clicked.connect(self._arm)
        self._refresh()

    def set_keybind(self, keybind: Keybind) -> None:
        self._keybind = keybind
        self._refresh()

    def _refresh(self) -> None:
        self.setText(self._keybind.display() if self._keybind else "Unset")

    def _arm(self) -> None:
        self._listening = True
        self.setText("Press keys...")
        self.grabKeyboard()

    def _disarm(self) -> None:
        self._listening = False
        self.releaseKeyboard()
        self._refresh()

    def keyPressEvent(self, event) -> None:
        if not self._listening:
            super().keyPressEvent(event)
            return
        key = event.key()
        if key in (
            Qt.Key.Key_Control,
            Qt.Key.Key_Shift,
            Qt.Key.Key_Alt,
            Qt.Key.Key_Meta,
        ):
            return  # wait for a non-modifier key
        if key == Qt.Key.Key_Escape:
            self._disarm()
            return
        vk = qt_key_to_vk(key)
        if vk is None:
            self._disarm()
            return
        mods = event.modifiers()
        keybind = Keybind(
            vk=vk,
            ctrl=bool(mods & Qt.KeyboardModifier.ControlModifier),
            shift=bool(mods & Qt.KeyboardModifier.ShiftModifier),
            alt=bool(mods & Qt.KeyboardModifier.AltModifier),
        )
        self._keybind = keybind
        self._disarm()
        self.captured.emit(keybind)
