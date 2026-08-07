"""Route editor: build the Events lobby navigation as data.

Lives in the Run panel's Route tab. Owns three things: the list of custom maps
(events) and their acts, the ordered `NavStep` list for the selected map/act, and
the field row for the selected step.

Everything saves as you edit, like Settings — there is no Save button, because a
half-saved route is worse than none.

Coordinates and regions are picked with `RegionOverlay` (the Macro Tester's
picker): it is translucent, so you click straight through to what the live Roblox
window is showing, and it hands back client-space numbers with no conversion
because DPI scaling is off and the viewport is pinned.
"""

from __future__ import annotations

import os
from typing import Callable

from PySide6.QtCore import QTimer, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDoubleSpinBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from sloppykeys.config import route_paths
from sloppykeys.config.nav_routes import RouteStore, clean_name
from sloppykeys.content.nav_images import events_templates_dir
from sloppykeys.core.image_search import ImageSearchEngine, find_until
from sloppykeys.content.nav_route import (
    BUTTON_OPTIONS,
    KIND_LABELS,
    KIND_WAIT,
    KINDS,
    MAX_SCROLLS_CEILING,
    NOTCHES_CEILING,
    NavStep,
    route_problems,
)

from . import icons, theme
from .macro_tester import RegionOverlay


RectProvider = Callable[[], "tuple[int, int, int, int] | None"]


