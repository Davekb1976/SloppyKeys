"""Placement coordinate picker.

Opens over the Roblox client area and lets you click a point. Two backgrounds,
because the two pickers answer different questions:

- Unit placement wants the map's playfield, so it prefers the reference screenshot
  dropped in for the selected target: `images/reference/<Gamemode>/<Map>/<Act>.png`
  first, then `images/reference/<Gamemode>/<Map>.png`. Per act matters for Raid,
  where Spirit City's three acts are separate areas of one map; Story's acts share
  a playfield and keep the single per-map file. That way placements can be planned
  from the lobby, and the same target always looks the same. Falls back to a live
  capture when no reference file exists.
- Sequence actions want a live capture: an ability target depends on where the
  unit actually is right now, and the buttons being clicked are on-screen UI.

Why a click maps straight to a coordinate: DPI scaling is disabled and the client
area is pinned to 1152x756, so one overlay pixel is one client pixel. A click at
overlay (x, y) *is* client coordinate (x, y) — no scaling, no transform.

The step being edited is drawn full-size; other steps that already have
coordinates are drawn dimmed for context. Dot colour comes from the hotbar slot
(see theme.slot_color) so the same unit reads the same everywhere in the UI.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Callable

from PySide6.QtCore import QEvent, QPoint, QRect, Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QWidget

from sloppykeys.config.unit_configs import safe_component
from sloppykeys.content.gamemodes import CHALLENGE
from sloppykeys.content.units import slot_index

from . import theme

DOT_RADIUS = 13
CROSSHAIR = 26

# # Where the in-match Start Game button sits
# Client-space `(x, y, w, h)` at the pinned 1152x756 size, measured by the user from the
# corners (450,194)-(702,236). Drawn as a blocked band on the placement picker because a
# **pre-placement** step clicks before the wave starts, i.e. while that button is still on
# screen — a coordinate under it presses Start Game instead of placing the unit. Nothing
# enforces it: the picker still accepts the click, because after Start Game the button is
# gone and placing there is fine for a normal step.
START_GAME_ZONE = (450, 194, 252, 42)
# Drawn *above* the band, in a rect measured to the text rather than the band's width — the
# label is wider than the 252px band, and a band-width rect clipped it at both ends.
ZONE_LABEL = "Start Game — don't put a pre-placement step here"


@dataclass(frozen=True)
class PlacedDot:
    """An already-placed step, drawn for context while picking another one."""

    step: int
    x: int
    y: int
    slot: str


class PlacementOverlay(QWidget):
    """Frameless, always-on-top picker covering the Roblox client rect.

    on_picked(x, y) receives client-space coordinates. on_closed() fires once,
    whether the pick was taken or cancelled, so the caller can drop its
    reference — without it the widget is garbage collected mid-use.
    """

    def __init__(
        self,
        rect: tuple[int, int, int, int],
        step_number: int,
        slot: str,
        existing: tuple[int, int] | None,
        background: QPixmap | None,
        on_picked: Callable[[int, int], None],
        on_closed: Callable[[], None],
        title: str = "",
        others: "list[PlacedDot] | None" = None,
        show_zones: bool = False,
    ) -> None:
        super().__init__(None)
        self._show_zones = show_zones
        self._origin = (rect[0], rect[1])
        self._step_number = step_number
        self._slot = slot_index(slot)
        self._point: QPoint | None = (
            QPoint(existing[0], existing[1]) if existing is not None else None
        )
        self._others = others or []
        self._background = background
        self._on_picked = on_picked
        self._on_closed = on_closed
        self._closed = False
        self._title = title
        self._hover: QPoint | None = None
        # Has this window ever been active? Deactivation only cancels *after* the first
        # activation — a WindowDeactivate can arrive while the widget is still being shown,
        # and closing on that would make the picker vanish the instant it opened.
        self._was_active = False

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        # Blank, not `CrossCursor`: `_paint_hover` draws its own 1px crosshair, and the OS
        # cross is several pixels thick with no findable centre, so the two together were
        # a fat blob over the pixel being aimed at. Same reasoning as
        # `macro_tester.RegionOverlay`, which this now matches.
        self.setCursor(Qt.CursorShape.BlankCursor)
        # Explicit, so Escape reaches `keyPressEvent`. A QWidget defaults to NoFocus, and
        # a top-level with no focusable child is one refactor away from dropping keys.
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMouseTracking(True)
        self.setGeometry(*rect)

    # # Input
    def changeEvent(self, event) -> None:
        """Cancel the pick when this window stops being the active one.

        Escape is only delivered to the *active* window, so any click on the main window
        left the picker open with no key that could close it — reported three ways: Escape
        doing nothing after clicking away and back, Escape doing nothing after a
        double-clicked Set (the second click activates the main window), and a chip click
        appearing to be ignored because it was spent taking activation back.

        Cancelling is safe: a pick is a single click, so there is nothing in progress to
        lose, and the caller's `on_closed` drops the reference either way.
        """
        if event.type() == QEvent.Type.ActivationChange:
            if self.isActiveWindow():
                self._was_active = True
            elif self._was_active:
                self.close()
        super().changeEvent(event)

    def keyPressEvent(self, event) -> None:
        if event.key() in (
            Qt.Key.Key_Escape,
            Qt.Key.Key_Return,
            Qt.Key.Key_Enter,
        ):
            self.close()
            return
        super().keyPressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        self._hover = event.position().toPoint()
        self.update()

    def mousePressEvent(self, event) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            self.close()
            return
        point = self._clamp(event.position().toPoint())
        self._point = point
        # Client space == overlay space, so the position needs no conversion.
        self._on_picked(point.x(), point.y())
        # One pick per open: closing immediately is what makes the picker exit,
        # and it removes any window where the overlay could still be bound to a
        # step the user has since navigated away from.
        self.close()

    def _clamp(self, point: QPoint) -> QPoint:
        return QPoint(
            max(0, min(point.x(), self.width() - 1)),
            max(0, min(point.y(), self.height() - 1)),
        )

    def closeEvent(self, event) -> None:
        if not self._closed:
            self._closed = True
            self._on_closed()
        super().closeEvent(event)

    # # Painting
    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        if self._background is not None:
            painter.drawPixmap(0, 0, self._background)
        else:
            painter.fillRect(self.rect(), QColor(theme.INK_900))

        # Dim slightly so the dot and hint stay readable over a busy screenshot.
        painter.fillRect(self.rect(), QColor(0, 0, 0, 70))

        # Under the dots and the crosshair: it's a warning about the map, not an object
        # you aim at, and a dot already placed in there must stay visible.
        if self._show_zones:
            self._paint_zone(painter)
        self._paint_hover(painter)
        # Context first, so the step being edited always draws on top of it.
        for dot in self._others:
            self._paint_dot(painter, QPoint(dot.x, dot.y), dot.step, slot_index(dot.slot), dim=True)
        if self._point is not None:
            self._paint_dot(painter, self._point, self._step_number, self._slot, dim=False)
        self._paint_hint(painter)
        painter.end()

    def _paint_zone(self, painter: QPainter) -> None:
        """The Start Game band: a tinted block with its label above it.

        `theme.WARN` (amber) is a colour no slot dot uses, so the band can't be read as a
        placement, and the tint is light enough to judge a placement against the ground it
        covers.
        """
        x, y, width, height = START_GAME_ZONE
        box = QRect(x, y, width, height)
        fill = QColor(theme.WARN)
        fill.setAlpha(90)
        painter.setBrush(fill)
        pen = QPen(QColor(theme.WARN))
        pen.setWidth(1)
        painter.setPen(pen)
        painter.drawRect(box)

        font = QFont(theme.FAMILY)
        font.setPixelSize(11)
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(QColor(theme.WARN))
        painter.drawText(self._zone_label_rect(box, font), Qt.AlignmentFlag.AlignCenter, ZONE_LABEL)

    def _zone_label_rect(self, box: QRect, font: QFont) -> QRect:
        """A rect wide enough for the whole label, centred on the band and kept on screen.

        Measured from the font, not taken from the band: the label is wider than the 252px
        band, so a band-width rect cut the first and last few characters off. Clamped to the
        widget so a band near an edge pushes the text inwards instead of off the client, and
        it drops inside the band when there is no room above.
        """
        text_width = min(QFontMetrics(font).horizontalAdvance(ZONE_LABEL) + 8, self.width())
        left = max(0, min(box.center().x() - text_width // 2, self.width() - text_width))
        if box.top() < 16:
            return QRect(left, box.top() + 2, text_width, 14)
        return QRect(left, box.top() - 16, text_width, 14)

    def _paint_hover(self, painter: QPainter) -> None:
        """The cursor. There is no OS cursor here — see `BlankCursor` in the constructor.

        Antialiasing off for these two lines only: a 1px line drawn with AA on is smeared
        across two rows at half intensity, which is exactly the blur that made the old
        cursor impossible to aim with.
        """
        if self._hover is None:
            return
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        pen = QPen(QColor(255, 255, 255, 90))
        pen.setWidth(1)
        painter.setPen(pen)
        x, y = self._hover.x(), self._hover.y()
        painter.drawLine(x - CROSSHAIR, y, x + CROSSHAIR, y)
        painter.drawLine(x, y - CROSSHAIR, x, y + CROSSHAIR)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

    def _paint_dot(
        self,
        painter: QPainter,
        point: QPoint,
        step_number: int,
        slot: int | None,
        dim: bool,
    ) -> None:
        """Draw one numbered dot. `dim` marks a step that isn't being edited, so
        the one you're placing stands out from the ones already set."""
        color = QColor(theme.slot_color(slot))
        radius = DOT_RADIUS - 2 if dim else DOT_RADIUS
        if dim:
            color.setAlpha(150)

        if not dim:
            halo = QColor(color)
            halo.setAlpha(70)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(halo)
            painter.drawEllipse(point, radius + 5, radius + 5)

        painter.setBrush(color)
        pen = QPen(QColor(255, 255, 255, 110 if dim else 255))
        pen.setWidth(1 if dim else 2)
        painter.setPen(pen)
        painter.drawEllipse(point, radius, radius)

        font = QFont(theme.FAMILY)
        font.setPixelSize(11 if dim else 13)
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(QColor(11, 13, 20, 170 if dim else 255))
        painter.drawText(
            QRect(point.x() - radius, point.y() - radius, radius * 2, radius * 2),
            Qt.AlignmentFlag.AlignCenter,
            str(step_number),
        )

    def _paint_hint(self, painter: QPainter) -> None:
        text = self._hint_text()
        font = QFont(theme.FAMILY)
        font.setPixelSize(12)
        font.setBold(True)
        painter.setFont(font)

        box = QRect(10, 10, self.width() - 20, 26)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(7, 8, 13, 210))
        painter.drawRoundedRect(box, 6, 6)
        painter.setPen(QColor(theme.TEXT))
        painter.drawText(box.adjusted(10, 0, -10, 0), Qt.AlignmentFlag.AlignVCenter, text)

    def _hint_text(self) -> str:
        where = (
            f"X {self._point.x()}  Y {self._point.y()}"
            if self._point is not None
            else "no coordinate set"
        )
        slot = f"slot {self._slot}" if self._slot else "no slot"
        prefix = f"{self._title} · " if self._title else ""
        return (
            f"{prefix}Step {self._step_number} ({slot}) — {where}"
            "   ·   click to set and close, Esc to cancel"
        )


