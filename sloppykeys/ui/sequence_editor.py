"""Sequence editor: the ordered action list for a Sequence step.

A list of input primitives (see content/units.StepAction) with reordering,
insertion around the selection, and a field row that shows only the fields the
selected action type actually uses. Edits write straight into the step's action
list, matching how the unit form behaves.

Coordinates are picked with the same placement overlay the unit form uses, so an
ability click is captured exactly like a placement.
"""

from __future__ import annotations

import os
from typing import Callable

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from sloppykeys.content.units import (
    ACTION_FIELDS,
    ACTION_FIND_CLICK,
    ACTION_LABELS,
    ACTION_TYPES,
    ACTION_WAIT,
    ACTION_WAVE,
    BUTTON_OPTIONS,
    WAVE_MAX,
    StepAction,
)
from sloppykeys.core.image_search import ImageSearchEngine

from . import icons, theme
from .macro_tester import RegionOverlay
from .widgets import SecondsSpin

RectProvider = Callable[[], "tuple[int, int, int, int] | None"]


class SequenceEditor(QWidget):
    """Edits one step's action list. `changed` fires after any modification."""

    changed = Signal()
    pickRequested = Signal(int, str)  # action row, which coordinate ("from"/"to")

    def __init__(
        self,
        app_root: str = "",
        get_rect: RectProvider | None = None,
        engine: "ImageSearchEngine | None" = None,
        template_name: "Callable[[int], str] | None" = None,
        log: Callable[[str], None] | None = None,
    ) -> None:
        """The last four are only needed by Find + Click's capture. Optional so the
        editor still builds standalone, in which case Capture says it can't."""
        super().__init__()
        self._app_root = app_root
        self._get_rect = get_rect or (lambda: None)
        self._engine = engine
        self._template_name = template_name or (lambda _row: "")
        self._log = log or (lambda _m: None)
        self._overlay: RegionOverlay | None = None
        self._actions: list[StepAction] = []
        self._loading = False
        # Last row that had fields on screen, so a cleared selection can be
        # restored instead of leaving the field row blank.
        self._last_row = 0

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(8)

        # # The list
        self._list = QListWidget()
        self._list.setObjectName("actionList")
        self._list.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self._list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._list.setMinimumHeight(120)
        self._list.currentRowChanged.connect(lambda _r: self._show_fields())
        # Drag-drop reorders the widget; mirror that into the data.
        self._list.model().rowsMoved.connect(self._on_rows_moved)
        root.addWidget(self._list, 1)

        # # Row buttons
        buttons = QHBoxLayout()
        buttons.setSpacing(6)
        # Shows the selected action's type and changes it in place; also decides
        # the type used by Add. One control for both, so what you see is what the
        # selected row is.
        self._type_picker = QComboBox()
        for action_type in ACTION_TYPES:
            self._type_picker.addItem(ACTION_LABELS[action_type], action_type)
        self._type_picker.setFixedWidth(96)
        self._type_picker.currentIndexChanged.connect(lambda _i: self._on_type_changed())
        buttons.addWidget(self._type_picker)

        # Add inserts below the selection (end of list when nothing is selected),
        # so building a sequence top-down needs one button. Reordering is the
        # arrows on the right, or a drag — no separate insert-above/below pair,
        # which just duplicated those arrows.
        buttons.addWidget(self._icon_button(icons.PLUS, "Add action below the selection", self._add))
        buttons.addStretch(1)
        for glyph, tip, handler in (
            (icons.UP, "Move up", lambda: self._move(-1)),
            (icons.DOWN, "Move down", lambda: self._move(1)),
            (icons.COPY, "Duplicate", self._duplicate),
            (icons.TRASH, "Delete", self._delete),
        ):
            buttons.addWidget(self._icon_button(glyph, tip, handler))
        root.addLayout(buttons)

        # # Field row for the selected action
        self._fields = QWidget()
        grid = QVBoxLayout(self._fields)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(6)

        coords = QHBoxLayout()
        coords.setSpacing(6)
        self._x = self._spin(0, 4000, lambda v: self._write("x", v))
        self._y = self._spin(0, 4000, lambda v: self._write("y", v))
        self._pick_from = self._text_button("Set", "Pick this point on the map")
        self._pick_from.clicked.connect(lambda: self._request_pick("from"))
        self._lbl_x = QLabel("X")
        self._lbl_y = QLabel("Y")
        for widget in (self._lbl_x, self._x, self._lbl_y, self._y, self._pick_from):
            coords.addWidget(widget)
        coords.addStretch(1)
        grid.addLayout(coords)

        to_coords = QHBoxLayout()
        to_coords.setSpacing(6)
        self._to_x = self._spin(0, 4000, lambda v: self._write("to_x", v))
        self._to_y = self._spin(0, 4000, lambda v: self._write("to_y", v))
        self._pick_to = self._text_button("Set", "Pick the drag destination")
        self._pick_to.clicked.connect(lambda: self._request_pick("to"))
        self._lbl_to = QLabel("To")
        for widget in (self._lbl_to, self._to_x, self._to_y, self._pick_to):
            to_coords.addWidget(widget)
        to_coords.addStretch(1)
        grid.addLayout(to_coords)

        # # Find + Click: the template, its search region, and click-every-instance
        image_row = QHBoxLayout()
        image_row.setSpacing(6)
        self._image = QLineEdit()
        self._image.setReadOnly(True)
        self._image.setPlaceholderText("no template — Capture one")
        self._image.setToolTip(
            "Captured from the live window, so it matches at the resolution it was taken "
            "at.\nTolerance for it is set per template in Settings > Vision."
        )
        self._capture = self._text_button("Capture", "Drag a box around the button to press")
        self._capture.clicked.connect(self._capture_image)
        self._region = self._text_button("Region", "Limit where this template is searched for")
        self._region.clicked.connect(self._pick_region)
        self._lbl_image = QLabel("Image")
        for widget in (self._lbl_image, self._image, self._capture, self._region):
            image_row.addWidget(widget)
        grid.addLayout(image_row)

        # # Wait for Wave: which wave to open on, and the map's total to check the read
        wave_row = QHBoxLayout()
        wave_row.setSpacing(6)
        self._wave = self._spin(0, WAVE_MAX, lambda v: self._write("wave", v))
        self._wave.setToolTip("The rest of this sequence runs once the match reaches it.")
        self._max_wave = self._spin(0, WAVE_MAX, lambda v: self._write("max_wave", v))
        self._max_wave.setToolTip(
            "How many waves this stage has, e.g. 25.\n\n"
            "It is what makes the read trustworthy: a counter showing '12/25' is checked "
            "against it, and a bare '125' is rejected as a misread of '12' rather than "
            "opening the gate 100 waves early. Leave 0 if you don't know it."
        )
        self._wave_region = self._text_button("Region", "Box the wave counter for OCR")
        self._wave_region.clicked.connect(self._pick_region)
        self._lbl_wave = QLabel("Wave")
        self._lbl_max_wave = QLabel("of")
        for widget in (
            self._lbl_wave, self._wave,
            self._lbl_max_wave, self._max_wave,
            self._wave_region,
        ):
            wave_row.addWidget(widget)
        wave_row.addStretch(1)
        grid.addLayout(wave_row)

        all_row = QHBoxLayout()
        all_row.setSpacing(6)
        self._click_all = QCheckBox("Click every instance found")
        self._click_all.setToolTip(
            "Off: click the single best match.\n"
            "On: click each place the template appears, left to right.\n\n"
            "Matching is grayscale, so it cannot tell a greyed-out button on cooldown from "
            "a ready one — set a Region that excludes the cooldown overlay if that matters."
        )
        self._click_all.toggled.connect(lambda on: self._write("click_all", bool(on)))
        all_row.addWidget(self._click_all)
        all_row.addStretch(1)
        grid.addLayout(all_row)

        misc = QHBoxLayout()
        misc.setSpacing(6)
        self._button = QComboBox()
        self._button.addItems(BUTTON_OPTIONS)
        self._button.setFixedWidth(84)
        self._button.currentTextChanged.connect(lambda v: self._write("button", v))
        self._count = self._spin(1, 50, lambda v: self._write("count", v))
        self._key = QLineEdit()
        self._key.setMaxLength(1)
        self._key.setFixedWidth(44)
        self._key.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._key.textChanged.connect(lambda v: self._write("key", v.strip().lower()))
        # Seconds in the field, milliseconds in `StepAction` — see `SecondsSpin`.
        self._hold = SecondsSpin(10000)
        self._hold.valueChanged.connect(lambda _v: self._write("hold_ms", self._hold.ms()))
        self._notches = self._spin(-50, 50, lambda v: self._write("notches", v))
        self._wait = SecondsSpin(60000)
        self._wait.valueChanged.connect(lambda _v: self._write("wait_ms", self._wait.ms()))

        self._lbl_button = QLabel("Button")
        self._lbl_count = QLabel("Times")
        self._lbl_key = QLabel("Key")
        self._lbl_hold = QLabel("Hold")
        self._lbl_notches = QLabel("Notches")
        self._lbl_wait = QLabel("Wait")
        for widget in (
            self._lbl_button, self._button,
            self._lbl_count, self._count,
            self._lbl_key, self._key,
            self._lbl_hold, self._hold,
            self._lbl_notches, self._notches,
            self._lbl_wait, self._wait,
        ):
            misc.addWidget(widget)
        misc.addStretch(1)
        grid.addLayout(misc)
        # Keep whichever rows are visible pinned to the top of the reserved area,
        # so a one-row type doesn't float in the middle of the empty space.
        grid.addStretch(1)
        root.addWidget(self._fields)

        # Pin this area to its tallest arrangement, which is Drag (point row, "to"
        # row, button row). Without it, retyping an action changes this widget's
        # height, which grows the whole detail card and shoves the viewport and
        # run strip around — measured 35px for Wait against 116px for Drag. Every
        # row is built now, so the current hint *is* the maximum.
        grid.activate()
        self._fields.setFixedHeight(self._fields.sizeHint().height())

        self._hint = QLabel("Runs top to bottom. Drag to reorder. The dropdown retypes the selection.")
        self._hint.setWordWrap(True)
        self._hint.setStyleSheet(f"color: {theme.TEXT_FAINT}; font-size: 10px;")
        root.addWidget(self._hint)

    # # Building blocks
    def _icon_button(self, glyph: str, tip: str, handler: Callable[[], None]) -> QPushButton:
        button = QPushButton(glyph)
        button.setToolTip(tip)
        button.setFixedSize(30, 28)
        button.setStyleSheet(f"font-family: '{theme.ICON_FAMILY}'; padding: 0;")
        button.clicked.connect(handler)
        return button

    def _text_button(self, text: str, tip: str) -> QPushButton:
        button = QPushButton(text)
        button.setToolTip(tip)
        button.setFixedHeight(28)
        button.setStyleSheet("padding: 2px 10px;")
        return button

    def _spin(
        self,
        low: int,
        high: int,
        on_change: Callable[[int], None],
        step: int = 1,
    ) -> QSpinBox:
        spin = QSpinBox()
        spin.setRange(low, high)
        spin.setSingleStep(step)
        spin.setFixedWidth(78)
        spin.valueChanged.connect(on_change)
        return spin

    # # Data in / out
    def load(self, actions: list[StepAction]) -> None:
        """Bind to a step's action list (by reference — edits write through)."""
        self._actions = actions
        self._refresh_list(select=0 if actions else -1)

    def current_row(self) -> int:
        return self._list.currentRow()

    def apply_coords(self, row: int, which: str, x: int, y: int) -> None:
        if not 0 <= row < len(self._actions):
            return
        action = self._actions[row]
        if which == "to":
            action.to_x, action.to_y = x, y
        else:
            action.x, action.y = x, y
        self._refresh_list(select=row)
        self.changed.emit()

    def _on_type_changed(self) -> None:
        """Retype the selected action, then rebuild its field row so the visible
        fields match the new type."""
        if self._loading:
            return
        row = self._list.currentRow()
        new_type = self._type_picker.currentData()
        if not 0 <= row < len(self._actions) or not new_type:
            # Nothing selected: there's no action to retype, so just refresh the
            # preview of what this type will ask for.
            self._apply_field_visibility(new_type)
            return
        action = self._actions[row]
        if action.type == new_type:
            return
        action.type = new_type
        # A Wait of 0ms does nothing, so give a freshly retyped Wait a usable
        # default rather than a silent no-op.
        if new_type == ACTION_WAIT and not action.wait_ms:
            action.wait_ms = 250
        # Wave 0 is "no wave set", which the gate refuses. Same reasoning as the Wait
        # above: a freshly retyped action should do something.
        if new_type == ACTION_WAVE and not action.wave:
            action.wave = 1
        self._refresh_row_text(row)
        self._show_fields()
        self.changed.emit()

    def _write(self, attr: str, value) -> None:
        if self._loading:
            return
        row = self._list.currentRow()
        if not 0 <= row < len(self._actions):
            return
        setattr(self._actions[row], attr, value)
        self._refresh_row_text(row)
        self.changed.emit()

    # # List maintenance
    def _refresh_list(self, select: int) -> None:
        self._loading = True
        self._list.blockSignals(True)
        self._list.clear()
        for position, action in enumerate(self._actions, start=1):
            item = QListWidgetItem(f"{position}.  {action.summary()}")
            self._list.addItem(item)
        self._list.blockSignals(False)
        if 0 <= select < self._list.count():
            self._list.setCurrentRow(select)
        self._loading = False
        self._show_fields()

    def _refresh_row_text(self, row: int) -> None:
        item = self._list.item(row)
        if item is not None:
            item.setText(f"{row + 1}.  {self._actions[row].summary()}")

    def _on_rows_moved(self, _parent, start: int, end: int, _dest, destination: int) -> None:
        """Mirror a drag-reorder into the data. Qt reports the destination as the
        index *before* removal, so shift it when moving down."""
        if self._loading or not 0 <= start < len(self._actions):
            return
        target = destination if destination < start else destination - 1
        moved = self._actions.pop(start)
        self._actions.insert(max(0, min(target, len(self._actions))), moved)
        self._refresh_list(select=max(0, min(target, len(self._actions) - 1)))
        self.changed.emit()

    # # Commands
    def _new_action(self) -> StepAction:
        action_type = self._type_picker.currentData() or ACTION_WAIT
        action = StepAction(type=action_type)
        if action_type == ACTION_WAIT:
            action.wait_ms = 250  # a bare 0ms wait does nothing useful
        if action_type == ACTION_WAVE:
            action.wave = 1  # wave 0 means "unset", which the gate refuses
        return action

    def _insert_at(self, index: int) -> None:
        index = max(0, min(index, len(self._actions)))
        self._actions.insert(index, self._new_action())
        self._refresh_list(select=index)
        self.changed.emit()

    def _add(self) -> None:
        row = self._list.currentRow()
        self._insert_at(row + 1 if row >= 0 else len(self._actions))

    def _move(self, delta: int) -> None:
        row = self._list.currentRow()
        target = row + delta
        if not (0 <= row < len(self._actions) and 0 <= target < len(self._actions)):
            return
        self._actions[row], self._actions[target] = self._actions[target], self._actions[row]
        self._refresh_list(select=target)
        self.changed.emit()

    def _duplicate(self) -> None:
        row = self._list.currentRow()
        if not 0 <= row < len(self._actions):
            return
        import copy

        self._actions.insert(row + 1, copy.deepcopy(self._actions[row]))
        self._refresh_list(select=row + 1)
        self.changed.emit()

    def _delete(self) -> None:
        row = self._list.currentRow()
        if not 0 <= row < len(self._actions):
            return
        self._actions.pop(row)
        self._refresh_list(select=min(row, len(self._actions) - 1))
        self.changed.emit()

    def _request_pick(self, which: str) -> None:
        row = self._list.currentRow()
        if not 0 <= row < len(self._actions):
            # Nothing selected (usually an empty list): the button used to do
            # nothing at all, which reads as broken. Add the action the type
            # dropdown is previewing and pick for that, so Set is the one click
            # it looks like. Skipped for a type with no such coordinate.
            action_type = self._type_picker.currentData() or ""
            field = "to_x" if which == "to" else "x"
            if field not in ACTION_FIELDS.get(action_type, ()):
                return
            self._insert_at(len(self._actions))
            row = self._list.currentRow()
            if not 0 <= row < len(self._actions):
                return
        self.pickRequested.emit(row, which)



    # # Field visibility
    def _show_fields(self) -> None:
        row = self._list.currentRow()
        if row < 0 and self._actions:
            # Clicking the empty area below the items clears QListWidget's
            # selection, which used to blank the field row until the next add.
            # With actions present there is always something to edit, so put the
            # selection back rather than showing nothing.
            row = min(max(self._last_row, 0), len(self._actions) - 1)
            self._list.blockSignals(True)
            self._list.setCurrentRow(row)
            self._list.blockSignals(False)

        if not 0 <= row < len(self._actions):
            # Empty list: preview the fields for the type in the dropdown, inert,
            # so you can see what an action of that type will ask for before
            # adding one. Only that type's fields — the widgets are all built
            # visible, so without this the union of every type showed at once.
            self._fields.setEnabled(False)
            self._apply_field_visibility(self._type_picker.currentData())
            return

        self._fields.setEnabled(True)
        self._last_row = row
        action = self._actions[row]
        self._loading = True
        # Populate before showing so a valueChanged can't write to the wrong row.
        # The type picker follows the selection, hence the _loading guard.
        index = self._type_picker.findData(action.type)
        if index >= 0:
            self._type_picker.setCurrentIndex(index)
        self._x.setValue(action.x)
        self._y.setValue(action.y)
        self._to_x.setValue(action.to_x)
        self._to_y.setValue(action.to_y)
        self._button.setCurrentText(action.button)
        self._count.setValue(max(1, action.count))
        self._key.setText(action.key)
        self._hold.set_ms(action.hold_ms)
        self._notches.setValue(action.notches)
        self._wait.set_ms(action.wait_ms)
        self._image.setText(action.image)
        region = action.region()
        label = "Region" if region is None else f"{region[2]}x{region[3]}"
        self._region.setText(label)
        self._wave_region.setText(label)
        self._click_all.setChecked(bool(action.click_all))
        self._wave.setValue(action.wave)
        self._max_wave.setValue(action.max_wave)
        self._loading = False
        self._apply_field_visibility(action.type)

    def _apply_field_visibility(self, action_type: str | None) -> None:
        """Show only the fields the given action type uses. Drives both the
        selected action's row and the empty-list preview."""
        used = ACTION_FIELDS.get(action_type or "", ())
        groups = (
            (("x", "y"), (self._lbl_x, self._x, self._lbl_y, self._y, self._pick_from)),
            (("to_x",), (self._lbl_to, self._to_x, self._to_y, self._pick_to)),
            (("button",), (self._lbl_button, self._button)),
            (("count",), (self._lbl_count, self._count)),
            (("key",), (self._lbl_key, self._key)),
            (("hold_ms",), (self._lbl_hold, self._hold)),
            (("notches",), (self._lbl_notches, self._notches)),
            (("wait_ms",), (self._lbl_wait, self._wait)),
            (
                ("image",),
                (self._lbl_image, self._image, self._capture, self._region),
            ),
            (("click_all",), (self._click_all,)),
            (
                ("wave",),
                (
                    self._lbl_wave, self._wave,
                    self._lbl_max_wave, self._max_wave,
                    self._wave_region,
                ),
            ),
        )
        for names, widgets in groups:
            visible = any(name in used for name in names)
            for widget in widgets:
                widget.setVisible(visible)

    # # Find + Click's template
    def _pick_region(self) -> None:
        """Limit where the template is searched for. Also the cooldown workaround: a
        region that excludes the greyed overlay is the only way to tell a ready button
        from a disabled one, since matching is grayscale."""
        action = self._current_action()
        if action is None or not action.uses("region"):
            return

        def done(result) -> None:
            self._overlay = None
            if result is None or result[0] != "region":
                return
            _mode, ax, ay, bx, by = result
            action.region_x = min(ax, bx)
            action.region_y = min(ay, by)
            action.region_w = abs(bx - ax)
            action.region_h = abs(by - ay)
            self._after_capture()

        self._open_overlay("region", done)

    def _capture_image(self) -> None:
        """Drag a box around the button; screenshot exactly that box.

        Same approach as the route editor's capture, and for the same measured reason: a
        template cropped from a full-desktop screenshot lands at a different scale, and
        `matchTemplate` is not scale invariant — a wrong-size crop costs 0.253 correlation
        and then matches at no threshold at all.
        """
        action = self._current_action()
        if action is None or action.type != ACTION_FIND_CLICK:
            return
        if self._engine is None or not self._app_root:
            self._log("Capture needs the running app — no image engine here.")
            return
        relative = self._template_name(self._list.currentRow())
        if not relative:
            self._log("Capture needs a target selected on the Run strip first.")
            return

        def done(result) -> None:
            self._overlay = None
            if result is None or result[0] != "region":
                return
            _mode, ax, ay, bx, by = result
            box = (min(ax, bx), min(ay, by), abs(bx - ax), abs(by - ay))
            if box[2] < 4 or box[3] < 4:
                self._log("That box is too small to match on — drag a bigger one.")
                return
            # The overlay was covering Roblox a moment ago; let the desktop repaint or
            # the crop catches the picker instead of the game.
            QTimer.singleShot(150, lambda: self._write_capture(action, relative, box))

        self._open_overlay("region", done)

    def _write_capture(
        self, action: StepAction, relative: str, box: tuple[int, int, int, int]
    ) -> None:
        rect = self._get_rect()
        if rect is None or self._engine is None:
            self._log("Roblox not found — start it first.")
            return
        png = self._engine.capture_png(
            (rect[0] + box[0], rect[1] + box[1], box[2], box[3])
        )
        if png is None:
            self._log("Could not capture that area.")
            return
        target = os.path.join(self._app_root, relative)
        try:
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with open(target, "wb") as handle:
                handle.write(png)
        except OSError as exc:
            self._log(f"Could not save the template: {exc}")
            return

        action.image = relative
        # The box it came from is its search region: faster, and it can't false-hit
        # elsewhere on screen. Editable afterwards with Region.
        action.region_x, action.region_y, action.region_w, action.region_h = box
        self._log(f"Action template saved: {relative} ({box[2]}x{box[3]})")
        self._after_capture()

    def _after_capture(self) -> None:
        self._show_fields()
        self._refresh_row_text(self._list.currentRow())
        self.changed.emit()

    def _open_overlay(self, mode: str, done) -> None:
        rect = self._get_rect()
        if rect is None:
            self._log("Roblox not found — start it first.")
            return
        # Keep the reference: a local would be collected mid-pick, taking the callback
        # with it.
        self._overlay = RegionOverlay(mode, rect, done)
        self._overlay.show()
        self._overlay.raise_()

    def _current_action(self) -> StepAction | None:
        row = self._list.currentRow()
        if not 0 <= row < len(self._actions):
            return None
        return self._actions[row]


