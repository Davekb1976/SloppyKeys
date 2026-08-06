"""Task queue editor: the Run panel's Tasks tab.

A challenges **toggle**, then three target slots (gamemode / map / act with a run limit).
Challenges are deliberately not one of the slots: `TaskDirector.decide` returns a challenge
whenever one is runnable regardless of position, so a slot spent one of three places
storing a boolean. Now all three can be targets. The toggle keeps its own map picker,
because the game chooses which of the five challenge maps you get and every one of them
needs a `configs/Challenge/<Map>.json` plan in advance.

Saves on every edit like the Route tab and Settings — there is no Save button, because a
half-saved queue is worse than none.

Reads and writes nothing itself: it emits `slotsChanged` / `challengesToggled` and
MainWindow talks to `TaskStore` / `AppSettings`, the same split `PositionEditor` uses.
"""

from __future__ import annotations

from typing import Callable

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from sloppykeys.config.tasks import (
    KIND_LABELS,
    KIND_OFF,
    KIND_TARGET,
    KINDS,
    LIMIT_MAX,
    LIMIT_MIN,
    MAX_SLOTS,
    TaskSlot,
)
from sloppykeys.config.tasks import challenge_maps
from sloppykeys.content.gamemodes import (
    CHALLENGE,
    FARM_GAMEMODE_NAMES,
    has_targets,
    labels_for,
    maps_for,
    targets_for,
)

from . import theme


