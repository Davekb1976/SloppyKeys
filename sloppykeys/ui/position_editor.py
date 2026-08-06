"""Start-position editor: the ordered movement holds for one target.

Same shape as the sequence editor — a reorderable list plus a field row for the
selection — but deliberately smaller: a plan is only ever "hold a movement key for
n milliseconds", so the field row is one dropdown and one number.

Owns its own Gamemode / Map / Act selectors because a plan belongs to a target, not
to the run that happens to be loaded. Reads and writes nothing itself: it emits
`targetChanged` (asking to be filled) and `movesChanged` (asking to be saved), and
MainWindow talks to `StartPositionStore`.
"""

from __future__ import annotations

from typing import Callable

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from sloppykeys.content.gamemodes import (
    GAMEMODE_NAMES,
    has_targets,
    labels_for,
    maps_for,
    targets_for,
)
from sloppykeys.content.start_position import (
    MAX_HOLD_MS,
    MIN_HOLD_MS,
    MOVE_KEYS,
    MOVE_LABELS,
    PositionMove,
    total_hold_ms,
)

from . import icons, theme


class PositionEditor(QWidget):
    targetChanged = Signal(str, str, str)   # gamemode, map, act — fill me
    movesChanged = Signal(str, str, str, object)  # gamemode, map, act, list[PositionMove]
    resetRequested = Signal(str, str, str)  # gamemode, map, act — back to the preset

    def __init__(self, maps_provider=None, targets_provider=None) -> None:
        """`maps_provider(gamemode)` / `targets_provider(gamemode, map)` override the
        static tables, same contract as `RunPage`.

        Events has no maps in `content.gamemodes` — they're the routes the user
        built — so without these its Map dropdown comes up empty and no start
        position can be set for an event.
        """
        super().__init__()
        self._maps_for = maps_provider or maps_for
        self._targets_for = targets_provider or targets_for
        self._moves: list[PositionMove] = []
        self._loading = False
        # Whether the current gamemode has an act dimension at all. Tracked as data
        # because widget visibility can't answer it: this editor lives inside a
        # QStackedWidget page, so every control here reports not-visible whenever
        # another tab or page is showing, and target() would drop the act.
        self._has_acts = False

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(8)

        root.addWidget(self._build_target())
        root.addWidget(self._build_list(), 1)
        root.addLayout(self._build_buttons())
        root.addWidget(self._build_fields())

        self._summary = QLabel("")
        self._summary.setWordWrap(True)
        self._summary.setStyleSheet(f"color: {theme.TEXT_FAINT}; font-size: 10px;")
        root.addWidget(self._summary)

        self._fill_maps()

    # # Target selectors
    def _build_target(self) -> QWidget:
        """One row per selector: this editor lives in the right-hand panel, where
        three combos side by side would run off the edge."""
        holder = QWidget()
        grid = QGridLayout(holder)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(4)
        grid.setColumnStretch(1, 1)

        self._gamemode = QComboBox()
        self._gamemode.addItems(GAMEMODE_NAMES)
        self._gamemode.currentIndexChanged.connect(lambda _i: self._fill_maps())

        self._map = QComboBox()
        self._map.currentIndexChanged.connect(lambda _i: self._fill_acts())

        self._act = QComboBox()
        self._act.currentIndexChanged.connect(lambda _i: self._request_target())

        self._act_label = QLabel("Act")
        for row, (label, combo) in enumerate(
            (
                (QLabel("Gamemode"), self._gamemode),
                (QLabel("Map"), self._map),
                (self._act_label, self._act),
            )
        ):
            label.setStyleSheet(f"color: {theme.TEXT_DIM}; font-size: 11px;")
            grid.addWidget(label, row, 0)
            grid.addWidget(combo, row, 1)
        return holder

    def _fill_maps(self) -> None:
        gamemode = self._gamemode.currentText()
        map_label, act_label = labels_for(gamemode)
        self._act_label.setText(act_label)
        self._map.blockSignals(True)
        self._map.clear()
        self._map.addItems(self._maps_for(gamemode))
        self._map.blockSignals(False)
        self._fill_acts()

    def _fill_acts(self) -> None:
        gamemode = self._gamemode.currentText()
        map_name = self._map.currentText()
        acts = self._targets_for(gamemode, map_name) if has_targets(gamemode) else []
        self._act.blockSignals(True)
        self._act.clear()
        self._act.addItems(acts)
        self._act.blockSignals(False)
        # A gamemode with no act dimension (Expedition) stores one plan per map.
        self._has_acts = bool(acts)
        self._act.setVisible(self._has_acts)
        self._act_label.setVisible(self._has_acts)
        self._request_target()

    def refresh_options(self) -> None:
        """Re-read the provider lists, keeping the selection if it survived.

        A custom event added or deleted in the Route tab changes what this editor
        can offer, and Settings can be open while that happens.
        """
        gamemode, map_name, act = self.target()
        self._fill_maps()
        if map_name and self._map.findText(map_name) >= 0:
            self._map.setCurrentText(map_name)  # cascades into the act combo
            if act and self._act.findText(act) >= 0:
                self._act.setCurrentText(act)
        elif gamemode:
            self._request_target()

    def _request_target(self) -> None:
        gamemode, map_name, act = self.target()
        if not map_name:
            return
        self.targetChanged.emit(gamemode, map_name, act)

    def target(self) -> tuple[str, str, str]:
        act = self._act.currentText() if self._has_acts else ""
        return (self._gamemode.currentText(), self._map.currentText(), act)

    # # List + buttons
    def _build_list(self) -> QWidget:
        self._list = QListWidget()
        self._list.setObjectName("actionList")
        self._list.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self._list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._list.setMinimumHeight(150)
        self._list.currentRowChanged.connect(lambda _r: self._show_fields())
        self._list.model().rowsMoved.connect(self._on_rows_moved)
        return self._list

    def _build_buttons(self) -> QHBoxLayout:
        buttons = QHBoxLayout()
        buttons.setSpacing(6)
        buttons.addWidget(self._icon_button(icons.PLUS, "Add a move below the selection", self._add))
        buttons.addStretch(1)
        for glyph, tip, handler in (
            (icons.UP, "Move up", lambda: self._reorder(-1)),
            (icons.DOWN, "Move down", lambda: self._reorder(1)),
            (icons.TRASH, "Delete", self._delete),
        ):
            buttons.addWidget(self._icon_button(glyph, tip, handler))
        reset = QPushButton(f"{icons.REFRESH}  Preset")
        reset.setToolTip("Discard this target's edits and go back to its built-in plan")
        reset.setFixedHeight(28)
        reset.setStyleSheet(f"font-family: '{theme.ICON_FAMILY}'; padding: 2px 10px;")
        reset.clicked.connect(self._reset)
        buttons.addWidget(reset)
        return buttons

    def _icon_button(self, glyph: str, tip: str, handler: Callable[[], None]) -> QPushButton:
        button = QPushButton(glyph)
        button.setToolTip(tip)
        button.setFixedSize(30, 28)
        button.setStyleSheet(f"font-family: '{theme.ICON_FAMILY}'; padding: 0;")
        button.clicked.connect(handler)
        return button

    # # Field row
    def _build_fields(self) -> QWidget:
        self._fields = QWidget()
        row = QHBoxLayout(self._fields)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)

        self._key = QComboBox()
        for key in MOVE_KEYS:
            self._key.addItem(MOVE_LABELS[key], key)
        self._key.setFixedWidth(120)
        self._key.currentIndexChanged.connect(lambda _i: self._write("key", self._key.currentData()))

        self._hold = QSpinBox()
        self._hold.setRange(MIN_HOLD_MS, MAX_HOLD_MS)
        self._hold.setSingleStep(100)
        self._hold.setSuffix(" ms")
        self._hold.setFixedWidth(100)
        self._hold.valueChanged.connect(lambda value: self._write("hold_ms", int(value)))

        for widget in (QLabel("Key"), self._key, QLabel("Hold"), self._hold):
            row.addWidget(widget)
        row.addStretch(1)
        return self._fields

    def _show_fields(self) -> None:
        row = self._list.currentRow()
        if not 0 <= row < len(self._moves):
            self._fields.setEnabled(False)
            return
        self._fields.setEnabled(True)
        move = self._moves[row]
        self._loading = True
        index = self._key.findData(move.key)
        if index >= 0:
            self._key.setCurrentIndex(index)
        self._hold.setValue(move.hold_ms)
        self._loading = False

    def _write(self, attr: str, value) -> None:
        if self._loading or value is None:
            return
        row = self._list.currentRow()
        if not 0 <= row < len(self._moves):
            return
        setattr(self._moves[row], attr, value)
        self._refresh_row(row)
        self._emit_changed()

    # # Data in / out
    def set_moves(self, moves: list[PositionMove]) -> None:
        """Fill the list for the current target. Called after targetChanged."""
        self._moves = list(moves)
        self._refresh_list(select=0 if self._moves else -1)

    def moves(self) -> list[PositionMove]:
        return list(self._moves)

    def _emit_changed(self) -> None:
        gamemode, map_name, act = self.target()
        if not map_name:
            return
        self.movesChanged.emit(gamemode, map_name, act, list(self._moves))
        self._refresh_summary()

    # # List maintenance
    def _refresh_list(self, select: int) -> None:
        self._loading = True
        self._list.blockSignals(True)
        self._list.clear()
        for position, move in enumerate(self._moves, start=1):
            self._list.addItem(QListWidgetItem(f"{position}.  {move.summary()}"))
        self._list.blockSignals(False)
        if 0 <= select < self._list.count():
            self._list.setCurrentRow(select)
        self._loading = False
        self._show_fields()
        self._refresh_summary()

    def _refresh_row(self, row: int) -> None:
        item = self._list.item(row)
        if item is not None:
            item.setText(f"{row + 1}.  {self._moves[row].summary()}")

    def _refresh_summary(self) -> None:
        gamemode, map_name, act = self.target()
        where = " / ".join(part for part in (gamemode, map_name, act) if part) or "no target"
        if not self._moves:
            self._summary.setText(f"{where}: no movement — the run starts placing straight away.")
            return
        seconds = total_hold_ms(self._moves) / 1000.0
        self._summary.setText(
            f"{where}: {len(self._moves)} moves, {seconds:.1f}s of walking, "
            "run once right after the camera step."
        )

    def _on_rows_moved(self, _parent, start: int, _end: int, _dest, destination: int) -> None:
        """Mirror a drag-reorder into the data. Qt reports the destination as the
        index *before* removal, so shift it when moving down."""
        if self._loading or not 0 <= start < len(self._moves):
            return
        target = destination if destination < start else destination - 1
        moved = self._moves.pop(start)
        self._moves.insert(max(0, min(target, len(self._moves))), moved)
        self._refresh_list(select=max(0, min(target, len(self._moves) - 1)))
        self._emit_changed()

    # # Commands
    def _add(self) -> None:
        row = self._list.currentRow()
        index = row + 1 if row >= 0 else len(self._moves)
        self._moves.insert(index, PositionMove())
        self._refresh_list(select=index)
        self._emit_changed()

    def _reorder(self, delta: int) -> None:
        row = self._list.currentRow()
        target = row + delta
        if not (0 <= row < len(self._moves) and 0 <= target < len(self._moves)):
            return
        self._moves[row], self._moves[target] = self._moves[target], self._moves[row]
        self._refresh_list(select=target)
        self._emit_changed()

    def _delete(self) -> None:
        row = self._list.currentRow()
        if not 0 <= row < len(self._moves):
            return
        self._moves.pop(row)
        self._refresh_list(select=min(row, len(self._moves) - 1))
        # Emitted even when the list is now empty: an empty plan is a real answer,
        # and saving it is what stops a preset coming back on the next read.
        self._emit_changed()

    def _reset(self) -> None:
        gamemode, map_name, act = self.target()
        if not map_name:
            return
        self.resetRequested.emit(gamemode, map_name, act)