REFERENCE_DIR_NAME = "reference"
# Challenge draws from the Story maps, so it can borrow their playfield pictures.
STORY = "Story"


def reference_path(images_dir: str, gamemode: str, stage: str, act: str = "") -> str | None:
    """Where a reference screenshot lives, or None without a full selection.

    Two shapes, because maps differ:
      images/reference/<Gamemode>/<Map>.png              one playfield per map (Story)
      images/reference/<Gamemode>/<Map>/<Act>.png        one per act (Raid — Spirit
                                                         City's acts are separate
                                                         areas of the same map)
    With `act` given this returns the per-act path; `load_reference` falls back to
    the per-map file, so Story's existing files keep working untouched.

    Names come from the content tables but still go through safe_component, since
    they end up as a path.
    """
    if not images_dir or not gamemode or not stage:
        return None
    parts = [images_dir, REFERENCE_DIR_NAME, safe_component(gamemode)]
    if act:
        parts += [safe_component(stage), f"{safe_component(act)}.png"]
    else:
        parts.append(f"{safe_component(stage)}.png")
    return os.path.join(*parts)


def load_reference(
    images_dir: str, gamemode: str, stage: str, act: str = ""
) -> QPixmap | None:
    """The saved screenshot for this target: the act's own file if there is one,
    otherwise the map's. None when neither exists or the file isn't an image.

    Challenge falls back to that same map's **Story** reference, because a challenge on
    Rose Kingdom is played on the Story Rose Kingdom playfield — the fight is harder, the
    ground is the same. Without this, planning a challenge config meant re-capturing a
    picture of a map that already had one.
    """
    candidates = [reference_path(images_dir, gamemode, stage, act)] if act else []
    candidates.append(reference_path(images_dir, gamemode, stage))
    if gamemode == CHALLENGE:
        candidates.append(reference_path(images_dir, STORY, stage))
    for path in candidates:
        if path is None or not os.path.isfile(path):
            continue
        pixmap = QPixmap(path)
        if not pixmap.isNull():
            return pixmap
    return None





def capture_pixmap(rect: tuple[int, int, int, int]) -> QPixmap | None:
    """Grab the Roblox client area with mss (already a dependency for image
    search). Returns None if the capture fails rather than raising into the UI."""
    try:
        import mss  # local import: only needed when a reference image is missing
    except ImportError:
        return None

    left, top, width, height = rect
    if width <= 0 or height <= 0:
        return None
    try:
        with mss.mss() as camera:
            shot = camera.grab({"left": left, "top": top, "width": width, "height": height})
            image = QImage(
                bytes(shot.rgb), shot.width, shot.height, shot.width * 3, QImage.Format.Format_RGB888
            )
            # QImage wraps the buffer without owning it; copy before the buffer dies.
            return QPixmap.fromImage(image.copy())
    except Exception as exc:  # mss raises its own errors for bad monitors/permissions
        print(f"Failed to capture Roblox for the placement picker: {exc}")
        return None