class TaskRow(QFrame):
    """One slot. Owns its own widgets; the parent owns the data."""

    changed = Signal()
    editRequested = Signal(str, str, str)  # gamemode, map, act — open this config

    def __init__(
        self,
        number: int,
        maps_provider: Callable[[str], list[str]],
        targets_provider: Callable[[str, str], list[str]],
    ) -> None:
        super().__init__()
        self.setObjectName("sectionBox")
        self._number = number
        self._maps_for = maps_provider
        self._targets_for = targets_provider
        self._slot = TaskSlot()
        self._loading = False

        box = QVBoxLayout(self)
        box.setContentsMargins(8, 6, 8, 8)
        box.setSpacing(5)

        head = QHBoxLayout()
        head.setSpacing(6)
        badge = QLabel(str(number))
        badge.setObjectName("chipBadge")
        badge.setFixedHeight(20)
        self._kind = QComboBox()
        for kind in KINDS:
            self._kind.addItem(KIND_LABELS[kind], kind)
        self._kind.currentIndexChanged.connect(self._on_kind_changed)
        self._limit_label = QLabel("Runs")
        self._limit = QSpinBox()
        self._limit.setRange(LIMIT_MIN, LIMIT_MAX)
        self._limit.setFixedWidth(64)
        self._limit.setToolTip(
            "How many matches to run before moving to the next slot. Only matters "
            "with two targets queued."
        )
        self._limit.valueChanged.connect(self._on_limit_changed)
        head.addWidget(badge)
        head.addWidget(self._kind, 1)
        head.addWidget(self._limit_label)
        head.addWidget(self._limit)
        box.addLayout(head)

        # Target selectors on their own rows: three combos side by side don't fit
        # the ~408px run panel.
        self._target = QWidget()
        grid = QGridLayout(self._target)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(6)
        grid.setVerticalSpacing(4)
        grid.setColumnStretch(1, 1)
        self._gamemode = QComboBox()
        self._gamemode.addItems(FARM_GAMEMODE_NAMES)
        self._gamemode.currentIndexChanged.connect(lambda _i: self._on_gamemode_changed())
        self._map = QComboBox()
        self._map.currentIndexChanged.connect(lambda _i: self._on_map_changed())
        self._act = QComboBox()
        self._act.currentIndexChanged.connect(lambda _i: self._on_act_changed())
        self._map_label = QLabel("Map")
        self._act_label = QLabel("Act")
        for row, (label, combo) in enumerate(
            (
                (QLabel("Gamemode"), self._gamemode),
                (self._map_label, self._map),
                (self._act_label, self._act),
            )
        ):
            label.setStyleSheet(f"color: {theme.TEXT_DIM}; font-size: 11px;")
            grid.addWidget(label, row, 0)
            grid.addWidget(combo, row, 1)
        box.addWidget(self._target)

        # Opens this slot's own unit config. The challenge maps have their own picker up
        # beside the toggle, since which one you get isn't this slot's business.
        edit_row = QHBoxLayout()
        edit_row.setSpacing(6)
        edit_row.addStretch(1)
        self._edit = QPushButton("Edit units")
        self._edit.setFixedHeight(26)
        self._edit.setStyleSheet("padding: 2px 8px;")
        self._edit.clicked.connect(self._request_edit)
        edit_row.addWidget(self._edit)
        box.addLayout(edit_row)

        self._summary = QLabel("")
        self._summary.setWordWrap(True)
        self._summary.setStyleSheet(f"color: {theme.TEXT_FAINT}; font-size: 10px;")
        box.addWidget(self._summary)

        self.load(TaskSlot())

    # # Data in / out
    def load(self, slot: TaskSlot) -> None:
        self._loading = True
        self._slot = slot
        index = self._kind.findData(slot.kind)
        self._kind.setCurrentIndex(max(0, index))
        if slot.gamemode and self._gamemode.findText(slot.gamemode) >= 0:
            self._gamemode.setCurrentText(slot.gamemode)
        self._fill_maps(slot.map_name, slot.act)
        self._limit.setValue(slot.limit)
        self._loading = False
        self._apply_visibility()

    def slot(self) -> TaskSlot:
        return self._slot

    # # Reactions
    def _on_kind_changed(self) -> None:
        # Guarded like the other reactions: `load()` sets this combo, which fires here
        # *before* the gamemode/map/act combos are filled. Unguarded, it ran `_read_target`
        # against the still-default combos, overwrote the slot being loaded with "Story /
        # School Grounds / Act 1", and emitted a save of that — so restoring a saved queue
        # silently rewrote it to the defaults. That was the "it won't keep my Events task"
        # bug, and it hit any non-default slot, not just Events.
        if self._loading:
            return
        kind = self._kind.currentData() or KIND_OFF
        self._slot.kind = kind
        self._apply_visibility()
        if kind == KIND_TARGET:
            # Fill from the combos, which may already hold a usable selection.
            self._read_target()
        self._emit()

    def _on_limit_changed(self, value: int) -> None:
        if self._loading:
            return
        self._slot.limit = int(value)
        self._emit()

    def _on_gamemode_changed(self) -> None:
        if self._loading:
            return
        self._fill_maps()
        self._read_target()
        self._emit()

    def _on_map_changed(self) -> None:
        if self._loading:
            return
        self._fill_acts()
        self._read_target()
        self._emit()

    def _on_act_changed(self) -> None:
        if self._loading:
            return
        self._read_target()
        self._emit()

    # # Selector filling
    def _fill_maps(self, wanted_map: str = "", wanted_act: str = "") -> None:
        gamemode = self._gamemode.currentText()
        map_label, act_label = labels_for(gamemode)
        self._map_label.setText(map_label)
        self._act_label.setText(act_label)
        was_loading = self._loading
        self._loading = True
        self._map.clear()
        self._map.addItems(self._maps_for(gamemode))
        if wanted_map and self._map.findText(wanted_map) >= 0:
            self._map.setCurrentText(wanted_map)
        self._loading = was_loading
        self._fill_acts(wanted_act)

    def _fill_acts(self, wanted: str = "") -> None:
        gamemode = self._gamemode.currentText()
        map_name = self._map.currentText()
        acts = self._targets_for(gamemode, map_name) if has_targets(gamemode) else []
        was_loading = self._loading
        self._loading = True
        self._act.clear()
        self._act.addItems(acts)
        if wanted and self._act.findText(wanted) >= 0:
            self._act.setCurrentText(wanted)
        self._loading = was_loading
        self._has_acts = bool(acts)
        self._act.setVisible(self._has_acts)
        self._act_label.setVisible(self._has_acts)

    def _read_target(self) -> None:
        self._slot.gamemode = self._gamemode.currentText()
        self._slot.map_name = self._map.currentText()
        # Tracked as data, not widget visibility: this tab lives in a QStackedWidget,
        # so every control here reports not-visible whenever another tab is showing
        # and the act would be dropped (the same trap PositionEditor documents).
        self._slot.act = self._act.currentText() if getattr(self, "_has_acts", False) else ""

    def _request_edit(self) -> None:
        """Open this task's unit config in the Units page."""
        if (self._kind.currentData() or KIND_OFF) == KIND_TARGET:
            self.editRequested.emit(self._slot.gamemode, self._slot.map_name, self._slot.act)

    def _apply_visibility(self) -> None:
        is_target = (self._kind.currentData() or KIND_OFF) == KIND_TARGET
        self._target.setVisible(is_target)
        self._limit.setVisible(is_target)
        self._limit_label.setVisible(is_target)
        self._edit.setVisible(is_target)
        self.refresh_summary()

    def refresh_summary(self) -> None:
        note = self._slot.summary()
        if self._slot.kind == KIND_TARGET and not self._slot.is_runnable():
            note = f"{note} — pick a {labels_for(self._slot.gamemode)[0]} to finish it"
        self._summary.setText(note)

    def _emit(self) -> None:
        self.refresh_summary()
        self.changed.emit()


