"""Run strip: the horizontal panel below the viewport.

Three columns like the reference: PROCESS LOG (wide) | CURRENT CONFIG | ACTIONS.
The gamemode is chosen on the Selector and shown in the titlebar, so this only
cascades Map -> Act/Difficulty and exposes Save / Import / Reset.

The middle column has a second face. With **Task** picked on the Selector it becomes
the queue view (`QueueView`): the slots in the order the run will follow them, each
with its run limit. The queue is edited in Settings > Tasks; here it is what the run
is doing, plus the one number worth changing while watching it.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from sloppykeys.config.tasks import LIMIT_MAX, LIMIT_MIN

from sloppykeys.content.gamemodes import (
    has_targets,
    labels_for,
    maps_for,
    selection_complete,
    targets_for,
)

from .. import icons, theme
from ..glow import TrailBorder
from ..widgets import LogView


class RunPage(QWidget):
    targetChanged = Signal()
    saveRequested = Signal()
    importRequested = Signal()
    resetRequested = Signal()
    queueLimitChanged = Signal(int, int)  # slot index (0-based), new run limit

    def __init__(self, maps_provider=None, targets_provider=None) -> None:
        """`maps_provider(gamemode)` / `targets_provider(gamemode, map)` override
        the static tables in `content.gamemodes`.

        Events builds its maps and acts at runtime (routes.json), so this page
        can't read them from a table. Both default to the table lookups, which is
        what Story, Raid and Expedition keep using.
        """
        super().__init__()
        self._gamemode = ""
        self._maps_for = maps_provider or maps_for
        self._targets_for = targets_provider or targets_for

        root = QHBoxLayout(self)
        root.setContentsMargins(12, 8, 12, 10)
        root.setSpacing(10)

        root.addWidget(self._build_log(), 1)
        root.addWidget(self._build_config())
        root.addWidget(self._build_actions())

    # # Columns
    def _build_log(self) -> QWidget:
        col = QFrame()
        col.setObjectName("sectionBox")
        box = QVBoxLayout(col)
        box.setContentsMargins(12, 10, 12, 12)
        box.setSpacing(8)
        box.addLayout(_group("PROCESS LOG"))
        self._log = LogView()
        # Let the log shrink: its default sizeHint is tall enough to force the
        # whole strip past its fixed height.
        self._log.setMinimumHeight(40)
        box.addWidget(self._log, 1)

        # Status lives here rather than in CURRENT CONFIG, which has no spare room.
        self._status = QLabel("Pick a gamemode to configure.")
        self._status.setObjectName("status")
        # Wrap, and never let the text drive this column's width: the strip sits in a
        # fixed-width left column, and an unwrapped status line used to widen it and
        # squeeze the right-hand panel.
        self._status.setWordWrap(True)
        self._status.setMinimumWidth(1)
        box.addWidget(self._status)
        return col

    def _build_config(self) -> QWidget:
        col = QFrame()
        col.setObjectName("sectionBox")
        col.setFixedWidth(250)
        box = QVBoxLayout(col)
        box.setContentsMargins(12, 10, 12, 12)
        box.setSpacing(8)
        self._config_head = QLabel("CURRENT CONFIG")
        self._config_head.setObjectName("groupHead")
        head = QHBoxLayout()
        head.setSpacing(8)
        line = QFrame()
        line.setObjectName("sep")
        head.addWidget(self._config_head)
        head.addWidget(line, 1)
        box.addLayout(head)

        # Two faces for this column: the Map/Act selectors for a normal gamemode, and
        # the task queue when Task is the selection. Same column because it answers the
        # same question either way — what is this run going to play.
        self._config_stack = QStackedWidget()

        selectors = QWidget()
        selector_box = QVBoxLayout(selectors)
        selector_box.setContentsMargins(0, 0, 0, 0)
        selector_box.setSpacing(8)
        self._map_label, self._map = _selector(selector_box, "Map")
        self._map.currentIndexChanged.connect(self._on_map_changed)
        self._target_label, self._target = _selector(selector_box, "Act")
        self._target.currentIndexChanged.connect(self._on_target_picked)
        selector_box.addStretch(1)
        self._config_stack.addWidget(selectors)

        self._queue_view = QueueView()
        self._queue_view.limitChanged.connect(self.queueLimitChanged.emit)
        self._config_stack.addWidget(self._queue_view)
        box.addWidget(self._config_stack, 1)

        # Nothing else on this screen moves, so a freshly picked gamemode leaves
        # the user hunting for where to choose the map. The trail runs until the
        # selection is complete, then settles into a solid outline.
        self._trail = TrailBorder(col, theme.ACCENT, radius=12)
        return col

    # # Task mode
    def show_queue(self, slots: list) -> None:
        """Swap this column to the queue view and fill it.

        The queue is *edited* in Settings > Tasks; here it is the order the run will
        follow, with the one number worth changing while you watch a run — how many
        matches each target gets before handing over.
        """
        self._config_head.setText("TASK QUEUE")
        self._queue_view.load(slots)
        self._config_stack.setCurrentIndex(1)
        self._trail.set_outline(bool(slots))

    def show_selectors(self) -> None:
        self._config_head.setText("CURRENT CONFIG")
        self._config_stack.setCurrentIndex(0)

    def _update_trail(self) -> None:
        """Moving trail while a selection is still owed, solid full outline once it
        is complete, nothing at all before a gamemode is picked."""
        gamemode, map_name, target = self.selection()
        if not gamemode:
            self._trail.set_active(False)
            return
        if selection_complete(gamemode, map_name, target):
            self._trail.set_outline(True)
            return
        self._trail.set_active(True)

    def _build_actions(self) -> QWidget:
        col = QFrame()
        col.setObjectName("sectionBox")
        col.setFixedWidth(180)
        box = QVBoxLayout(col)
        box.setContentsMargins(12, 10, 12, 12)
        box.setSpacing(8)
        box.addLayout(_group("ACTIONS"))

        # Just "Save": it is the app's only save button now (Settings has none — those
        # controls write as you edit), so naming it after one of the things it saves was
        # misleading.
        self._save = QPushButton(f"{icons.SAVE}  Save")
        self._save.setObjectName("primary")
        self._save.clicked.connect(self.saveRequested.emit)
        imp = QPushButton(f"{icons.IMAGE}  Import Config")
        imp.clicked.connect(self.importRequested.emit)
        reset = QPushButton(f"{icons.REFRESH}  Reset Config")
        reset.clicked.connect(self.resetRequested.emit)
        box.setSpacing(6)
        for btn in (self._save, imp, reset):
            btn.setStyleSheet(f"font-family: '{theme.ICON_FAMILY}'; padding: 3px 10px;")
            btn.setFixedHeight(28)
            box.addWidget(btn)
        box.addStretch(1)
        return col

    # # Gamemode wiring
    def set_gamemode(self, name: str) -> None:
        self._gamemode = name
        map_label, target_label = labels_for(name)
        self._map_label.setText(map_label.upper())
        self._target_label.setText(target_label.upper())
        _fill(self._map, self._maps_for(name), f"Select {map_label}")
        self._target.parentWidget().hide()
        _blank(self._target)
        self._update_trail()
        self.targetChanged.emit()

    def _on_target_picked(self, _index: int) -> None:
        self._update_trail()
        self.targetChanged.emit()

    def _on_map_changed(self, _index: int) -> None:
        map_name = _current(self._map)
        # A gamemode with no target dimension (Expedition) saves one config per
        # map, so there is nothing to pick here — keep the selector hidden.
        if not (self._gamemode and map_name) or not has_targets(self._gamemode):
            self._target.parentWidget().hide()
            _blank(self._target)
            self._update_trail()
            self.targetChanged.emit()
            return
        _map_label, target_label = labels_for(self._gamemode)
        _fill(
            self._target, self._targets_for(self._gamemode, map_name), f"Select {target_label}"
        )
        self._target.parentWidget().show()
        self._update_trail()
        self.targetChanged.emit()

    def clear_gamemode(self) -> None:
        """Reset to no selection so switching pages can't resurrect a stale mode."""
        self._gamemode = ""
        _blank(self._map)
        _blank(self._target)
        self._target.parentWidget().hide()
        self._update_trail()
        self.set_status("Pick a gamemode to configure.")

    def refresh_options(self) -> None:
        """Re-read the provider lists, keeping the current selection if it survived.

        Called when a custom map or act is added, renamed away or deleted: the
        dropdowns are the only place those names appear, so without this the strip
        keeps offering a route that no longer exists.
        """
        if not self._gamemode:
            return
        map_name, target = _current(self._map), _current(self._target)
        self.set_gamemode(self._gamemode)
        if map_name and self._map.findText(map_name) >= 0:
            self._map.setCurrentText(map_name)  # cascades into the target combo
            if target and self._target.findText(target) >= 0:
                self._target.setCurrentText(target)

    # # Public API
    def selection(self) -> tuple[str, str, str]:
        return (self._gamemode, _current(self._map), _current(self._target))

    def set_status(self, text: str, is_error: bool = False) -> None:
        color = theme.BAD if is_error else theme.TEXT_DIM
        self._status.setStyleSheet(f"color: {color}; font-size: 11px;")
        self._status.setText(text)

    def append_log(self, text: str) -> None:
        self._log.append_line(text)

    def set_running(self, running: bool) -> None:
        self._save.setEnabled(not running)