class RouteEditor(QWidget):
    """Custom maps/acts plus the navigation route for the selected one."""

    # The map or act lists changed, so the Run strip's dropdowns are stale.
    changed = Signal()
    # Run this event/act's route once, now. Driving the game blocks and clicks, so
    # MainWindow runs it on a worker and reports back through `show_note`.
    testRequested = Signal(str, str)  # event, act
    # Renamed, and the files have already moved. Separate from `changed` because a queued
    # task stores the name as *data* — rebuilding a dropdown does not fix a slot that still
    # points at the old event, and the task queue is owned by `MainWindow`, not this editor.
    eventRenamed = Signal(str, str)  # old, new
    actRenamed = Signal(str, str, str)  # event, old act, new act

    def __init__(
        self,
        store: RouteStore,
        app_root: str,
        get_rect: RectProvider,
        engine: ImageSearchEngine,
        log: Callable[[str], None] | None = None,
    ) -> None:
        super().__init__()
        self._store = store
        self._app_root = app_root
        self._get_rect = get_rect
        self._engine = engine
        self._log = log or (lambda _m: None)
        self._steps: list[NavStep] = []
        self._loading = False
        self._overlay: RegionOverlay | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(8)
        root.addLayout(self._build_target_rows())
        root.addLayout(self._build_route_actions())
        # Feedback goes *above* the list, not at the bottom. Measured: this editor
        # is ~520px inside a ~415px scroll viewport, so a note under the field rows
        # sat below the fold — every message it printed (a refused act delete, a
        # Test result) was invisible, which reads as a dead button.
        self._note = QLabel("")
        self._note.setWordWrap(True)
        self._note.setStyleSheet(f"color: {theme.TEXT_FAINT}; font-size: 10px;")
        self._note.setMinimumHeight(26)
        root.addWidget(self._note)
        root.addWidget(self._build_list(), 1)
        root.addLayout(self._build_step_buttons())
        root.addWidget(self._build_fields())

        self.reload()

    # # Construction
    def _build_target_rows(self) -> QVBoxLayout:
        rows = QVBoxLayout()
        rows.setSpacing(6)

        map_row = QHBoxLayout()
        map_row.setSpacing(6)
        map_row.addWidget(QLabel("Event"))
        self._map = QComboBox()
        self._map.currentIndexChanged.connect(lambda _i: self._on_map_changed())
        map_row.addWidget(self._map, 1)
        map_row.addWidget(self._icon(icons.PLUS, "Add an event", self._add_map))
        map_row.addWidget(
            self._icon(
                icons.RENAME,
                "Rename this event — moves its step templates, placement backdrops, "
                "unit configs and any queued task with it",
                self._rename_map,
            )
        )
        map_row.addWidget(self._icon(icons.TRASH, "Delete this event", self._remove_map))
        rows.addLayout(map_row)

        act_row = QHBoxLayout()
        act_row.setSpacing(6)
        act_row.addWidget(QLabel("Act"))
        self._act = QComboBox()
        self._act.currentIndexChanged.connect(lambda _i: self._on_act_changed())
        act_row.addWidget(self._act, 1)
        act_row.addWidget(self._icon(icons.PLUS, "Add an act", self._add_act))
        act_row.addWidget(
            self._icon(
                icons.RENAME,
                "Rename this act — moves its step templates, placement backdrop, unit "
                "config and any queued task with it",
                self._rename_act,
            )
        )
        act_row.addWidget(self._icon(icons.TRASH, "Delete this act", self._remove_act))
        rows.addLayout(act_row)
        return rows

    def _build_route_actions(self) -> QHBoxLayout:
        """Whole-route actions, as opposed to the per-step row lower down. Directly
        above the note so what they report is on screen next to them."""
        row = QHBoxLayout()
        row.setSpacing(6)
        self._run_route = self._text_button(
            "Test route", "Run every step of this route now, in order — this drives the game"
        )
        self._run_route.clicked.connect(self._request_test)
        row.addWidget(self._run_route)
        # No map-image capture here: an act added in this tab shows up as its own row in
        # Settings > Vision, which manages every image the macro uses.
        row.addStretch(1)
        return row

    def _build_list(self) -> QWidget:
        self._list = QListWidget()
        self._list.setObjectName("actionList")
        self._list.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self._list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._list.setMinimumHeight(96)
        self._list.currentRowChanged.connect(lambda _r: self._show_fields())
        self._list.model().rowsMoved.connect(self._on_rows_moved)
        return self._list

    def _build_step_buttons(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(6)
        self._kind = QComboBox()
        for kind in KINDS:
            self._kind.addItem(KIND_LABELS[kind], kind)
        # Measured: the widest KIND_LABELS entry needs 116px with the combo's arrow and
        # QSS padding, so 104 clipped it.
        self._kind.setFixedWidth(118)
        self._kind.currentIndexChanged.connect(lambda _i: self._on_kind_changed())
        row.addWidget(self._kind)
        row.addWidget(self._icon(icons.PLUS, "Add a step below the selection", self._add_step))
        row.addWidget(
            self._icon(icons.REFRESH, "Reset — delete every step in this route", self._reset_steps)
        )
        row.addStretch(1)
        for glyph, tip, handler in (
            (icons.UP, "Move up", lambda: self._move(-1)),
            (icons.DOWN, "Move down", lambda: self._move(1)),
            (icons.COPY, "Duplicate", self._duplicate),
            (icons.TRASH, "Delete", self._delete),
        ):
            row.addWidget(self._icon(glyph, tip, handler))
        return row

    def _build_fields(self) -> QWidget:
        self._fields = QWidget()
        box = QVBoxLayout(self._fields)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(5)

        note_row = QHBoxLayout()
        note_row.setSpacing(6)
        self._label = QLineEdit()
        self._label.setPlaceholderText("Note (optional) — shows in the run log")
        self._label.setMaxLength(60)
        self._label.textChanged.connect(lambda v: self._write("label", v))
        note_row.addWidget(QLabel("Note"))
        note_row.addWidget(self._label, 1)
        box.addLayout(note_row)

        point_row = QHBoxLayout()
        point_row.setSpacing(6)
        self._x = self._spin(0, 4000, lambda v: self._write("x", v))
        self._y = self._spin(0, 4000, lambda v: self._write("y", v))
        self._lbl_point = QLabel("X / Y")
        self._pick_point = self._text_button("Set", "Click the point on the Roblox window")
        self._pick_point.clicked.connect(lambda: self._pick_point_for("click"))
        for widget in (self._lbl_point, self._x, self._y, self._pick_point):
            point_row.addWidget(widget)
        point_row.addStretch(1)
        box.addLayout(point_row)

        image_row = QHBoxLayout()
        image_row.setSpacing(6)
        self._lbl_image = QLabel("Image")
        self._image = QLineEdit()
        self._image.setReadOnly(True)
        self._image.setPlaceholderText("no template")
        self._capture = self._text_button(
            "Capture", "Drag a box on the Roblox window to screenshot it as this step's template"
        )
        self._capture.clicked.connect(self._capture_image)
        self._test = self._text_button(
            "Test", "Look for this template on screen right now (no click)"
        )
        self._test.clicked.connect(self._test_image)
        for widget in (self._lbl_image, self._image, self._capture, self._test):
            image_row.addWidget(widget)
        box.addLayout(image_row)

        region_row = QHBoxLayout()
        region_row.setSpacing(6)
        self._lbl_region = QLabel("Region")
        self._region = QLineEdit()
        self._region.setReadOnly(True)
        self._region.setPlaceholderText("whole screen")
        self._pick_region = self._text_button("Set", "Drag the area to search in")
        self._pick_region.clicked.connect(self._pick_region_for)
        self._clear_region = self._text_button("Clear", "Search the whole client area")
        self._clear_region.clicked.connect(self._clear_region_value)
        for widget in (
            self._lbl_region,
            self._region,
            self._pick_region,
            self._clear_region,
        ):
            region_row.addWidget(widget)
        box.addLayout(region_row)

        search_row = QHBoxLayout()
        search_row.setSpacing(6)
        self._timeout = QDoubleSpinBox()
        self._timeout.setRange(0.0, 120.0)
        self._timeout.setSingleStep(0.5)
        self._timeout.setDecimals(1)
        self._timeout.setFixedWidth(64)
        self._timeout.setToolTip("0 uses the Settings > Delays search timeout")
        self._timeout.valueChanged.connect(lambda v: self._write("timeout", float(v)))
        self._scrolls = self._spin(0, MAX_SCROLLS_CEILING, lambda v: self._write("max_scrolls", v))
        self._notches = self._spin(
            -NOTCHES_CEILING, NOTCHES_CEILING, lambda v: self._write("notches", v)
        )
        self._lbl_timeout = QLabel("Wait s")
        self._lbl_scrolls = QLabel("Scrolls")
        self._lbl_notches = QLabel("Notches")
        for widget in (
            self._lbl_timeout, self._timeout,
            self._lbl_scrolls, self._scrolls,
            self._lbl_notches, self._notches,
        ):
            search_row.addWidget(widget)
        search_row.addStretch(1)
        box.addLayout(search_row)

        scroll_row = QHBoxLayout()
        scroll_row.setSpacing(6)
        self._scroll_x = self._spin(0, 4000, lambda v: self._write("scroll_x", v))
        self._scroll_y = self._spin(0, 4000, lambda v: self._write("scroll_y", v))
        self._lbl_scroll_point = QLabel("Wheel at")
        self._pick_scroll = self._text_button(
            "Set",
            "Where to put the cursor before scrolling — the wheel goes to whatever is under it, "
            "so the event list and the act carousel need different points",
        )
        self._pick_scroll.clicked.connect(lambda: self._pick_point_for("scroll"))
        self._clear_scroll = self._text_button("Clear", "Back to the client centre")
        self._clear_scroll.clicked.connect(self._clear_scroll_point)
        for widget in (
            self._lbl_scroll_point,
            self._scroll_x,
            self._scroll_y,
            self._pick_scroll,
            self._clear_scroll,
        ):
            scroll_row.addWidget(widget)
        scroll_row.addStretch(1)
        box.addLayout(scroll_row)

        misc_row = QHBoxLayout()
        misc_row.setSpacing(6)
        self._button = QComboBox()
        self._button.addItems(BUTTON_OPTIONS)
        self._button.setFixedWidth(86)
        self._button.currentTextChanged.connect(lambda v: self._write("button", v))
        self._count = self._spin(1, 20, lambda v: self._write("count", v))
        self._wait = self._spin(0, 60000, lambda v: self._write("wait_ms", v), step=100)
        self._lbl_button = QLabel("Button")
        self._lbl_count = QLabel("Times")
        self._lbl_wait = QLabel("Wait ms")
        for widget in (
            self._lbl_button, self._button,
            self._lbl_count, self._count,
            self._lbl_wait, self._wait,
        ):
            misc_row.addWidget(widget)
        misc_row.addStretch(1)
        box.addLayout(misc_row)

        # Pin to the tallest arrangement, exactly like the sequence editor: without
        # it, retyping a step changes this widget's height and the whole panel
        # re-lays out under the fixed window.
        box.activate()
        self._fields.setFixedHeight(self._fields.sizeHint().height())
        return self._fields

    # # Small builders
    def _icon(self, glyph: str, tip: str, handler: Callable[[], None]) -> QPushButton:
        button = QPushButton(glyph)
        button.setToolTip(tip)
        button.setFixedSize(28, 26)
        button.setStyleSheet(f"font-family: '{theme.ICON_FAMILY}'; padding: 0;")
        button.clicked.connect(handler)
        return button

    def _text_button(self, text: str, tip: str) -> QPushButton:
        button = QPushButton(text)
        button.setToolTip(tip)
        button.setFixedHeight(26)
        button.setStyleSheet("padding: 2px 8px;")
        return button

    def _spin(
        self, low: int, high: int, on_change: Callable[[int], None], step: int = 1
    ) -> QSpinBox:
        spin = QSpinBox()
        spin.setRange(low, high)
        spin.setSingleStep(step)
        spin.setFixedWidth(64)
        spin.valueChanged.connect(on_change)
        return spin

    # # Target (map / act) selection
    def reload(self) -> None:
        """Re-read maps and acts from the store, keeping the selection if it lives."""
        wanted_map = self.current_map()
        wanted_act = self.current_act()
        self._loading = True
        self._map.clear()
        self._map.addItems(self._store.maps())
        if wanted_map and self._map.findText(wanted_map) >= 0:
            self._map.setCurrentText(wanted_map)
        self._loading = False
        self._fill_acts(wanted_act)

    def _fill_acts(self, wanted: str = "") -> None:
        self._loading = True
        self._act.clear()
        map_name = self.current_map()
        if map_name:
            self._act.addItems(self._store.acts(map_name))
            if wanted and self._act.findText(wanted) >= 0:
                self._act.setCurrentText(wanted)
        self._loading = False
        self._load_steps()

    def current_map(self) -> str:
        return self._map.currentText().strip()

    def current_act(self) -> str:
        return self._act.currentText().strip()

    def _on_map_changed(self) -> None:
        if self._loading:
            return
        self._fill_acts()

    def _on_act_changed(self) -> None:
        if self._loading:
            return
        self._load_steps()

    def _rename_map(self) -> None:
        """Rename an event and everything named after it.

        The name is a folder under `images/events/`, `images/reference/Events/` and
        `configs/Events/`, a key in `routes.json`, each step's `Image` path, and possibly a
        queued task. Renaming the label alone would leave a route that still runs while the
        placement backdrop and unit plan quietly stop being found.
        """
        old = self.current_map()
        if not old:
            return
        name, ok = QInputDialog.getText(
            self, "Rename event", "New event name:", text=old
        )
        if not ok:
            return
        moved, message = route_paths.rename_event(self._app_root, self._store, old, name)
        if not moved:
            self._set_note(f"Couldn't rename {old}: {message}.", bad=True)
            return
        stored = clean_name(name)
        self._log(f"Renamed event {old} to {stored}: {message}.")
        self.reload()
        self._map.setCurrentText(stored)
        # Before `changed`, so the queue is already correct when the Tasks tab rebuilds.
        self.eventRenamed.emit(old, stored)
        self.changed.emit()
        self._set_note(f"{old} is now {stored} — {message}.")

    def _rename_act(self) -> None:
        """Rename one act, moving its step templates, backdrop and unit config with it."""
        map_name, old = self.current_map(), self.current_act()
        if not (map_name and old):
            return
        name, ok = QInputDialog.getText(self, "Rename act", "New act name:", text=old)
        if not ok:
            return
        moved, message = route_paths.rename_act(
            self._app_root, self._store, map_name, old, name
        )
        if not moved:
            self._set_note(f"Couldn't rename {old}: {message}.", bad=True)
            return
        stored = clean_name(name)
        self._log(f"Renamed act {map_name} / {old} to {stored}: {message}.")
        self._fill_acts(stored)
        self.actRenamed.emit(map_name, old, stored)
        self.changed.emit()
        self._set_note(f"{old} is now {stored} — {message}.")

    def _add_map(self) -> None:
        name, ok = QInputDialog.getText(self, "Add event", "Event name (shown in the Map list):")
        if not ok:
            return
        stored = self._store.add_map(name)
        if not stored:
            self._set_note("That name can't be used as a folder name.", bad=True)
            return
        self.reload()
        self._map.setCurrentText(stored)
        self.changed.emit()

    def _remove_map(self) -> None:
        map_name = self.current_map()
        if not map_name:
            return
        images = self._store.images_for(map_name)
        confirm = QMessageBox.question(
            self,
            "Delete event",
            f"Delete {map_name} and all of its acts and routes?\n\n"
            f"{len(images)} captured template(s) go with it. Unit configs under "
            f"configs/Events/{clean_name(map_name)}/ are kept.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return
        # The unit config stays: it's the user's placement work, and deleting it
        # from here would be a surprise.
        if self._store.remove_map(map_name):
            binned = self._purge_templates(images)
            self.reload()
            self.changed.emit()
            self._set_note(
                f"Deleted {map_name} and {binned} template(s). Its unit configs are kept."
            )

    def _add_act(self) -> None:
        map_name = self.current_map()
        if not map_name:
            self._set_note("Add an event first.", bad=True)
            return
        name, ok = QInputDialog.getText(self, "Add act", "Act name:")
        if not ok:
            return
        stored = self._store.add_act(map_name, name)
        if not stored:
            self._set_note("That name can't be used as a file name.", bad=True)
            return
        self._fill_acts(stored)
        self.changed.emit()

    def _remove_act(self) -> None:
        map_name, act = self.current_map(), self.current_act()
        if not (map_name and act):
            return
        if len(self._store.acts(map_name)) <= 1:
            # Not a failure to report vaguely: the config path needs an act to name
            # configs/Events/<Event>/<Act>.json, so the last one can't go. Say which.
            self._set_note(
                f"{act} is the only act of {map_name} — an event keeps one. "
                "Add another act first, or delete the event.",
                bad=True,
            )
            return
        images = self._store.images_for(map_name, act)
        confirm = QMessageBox.question(
            self,
            "Delete act",
            f"Delete {act} of {map_name} and its route?\n\n"
            f"{len(images)} captured template(s) go with it.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return
        if not self._store.remove_act(map_name, act):
            self._set_note(f"Could not delete {act}.", bad=True)
            return
        binned = self._purge_templates(images)
        self._fill_acts()
        self.changed.emit()
        self._set_note(f"Deleted act {act} and {binned} template(s).")

    # # Steps
    def _load_steps(self) -> None:
        map_name, act = self.current_map(), self.current_act()
        self._steps = self._store.steps(map_name, act) if map_name and act else []
        self._refresh_list(select=0 if self._steps else -1)

    def _save(self) -> None:
        map_name, act = self.current_map(), self.current_act()
        if map_name and act:
            self._store.set_steps(map_name, act, self._steps)
        self._refresh_problems()

    def _refresh_list(self, select: int) -> None:
        self._loading = True
        self._list.blockSignals(True)
        self._list.clear()
        for position, step in enumerate(self._steps, start=1):
            self._list.addItem(QListWidgetItem(f"{position}.  {step.summary()}"))
        self._list.blockSignals(False)
        if 0 <= select < self._list.count():
            self._list.setCurrentRow(select)
        self._loading = False
        self._show_fields()
        self._refresh_problems()

    def _refresh_row(self, row: int) -> None:
        item = self._list.item(row)
        if item is not None:
            item.setText(f"{row + 1}.  {self._steps[row].summary()}")

    def _refresh_problems(self) -> None:
        if not self.current_map():
            self._set_note("Add an event to build its route.")
            return
        problems = route_problems(self._steps)
        if problems:
            self._set_note("Won't run — " + "; ".join(problems[:3]), bad=True)
        elif self._steps:
            self._set_note(f"{len(self._steps)} steps. Runs top to bottom after Events is clicked.")
        else:
            self._set_note("No steps yet. The last step should click Start.")

    def _set_note(self, text: str, bad: bool = False) -> None:
        color = theme.BAD if bad else theme.TEXT_FAINT
        self._note.setStyleSheet(f"color: {color}; font-size: 10px;")
        self._note.setText(text)

    def _current_step(self) -> NavStep | None:
        row = self._list.currentRow()
        return self._steps[row] if 0 <= row < len(self._steps) else None

    def _write(self, attr: str, value) -> None:
        if self._loading:
            return
        row = self._list.currentRow()
        if not 0 <= row < len(self._steps):
            return
        setattr(self._steps[row], attr, value)
        self._refresh_row(row)
        self._save()

    def _on_kind_changed(self) -> None:
        if self._loading:
            return
        kind = self._kind.currentData()
        row = self._list.currentRow()
        if not 0 <= row < len(self._steps) or not kind:
            self._apply_visibility(kind)
            return
        step = self._steps[row]
        if step.kind == kind:
            return
        step.kind = kind
        # A zero wait is a no-op, so a freshly retyped Wait gets a usable default.
        if kind == KIND_WAIT and not step.wait_ms:
            step.wait_ms = 500
        self._refresh_row(row)
        self._show_fields()
        self._save()

    def _add_step(self) -> None:
        if not self.current_map():
            self._set_note("Add an event first.", bad=True)
            return
        kind = self._kind.currentData() or KINDS[0]
        step = NavStep(kind=kind)
        if kind == KIND_WAIT:
            step.wait_ms = 500
        row = self._list.currentRow()
        index = row + 1 if row >= 0 else len(self._steps)
        self._steps.insert(index, step)
        self._refresh_list(select=index)
        self._save()

    def _reset_steps(self) -> None:
        """Empty this route's step list and bin the templates it captured.

        Asks first: it throws away every step for the selected event/act and there
        is no undo on a saved route.
        """
        map_name, act = self.current_map(), self.current_act()
        if not (map_name and act):
            return
        if not self._steps:
            self._set_note("This route is already empty.")
            return
        images = {step.image for step in self._steps if step.image}
        confirm = QMessageBox.question(
            self,
            "Reset route",
            f"Delete all {len(self._steps)} steps of {map_name} / {act}?\n\n"
            f"{len(images)} captured template(s) will be deleted with them. "
            "The event and act stay.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return
        removed = len(self._steps)
        self._steps = []
        self._refresh_list(select=-1)
        self._save()
        binned = self._purge_templates(images)
        self._log(f"Route {map_name} / {act}: reset ({removed} steps, {binned} templates deleted)")
        self._set_note(f"Reset — {removed} steps and {binned} template(s) deleted.")

    def _purge_templates(self, images: set[str]) -> int:
        """Delete captured templates nothing references any more. Returns the count.

        Called *after* the store has been written, so `all_images` already reflects
        the deletion. Two guards, because this removes files: a path still used by
        another route survives, and anything outside `images/events/` is left alone
        — a route can point at a template elsewhere, and that isn't ours to bin.
        """
        if not images:
            return 0
        still_used = self._store.all_images()
        base = events_templates_dir().replace("\\", "/").rstrip("/") + "/"
        removed = 0
        for relative in sorted(images):
            normalized = relative.replace("\\", "/")
            if not normalized or relative in still_used or not normalized.startswith(base):
                continue
            try:
                os.remove(os.path.join(self._app_root, relative))
                removed += 1
            except OSError:
                continue  # already gone, or in use — not worth failing the delete over
        return removed

    def _move(self, delta: int) -> None:
        row = self._list.currentRow()
        target = row + delta
        if not (0 <= row < len(self._steps) and 0 <= target < len(self._steps)):
            return
        self._steps[row], self._steps[target] = self._steps[target], self._steps[row]
        self._refresh_list(select=target)
        self._save()

    def _duplicate(self) -> None:
        row = self._list.currentRow()
        if not 0 <= row < len(self._steps):
            return
        import copy

        self._steps.insert(row + 1, copy.deepcopy(self._steps[row]))
        self._refresh_list(select=row + 1)
        self._save()

    def _delete(self) -> None:
        row = self._list.currentRow()
        if not 0 <= row < len(self._steps):
            return
        gone = self._steps.pop(row)
        self._refresh_list(select=min(row, len(self._steps) - 1))
        self._save()
        # Its template goes too, unless a duplicate of this step still points at it.
        if gone.image and self._purge_templates({gone.image}):
            self._set_note(f"Step deleted, and {os.path.basename(gone.image)} with it.")

    def _on_rows_moved(self, _parent, start: int, _end: int, _dest, destination: int) -> None:
        """Mirror a drag-reorder into the data. Qt reports the destination as the
        index before removal, so shift it when moving down."""
        if self._loading or not 0 <= start < len(self._steps):
            return
        target = destination if destination < start else destination - 1
        moved = self._steps.pop(start)
        self._steps.insert(max(0, min(target, len(self._steps))), moved)
        self._refresh_list(select=max(0, min(target, len(self._steps) - 1)))
        self._save()

    # # Picking
    def _pick_point_for(self, which: str) -> None:
        step = self._current_step()
        if step is None:
            self._set_note("Select a step first.", bad=True)
            return

        def done(result) -> None:
            self._overlay = None
            if result is None or result[0] != "point":
                return
            _mode, x, y = result
            if which == "scroll":
                step.scroll_x, step.scroll_y = x, y
            else:
                step.x, step.y = x, y
            self._show_fields()
            self._refresh_row(self._list.currentRow())
            self._save()

        self._open_overlay("point", done)

    def _pick_region_for(self) -> None:
        step = self._current_step()
        if step is None:
            self._set_note("Select a step first.", bad=True)
            return

        def done(result) -> None:
            self._overlay = None
            if result is None or result[0] != "region":
                return
            _mode, ax, ay, bx, by = result
            step.region_x, step.region_y = min(ax, bx), min(ay, by)
            step.region_w, step.region_h = abs(bx - ax), abs(by - ay)
            self._show_fields()
            self._save()

        self._open_overlay("region", done)

    def _open_overlay(self, mode: str, done: Callable[[object], None]) -> None:
        if self._overlay is not None:  # one picker at a time
            return
        rect = self._get_rect()
        if rect is None:
            self._set_note("Roblox not found — start it first.", bad=True)
            return
        # Keep the reference: a local would be collected mid-pick, taking the
        # callback with it.
        self._overlay = RegionOverlay(mode, rect, done)
        self._overlay.show()
        self._overlay.raise_()
        self._overlay.activateWindow()

    def _clear_region_value(self) -> None:
        step = self._current_step()
        if step is None:
            return
        step.region_x = step.region_y = step.region_w = step.region_h = 0
        self._show_fields()
        self._save()

    # # Capturing a template
    def _capture_image(self) -> None:
        """Drag a box on the Roblox window and screenshot exactly that box.

        Same picker as Region; the capture is that box offset by the Roblox client
        origin, so it is the same pixels the search reads and the template is at the
        resolution it will be matched at. A template cropped out of a full-desktop
        screenshot can land at a different scale and then never matches at any
        confidence.
        """
        step = self._current_step()
        if step is None:
            self._set_note("Select a step first.", bad=True)
            return

        def done(result) -> None:
            self._overlay = None
            if result is None or result[0] != "region":
                return
            _mode, ax, ay, bx, by = result
            box = (min(ax, bx), min(ay, by), abs(bx - ax), abs(by - ay))
            if box[2] < 4 or box[3] < 4:
                self._set_note("That box is too small to match on. Drag a bigger one.", bad=True)
                return
            # The overlay covered Roblox a moment ago; give the desktop a beat to
            # repaint or the crop catches the picker instead of the game.
            QTimer.singleShot(150, lambda: self._write_capture(step, box))

        self._open_overlay("region", done)

    def _write_capture(self, step: NavStep, box: tuple[int, int, int, int]) -> None:
        rect = self._get_rect()
        if rect is None:
            self._set_note("Roblox not found — start it first.", bad=True)
            return
        # Client-space box -> screen rect. The picker is sized to the client area
        # and clamps the drag inside it, so this can't reach past the game window.
        png = self._engine.capture_png(
            (rect[0] + box[0], rect[1] + box[1], box[2], box[3])
        )
        if png is None:
            self._set_note("Could not capture that area.", bad=True)
            return

        relative = self._template_name(step)
        target = os.path.join(self._app_root, relative)
        try:
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with open(target, "wb") as handle:
                handle.write(png)
        except OSError as exc:
            self._set_note(f"Could not save the template: {exc}", bad=True)
            return

        step.image = relative
        # A captured template is its own search region: it came from exactly this
        # box, so searching that box is both faster and impossible to false-hit
        # elsewhere. Editable afterwards with Region > Set.
        step.region_x, step.region_y, step.region_w, step.region_h = box
        self._show_fields()
        self._refresh_row(self._list.currentRow())
        self._save()
        self._log(f"Route template saved: {relative} ({box[2]}x{box[3]})")
        self._set_note(f"Saved {relative} — {box[2]}x{box[3]}, region set to match.")

    def _template_name(self, step: NavStep) -> str:
        """Where a captured template goes: `images/events/<Event>/<Act>_<n>.png`.

        Grouped per event so deleting an event is one folder to bin, and named
        independently of the step's position. Numbering by position was a bug: move
        a step and its file name no longer matches where it sits, then the next
        capture at that position overwrites a template another step still points at.
        A step that already has an image re-captures over its own file; one without
        takes the first free number.
        """
        # Re-capture over its own file — unless a duplicated step shares that path,
        # in which case overwriting would silently change the other step's template.
        shared = any(other is not step and other.image == step.image for other in self._steps)
        if step.image and not shared:
            return step.image
        folder = f"{events_templates_dir()}/{clean_name(self.current_map()) or 'route'}"
        stem = clean_name(self.current_act()) or "step"
        taken = {other.image for other in self._steps if other.image}
        number = 1
        while True:
            candidate = f"{folder}/{stem}_{number}.png".replace("\\", "/")
            on_disk = os.path.isfile(os.path.join(self._app_root, candidate))
            if candidate not in taken and not on_disk:
                return candidate
            number += 1

    # # Whole-route actions
    def _request_test(self) -> None:
        """Ask MainWindow to run this route. Refused here for the cases this widget
        can answer itself, so a doomed run never touches the game."""
        map_name, act = self.current_map(), self.current_act()
        if not (map_name and act):
            self._set_note("Pick an Event and an Act first.", bad=True)
            return
        if not self._steps:
            self._set_note("No steps in this route yet.", bad=True)
            return
        problems = route_problems(self._steps)
        if problems:
            self._set_note("Route can't run: " + "; ".join(problems[:2]), bad=True)
            return
        self.set_testing(True)
        self.testRequested.emit(map_name, act)

    def set_testing(self, running: bool) -> None:
        """Called by MainWindow around the worker: one run at a time, and the button
        says which state it's in."""
        self._run_route.setEnabled(not running)
        self._run_route.setText("Running..." if running else "Test route")

    def show_note(self, text: str, bad: bool = False) -> None:
        """Public form of the note line, for results that arrive from a worker."""
        self._set_note(text, bad=bad)

    def _test_image(self) -> None:
        """Look for this step's template on screen right now, without clicking.

        One look (`timeout=0`), so it answers "is this screen up and does the
        template still match" rather than waiting for it. Runs on the UI thread on
        purpose: a look is ~17ms measured (capture + match) and nothing sleeps, so
        there is no worker to justify — unlike a route step, which clicks.
        """
        step = self._current_step()
        if step is None:
            self._set_note("Select a step first.", bad=True)
            return
        if not step.image:
            self._set_note("No template on this step yet — press Capture.", bad=True)
            return
        if not os.path.isfile(self._engine.to_absolute_path(step.image)):
            self._set_note(f"{step.image} is missing from disk.", bad=True)
            return
        if self._get_rect() is None:
            self._set_note("Roblox not found — start it first.", bad=True)
            return

        match = find_until(self._engine, self._get_rect, step.image, region=step.region())
        if match is None:
            where = "in its region" if step.region() else "on screen"
            self._set_note(
                f"Not found {where}. Wrong screen, or the region excludes it.", bad=True
            )
            self._log(f"Route test: {step.image} not found")
            return
        self._set_note(
            f"Found at {match.center_x}, {match.center_y} — score {match.score:.2f}"
            f" (0.70 is the match threshold)."
        )
        self._log(
            f"Route test: {step.image} found at {match.center_x},{match.center_y} "
            f"({match.score:.2f})"
        )

    def _clear_scroll_point(self) -> None:
        """Back to the client centre. Without this a wheel point could be typed but
        never unset, since 0 is the spin box's minimum rather than an obvious 'off'."""
        step = self._current_step()
        if step is None:
            return
        step.scroll_x = step.scroll_y = 0
        self._show_fields()
        self._refresh_row(self._list.currentRow())
        self._save()

    # # Field row
    def _show_fields(self) -> None:
        step = self._current_step()
        if step is None:
            self._fields.setEnabled(False)
            self._apply_visibility(self._kind.currentData())
            return

        self._fields.setEnabled(True)
        self._loading = True
        index = self._kind.findData(step.kind)
        if index >= 0:
            self._kind.setCurrentIndex(index)
        self._label.setText(step.label)
        self._x.setValue(step.x)
        self._y.setValue(step.y)
        self._image.setText(step.image)
        region = step.region()
        self._region.setText(
            f"{region[0]}, {region[1]}  {region[2]}x{region[3]}" if region else ""
        )
        self._timeout.setValue(step.timeout)
        self._scrolls.setValue(step.max_scrolls)
        self._notches.setValue(step.notches)
        self._scroll_x.setValue(step.scroll_x)
        self._scroll_y.setValue(step.scroll_y)
        self._button.setCurrentText(step.button)
        self._count.setValue(max(1, step.count))
        self._wait.setValue(step.wait_ms)
        self._loading = False
        self._apply_visibility(step.kind)

    def _apply_visibility(self, kind: str | None) -> None:
        """Show only the fields this kind uses — every widget is built visible, so
        without this the union of all kinds shows at once."""
        probe = NavStep(kind=kind or "")
        groups = (
            ("x", (self._lbl_point, self._x, self._y, self._pick_point)),
            ("image", (self._lbl_image, self._image, self._capture, self._test)),
            (
                "region",
                (self._lbl_region, self._region, self._pick_region, self._clear_region),
            ),
            ("timeout", (self._lbl_timeout, self._timeout)),
            ("max_scrolls", (self._lbl_scrolls, self._scrolls)),
            ("notches", (self._lbl_notches, self._notches)),
            (
                "scroll_x",
                (
                    self._lbl_scroll_point,
                    self._scroll_x,
                    self._scroll_y,
                    self._pick_scroll,
                    self._clear_scroll,
                ),
            ),
            ("button", (self._lbl_button, self._button)),
            ("count", (self._lbl_count, self._count)),
            ("wait_ms", (self._lbl_wait, self._wait)),
        )
        for name, widgets in groups:
            visible = probe.uses(name)
            for widget in widgets:
                widget.setVisible(visible)
        self._label.setVisible(bool(kind))