class TaskEditor(QWidget):
    """The Tasks tab: the challenges toggle, three `TaskRow`s and one note."""

    slotsChanged = Signal(object)  # list[TaskSlot] — save me
    challengesToggled = Signal(bool)  # run_challenges — save me
    editRequested = Signal(str, str, str)  # gamemode, map, act — open this config

    def __init__(self, maps_provider=None, targets_provider=None) -> None:
        """The two providers are the same contract as `RunPage` — Events supplies its
        maps and acts from `routes.json`, not from the gamemode table."""
        super().__init__()
        # Set before any widget exists: `_on_challenges_toggled` reads it, and a signal
        # firing during construction must not be mistaken for a user edit.
        self._loading = True
        maps_for_gamemode = maps_provider or maps_for
        targets_for_map = targets_provider or targets_for

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(6)
        root.addWidget(self._build_challenge_box())

        self._rows: list[TaskRow] = []
        for number in range(1, MAX_SLOTS + 1):
            row = TaskRow(number, maps_for_gamemode, targets_for_map)
            row.changed.connect(self._on_row_changed)
            row.editRequested.connect(self.editRequested.emit)
            self._rows.append(row)
            root.addWidget(row)

        self._note = QLabel("")
        self._note.setWordWrap(True)
        self._note.setStyleSheet(f"color: {theme.TEXT_FAINT}; font-size: 10px;")
        root.addWidget(self._note)
        root.addStretch(1)
        self._loading = False
        self._refresh_note()

    # # The challenges toggle
    def _build_challenge_box(self) -> QWidget:
        """Challenges as one switch, above the queue it preempts.

        The map picker stays: the game decides which of the five challenge maps is offered,
        so all five need a plan whether or not any target names them. Its Edit units button
        is the only way to reach `configs/Challenge/<Map>.json` from here.
        """
        box = QFrame()
        box.setObjectName("sectionBox")
        column = QVBoxLayout(box)
        column.setContentsMargins(8, 6, 8, 8)
        column.setSpacing(5)

        self._challenges = QCheckBox("Run daily challenges first")
        self._challenges.setToolTip(
            "Challenges preempt the queue: while one is offered and unplayed this "
            "rotation it runs before any target, then the targets fill the gap."
        )
        self._challenges.toggled.connect(self._on_challenges_toggled)
        column.addWidget(self._challenges)

        edit_row = QHBoxLayout()
        edit_row.setSpacing(6)
        self._edit_map = QComboBox()
        self._edit_map.addItems(challenge_maps())
        self._edit_map.setToolTip("Which challenge map's unit config to open")
        edit = QPushButton("Edit units")
        edit.setFixedHeight(26)
        edit.setStyleSheet("padding: 2px 8px;")
        # No act: Challenge saves one plan per map (`configs/Challenge/<Map>.json`).
        edit.clicked.connect(
            lambda: self.editRequested.emit(CHALLENGE, self._edit_map.currentText(), "")
        )
        edit_row.addWidget(self._edit_map, 1)
        edit_row.addWidget(edit)
        column.addLayout(edit_row)
        return box

    def _on_challenges_toggled(self, enabled: bool) -> None:
        if self._loading:
            return
        self._refresh_note()
        self.challengesToggled.emit(bool(enabled))

    def set_challenges(self, enabled: bool) -> None:
        """Called by MainWindow with the stored setting. Guarded so restoring it doesn't
        echo straight back as a save — the same `_loading` discipline `TaskRow` uses."""
        self._loading = True
        self._challenges.setChecked(bool(enabled))
        self._loading = False
        self._refresh_note()

    def load(self, slots: list[TaskSlot]) -> None:
        for row, slot in zip(self._rows, slots):
            row.load(slot)
        self._refresh_note()

    def slots(self) -> list[TaskSlot]:
        return [row.slot() for row in self._rows]

    def refresh_options(self) -> None:
        """Re-read the provider lists after an event was added or deleted in the
        Route tab, keeping each row's selection if it survived."""
        for row in self._rows:
            row.load(row.slot())
        self._refresh_note()

    def _on_row_changed(self) -> None:
        self._refresh_note()
        self.slotsChanged.emit(self.slots())

    def _refresh_note(self) -> None:
        challenge = self._challenges.isChecked()
        targets = [slot for slot in self.slots() if slot.is_runnable()]
        if not challenge and not targets:
            self._note.setText(
                "Nothing queued — F1 runs the Run strip's selection, looping that one target."
            )
            return
        order = []
        if challenge:
            order.append("challenges first (all three)")
        if targets:
            order.append(
                " then ".join(
                    f"{slot.map_name or slot.gamemode} x{slot.limit}" for slot in targets
                )
            )
        tail = ", then loops." if targets else "."
        if challenge and not targets:
            tail = ", then idles until the next rotation — queue a target to fill the gap."
        self._note.setText(" \u2192 ".join(order) + tail)
