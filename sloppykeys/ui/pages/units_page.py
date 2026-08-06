"""Units page: master-detail editor for the 72-step unit plan.

Left of this panel is the Roblox viewport (owned by the window). This panel is a
search + filter bar over a scrollable grid of 72 compact step chips, with a
detail editor below for the currently selected step. Edits write straight into
the plan, so switching chips or leaving the page needs no explicit save.
"""

from __future__ import annotations

import os
from typing import Callable

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from sloppykeys.content.units import (
    AUTOUPGRADE_OPTIONS,
    KIND_LABELS,
    KIND_SEQUENCE,
    KINDS,
    PRIORITY_OPTIONS,
    SLOT_OPTIONS,
    SLOT_PLACEHOLDER,
    TOTAL_STEPS,
    UPGRADE_DEFAULT,
    UPGRADE_OPTIONS,
    UnitPlan,
    UnitStep,
    autoupgrade_is_on,
    autoupgrade_presses,
    slot_index,
)

from .. import icons, theme
from ..placement_overlay import (
    PlacedDot,
    PlacementOverlay,
    capture_pixmap,
    load_reference,
)
from ..sequence_editor import SequenceEditor

GRID_COLS = 3
FILTERS = ("All", "On", "Off")


def _short(name: str, limit: int = 9) -> str:
    """Cut a custom name to what fits on a chip. Three per row in a ~408px panel
    leaves ~120px, so a long name has to be truncated somewhere; the full text is
    on the chip's tooltip and in the detail card."""
    name = (name or "").strip()
    return name if len(name) <= limit else f"{name[: limit - 1]}\u2026"


def _coord_pair(step: UnitStep) -> tuple[int, int] | None:
    """The step's stored coordinate, or None when it isn't a usable pair."""
    try:
        return (int(step.x), int(step.y))
    except (TypeError, ValueError):
        return None


def _placed_dots(plan: UnitPlan, exclude: int) -> list[PlacedDot]:
    """Every other step that already has a coordinate, for context on the map."""
    dots = []
    for step in plan.steps:
        if step.step == exclude:
            continue
        point = _coord_pair(step)
        if point is not None:
            dots.append(PlacedDot(step=step.step, x=point[0], y=point[1], slot=step.slot))
    return dots


class StepChip(QFrame):
    clicked = Signal(int)
    menuRequested = Signal(int, object)  # step number, global position

    def __init__(self, step_number: int) -> None:
        super().__init__()
        self.step_number = step_number
        self.setObjectName("stepChip")
        self.setFixedHeight(84)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        box = QVBoxLayout(self)
        box.setContentsMargins(8, 8, 8, 8)
        box.setSpacing(3)
        box.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._num = QLabel(f"#{step_number}")
        self._num.setObjectName("chipNum")
        self._num.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._badge = QLabel("+0")
        self._badge.setObjectName("chipBadge")
        self._badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._badge.setFixedHeight(22)

        self._sub = QLabel("Slot -")
        self._sub.setObjectName("chipSub")
        self._sub.setAlignment(Qt.AlignmentFlag.AlignCenter)

        box.addWidget(self._num)
        box.addWidget(self._badge, 0, Qt.AlignmentFlag.AlignCenter)
        box.addWidget(self._sub)

    def refresh(self, step: UnitStep) -> None:
        if step.is_sequence():
            # Sequence chips have no slot or upgrade level, so the badge carries
            # the action count instead — enough to spot them in the grid.
            count = len(step.actions)
            self._badge.setText(f"{count}")
            self._sub.setText("action" if count == 1 else "actions")
            self._sub.setStyleSheet(
                f"color: {theme.CYAN}; font-size: 10px; font-weight: 700;"
            )
        else:
            # Badge mirrors the chosen upgrade level, so +0 is a real state. Auto
            # upgrade takes the badge when it's left running, because then the
            # manual level isn't pressed at all.
            if autoupgrade_is_on(step.autoupgrade):
                self._badge.setText(f"A{autoupgrade_presses(step.autoupgrade)}")
            else:
                self._badge.setText(f"+{step.upgrades or UPGRADE_DEFAULT}")
            self._sub.setText(f"Slot {step.slot or '-'}")
            # Same colour as this slot's placement dot: two chips sharing a
            # colour are placing the same unit.
            self._sub.setStyleSheet(
                f"color: {theme.slot_color(slot_index(step.slot))}; "
                "font-size: 10px; font-weight: 700;"
            )
        # The custom name goes on the chip, after the number: naming a step is how
        # you find it again in a grid of 72, and the number stays because it's the
        # step's identity everywhere else (log lines, the detail badge, Reset).
        self._num.setText(f"#{self.step_number}  {_short(step.unit_name)}".rstrip())
        self._num.setToolTip(step.unit_name)
        self._num.setStyleSheet(
            f"color: {theme.TEXT if step.is_actionable() else theme.TEXT_FAINT};"
        )

    def set_selected(self, selected: bool) -> None:
        self.setObjectName("stepChipOn" if selected else "stepChip")
        self.style().unpolish(self)
        self.style().polish(self)

    def mousePressEvent(self, event) -> None:
        # Right-click selects *and* opens the menu: acting on a chip you haven't selected
        # would mean the detail card below shows a different step than the one you copied.
        self.clicked.emit(self.step_number)
        if event.button() == Qt.MouseButton.RightButton:
            self.menuRequested.emit(self.step_number, event.globalPosition().toPoint())


