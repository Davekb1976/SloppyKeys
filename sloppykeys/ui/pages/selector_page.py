"""Selector screen: choose which gamemode the macro runs.

Shown on launch. Picking a card sets the active gamemode and moves to the Run
view. Reachable again from the gamemode button in the titlebar.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from sloppykeys.content.gamemodes import GAMEMODES, TASK_SELECTION

from .. import theme
from ..glow import HoverGlow

COLS = 3


class GamemodeCard(QFrame):
    clicked = Signal(str)

    def __init__(self, name: str, subtitle: str, accent: str) -> None:
        super().__init__()
        self._name = name
        self.setObjectName("selCard")
        self.setStyleSheet(
            f"QFrame#selCard {{ background: {theme.INK_850}; border: 1px solid {theme.LINE};"
            f" border-radius: 12px; }}"
            f"QFrame#selCard:hover {{ border-color: {accent}; }}"
        )
        self.setFixedHeight(76)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        row = QHBoxLayout(self)
        row.setContentsMargins(14, 12, 14, 12)
        row.setSpacing(12)

        badge = QLabel(name[:1])
        badge.setFixedSize(40, 40)
        badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        badge.setStyleSheet(
            f"background: {accent}; color: #0A0C13; border-radius: 12px;"
            f" font-size: 18px; font-weight: 800;"
        )
        row.addWidget(badge)

        text = QVBoxLayout()
        text.setSpacing(2)
        title = QLabel(name)
        title.setStyleSheet(f"font-size: 14px; font-weight: 700; color: {theme.TEXT};")
        sub = QLabel(subtitle)
        sub.setStyleSheet(f"font-size: 11px; color: {theme.TEXT_FAINT};")
        text.addWidget(title)
        text.addWidget(sub)
        row.addLayout(text)
        row.addStretch(1)

        self._glow = HoverGlow(self, accent, radius=22)

    def mousePressEvent(self, _event) -> None:
        self.clicked.emit(self._name)


class SelectorPage(QWidget):
    gamemodeChosen = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(4)

        title = QLabel("Selectors")
        title.setObjectName("h1")
        subtitle = QLabel("Choose what the macro runs")
        subtitle.setStyleSheet(f"color: {theme.TEXT_FAINT}; font-size: 12px;")
        layout.addWidget(title)
        layout.addWidget(subtitle)
        layout.addSpacing(12)

        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(12)
        # Side tasks (Challenge) are played by the macro but never chosen here:
        # they are entered from inside a match, and picking one as the run target
        # would mean an F1 with no lobby chain to follow.
        cards = [
            (name, gamemode)
            for name, gamemode in GAMEMODES.items()
            if not gamemode.side_task
        ]
        # Task is a card but not a gamemode: choosing it runs the queue from
        # Settings > Tasks instead of a single target, so it carries no map count.
        task_card = GamemodeCard(
            TASK_SELECTION, "Your queue \u00b7 up to 3 slots", theme.ACCENT
        )
        task_card.clicked.connect(self.gamemodeChosen.emit)

        for position, (name, gamemode) in enumerate(cards):
            accent = theme.GAMEMODE_ACCENTS.get(name, theme.VIOLET)
            # A custom gamemode has no map count to show: its events are whatever
            # routes the user has built, and the table here doesn't know them.
            subtitle_text = (
                f"Your routes \u00b7 {gamemode.target_label}"
                if gamemode.custom
                else f"{len(gamemode.maps)} maps \u00b7 {gamemode.target_label}"
            )
            card = GamemodeCard(name, subtitle_text, accent)
            card.clicked.connect(self.gamemodeChosen.emit)
            grid.addWidget(card, position // COLS, position % COLS)
        last = len(cards)
        grid.addWidget(task_card, last // COLS, last % COLS)
        for col in range(COLS):
            grid.setColumnStretch(col, 1)
        layout.addLayout(grid)
        layout.addStretch(1)