# # Builders
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


def _selector(box: QVBoxLayout, label: str) -> tuple[QLabel, QComboBox]:
    row = QWidget()
    inner = QVBoxLayout(row)
    inner.setContentsMargins(0, 0, 0, 0)
    inner.setSpacing(3)
    caption = QLabel(label.upper())
    caption.setObjectName("fieldLabel")
    combo = QComboBox()
    combo.setFixedHeight(28)
    inner.addWidget(caption)
    inner.addWidget(combo)
    box.addWidget(row)
    return caption, combo


def _current(combo: QComboBox) -> str:
    return "" if combo.currentIndex() <= 0 else combo.currentText()


def _fill(combo: QComboBox, items: list[str], placeholder: str) -> None:
    combo.blockSignals(True)
    combo.clear()
    combo.addItem(placeholder)
    combo.addItems(items)
    combo.setCurrentIndex(0)
    combo.blockSignals(False)


def _blank(combo: QComboBox) -> None:
    combo.blockSignals(True)
    combo.clear()
    combo.blockSignals(False)


class QueueView(QWidget):
    """The task queue as the run will follow it: order, target, and a run limit.

    Read-only about *what* each slot is — that is edited in Settings > Tasks — and
    editable only for the limit, which is the number you actually want to nudge while
    watching a run. Empty slots are skipped rather than drawn as blanks.
    """

    limitChanged = Signal(int, int)  # slot index (0-based), new limit

    def __init__(self) -> None:
        super().__init__()
        self._box = QVBoxLayout(self)
        self._box.setContentsMargins(0, 0, 0, 0)
        self._box.setSpacing(4)
        # No re-roll clock here: the stats card's CHALLENGES group shows it, and the same
        # fact in two places is one place too many.
        self._empty = QLabel("No tasks queued.\nAdd them in Settings > Tasks.")
        self._empty.setWordWrap(True)
        self._empty.setMinimumWidth(1)
        self._empty.setStyleSheet(f"color: {theme.TEXT_FAINT}; font-size: 10px;")
        self._box.addWidget(self._empty)
        self._box.addStretch(1)
        self._rows: list[QWidget] = []

    def load(self, slots: list) -> None:
        for row in self._rows:
            self._box.removeWidget(row)
            row.deleteLater()
        self._rows = []

        position = 0
        for index, slot in enumerate(slots):
            if not slot.is_runnable():
                continue
            position += 1
            self._rows.append(self._build_row(position, index, slot))
        self._empty.setVisible(not self._rows)
        for offset, row in enumerate(self._rows):
            self._box.insertWidget(offset, row)

    def _build_row(self, position: int, index: int, slot) -> QWidget:
        holder = QWidget()
        row = QHBoxLayout(holder)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)

        label = QLabel(f"{position}. {slot.summary().split(' \u00b7 ')[0]}")
        label.setWordWrap(True)
        label.setMinimumWidth(1)
        label.setStyleSheet(f"color: {theme.TEXT}; font-size: 10px;")
        row.addWidget(label, 1)

        if slot.uses_limit():
            spin = QSpinBox()
            spin.setRange(LIMIT_MIN, LIMIT_MAX)
            spin.setValue(slot.limit)
            spin.setFixedWidth(56)
            spin.setToolTip("Matches to run before moving to the next task")
            spin.valueChanged.connect(
                lambda value, position=index: self.limitChanged.emit(position, int(value))
            )
            row.addWidget(spin)
        else:
            # Challenges run until the game says no, so a limit here would be fiction.
            tag = QLabel("all")
            tag.setStyleSheet(f"color: {theme.TEXT_FAINT}; font-size: 10px;")
            row.addWidget(tag)
        return holder