class DetailEditor(QWidget):
    """Edits a single step. Writes live into the step it was loaded with."""

    stepChanged = Signal(int)  # emits step number after any edit
    pickRequested = Signal(int)  # step number wants a coordinate picked
    actionPickRequested = Signal(int, int, str)  # step, action row, "from"/"to"
    resetRequested = Signal(int)  # step number should be cleared
    editingFinished = Signal()  # done editing a side task's config

    def __init__(self) -> None:
        super().__init__()
        self._step: UnitStep | None = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(8)

        # Header: number badge + custom name (fixed, never scrolls)
        header = QHBoxLayout()
        header.setSpacing(10)
        self._badge = QLabel("-")
        self._badge.setObjectName("numBadge")
        self._badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._badge.setFixedSize(34, 34)
        self._name = QLineEdit()
        self._name.setPlaceholderText("Custom name...")
        self._name.textChanged.connect(lambda v: self._set("unit_name", v.strip()))
        self._reset_btn = QPushButton(icons.UNDO)
        self._reset_btn.setToolTip("Reset this step only (leaves the rest of the config alone)")
        self._reset_btn.setFixedSize(32, 30)
        self._reset_btn.setStyleSheet(f"font-family: '{theme.ICON_FAMILY}'; padding: 0;")
        self._reset_btn.clicked.connect(self._request_reset)
        header.addWidget(self._badge)
        header.addWidget(self._name, 1)
        header.addWidget(self._reset_btn)
        outer.addLayout(header)

        # Only visible while editing a config the Run strip didn't choose. The Done
        # button is the way out: relying on "go and touch the Run strip" left no
        # visible exit, which is how you get stranded in a side task's config.
        self._editing_row = QWidget()
        editing_box = QHBoxLayout(self._editing_row)
        editing_box.setContentsMargins(0, 0, 0, 0)
        editing_box.setSpacing(6)
        self._editing = QLabel("")
        self._editing.setWordWrap(True)
        self._editing.setMinimumWidth(1)
        self._editing.setStyleSheet(
            f"color: {theme.WARN}; font-family: '{theme.ICON_FAMILY}'; font-size: 10px;"
        )
        self._editing_done = QPushButton("Done")
        self._editing_done.setToolTip("Stop editing this side task and go back to the run's config")
        self._editing_done.setFixedHeight(24)
        self._editing_done.setStyleSheet("padding: 1px 10px;")
        self._editing_done.clicked.connect(self.editingFinished.emit)
        editing_box.addWidget(self._editing, 1)
        editing_box.addWidget(self._editing_done)
        self._editing_row.setVisible(False)
        outer.addWidget(self._editing_row)

        # Kind switch: the two modes are mutually exclusive, and swapping the
        # whole form is what keeps either one readable in this space.
        kinds = QHBoxLayout()
        kinds.setSpacing(6)
        self._kind_buttons: dict[str, QPushButton] = {}
        for kind in KINDS:
            button = QPushButton(KIND_LABELS[kind])
            button.setObjectName("tab")
            button.setFixedHeight(28)
            button.clicked.connect(lambda _c=False, k=kind: self._set_kind(k))
            self._kind_buttons[kind] = button
            kinds.addWidget(button)
        kinds.addStretch(1)
        outer.addLayout(kinds)

        header_sep = QFrame()
        header_sep.setObjectName("sep")
        outer.addWidget(header_sep)

        # Two forms, one at a time: the unit fields or the sequence editor.
        self._stack = QStackedWidget()
        outer.addWidget(self._stack, 1)

        unit_page = QWidget()
        unit_layout = QVBoxLayout(unit_page)
        unit_layout.setContentsMargins(0, 0, 0, 0)
        unit_layout.setSpacing(8)
        self._stack.addWidget(unit_page)

        # Middle: scrollable settings between the fixed header and coords footer.
        middle = QScrollArea()
        middle.setObjectName("detail")
        middle.setWidgetResizable(True)
        middle_body = QWidget()
        unit_layout.addWidget(middle, 1)

        fields = QVBoxLayout(middle_body)
        fields.setContentsMargins(0, 0, 6, 0)
        fields.setSpacing(8)
        middle.setWidget(middle_body)

        # BASIC
        fields.addLayout(_group("BASIC"))
        # Dropdown: there are only six hotbar slots, and the slot is the unit's
        # visual identity, so picking from the real set beats typing a number.
        self._slot = _combo(SLOT_OPTIONS, SLOT_PLACEHOLDER)
        self._slot.currentIndexChanged.connect(
            lambda _i: self._set("slot", _val(self._slot))
        )
        self._priority = _combo(PRIORITY_OPTIONS, "Priority")
        self._priority.currentIndexChanged.connect(
            lambda _i: self._set("priority", _val(self._priority))
        )
        fields.addLayout(_pair("Slot #", self._slot, "Priority", self._priority))

        # No placeholder: 0 is a real level (placed, no upgrades bought), so every
        # entry is a valid choice and the value is read straight off the combo.
        self._upgrades = _plain_combo(UPGRADE_OPTIONS)
        self._upgrades.currentTextChanged.connect(
            lambda text: self._set("upgrades", text)
        )
        # Next to the manual level because it's the same decision, not a separate
        # action: with auto on, the game does the upgrading and the level on the
        # left is not pressed. The value is a press count of the auto-upgrade key —
        # the panel's control cycles 1..6 and the 7th press returns it to off.
        self._autoupgrade = QComboBox()
        for label, presses in AUTOUPGRADE_OPTIONS:
            self._autoupgrade.addItem(label, presses)
        self._autoupgrade.setToolTip(
            "The game's auto upgrade cycles: each press of the auto-upgrade key "
            "goes up one level, 1 to 6, and a 7th press turns it back off. "
            "Pick the level you want; the macro presses that many times. "
            "With 1-6 chosen, Upgrade Level is left alone."
        )
        self._autoupgrade.currentIndexChanged.connect(
            lambda _i: self._set("autoupgrade", int(self._autoupgrade.currentData()))
        )
        fields.addLayout(
            _pair("Upgrade Level", self._upgrades, "Auto upgrade", self._autoupgrade)
        )

        # TIMING
        fields.addLayout(_group("TIMING"))
        self._wait = QLineEdit()
        self._wait.setPlaceholderText("Wait (ms)")
        self._wait.textChanged.connect(lambda v: self._set("wait", v.strip()))
        # Sell delay: counted from the end of the step, not from placement, so a
        # unit can earn for a while before it's sold. Needs Sell on to do anything.
        self._sell_wait = QLineEdit()
        self._sell_wait.setPlaceholderText("Sell after (ms)")
        self._sell_wait.setToolTip(
            "With Sell on: how long to wait after the step's other settings finish, "
            "before selling. Blank sells immediately."
        )
        self._sell_wait.textChanged.connect(lambda v: self._set("sell_wait", v.strip()))
        fields.addLayout(_pair("Wait", self._wait, "Sell after", self._sell_wait))

        # ACTIONS — what the step does beyond setting the unit up. Auto upgrade used
        # to live here as a checkbox; it sits with Upgrade Level now, because the
        # two are alternatives rather than separate actions.
        fields.addLayout(_group("ACTIONS"))
        self._preplacement = QCheckBox("Pre-placement (run during the placement phase)")
        self._preplacement.toggled.connect(lambda on: self._set("preplacement", bool(on)))
        fields.addWidget(self._preplacement)

        self._sell = QCheckBox("Sell this unit instead of keeping it")
        self._sell.toggled.connect(lambda on: self._set("sell", bool(on)))
        fields.addWidget(self._sell)

        # A step turns on automatically once it has coordinates; no manual toggle.
        hint = QLabel("A step runs automatically once it has X/Y coordinates.")
        hint.setWordWrap(True)
        hint.setStyleSheet(f"color: {theme.TEXT_FAINT}; font-size: 10px;")
        fields.addWidget(hint)
        fields.addStretch(1)

        # Coordinates footer: fixed at the bottom, never scrolls.
        footer_sep = QFrame()
        footer_sep.setObjectName("sep")
        unit_layout.addWidget(footer_sep)
        coords = QHBoxLayout()
        coords.setSpacing(8)
        self._x = QLineEdit()
        self._x.setPlaceholderText("X")
        self._x.textChanged.connect(lambda v: self._set("x", v.strip()))
        self._y = QLineEdit()
        self._y.setPlaceholderText("Y")
        self._y.textChanged.connect(lambda v: self._set("y", v.strip()))
        self._set_btn = QPushButton("Set")
        self._set_btn.setToolTip("Pick this step's coordinate on the map")
        self._set_btn.clicked.connect(self._request_pick)
        coords.addWidget(QLabel("X"))
        coords.addWidget(self._x, 1)
        coords.addWidget(QLabel("Y"))
        coords.addWidget(self._y, 1)
        coords.addWidget(self._set_btn)
        unit_layout.addLayout(coords)

        # Sequence page
        self._sequence = SequenceEditor()
        self._sequence.changed.connect(self._on_sequence_changed)
        self._sequence.pickRequested.connect(self._on_action_pick)
        self._stack.addWidget(self._sequence)

        # Shared footer note: picker feedback for either form.
        self._coord_note = QLabel("")
        self._coord_note.setStyleSheet(f"color: {theme.TEXT_FAINT}; font-size: 10px;")
        outer.addWidget(self._coord_note)

        self.setEnabled(False)

    # # Kind switching
    def _set_kind(self, kind: str) -> None:
        if self._step is None or self._step.kind == kind:
            self._paint_kind(kind)
            return
        self._step.kind = kind
        self._paint_kind(kind)
        self._show_kind_page(kind)
        self.stepChanged.emit(self._step.step)

    def _paint_kind(self, kind: str) -> None:
        for name, button in self._kind_buttons.items():
            button.setObjectName("tabOn" if name == kind else "tab")
            button.style().unpolish(button)
            button.style().polish(button)

    def _show_kind_page(self, kind: str) -> None:
        self._stack.setCurrentIndex(1 if kind == KIND_SEQUENCE else 0)

    def _on_sequence_changed(self) -> None:
        if self._step is not None:
            self.stepChanged.emit(self._step.step)

    def _on_action_pick(self, row: int, which: str) -> None:
        if self._step is not None:
            self.actionPickRequested.emit(self._step.step, row, which)

    def apply_action_coords(self, row: int, which: str, x: int, y: int) -> None:
        self._sequence.apply_coords(row, which, x, y)

    def _request_reset(self) -> None:
        if self._step is not None:
            self.resetRequested.emit(self._step.step)

    def set_editing_note(self, target: str) -> None:
        """Name the config being edited when it isn't the Run strip's selection.

        Without this the page looks identical whether you are editing the run target or
        a challenge map, which is the ambiguity that produces "I edited the wrong
        config" an hour later.
        """
        if not target:
            self._editing.setText("")
            self._editing_row.setVisible(False)
            return
        self._editing.setText(f"Editing {target} — a side task, not the run target")
        self._editing_row.setVisible(True)

    def set_coord_note(self, text: str, ok: bool) -> None:
        color = theme.GOOD if ok else theme.BAD
        self._coord_note.setText(text)
        self._coord_note.setStyleSheet(f"color: {color}; font-size: 10px;")

    def load(self, step: UnitStep) -> None:
        self._step = None  # suppress writes while populating
        self.setEnabled(True)
        self._badge.setText(str(step.step))
        self._name.setText(step.unit_name)
        _set_combo(self._slot, step.slot)
        self._wait.setText(step.wait)
        self._sell_wait.setText(step.sell_wait)
        self._x.setText(step.x)
        self._y.setText(step.y)
        _set_combo(self._priority, step.priority)
        _set_plain_combo(self._upgrades, step.upgrades, UPGRADE_DEFAULT)
        # By data, not text: the entries are press counts and one of them reads
        # "7 (back to off)", so findText would never match it.
        self._autoupgrade.blockSignals(True)
        self._autoupgrade.setCurrentIndex(
            max(0, self._autoupgrade.findData(autoupgrade_presses(step.autoupgrade)))
        )
        self._autoupgrade.blockSignals(False)
        for box, value in (
            (self._sell, step.sell),
            (self._preplacement, step.preplacement),
        ):
            box.blockSignals(True)
            box.setChecked(bool(value))
            box.blockSignals(False)
        self._paint_kind(step.kind)
        self._show_kind_page(step.kind)
        # Bound by reference, so the editor's edits land in this step's list.
        self._sequence.load(step.actions)
        self._coord_note.setText("")
        self._step = step

    def _set(self, attr: str, value) -> None:
        if self._step is None:
            return
        setattr(self._step, attr, value)
        self.stepChanged.emit(self._step.step)

    def _request_pick(self) -> None:
        if self._step is not None:
            self.pickRequested.emit(self._step.step)

    def apply_coords(self, x: int, y: int) -> None:
        """Write a picked coordinate back into the fields (which write the step)."""
        self._x.setText(str(x))
        self._y.setText(str(y))


