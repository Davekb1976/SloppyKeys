"""Settings screen: global macro configuration, split into tabs.

Tasks and Route live here rather than in the Run panel's stats card. They are things you
set up and then leave alone, so they belong with the other configuration; the Run panel
went back to being what you watch while the macro works. The viewport is still on the
left in this screen, which is what lets the Route tab's capture and coordinate pickers
keep working from here.

Main     — connection and macro behaviour.
Keybinds — the app's hotkeys and the keys the macro sends in game.
Delays   — the DELAY_SPEC tunables.
Position — per-target start-position plans (see ui/position_editor.py).
Debug    — the image tester plus the entry point to the Macro Tester window.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from sloppykeys.config.delays import DELAY_SPEC
from sloppykeys.config.keybinds import ACTIONS, GAME_ACTIONS, Keybind


from .. import icons, theme
from ..position_editor import PositionEditor
from ..widgets import KeyCaptureButton, ToggleSwitch

# "Vision", not "Images": the tab holds the template images *and* the OCR text boxes, and
# it matches the Macro Tester's VISION group, which is where the same things are tested.
TABS = ("Main", "Tasks", "Route", "Vision", "Keybinds", "Delays", "Position", "Debug")
TABS_PER_ROW = 4


class SettingsPage(QWidget):
    linkCommitted = Signal(str)
    joinRequested = Signal()
    webhookCommitted = Signal(str)
    webhookTestRequested = Signal()
    hardModeToggled = Signal(bool)
    cameraOnceToggled = Signal(bool)
    autoUpdateToggled = Signal(bool)
    updateCheckRequested = Signal()
    updateActionRequested = Signal()
    openTesterRequested = Signal()
    keybindChanged = Signal(str, object)  # action, Keybind
    gameKeyChanged = Signal(str, str)     # action, single key character
    expeditionDifficultyChanged = Signal(int)  # 1-3

    delayChanged = Signal(str, float)     # key, seconds

    def __init__(
        self,
        maps_provider=None,
        targets_provider=None,
        tasks_tab: QWidget | None = None,
        route_tab: QWidget | None = None,
        images_tab: QWidget | None = None,
    ) -> None:
        """The two providers are forwarded to the Position tab's editor, which owns
        its own Gamemode/Map/Act selectors. Events supplies its maps and acts from
        routes.json rather than the gamemode table."""
        super().__init__()
        self._maps_provider = maps_provider
        self._targets_provider = targets_provider
        root = QVBoxLayout(self)
        root.setContentsMargins(14, 12, 14, 14)
        root.setSpacing(10)

        root.addLayout(self._build_header())
        root.addLayout(self._build_tabbar())

        self._tabs = QStackedWidget()
        # Order must match TABS.
        self._tabs.addWidget(self._build_main_tab())
        self._tabs.addWidget(_scroll_wrapped(tasks_tab, "Task queue is unavailable."))
        self._tabs.addWidget(_scroll_wrapped(route_tab, "Route building is unavailable."))
        # Not `_scroll_wrapped`: the Vision tab scrolls its own list, and nesting two
        # scroll areas leaves the inner one unable to size itself.
        self._tabs.addWidget(images_tab or _scroll_wrapped(None, "Vision tools are unavailable."))
        self._tabs.addWidget(self._build_keybinds_tab())
        self._tabs.addWidget(self._build_delays_tab())
        self._tabs.addWidget(self._build_position_tab())
        self._tabs.addWidget(self._build_debug_tab())
        root.addWidget(self._tabs, 1)

        self._set_tab(0)

    # # Header + tab bar
    def _build_header(self) -> QHBoxLayout:
        header = QHBoxLayout()
        titles = QVBoxLayout()
        titles.setSpacing(1)
        title = QLabel("Settings")
        title.setObjectName("h1")
        sub = QLabel("Global macro configuration")
        sub.setStyleSheet(f"color: {theme.TEXT_FAINT}; font-size: 11px;")
        # Wraps instead of forcing the header (and so the whole page) wider than
        # the right-hand panel it now lives in.
        sub.setWordWrap(True)
        titles.addWidget(title)
        titles.addWidget(sub)
        header.addLayout(titles)
        header.addStretch(1)

        # No Save button here. Every control on this page writes as you edit it, so the
        # button only ever logged "Settings saved." — and two Save buttons in one app,
        # one of which did nothing, is worse than none. The run strip's Save is the only
        # one, and it covers the thing that genuinely needs an explicit save: the unit
        # plan.
        return header

    def _build_tabbar(self) -> QGridLayout:
        """Tabs on a grid, TABS_PER_ROW across.

        A single row of five would need ~500px with the QSS padding, and this page
        now lives in the right-hand panel (~430px), where a squeezed row elides its
        labels. Wrapping keeps every tab readable.
        """
        bar = QGridLayout()
        bar.setSpacing(6)
        self._tab_buttons: list[QPushButton] = []
        for index, name in enumerate(TABS):
            btn = QPushButton(name)
            btn.setObjectName("tab")
            btn.setFixedHeight(30)
            btn.clicked.connect(lambda _c=False, i=index: self._set_tab(i))
            bar.addWidget(btn, index // TABS_PER_ROW, index % TABS_PER_ROW)
            self._tab_buttons.append(btn)
        for column in range(TABS_PER_ROW):
            bar.setColumnStretch(column, 1)
        return bar

    def show_tab(self, name: str) -> None:
        """Open a tab by name, for callers sending the user back where they came from."""
        if name in TABS:
            self._set_tab(TABS.index(name))

    def _set_tab(self, index: int) -> None:
        self._tabs.setCurrentIndex(index)
        for position, btn in enumerate(self._tab_buttons):
            btn.setObjectName("tabOn" if position == index else "tab")
            btn.style().unpolish(btn)
            btn.style().polish(btn)

    # # Main tab
    def _build_main_tab(self) -> QWidget:
        body, col = _scroll_body()

        col.addLayout(_group("CONNECTION"))
        self._link = QLineEdit()
        self._link.setPlaceholderText("https://www.roblox.com/share?code=...&type=Server")
        self._link.editingFinished.connect(
            lambda: self.linkCommitted.emit(self._link.text().strip())
        )
        col.addWidget(_row("Private Server Link", self._link, stretch_widget=True))

        join = QPushButton(f"{icons.LINK}  Join Server")
        join.setStyleSheet(f"font-family: '{theme.ICON_FAMILY}';")
        join.clicked.connect(self.joinRequested.emit)
        col.addLayout(_left(join))
        self._link_status = _status_label()
        col.addWidget(self._link_status)

        col.addLayout(_group("DISCORD"))
        self._webhook = QLineEdit()
        self._webhook.setPlaceholderText("https://discord.com/api/webhooks/...")
        # Echo mode stays Normal on purpose: a webhook URL is a secret, but masking
        # it would make a paste impossible to check, and it is already visible in
        # settings.json. Never log the URL itself.
        self._webhook.editingFinished.connect(
            lambda: self.webhookCommitted.emit(self._webhook.text().strip())
        )
        col.addWidget(_row("Discord Webhook URL", self._webhook, stretch_widget=True))

        test = QPushButton(f"{icons.LINK}  Send Test")
        test.setStyleSheet(f"font-family: '{theme.ICON_FAMILY}';")
        test.clicked.connect(self.webhookTestRequested.emit)
        col.addLayout(_left(test))
        self._webhook_status = _status_label()
        col.addWidget(self._webhook_status)

        col.addLayout(_group("MACRO"))
        # No "Run challenges" toggle here on purpose: putting a challenge slot in the
        # Tasks tab *is* the enable. Two switches for one intent meant a queued
        # challenge slot silently did nothing until this was also on.
        self._camera_once = ToggleSwitch()
        self._camera_once.setToolTip(
            "Off (default): the ~8s camera sequence runs before every match.\n"
            "On: it runs once per Roblox session, saving ~8s on each following match.\n\n"
            "Turn it on only if the camera is still correct on the second match — every "
            "placement coordinate is stored against one camera angle, so a camera that "
            "quietly reset would misplace every unit."
        )
        self._camera_once.toggled.connect(self.cameraOnceToggled.emit)
        col.addWidget(_row("Set the camera once per session", self._camera_once))

        self._hard_mode = ToggleSwitch()
        self._hard_mode.toggled.connect(self.hardModeToggled.emit)
        col.addWidget(_row("Hard Mode (Story only)", self._hard_mode))

        # Expedition's difficulty is a toggle for the same map, like Hard Mode —
        # not a farm target, so it belongs here and not in the Run selectors.
        self._expedition_difficulty = QComboBox()
        self._expedition_difficulty.addItems(["1", "2", "3"])
        self._expedition_difficulty.setFixedWidth(80)
        self._expedition_difficulty.currentTextChanged.connect(
            lambda text: self.expeditionDifficultyChanged.emit(int(text))
        )
        col.addWidget(_row("Difficulty (Expedition only)", self._expedition_difficulty))

        # Still no **global** "Match tolerance" control here, and no Auto-calibrate button.
        # Both stay removed: one number for every template made the macro's behaviour depend
        # on a value nobody could judge, and the Auto button calibrated it from whatever was
        # on screen — observed at **0.57** one minute (false matches) and **0.95** the next
        # (rejecting nearly everything, since a good match scores 0.95-1.00). Either way the
        # following run broke and it looked like an image problem.
        #
        # Tolerance is **per template** now, in Settings > Vision: one image's threshold
        # can't break the others, the floor is `CONFIDENCE_USER_MIN` (0.60), and each row has
        # a Test button so the number is set against a measured score instead of a feeling.
        # A template that can't clear the default 0.70 is usually still the wrong size or
        # crop — recapture before lowering (`images/README.md`).

        col.addLayout(_group("UPDATES"))
        self._auto_update = ToggleSwitch()
        self._auto_update.setToolTip(
            "Ask GitHub once per launch whether there's a newer release.\n"
            "Nothing is ever downloaded without you clicking the button below."
        )
        self._auto_update.toggled.connect(self.autoUpdateToggled.emit)
        col.addWidget(_row("Check for updates on startup", self._auto_update))

        check = QPushButton(f"{icons.REFRESH}  Check Now")
        check.setStyleSheet(f"font-family: '{theme.ICON_FAMILY}';")
        check.clicked.connect(self.updateCheckRequested.emit)
        col.addLayout(_left(check))

        # Hidden until there is something to do, so the Main tab doesn't carry a dead
        # button. Its label says which of the two things it will do.
        self._update_action = QPushButton("")
        self._update_action.setStyleSheet(f"font-family: '{theme.ICON_FAMILY}';")
        self._update_action.clicked.connect(self.updateActionRequested.emit)
        self._update_action.hide()
        col.addLayout(_left(self._update_action))
        self._update_status = _status_label()
        col.addWidget(self._update_status)

        col.addStretch(1)
        return body

    def set_auto_update(self, enabled: bool) -> None:
        self._auto_update.setChecked(bool(enabled))

    def set_update_status(self, text: str, is_error: bool = False) -> None:
        _paint_status(self._update_status, text, is_error)

    def set_update_action(self, label: str) -> None:
        """Show the button with `label`, or hide it when `label` is empty."""
        self._update_action.setText(label)
        self._update_action.setVisible(bool(label))

    # # Delays tab
    def _build_delays_tab(self) -> QWidget:
        body, col = _scroll_body()
        col.addLayout(_group("DELAYS"))
        note = QLabel("Seconds. Applied immediately.")
        note.setStyleSheet(f"color: {theme.TEXT_FAINT}; font-size: 11px;")
        col.addWidget(note)

        self._delay_spins: dict[str, QDoubleSpinBox] = {}
        for key, (label, _default) in DELAY_SPEC.items():
            spin = QDoubleSpinBox()
            spin.setRange(0.0, 60.0)
            spin.setSingleStep(0.5)
            spin.setDecimals(1)
            spin.setSuffix(" s")
            spin.setFixedWidth(110)
            spin.valueChanged.connect(lambda v, k=key: self.delayChanged.emit(k, float(v)))
            self._delay_spins[key] = spin
            col.addWidget(_row(label, spin))

        col.addStretch(1)
        return body

    def set_delay(self, key: str, value: float) -> None:
        spin = self._delay_spins.get(key)
        if spin is not None:
            spin.blockSignals(True)
            spin.setValue(value)
            spin.blockSignals(False)

    def set_camera_once(self, enabled: bool) -> None:
        self._camera_once.blockSignals(True)
        self._camera_once.setChecked(enabled)
        self._camera_once.blockSignals(False)

    def set_hard_mode(self, enabled: bool) -> None:
        self._hard_mode.blockSignals(True)
        self._hard_mode.setChecked(enabled)
        self._hard_mode.blockSignals(False)

    def set_expedition_difficulty(self, value: int) -> None:
        self._expedition_difficulty.blockSignals(True)
        self._expedition_difficulty.setCurrentText(str(max(1, min(3, int(value)))))
        self._expedition_difficulty.blockSignals(False)



    # # Keybinds tab
    def _build_keybinds_tab(self) -> QWidget:
        body, col = _scroll_body()
        col.addLayout(_group("HOTKEYS"))
        note = QLabel("Click a binding, then press the new key combo (Esc to cancel).")
        note.setStyleSheet(f"color: {theme.TEXT_FAINT}; font-size: 11px;")
        note.setWordWrap(True)
        col.addWidget(note)

        self._keybind_buttons: dict[str, KeyCaptureButton] = {}
        for action, label in ACTIONS.items():
            button = KeyCaptureButton(Keybind(0))
            button.captured.connect(
                lambda kb, a=action: self.keybindChanged.emit(a, kb)
            )
            self._keybind_buttons[action] = button
            col.addWidget(_row(label, button))

        col.addLayout(_group("IN-GAME KEYS"))
        game_note = QLabel(
            "Keys the macro presses in Anime Expedition. Match these to the game's "
            "own binds — one letter or number each."
        )
        game_note.setStyleSheet(f"color: {theme.TEXT_FAINT}; font-size: 11px;")
        game_note.setWordWrap(True)
        col.addWidget(game_note)

        self._game_key_edits: dict[str, QLineEdit] = {}
        for action, label in GAME_ACTIONS.items():
            edit = QLineEdit()
            edit.setMaxLength(1)
            edit.setFixedWidth(52)
            edit.setAlignment(Qt.AlignmentFlag.AlignCenter)
            edit.textChanged.connect(
                lambda text, a=action: self.gameKeyChanged.emit(a, text.strip().lower())
            )
            self._game_key_edits[action] = edit
            col.addWidget(_row(label, edit))

        col.addStretch(1)
        return body

    def set_keybind(self, action: str, keybind: Keybind) -> None:
        button = self._keybind_buttons.get(action)
        if button is not None:
            button.set_keybind(keybind)

    def set_game_key(self, action: str, key: str) -> None:
        edit = self._game_key_edits.get(action)
        if edit is None:
            return
        edit.blockSignals(True)
        edit.setText(key)
        edit.blockSignals(False)

    # # Position tab
    def _build_position_tab(self) -> QWidget:
        body, col = _scroll_body()
        col.addLayout(_group("START POSITION"))
        note = QLabel(
            "Walk the character into place before the first placement. Runs once per "
            "run, straight after the camera step, and only for the target picked "
            "here — most targets need nothing. Saved as you edit."
        )
        note.setStyleSheet(f"color: {theme.TEXT_FAINT}; font-size: 11px;")
        note.setWordWrap(True)
        col.addWidget(note)

        self._position = PositionEditor(self._maps_provider, self._targets_provider)
        col.addWidget(self._position)
        self._position_status = _status_label()
        col.addWidget(self._position_status)

        col.addStretch(1)
        return body

    @property
    def position_editor(self) -> PositionEditor:
        """MainWindow wires the editor's signals to StartPositionStore."""
        return self._position

    def set_position_status(self, text: str, is_error: bool = False) -> None:
        _paint_status(self._position_status, text, is_error)

    # # Debug tab
    def _build_debug_tab(self) -> QWidget:
        body, col = _scroll_body()

        col.addLayout(_group("MACRO TESTING"))
        note = QLabel(
            "Run individual macro steps in isolation before wiring them up. "
            "The image tester lives in this window too."
        )
        note.setStyleSheet(f"color: {theme.TEXT_FAINT}; font-size: 11px;")
        note.setWordWrap(True)
        col.addWidget(note)

        open_tester = QPushButton(f"{icons.PLAY}  Open Macro Tester")
        open_tester.setObjectName("primary")
        open_tester.setStyleSheet(f"font-family: '{theme.ICON_FAMILY}';")
        open_tester.setFixedHeight(34)
        open_tester.clicked.connect(self.openTesterRequested.emit)
        col.addLayout(_left(open_tester))

        col.addStretch(1)
        return body

    # # Public API
    def set_link(self, text: str) -> None:
        self._link.setText(text)

    def set_link_status(self, text: str, is_error: bool = False) -> None:
        _paint_status(self._link_status, text, is_error)

    def set_webhook(self, text: str) -> None:
        self._webhook.setText(text)

    def set_webhook_status(self, text: str, is_error: bool = False) -> None:
        _paint_status(self._webhook_status, text, is_error)