class UnitsPage(QWidget):
    def __init__(
        self,
        plan_provider: Callable[[], UnitPlan],
        get_rect: Callable[[], "tuple[int, int, int, int] | None"] | None = None,
        get_target: Callable[[], "tuple[str, str]"] | None = None,
        images_dir: str = "",
    ) -> None:
        super().__init__()
        self._plan_provider = plan_provider
        # One-shot clipboard for chip copy/paste. Deliberately not persisted: a copy that
        # outlives the session would paste settings whose context is long gone.
        self._copied: dict | None = None
        self._copied_from: int | None = None
        # Providers for the placement picker: where Roblox is, and which map's
        # reference screenshot to draw. Optional so the page still builds alone.
        self._get_rect = get_rect or (lambda: None)
        self._get_target = get_target or (lambda: ("", "", ""))
        self._images_dir = images_dir
        self._overlay: PlacementOverlay | None = None
        self._selected = 1
        self._filter = "All"

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        # Search + filter pills
        top = QHBoxLayout()
        top.setSpacing(6)
        self._search = QLineEdit()
        self._search.setPlaceholderText("Search...")
        self._search.textChanged.connect(lambda _v: self._apply_filter())
        top.addWidget(self._search, 1)
        self._filter_buttons: dict[str, QPushButton] = {}
        for name in FILTERS:
            btn = QPushButton(name)
            btn.setObjectName("pill")
            btn.setFixedHeight(30)
            btn.clicked.connect(lambda _c=False, n=name: self._set_filter(n))
            top.addWidget(btn)
            self._filter_buttons[name] = btn
        # No map-image capture button here: every image the macro uses is managed in
        # Settings > Vision, which lists each map/act row with its current picture.
        layout.addLayout(top)

        # Chip grid (its own bordered box)
        chips_box = QFrame()
        chips_box.setObjectName("sectionBox")
        chips_outer = QVBoxLayout(chips_box)
        chips_outer.setContentsMargins(10, 10, 10, 10)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        holder = QWidget()
        self._grid = QGridLayout(holder)
        self._grid.setHorizontalSpacing(10)
        self._grid.setVerticalSpacing(10)
        self._grid.setContentsMargins(0, 0, 6, 0)
        self._chips: list[StepChip] = []
        for number in range(1, TOTAL_STEPS + 1):
            chip = StepChip(number)
            chip.clicked.connect(self._select)
            chip.menuRequested.connect(self._open_chip_menu)
            self._chips.append(chip)
        scroll.setWidget(holder)
        chips_outer.addWidget(scroll)
        layout.addWidget(chips_box, 4)

        # Step detail (its own bordered box; scrolls internally)
        detail_box = QFrame()
        detail_box.setObjectName("sectionBox")
        detail_outer = QVBoxLayout(detail_box)
        detail_outer.setContentsMargins(12, 10, 12, 12)
        self._detail = DetailEditor()
        self._detail.stepChanged.connect(self._on_detail_changed)
        self._detail.pickRequested.connect(self._open_picker)
        self._detail.actionPickRequested.connect(self._open_action_picker)
        self._detail.resetRequested.connect(self._reset_step)
        detail_outer.addWidget(self._detail)
        layout.addWidget(detail_box, 5)

        self._set_filter("All")
        self.reload()

    # # Filtering / layout
    def _set_filter(self, name: str) -> None:
        self._filter = name
        for key, btn in self._filter_buttons.items():
            btn.setObjectName("pillOn" if key == name else "pill")
            btn.style().unpolish(btn)
            btn.style().polish(btn)
        self._apply_filter()

    def _apply_filter(self) -> None:
        plan = self._plan_provider()
        query = self._search.text().strip().lower()
        while self._grid.count():
            self._grid.takeAt(0)

        visible = 0
        for chip in self._chips:
            step = plan.step(chip.step_number)
            on = step.is_actionable()
            if self._filter == "On" and not on:
                chip.hide()
                continue
            if self._filter == "Off" and on:
                chip.hide()
                continue
            if query and query not in f"#{chip.step_number}" and query not in step.unit_name.lower():
                chip.hide()
                continue
            self._grid.addWidget(chip, visible // GRID_COLS, visible % GRID_COLS)
            chip.show()
            visible += 1

    # # Selection
    def _select(self, step_number: int) -> None:
        # A picker belongs to the step it was opened for; switching steps closes
        # it rather than leaving a stale one pointed at the previous step.
        if self._overlay is not None and step_number != self._selected:
            self._overlay.close()
        self._selected = step_number
        for chip in self._chips:
            chip.set_selected(chip.step_number == step_number)
        self._detail.load(self._plan_provider().step(step_number))

    # # Copy / paste between chips
    def _open_chip_menu(self, step_number: int, position) -> None:
        """Right-click menu on a chip: copy this step's settings, or paste onto it."""
        plan = self._plan_provider()
        menu = QMenu(self)
        copy_action = menu.addAction(f"Copy step {step_number}")
        source = self._copied_from
        paste_action = menu.addAction(
            f"Paste from step {source}" if source else "Paste"
        )
        # Nothing copied, or copied from this very chip: pasting would be a no-op, so the
        # entry is greyed rather than silently doing nothing.
        paste_action.setEnabled(self._copied is not None and source != step_number)

        chosen = menu.exec(position)
        if chosen is copy_action:
            self._copied = plan.step(step_number).copy_settings()
            self._copied_from = step_number
            self._detail.set_coord_note(
                f"Copied step {step_number} (coordinates not included).", ok=True
            )
            return
        if chosen is paste_action:
            self._paste_into(step_number)

    def _paste_into(self, step_number: int) -> None:
        if self._copied is None:
            return
        source = self._copied_from
        step = self._plan_provider().step(step_number)
        step.apply_settings(self._copied)
        # One paste per copy, by request: the clipboard clears so a stale copy can't be
        # dropped onto a third step days later.
        self._copied = None
        self._copied_from = None
        self._on_detail_changed(step_number)
        if self._selected == step_number:
            self._detail.load(step)
        self._detail.set_coord_note(
            f"Pasted step {source} onto step {step_number}. Its coordinates are unchanged.",
            ok=True,
        )

    # # Per-step reset
    def _reset_step(self, step_number: int) -> None:
        """Clear one chip. Deliberately separate from Reset Config, which wipes
        all 72 — this is the "I only got this one step wrong" case."""
        if self._overlay is not None:
            self._overlay.close()
        fresh = self._plan_provider().reset_step(step_number)
        self._on_detail_changed(step_number)
        if self._selected == step_number:
            self._detail.load(fresh)
        self._detail.set_coord_note(f"Step {step_number} reset.", ok=True)

    # # Placement picker
    def _open_action_picker(self, step_number: int, row: int, which: str) -> None:
        """Coordinate picking for one action inside a sequence. Same overlay as a
        placement pick — an ability click is captured exactly like a placement."""
        step = self._plan_provider().step(step_number)
        existing = None
        if 0 <= row < len(step.actions):
            action = step.actions[row]
            point = (action.to_x, action.to_y) if which == "to" else (action.x, action.y)
            existing = point if any(point) else None

        def write(x: int, y: int) -> None:
            self._detail.apply_action_coords(row, which, x, y)
            self._detail.set_coord_note(
                f"Action {row + 1} {'destination' if which == 'to' else 'point'} set to {x}, {y}",
                ok=True,
            )

        # Sequence actions target what's on screen right now, so: live.
        self._open_overlay_for(step_number, existing, write, slot=step.slot, live=True)

    def _open_picker(self, step_number: int) -> None:
        step = self._plan_provider().step(step_number)

        def picked(x: int, y: int) -> None:
            # Write to the step the picker was opened for, by number. Going
            # through the detail editor instead would land the coordinate on
            # whichever step happens to be loaded, so switching chips mid-pick
            # used to save onto the wrong step while the dot showed the old one.
            target = self._plan_provider().step(step_number)
            target.x = str(x)
            target.y = str(y)
            self._on_detail_changed(step_number)
            if self._selected == step_number:
                self._detail.load(target)
            self._detail.set_coord_note(f"Step {step_number} set to {x}, {y}", ok=True)

        self._open_overlay_for(
            step_number, _coord_pair(step), picked, slot=step.slot, live=False
        )

    def _open_overlay_for(
        self,
        step_number: int,
        existing: tuple[int, int] | None,
        on_picked,
        slot: str,
        live: bool,
    ) -> None:
        """Shared overlay setup for placement picks and sequence action picks.

        `live` picks the background: True forces a fresh capture (sequence
        actions), False prefers the selected map's saved reference (placements).
        """
        if self._overlay is not None:
            # Replace, don't refuse. A second Set — a double-click, or Set after clicking a
            # different chip — must leave exactly one picker open, on the step just asked
            # for. Refusing was safe only while a picker survived losing focus; now that
            # `PlacementOverlay` cancels on deactivation, refusing could end with the old
            # picker closed and no new one opened.
            self._overlay.close()
            self._overlay = None
        rect = self._get_rect()
        if rect is None:
            self._detail.set_coord_note("Roblox not found — start it first.", ok=False)
            return

        plan = self._plan_provider()
        gamemode, stage, act = self._get_target()

        # Unit placement prefers the saved reference so it can be planned from
        # anywhere; sequence actions always want the live screen.
        background = None
        source = "live view"
        if not live:
            background = load_reference(self._images_dir, gamemode, stage, act)
            if background is not None:
                where = f"{gamemode} / {stage}" + (f" / {act}" if act else "")
                source = f"{where} reference"
        if background is None:
            background = capture_pixmap(rect)
            if not live:
                source = (
                    f"live view — no reference image for {gamemode} / {stage}"
                    if gamemode and stage
                    else "live view — select a Gamemode / Map to use a reference"
                )
        if background is None:
            self._detail.set_coord_note("Could not capture the Roblox window.", ok=False)
            return

        def closed() -> None:
            self._overlay = None

        # Keep the reference: a local would be collected while the user is still
        # clicking, taking the overlay's signals with it.
        self._overlay = PlacementOverlay(
            rect=rect,
            step_number=step_number,
            slot=slot,
            existing=existing,
            background=background,
            on_picked=on_picked,
            on_closed=closed,
            title=source,
            others=_placed_dots(plan, exclude=step_number),
            # Placement picks only. A sequence action aims at live on-screen UI, and a
            # block drawn over it would hide the thing being aimed at.
            show_zones=not live,
        )
        self._overlay.show()
        self._overlay.raise_()
        self._overlay.activateWindow()
        self._overlay.setFocus()

    def _on_detail_changed(self, step_number: int) -> None:
        plan = self._plan_provider()
        for chip in self._chips:
            if chip.step_number == step_number:
                chip.refresh(plan.step(step_number))
                break
        if self._filter != "All":
            self._apply_filter()

    # # Public API (called by the window)
    def reload(self) -> None:
        plan = self._plan_provider()
        for chip in self._chips:
            chip.refresh(plan.step(chip.step_number))
        self._apply_filter()
        self._select(self._selected)

    def commit(self) -> None:
        # Edits are written live into the plan; nothing buffered to flush.
        return

    def set_editing_note(self, target: str) -> None:
        """Show which config is open when it isn't the Run strip's selection. Empty
        clears it."""
        self._detail.set_editing_note(target)

    @property
    def editing_finished(self):
        """The detail card's Done button, for MainWindow to connect to."""
        return self._detail.editingFinished


# # Small builders
def _group(title: str) -> QHBoxLayout:
    row = QHBoxLayout()
    row.setSpacing(8)
    label = QLabel(title)
    label.setObjectName("groupHead")
    line = QFrame()
    line.setObjectName("sep")
    row.addWidget(label)
    row.addWidget(line, 1)
    return row


def _pair(label_a: str, widget_a: QWidget, label_b: str, widget_b: QWidget | None) -> QHBoxLayout:
    row = QHBoxLayout()
    row.setSpacing(10)
    row.addWidget(_labeled(label_a, widget_a), 1)
    if widget_b is not None:
        row.addWidget(_labeled(label_b, widget_b), 1)
    else:
        row.addStretch(1)
    return row


def _labeled(label: str, widget: QWidget) -> QWidget:
    holder = QWidget()
    box = QVBoxLayout(holder)
    box.setContentsMargins(0, 0, 0, 0)
    box.setSpacing(3)
    caption = QLabel(label)
    caption.setObjectName("fieldLabel")
    box.addWidget(caption)
    box.addWidget(widget)
    return holder


def _combo(options: list[str], placeholder: str) -> QComboBox:
    combo = QComboBox()
    combo.addItem(placeholder)
    combo.addItems(options)
    return combo


def _plain_combo(options: list[str]) -> QComboBox:
    """Combo where every entry is a real value — no leading placeholder, so
    index 0 means the first option rather than "unset"."""
    combo = QComboBox()
    combo.addItems(options)
    return combo


def _set_plain_combo(combo: QComboBox, value: str, default: str) -> None:
    index = combo.findText(value or default, Qt.MatchFlag.MatchExactly)
    combo.setCurrentIndex(max(0, index))


def _set_combo(combo: QComboBox, value: str) -> None:
    if not value:
        combo.setCurrentIndex(0)
        return
    index = combo.findText(value, Qt.MatchFlag.MatchExactly)
    combo.setCurrentIndex(index if index > 0 else 0)


def _val(combo: QComboBox) -> str:
    return "" if combo.currentIndex() <= 0 else combo.currentText()