# # Builders
def _scroll_body() -> tuple[QWidget, QVBoxLayout]:
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    # Vertical only: the panel is narrow, so a horizontal bar would appear on
    # every tab. Rows wrap their labels instead (see _row).
    scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    inner = QWidget()
    col = QVBoxLayout(inner)
    col.setContentsMargins(0, 0, 6, 0)
    col.setSpacing(10)
    scroll.setWidget(inner)
    return scroll, col


def _scroll_wrapped(inner: QWidget | None, missing: str) -> QWidget:
    """A tab whose body is a widget built elsewhere (Tasks, Route).

    Scrolled for the same reason the other tabs are: these editors are taller than the
    panel, and without it their children paint past the fixed window instead of
    scrolling. `missing` names an absent widget rather than showing an empty tab.
    """
    if inner is None:
        label = QLabel(missing)
        label.setWordWrap(True)
        label.setStyleSheet(f"color: {theme.TEXT_FAINT}; font-size: 11px;")
        inner = label
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QFrame.Shape.NoFrame)
    scroll.setWidget(inner)
    scroll.setMinimumHeight(0)
    return scroll


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


def _row(label_text: str, control: QWidget, stretch_widget: bool = False) -> QWidget:
    holder = QWidget()
    row = QHBoxLayout(holder)
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(12)
    label = QLabel(label_text)
    label.setStyleSheet(f"color: {theme.TEXT_DIM}; font-size: 12px;")
    # Wraps rather than pushing the control off the edge of a ~430px panel.
    label.setWordWrap(True)
    row.addWidget(label)
    if stretch_widget:
        row.addWidget(control, 1)
    else:
        row.addStretch(1)
        row.addWidget(control, 0, Qt.AlignmentFlag.AlignRight)
    return holder


def _left(widget: QWidget) -> QHBoxLayout:
    row = QHBoxLayout()
    row.addWidget(widget)
    row.addStretch(1)
    return row


def _status_label() -> QLabel:
    label = QLabel("")
    label.setObjectName("status")
    label.setWordWrap(True)
    return label


def _paint_status(label: QLabel, text: str, is_error: bool) -> None:
    label.setStyleSheet(
        f"color: {theme.BAD if is_error else theme.TEXT_DIM}; font-size: 12px;"
    )
    label.setText(text)
