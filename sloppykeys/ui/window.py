"""Application shell: frameless titlebar, left rail, fixed Roblox viewport, and
swappable Run / Units / Settings pages. Backend services (config store, image
profiles, macro runner, challenge tracker, Roblox sync) live here; the pages are
thin views connected by signals.
"""

from __future__ import annotations

import os
import random
import sys
import threading
import time
import traceback
from datetime import datetime

from PySide6.QtCore import (
    QEvent,
    QPoint,
    QRectF,
    QSize,
    Qt,
    QThread,
    QThreadPool,
    QTimer,
    QUrl,
    Signal,
)
from PySide6.QtGui import (
    QColor,
    QDesktopServices,
    QImage,
    QPainter,
    QPainterPath,
    QPen,
    QRegion,
)
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from .glow import HoverGlow
from .image_manager import ImageManager
from .route_editor import RouteEditor

from sloppykeys.config.settings import AppSettings, ImageProfileStore, parse_private_server_link
from sloppykeys.config.stats import StatsTracker
from sloppykeys.core.webhook import (
    COLOR_END,
    COLOR_LOSS,
    COLOR_START,
    COLOR_WIN,
    DiscordWebhook,
    validate_webhook_url,
)
from sloppykeys.config.store import read_json
from sloppykeys.config.unit_configs import UnitConfigStore
from sloppykeys.content.gamemodes import (
    CHALLENGE,
    GAMEMODE_NAMES,
    TASK_SELECTION,
    is_side_task,
    has_targets,
    is_custom,
    maps_for,
    selection_complete,
    targets_for,
)
from sloppykeys.config.nav_routes import RouteStore
from sloppykeys.content.nav_images import events_image, gamemode_image, play_image
from sloppykeys.content.nav_route import KIND_EXPECT, KIND_FIND, route_problems
from sloppykeys.content.units import UnitPlan, UnitStep
from sloppykeys.core.ahk import AhkBridge
from sloppykeys.core.image_search import (
    ImageProfile,
    ImageSearchEngine,
    apply_confidence_overrides,
)
from sloppykeys.core.ocr import OcrReader
from sloppykeys.config.delays import DelaysStore
from sloppykeys.config.regions import ConfidenceStore, PointStore, RegionStore
from sloppykeys.config.start_position import StartPositionStore
from sloppykeys.config.tasks import TaskStore
from sloppykeys.content.start_position import total_hold_ms
from sloppykeys.config.keybinds import (
    ACTIONS,
    GAME_ACTIONS,
    GameKeyStore,
    Keybind,
    KeybindStore,
)
from sloppykeys.core.win32 import roblox_window as rbx
from sloppykeys.core.win32.display import refresh_hz_for_window, scale_percent_for_window
from sloppykeys.macro import input_scripts
from sloppykeys.macro.camera import camera_setup_script
from sloppykeys.macro.lobby import LobbyNavigator
from sloppykeys.macro.placement import OUTCOME_LOST, OUTCOME_WON, UnitPlacer, split_steps
from sloppykeys.core.win32.bindings import VK_CONTROL, VK_MENU, VK_SHIFT, is_key_down
from sloppykeys.content.acts import act_coord
from sloppykeys.content.acts import apply_point_overrides as apply_act_overrides
from sloppykeys.content.start_stage import apply_point_overrides as apply_start_overrides
from sloppykeys.content.start_stage import difficulty_coord
from sloppykeys.content.challenge import apply_region_overrides
from sloppykeys.content.challenge import row_click as challenge_row_click
from sloppykeys.content.challenge import SLOTS as CHALLENGE_SLOTS
from sloppykeys.content.challenge import SELECT_STAGE_CLICK as CHALLENGE_SELECT_STAGE
from sloppykeys.content.challenge import START_CLICK as CHALLENGE_START
from sloppykeys.content.challenge import debug_boxes as challenge_debug_boxes
from sloppykeys.content.challenge import debug_path as challenge_debug_path
from sloppykeys.content.challenge import next_interval_at
from sloppykeys.macro.challenge import (
    STATE_RUNNABLE,
    STATE_UNKNOWN,
    ChallengeRead,
    ChallengeScanner,
    ChallengeTracker,
)
from sloppykeys.macro.runner import MacroRunner, MacroStep, MacroTarget, Phase, StepResult
from sloppykeys.macro.tasks import (  # noqa: F401
    DO_CHALLENGE,
    DO_TARGET,
    TaskDecision,
    TaskDirector,
)

from . import icons, theme
from .macro_tester import MacroTesterWindow, Task
from .task_editor import TaskEditor
from .pages.run_page import RunPage
from .pages.selector_page import SelectorPage
from .pages.settings_page import SettingsPage
from .pages.stats_page import StatsPage
from .pages.units_page import UnitsPage
from .viewport import RobloxViewport

# Not a version number on purpose — there is no release cadence to track yet, and a
# stale "0.3.0" in the titlebar is worse than no number. `installer.iss`'s AppVersion
# says the same word; keep the two in step if this ever becomes a real number.
VERSION = "beta"
LOG_FILE = "log.txt"
LOG_PREV_FILE = "log.prev.txt"
# Nothing was ever deleting log.txt. One append per line is cheap, but a long grind
# would grow it without limit, so at this size it becomes log.prev.txt and a fresh
# file starts. Two generations is all anyone reads back.
LOG_FILE_MAX_BYTES = 2 * 1024 * 1024
HOTKEY_MS = 40
WINDOW_RADIUS = 13
# Longest a test worker will block waiting for a UI-thread dialog answer.
# Generous: it's a human deciding, not a machine.
ASK_DIALOG_TIMEOUT = 300.0
# The camera script sleeps ~7.8s (2x 3s zoom holds + the pitch drag). Only
# applies when it's run blocking; leaves headroom for a slow machine.
CAMERA_TIMEOUT = 20.0
# Idle between run-loop ticks. Steps block for seconds at a time, so this only
# decides how quickly a stop request is noticed once a step returns.
RUN_TICK_SLEEP = 0.05
# Per-step budget for the run loop. Steps report DONE/FAILED themselves, so this
# only bounds a step that keeps asking to retry.
RUN_STEP_TIMEOUT = 180.0
# How long closing the window waits for a run step to finish before giving up.
# Longer than the camera step, the slowest thing that can be in flight.
CLOSE_WAIT_MS = 15000

# How long to keep re-reading the challenge panel for a *complete* set of three rows.
# The rows fade in one at a time over a couple of seconds, so a read taken the moment the
# first one lands reports the other two as unknown. Not a Settings > Delays value: it costs
# nothing when the panel is ready (the poll returns as soon as all three read) and it is a
# property of the game's animation, not a user preference.
CHALLENGE_PANEL_READ_TIMEOUT = 8.0

# Which screen a run's chain starts on. Each needs different first clicks to reach the
# gamemode cards, and getting that wrong doesn't fail where it happens — it fails one step
# later on a card search, which is how it stayed confusing for several rounds.
#   lobby          -> the Play button is on screen
#   mode panel     -> what a finished match lands on; change gamemode
#   challenge list -> the panel over the gamemode menu; close it
# Auto-calibrating the match tolerance. A template scoring at least the floor is treated
# as a real match on screen; the margin is how much slack the chosen threshold gets under
# the weakest of those. The floor is deliberately well above the engine's 0.50 minimum:
# below it, a "match" is as likely to be noise, and calibrating against noise would set a
# threshold that makes every small text crop a false positive.
# How long to wait for the lobby after re-joining the private server. A cold client launch
# plus a place load is minutes, not seconds, and the alternative to waiting is failing a run
# that was about to work.
LOBBY_REJOIN_TIMEOUT = 150.0
LOBBY_REJOIN_POLL = 2.0



ENTRY_LOBBY = "lobby"
ENTRY_MODE_PANEL = "mode_panel"
ENTRY_CHALLENGE_LIST = "challenge_list"
# Standalone "Wait for win" row: answer quickly instead of idling for the in-run
# budget (UnitPlacer.won_timeout) with the row stuck on "running".
WIN_TEST_TIMEOUT = 20.0
# Full-run dialog: stage entry meaning "let the test pick one".
RANDOM_STAGE_LABEL = "Random"
# Standalone readiness row: you're already in a stage (or you aren't), so fail
# fast instead of polling for the full in-chain budget.
MATCH_READY_TEST_TIMEOUT = 5.0


class OutlineOverlay(QWidget):
    """Mouse-transparent overlay that paints the rounded window outline on top."""

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        pen = QPen(QColor(theme.LINE_BRIGHT))
        pen.setWidth(1)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        painter.drawRoundedRect(rect, WINDOW_RADIUS, WINDOW_RADIUS)
        painter.end()

RAIL_ITEMS = (
    ("run", "run", "RUN"),
    ("units", "units", "UNITS"),
    ("settings", "settings", "SETTINGS"),
)

# Rail item -> index in the right-hand panel stack. Every rail item is a card in
# that stack, so the viewport and run strip stay on screen whichever one is picked.
# Must match the order widgets are added in _build_workspace.
RIGHT_PANELS = {"run": 0, "units": 1, "settings": 2}


class RailIcon(QWidget):
    """Crisp, vector-drawn rail icon (no font dependency)."""

    def __init__(self, kind: str) -> None:
        super().__init__()
        self._kind = kind
        self._color = QColor(theme.TEXT_FAINT)
        self.setFixedSize(26, 26)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

    def set_color(self, color: str) -> None:
        self._color = QColor(color)
        self.update()

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        r = self.rect()
        pen = QPen(self._color)
        pen.setWidth(2)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)

        if self._kind == "run":
            path = QPainterPath()
            path.moveTo(r.left() + 8, r.top() + 5)
            path.lineTo(r.right() - 6, r.center().y() + 1)
            path.lineTo(r.left() + 8, r.bottom() - 4)
            path.closeSubpath()
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawPath(path)
        elif self._kind == "units":
            size, gap = 9, 4
            total = size * 2 + gap
            ox = (r.width() - total) // 2
            oy = (r.height() - total) // 2
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(self._color)
            for dx in (0, size + gap):
                for dy in (0, size + gap):
                    p.drawRoundedRect(ox + dx, oy + dy, size, size, 2, 2)
        else:  # settings: three slider rows with knobs
            ys = (r.top() + 6, r.center().y() + 1, r.bottom() - 5)
            knobs = (r.right() - 8, r.left() + 8, r.right() - 8)
            p.setPen(pen)
            for y in ys:
                p.drawLine(r.left() + 4, y, r.right() - 4, y)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(self._color)
            for y, kx in zip(ys, knobs):
                p.drawEllipse(QPoint(kx, y), 3, 3)
        p.end()


class RailButton(QWidget):
    def __init__(self, kind: str, label: str, on_click) -> None:
        super().__init__()
        self._on_click = on_click
        self._active = False
        self.setFixedHeight(58)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        box = QVBoxLayout(self)
        box.setContentsMargins(0, 8, 0, 8)
        box.setSpacing(3)
        box.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._icon = RailIcon(kind)
        self._text = QLabel(label)
        self._text.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._text.setAlignment(Qt.AlignmentFlag.AlignCenter)

        box.addWidget(self._icon, 0, Qt.AlignmentFlag.AlignHCenter)
        box.addWidget(self._text)

        self._glow = HoverGlow(self, theme.VIOLET, radius=22)
        self.set_active(False)

    def _paint(self, color: str) -> None:
        self._icon.set_color(color)
        self._text.setStyleSheet(f"font-size: 8px; font-weight: 700; color: {color};")

    def set_active(self, active: bool) -> None:
        self._active = active
        self._paint(theme.PURPLE if active else theme.TEXT_FAINT)
        self._glow.set_selected(active)

    def enterEvent(self, _event) -> None:
        if not self._active:
            self._paint(theme.TEXT_DIM)

    def leaveEvent(self, _event) -> None:
        if not self._active:
            self._paint(theme.TEXT_FAINT)

    def mousePressEvent(self, _event) -> None:
        self._on_click()


class TitleBar(QWidget):
    def __init__(self, on_minimize, on_close, on_gamemode) -> None:
        super().__init__()
        self.setObjectName("titlebar")
        self.setFixedHeight(theme.TITLEBAR_HEIGHT)

        # A card inside the drag strip, inset 12px at the sides like the body and 8px from
        # the top so it doesn't sit flush against the window's edge. The outer widget keeps
        # the full TITLEBAR_HEIGHT and stays the drag target — the height budget in
        # `theme.py` depends on it, and the inset margin is still draggable because it
        # belongs to this widget.
        outer = QHBoxLayout(self)
        outer.setContentsMargins(
            12, theme.TITLEBAR_HEIGHT - theme.TITLEBAR_CARD_HEIGHT, 12, 0
        )
        outer.setSpacing(0)
        card = QFrame()
        card.setObjectName("titlebarCard")
        # No `WA_TransparentForMouseEvents`: that attribute also blocks delivery to a
        # widget's children, which would kill the close button. A plain QFrame ignores a
        # press anyway, so it bubbles to this widget's `mousePressEvent` and the drag works
        # over the card as well as the inset margin.
        outer.addWidget(card)

        row = QHBoxLayout(card)
        row.setContentsMargins(14, 0, 6, 0)
        row.setSpacing(8)

        brand = QLabel("SloppyKeys")
        brand.setObjectName("brand")
        version = QLabel(VERSION)
        version.setObjectName("version")
        version.setFixedHeight(24)
        row.addWidget(brand)
        row.addWidget(version, 0, Qt.AlignmentFlag.AlignVCenter)
        row.addSpacing(10)

        self._hint_row = QHBoxLayout()
        self._hint_row.setSpacing(8)
        self._hint_labels: list[QLabel] = []
        # Cursor-to-window offset while dragging; None when not dragging. See
        # mousePressEvent for why the drag is done by hand.
        self._drag_from: QPoint | None = None
        row.addLayout(self._hint_row)

        row.addStretch(1)

        # Selected-gamemode button: hidden until a gamemode is chosen. Click
        # returns to the Selector screen.
        self._gamemode_btn = QPushButton("")
        self._gamemode_btn.setObjectName("gamemodePill")
        self._gamemode_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._gamemode_btn.clicked.connect(on_gamemode)
        self._gamemode_btn.setFixedHeight(30)
        self._gamemode_btn.hide()
        row.addWidget(self._gamemode_btn, 0, Qt.AlignmentFlag.AlignVCenter)
        row.addSpacing(10)

        # The session clock used to sit here; it lives at the foot of the rail now.
        for button in (
            _title_button(icons.MINIMIZE, on_minimize, danger=False),
            _title_button(icons.CLOSE, on_close, danger=True),
        ):
            row.addWidget(button, 0, Qt.AlignmentFlag.AlignVCenter)

    def set_gamemode(self, name: str | None) -> None:
        if not name:
            self._gamemode_btn.hide()
            return
        self._gamemode_btn.setText(f"\u2039  {name}   ·  change")
        self._gamemode_btn.show()

    def set_hints(self, texts: list[str]) -> None:
        while self._hint_labels:
            label = self._hint_labels.pop()
            self._hint_row.removeWidget(label)
            label.deleteLater()
        for text in texts:
            pill = QLabel(text)
            pill.setObjectName("hint")
            pill.setFixedHeight(24)
            self._hint_row.addWidget(pill, 0, Qt.AlignmentFlag.AlignVCenter)
            self._hint_labels.append(pill)

    def mousePressEvent(self, event) -> None:
        """Drag the window by hand — deliberately NOT `startSystemMove()`.

        `startSystemMove()` hands the drag to Windows' own modal move loop, and that loop
        honours the "Show window contents while dragging" preference. It is **off** on the
        user's machine (measured: `SPI_GETDRAGFULLWINDOWS` = 0,
        `HKCU\\Control Panel\\Desktop\\DragFullWindows` = "0"), so instead of moving the
        window Windows drew a white outline rectangle and only moved it on release. That is
        the "ghost outline" — it is Windows' drag rect, not our window, which is why no
        amount of mask rebuilding or size enforcement ever fixed it. It looked *taller*
        than the app because the outline is the full unmasked window rect while what you
        see is the mask (rounded, minus the Roblox hole).

        Moving the window ourselves never enters that loop, so the preference can't apply.
        What this gives up is Aero Snap while dragging, which a fixed-size always-on-top
        window can't use anyway — snapping would try to resize it and `_enforce_window_size`
        would immediately fight it. It also makes Roblox track the drag live, since
        `moveEvent` now fires continuously instead of once on release.
        """
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_from = (
                event.globalPosition().toPoint() - self.window().frameGeometry().topLeft()
            )
            event.accept()

    def mouseMoveEvent(self, event) -> None:
        if self._drag_from is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self.window().move(event.globalPosition().toPoint() - self._drag_from)
            event.accept()

    def mouseReleaseEvent(self, event) -> None:
        self._drag_from = None
        event.accept()


class MainWindow(QWidget):
    # Emitted for every log line so worker threads can append to the log widget
    # safely (queued to the UI thread).
    logLine = Signal(str)

    # Emitted with the three ChallengeReads after a scan, for the same reason: the
    # mid-run re-read happens on the macro worker, and StatsPage is a widget.
    challengesRead = Signal(list)

    # Emitted by the macro worker when it needs the client re-joined into the private
    # server — the Events chain's way back to the lobby. Queued, because the deep link
    # goes out through QDesktopServices and Qt belongs to the UI thread.
    joinServerRequested = Signal()
    # Emitted by a worker that needs a modal dialog built on the UI thread.
    # Payload: {"box": dict, "done": threading.Event}. A queued signal is the
    # only reliable marshal here — QTimer.singleShot from a QThreadPool worker
    # never fires, because that thread has no event loop.
    askFullTargetRequested = Signal(object)

    # Emitted from the macro worker when a counter changed, so the Run panel can
    # redraw on the UI thread. Same reason as logLine: workers must not touch
    # widgets.
    statsChanged = Signal()
    # Worker -> UI: which step is running, for the panel's Action card.
    actionChanged = Signal(str)

    def __init__(self, app_root: str) -> None:
        super().__init__()
        self._app_root = app_root
        self._log_path = os.path.join(app_root, LOG_FILE)
        self._rotate_log_file()

        # # Services
        self._settings = AppSettings(app_root)
        # `log=` so a failed screen capture says so instead of surfacing as a missing
        # template. Safe this early: `_log` only needs `_log_path` (set above) and the
        # queued `logLine` signal.
        self._search_engine = ImageSearchEngine(app_root, log=self._log)
        self._profile_store = ImageProfileStore(app_root, self._search_engine)
        self._config_store = UnitConfigStore(app_root)
        self._runner = MacroRunner(log=self._log)
        # The run loop drives blocking AHK steps, so it never runs on the UI
        # thread. One task at a time; _run_task doubles as the busy flag and as
        # the reference that keeps the task (and its signals) alive.
        self._pool = QThreadPool(self)
        self._run_task: Task | None = None
        # The Route tab's Test button, same lifetime rule as _run_task.
        self._route_task: Task | None = None
        # Task queue state for the run in flight. `_run_plan` is the plan the *macro*
        # is placing, kept separate from `self._plan` (what the Units page edits) so a
        # task switch never repoints the editor under the user.
        self._director = TaskDirector()
        self._run_plan: UnitPlan | None = None
        self._pending_target: MacroTarget | None = None
        self._pending_plan: UnitPlan | None = None
        self._last_decision = TaskDecision()
        self._last_won = True
        # Which challenge row the run in flight is playing, so `_build_run_steps` knows
        # which one to click. None for every other kind of run.
        self._challenge_slot: int | None = None
        # Where the next chain has to start from. A boolean here ("from the gamemode
        # panel") could not express the third case, and that cost two runs: the challenge
        # list is its own screen with its own close button, not the panel a finished match
        # lands on.
        self._entry_screen = ENTRY_LOBBY
        self._challenges = ChallengeTracker()
        # Lazy inside: building the OCR engine costs ~1s and three ONNX models, so a
        # launch that never reads the challenge panel never pays for it.
        self._ocr = OcrReader()
        self._challenge_scanner = ChallengeScanner(
            self._search_engine, self._roblox_rect, log=self._log, ocr=self._ocr
        )
        self._ahk = AhkBridge()
        self._nav = LobbyNavigator(
            self._search_engine,
            self._ahk,
            self._roblox_rect,
            log=self._log,
            # Makes F1 stop a run mid-step: every poll loop abandons its wait as soon as
            # this is true. A lambda, not the bool, so it is read live.
            should_stop=lambda: self._runner.stop_requested,
        )
        # game_keys is read through a lambda because Settings can rebind a key
        # mid-session; the placer must not capture the dict from startup.
        self._placer = UnitPlacer(
            self._search_engine,
            self._ahk,
            self._roblox_rect,
            game_keys=lambda: self._game_keys,
            log=self._log,
            should_stop=lambda: self._runner.stop_requested,
        )
        # Events navigation is data the user authors (routes.json), not a table.
        self._routes = RouteStore(app_root)
        self._delays_store = DelaysStore(app_root)
        self._delays = self._delays_store.all()
        self._position_store = StartPositionStore(app_root)
        self._task_store = TaskStore(app_root)
        self._nav.apply_delays(self._delays)
        self._placer.apply_delays(self._delays)

        self._stats = StatsTracker(app_root)
        # Read the URL through a callable so editing it in Settings takes effect
        # without rebuilding anything.
        self._webhook = DiscordWebhook(self._settings.get_discord_webhook, log=self._log)

        # # State
        self._plan = UnitPlan.empty()
        # Set when the Tasks tab points the Units page at a config the Run strip can't
        # select — Challenge, which is never an F1 target. Cleared by touching the Run
        # strip, so there is always one obvious way back.
        self._edit_target: MacroTarget | None = None
        self._active_config_path: str | None = None
        self._profiles: dict[str, ImageProfile] = {}
        self._active_profile_key: str | None = None
        self._roblox_hwnd: int | None = None
        # Has the ~8s camera sequence completed since this Roblox client was attached?
        # Only consulted when `camera_once_per_session` is on. Reset on attach and on a
        # private-server re-join, both of which give you a fresh camera.
        self._camera_is_set = False
        self._keybind_store = KeybindStore(app_root)
        self._keybinds = self._keybind_store.all()
        # Keys the macro sends into the game (not polled — see keybinds.py).
        self._game_key_store = GameKeyStore(app_root)
        self._game_keys = self._game_key_store.all()
        self._kb_down: dict[str, bool] = {action: False for action in ACTIONS}
        self._hole: object = None
        self._gamemode: str | None = None
        self._tester: MacroTesterWindow | None = None
        self._ws_rail = "run"
        self._session_start = time.monotonic()

        self._build_ui()
        self._connect()
        self._restore()

        # Launch on the gamemode selector.
        self._show_page("selector")
        self._log("Macro ready. F1 toggles start/stop, F3 reloads.")
        # Said at launch, not at the first click. AHK is a separate install the packaged
        # build cannot provide, so without this a new user's first run just fails on its
        # first click with a line buried in the log.
        if self._ahk.available():
            self._log(f"AutoHotkey v2: {self._ahk.exe_path}")
        else:
            self._log(
                "AutoHotkey v2 NOT FOUND — every click will fail. Install it from "
                "autohotkey.com (v2, not v1); the macro sends all input through it."
            )

        self._hotkeys = QTimer(self)
        self._hotkeys.timeout.connect(self._poll_hotkeys)
        self._hotkeys.start(HOTKEY_MS)

        self._session_timer = QTimer(self)
        self._session_timer.timeout.connect(self._tick_session)
        self._session_timer.start(1000)
        self._tick_session()

    # # Build
    def _build_ui(self) -> None:
        self.setObjectName("root")
        self.setWindowTitle("SloppyKeys")
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setFixedSize(theme.WINDOW_WIDTH, theme.WINDOW_HEIGHT)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self._titlebar = TitleBar(self.showMinimized, self.close, self._show_selector)
        root.addWidget(self._titlebar)

        # Body: rail is its own padded card on the left, page stack on the right.
        body = QHBoxLayout()
        body.setContentsMargins(12, 6, 12, 12)
        body.setSpacing(12)
        root.addLayout(body, 1)

        # Rail card — only as tall as the viewport row, like the reference.
        rail = QWidget()
        rail.setObjectName("rail")
        rail.setFixedWidth(theme.RAIL_WIDTH)
        rail_box = QVBoxLayout(rail)
        rail_box.setContentsMargins(6, 10, 6, 10)
        rail_box.setSpacing(6)
        self._rail_buttons: dict[str, RailButton] = {}
        for page, kind, label in RAIL_ITEMS:
            button = RailButton(kind, label, lambda p=page: self._rail_clicked(p))
            self._rail_buttons[page] = button
            rail_box.addWidget(button)
        rail_box.addStretch(1)
        # After the stretch, so it pins to the foot of the rail. Moved out of the titlebar:
        # it is ambient information, and the titlebar is for identity and window controls.
        rail_box.addWidget(self._build_session_tile())
        body.addWidget(rail, 0)

        self._viewport = RobloxViewport(on_attach=self._on_attach)
        self._selector_page = SelectorPage()
        # Events gets its maps and acts from routes.json, not from the gamemode
        # table, so the strip reads both through these instead of importing them.
        self._run_page = RunPage(
            maps_provider=self._maps_for_gamemode,
            targets_provider=self._targets_for_map,
        )
        self._units_page = UnitsPage(
            plan_provider=lambda: self._plan,
            get_rect=self._roblox_rect,
            get_target=self._placement_target,
            images_dir=self._profile_store.images_dir,
        )
        self._route_editor = RouteEditor(
            self._routes,
            self._app_root,
            get_rect=self._roblox_rect,
            engine=self._search_engine,
            log=self._log,
        )
        self._task_editor = TaskEditor(
            maps_provider=self._maps_for_gamemode,
            targets_provider=self._targets_for_map,
        )
        self._region_store = RegionStore(self._app_root)
        self._point_store = PointStore(self._app_root)
        self._confidence_store = ConfidenceStore(self._app_root)
        # Apply the user's challenge-box, click-point and match-threshold overrides before
        # anything reads them. The Vision tab re-applies on every edit; this covers a run
        # started without ever opening it.
        apply_region_overrides(self._region_store.all())
        stored_points = self._point_store.all()
        apply_act_overrides(stored_points)
        apply_start_overrides(stored_points)
        apply_confidence_overrides(self._confidence_store.all())
        self._image_manager = ImageManager(
            self._app_root,
            get_rect=self._roblox_rect,
            engine=self._search_engine,
            log=self._log,
            regions=self._region_store,
            # For the Events map-image rows: its events and acts are user-authored, so
            # `GAMEMODES` can't list them.
            routes=self._routes,
            points=self._point_store,
            confidence=self._confidence_store,
        )
        self._stats_page = StatsPage()
        self._settings_page = SettingsPage(
            maps_provider=self._maps_for_gamemode,
            targets_provider=self._targets_for_map,
            tasks_tab=self._task_editor,
            route_tab=self._route_editor,
            images_tab=self._image_manager,
        )

        # Settings is not a page of its own: it's the third card in the right
        # panel (see _build_workspace), so choosing it keeps the Roblox viewport
        # and the run strip on screen. Only the gamemode selector takes the
        # whole body, because picking a mode is a one-off.
        self._stack = QStackedWidget()
        self._pages: dict[str, QWidget] = {}
        self._pages["selector"] = _panel(self._selector_page)
        self._pages["workspace"] = self._build_workspace()
        for name in ("selector", "workspace"):
            self._stack.addWidget(self._pages[name])
        body.addWidget(self._stack, 1)

        # Last reported display scaling of Roblox's monitor. None so the first check always
        # logs, whichever way it comes out.
        self._monitor_scale_percent: int | None = None

        # Rounded corners + outline on top of everything.
        self._outline = OutlineOverlay(self)
        self._outline.setGeometry(self.rect())
        self._outline.raise_()
        self._apply_window_mask()
        self._center_on_primary()

    def _center_on_primary(self) -> None:
        """Open centred on the primary screen. Without this Qt can place the
        window on a secondary monitor that may be shorter than our fixed height,
        clipping the UI."""
        screen = QApplication.primaryScreen()
        if screen is None:
            return
        area = screen.availableGeometry()
        self.move(
            area.center().x() - self.width() // 2,
            max(area.top(), area.center().y() - self.height() // 2),
        )

    def _build_workspace(self) -> QWidget:
        """Viewport (top-left) + run strip (below it) + units panel (right).

        The panel spans both rows, so its *vertical* size policy is Ignored: the
        viewport and strip rows are fixed by design, and without this Qt tries to
        satisfy the panel's preferred height by resizing the rows it spans. That
        shrank the viewport row from 650 to 578 and inflated the strip row from
        166 to 238, sliding the run strip up over the viewport whenever the panel
        got taller (Sequence mode). Ignored means the panel takes whatever the
        rows give it and its content never drives the layout, so anything added
        to the Units page is contained by the fixed window instead of growing it.
        """
        page = QWidget()
        row = QHBoxLayout(page)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(12)

        strip = _panel(self._run_page)
        strip.setFixedHeight(theme.STRIP_HEIGHT)

        left = QWidget()
        column = QVBoxLayout(left)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(12)
        column.addWidget(self._viewport)
        column.addWidget(strip)
        # Exactly as tall as its two fixed children; nothing can squeeze it.
        left.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        # The column's width is its sizeHint, i.e. the *wider* of the viewport and the
        # run strip. Nothing pins it to a number here on purpose: the viewport widget is
        # 812 (VIEWPORT_WIDTH + border), and a hardcoded 800 would clip it. The strip is kept from
        # winning that comparison at its source instead — `RunPage`'s status label wraps
        # and has no minimum width, because an unwrapped status line grew the strip's
        # hint to 848 and squeezed the right panel to its 400px floor (measured).
        # (An attempt to cap the strip at `self._viewport.sizeHint().width()` here is a
        # trap: the viewport reports -1 during construction, and setMaximumWidth(-1)
        # collapses the strip to zero. Measured.)

        # The right panel follows the rail: Run shows live stats, Units shows the
        # chips + detail editor, Settings shows the settings tabs. One stack so the
        # left column never re-lays out. Order must match RIGHT_PANELS.
        self._right_stack = QStackedWidget()
        self._right_stack.addWidget(_panel(self._stats_page))
        self._right_stack.addWidget(_panel(self._units_page))
        self._right_stack.addWidget(_panel(self._settings_page))
        units = self._right_stack
        units.setMinimumWidth(theme.PANEL_MIN_WIDTH)
        # Default (Preferred) vertical policy on purpose. An Ignored policy lets
        # Qt hand the panel less height than its children need, and the children
        # then paint outside it — past the window edge. The Units page's minimum
        # (611) fits the available height (828), so honest sizing is correct here;
        # the row-span that used to make this necessary is gone.

        # AlignTop so the column can never end up vertically centred if the page
        # is ever taller than expected — that is what dropped the viewport 99px
        # down during the bad restore.
        row.addWidget(left, 0, Qt.AlignmentFlag.AlignTop)
        row.addWidget(units, 1)
        return page

    # # Window shape
    def set_roblox_hole(self, hole) -> None:
        """Called by the viewport: punch (or clear) the Roblox hole in our mask."""
        self._hole = hole
        self._apply_window_mask()

    def _apply_window_mask(self) -> None:
        path = QPainterPath()
        path.addRoundedRect(QRectF(self.rect()), WINDOW_RADIUS, WINDOW_RADIUS)
        region = QRegion(path.toFillPolygon().toPolygon())
        if self._hole is not None:
            region = region.subtracted(QRegion(self._hole))
        self.setMask(region)

    def _connect(self) -> None:
        self.logLine.connect(self._run_page.append_log)
        self.challengesRead.connect(self._stats_page.set_challenges)
        self.joinServerRequested.connect(self._on_join_server)
        self.statsChanged.connect(self._refresh_stats)
        self.actionChanged.connect(self._stats_page.set_action)
        self.askFullTargetRequested.connect(self._on_ask_full_target_requested)
        self._selector_page.gamemodeChosen.connect(self._on_gamemode_chosen)

        self._run_page.targetChanged.connect(self._on_target_changed)
        self._run_page.saveRequested.connect(self._on_save_config)
        self._run_page.importRequested.connect(self._on_import_config)
        self._run_page.resetRequested.connect(self._on_reset_config)
        # Adding or deleting an event/act changes what the Map and Act dropdowns
        # can offer, and they are the only place those names appear.
        self._route_editor.changed.connect(self._run_page.refresh_options)
        # Settings > Position has its own Map/Act selectors over the same names.
        self._route_editor.changed.connect(self._settings_page.position_editor.refresh_options)
        # The Tasks tab can queue an Events target, so its Map/Act lists go stale
        # for the same reason the Run strip's do.
        self._route_editor.changed.connect(self._task_editor.refresh_options)
        self._route_editor.testRequested.connect(self._on_route_test)
        self._task_editor.slotsChanged.connect(self._on_tasks_changed)
        self._task_editor.challengesToggled.connect(self._on_challenges_toggled)
        self._run_page.queueLimitChanged.connect(self._on_queue_limit_changed)
        self._task_editor.editRequested.connect(self._on_edit_config_requested)
        self._units_page.editing_finished.connect(self._on_editing_finished)

        self._settings_page.linkCommitted.connect(self._on_link_committed)
        self._settings_page.joinRequested.connect(self._on_join_server)
        self._settings_page.webhookCommitted.connect(self._on_webhook_committed)
        self._settings_page.webhookTestRequested.connect(self._on_webhook_test)
        self._settings_page.hardModeToggled.connect(self._on_hard_mode_toggled)
        self._settings_page.cameraOnceToggled.connect(self._on_camera_once_toggled)
        position = self._settings_page.position_editor
        position.targetChanged.connect(self._on_position_target)
        position.movesChanged.connect(self._on_position_moves)
        position.resetRequested.connect(self._on_position_reset)
        self._settings_page.delayChanged.connect(self._on_delay_changed)
        self._settings_page.openTesterRequested.connect(self._open_macro_tester)
        self._settings_page.keybindChanged.connect(self._on_keybind_changed)
        self._settings_page.gameKeyChanged.connect(self._on_game_key_changed)
        self._settings_page.expeditionDifficultyChanged.connect(
            self._on_expedition_difficulty_changed
        )



    def _restore(self) -> None:
        # One-time migration: challenges used to be one of the three task slots. A queue
        # saved under that shape switches the toggle on instead of silently losing them.
        if self._task_store.take_legacy_challenge_slot():
            self._settings.set_run_challenges(True)
            self._log("Challenges moved out of the task queue and onto their own toggle.")
        self._task_editor.set_challenges(self._settings.get_run_challenges())
        self._task_editor.load(self._task_store.slots())
        self._settings_page.set_hard_mode(self._settings.get_hard_mode())
        self._settings_page.set_camera_once(self._settings.get_camera_once())
        self._settings_page.set_link(self._settings.get_private_server_link())
        self._settings_page.set_webhook(self._settings.get_discord_webhook())
        self._refresh_stats()
        for action, keybind in self._keybinds.items():
            self._settings_page.set_keybind(action, keybind)
        for action, key in self._game_keys.items():
            self._settings_page.set_game_key(action, key)
        self._settings_page.set_expedition_difficulty(
            self._settings.get_expedition_difficulty()
        )

        for key, value in self._delays.items():
            self._settings_page.set_delay(key, value)
        # The editor emits targetChanged while it builds its combos, before the
        # signals are connected, so fill it once here for whatever it landed on.
        self._on_position_target(*self._settings_page.position_editor.target())
        self._titlebar.set_hints(self._hint_texts())
        self._load_profiles()

    def _build_session_tile(self) -> QFrame:
        """The session clock at the foot of the rail: caption over value, centred.

        Its own tile (`#railSession`) rather than bare labels, so the rail ends on the same
        card treatment the stat panel uses. Width is whatever `RAIL_WIDTH` leaves after the
        rail's 6px margins; the value is at 12px so `0:00:00` fits without eliding.
        """
        tile = QFrame()
        tile.setObjectName("railSession")
        box = QVBoxLayout(tile)
        box.setContentsMargins(4, 4, 4, 5)
        box.setSpacing(0)
        caption = QLabel("SESSION")
        caption.setObjectName("sessionCap")
        caption.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._session_label = QLabel("00:00")
        self._session_label.setObjectName("session")
        self._session_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        box.addWidget(caption)
        box.addWidget(self._session_label)
        return tile

    # # Pages / navigation
    def _rail_clicked(self, page: str) -> None:
        # Run needs a gamemode; without one, send the user to the selector. Units
        # and Settings are both right-panel cards on the workspace page.
        if page == "run" and self._gamemode is None:
            self._show_page("selector")
            return
        self._ws_rail = page if page in RIGHT_PANELS else "run"
        self._show_page("workspace")

    def _show_selector(self) -> None:
        """From the titlebar 'change' button: drop the current mode and reselect."""
        self._gamemode = None
        self._plan = UnitPlan.empty()
        self._active_config_path = None
        self._run_page.clear_gamemode()
        self._units_page.reload()
        self._show_page("selector")

    def _on_gamemode_chosen(self, name: str) -> None:
        self._gamemode = name
        self._run_page.set_gamemode(name)
        # Task is a card on the Selector but not a gamemode: there is no map or act to
        # cascade, so the middle column shows the queue instead of the selectors.
        self._refresh_queue_view()
        if self._in_task_mode():
            slots = self._task_store.slots()
            queued = [slot for slot in slots if slot.is_runnable()]
            self._run_page.set_status(
                f"{len(queued)} task(s) queued. F1 runs them in order."
                if queued
                else "No tasks queued yet — add them in Settings > Tasks."
            )
        # Land on Run and stay there: picking a target is done on this screen, and
        # its panel is what you watch while the macro works. Units is a click away.
        self._ws_rail = "run"
        self._show_page("workspace")
        self._log(f"Gamemode selected: {name}.")

    def _show_page(self, name: str) -> None:
        if name not in self._pages:
            return
        # Leaving the Units card flushes the step being edited into the plan. Keyed
        # on the card, not the page: Settings is a sibling card now, so "left the
        # workspace" would miss Units -> Settings and drop that edit.
        next_panel = RIGHT_PANELS.get(self._ws_rail, 0) if name == "workspace" else None
        if (
            self._right_stack.currentIndex() == RIGHT_PANELS["units"]
            and next_panel != RIGHT_PANELS["units"]
        ):
            self._units_page.commit()
        self._stack.setCurrentWidget(self._pages[name])
        if name == "selector":
            active = "run"
        else:  # workspace
            active = self._ws_rail
            # Right panel follows the rail: stats on Run, chips + editor on Units,
            # the settings tabs on Settings.
            self._right_stack.setCurrentIndex(RIGHT_PANELS.get(active, 0))
            if active == "run":
                self._refresh_stats()
        for page, button in self._rail_buttons.items():
            button.set_active(page == active)
        self._titlebar.set_gamemode(None if name == "selector" else self._gamemode)

    def _refresh_challenge_reset(self) -> None:
        """Countdown to the next challenge re-roll, for the stats panel.

        From the clock (`next_interval_at`), so it is right whether or not the panel has
        ever been on screen — the panel's own "Resets in" text is OCR-readable but would
        only be current while you happen to be looking at it.
        """
        if not self._in_task_mode():
            return
        when = next_interval_at()
        left = max(0, int((when - datetime.now()).total_seconds()))
        # 12-hour with AM/PM, and no leading zero — `%I` pads to two digits and there is
        # no portable strftime flag to stop it, so it is stripped by hand.
        clock = when.strftime("%I:%M %p").lstrip("0")
        # "next re-roll" was the game's mechanic named in the developer's words. What the
        # user wants to know is when three different maps show up, and the clock time is
        # the useful half — the countdown is the reassurance that it's ticking.
        self._stats_page.set_challenge_reset(
            f"new maps {clock} · {left // 60}m {left % 60:02d}s"
        )

    def _tick_session(self) -> None:
        # Piggyback on the existing 1s timer for the panel's two clocks, and only
        # while a run is up — no point redrawing labels nobody is watching change.
        if self._runner.is_running and self._right_stack.currentIndex() == 0:
            self._refresh_stats()
        if self._right_stack.currentIndex() == 0:
            # Counts down whether or not a run is up: it is a reason to *start* one.
            self._refresh_challenge_reset()
        elapsed = int(time.monotonic() - self._session_start)
        hours, rem = divmod(elapsed, 3600)
        minutes, seconds = divmod(rem, 60)
        text = f"{hours}:{minutes:02d}:{seconds:02d}" if hours else f"{minutes:02d}:{seconds:02d}"
        self._session_label.setText(text)

    # # Logging
    def _rotate_log_file(self) -> None:
        """Roll log.txt over once it passes LOG_FILE_MAX_BYTES.

        ponytail: checked at startup only, so a single session that writes past the
        cap keeps growing until the next launch. Upgrade path is a size check inside
        `_log`, which costs a stat per line — not worth it for a file that took
        weeks to reach 25 KB.
        """
        try:
            if os.path.getsize(self._log_path) < LOG_FILE_MAX_BYTES:
                return
            os.replace(self._log_path, os.path.join(self._app_root, LOG_PREV_FILE))
        except OSError:
            pass

    def _log(self, message: str) -> None:
        text = message.strip()
        if not text:
            return
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        try:
            with open(self._log_path, "a", encoding="utf-8") as handle:
                handle.write(f"[{stamp}] {text}\n")
        except OSError:
            pass
        # Safe from any thread: the signal is queued to the UI thread.
        self.logLine.emit(text)

    # # Viewport attach
    def _on_attach(self, attached: bool) -> None:
        if attached and self._roblox_hwnd is None:
            # A newly attached client is a new camera: whatever this session had set is
            # gone, so the once-per-session skip must not carry over from the last one.
            self._camera_is_set = False
            self._roblox_hwnd = rbx.find_roblox_window()
            self._sync_refresh_rate()
        elif not attached:
            self._roblox_hwnd = None

    def _sync_refresh_rate(self) -> None:
        """Tell the AHK script builders how fast the game's monitor refreshes.

        Every input timing in `input_scripts` is really a frame count: Roblox acts on the
        last mouse-move it has *processed*, and it processes them per rendered frame. The
        nudge settle was tuned at 165Hz, so on a 60Hz monitor the same milliseconds covered
        under half the frames and clicks landed on a stale cursor position — the macro
        misplacing clicks on one monitor and not another at identical resolution and
        scaling.
        """
        self._warn_if_monitor_scaled()
        hz = refresh_hz_for_window(self._roblox_hwnd)
        if hz == input_scripts.refresh_hz():
            return
        input_scripts.set_refresh_hz(hz)
        self._log(
            f"Game monitor refresh {hz}Hz — click settle {input_scripts.nudge_settle_ms()}ms "
            f"({input_scripts.NUDGE_SETTLE_FRAMES} frames)."
        )

    def _warn_if_monitor_scaled(self) -> None:
        """Say so, loudly, when Roblox is on a monitor that isn't at 100% display scaling.

        This is the one environment difference that breaks everything at once and explains
        itself as nothing: Roblox is per-monitor DPI aware, so on a scaled monitor it draws
        its UI larger in physical pixels (and blurry — a known Roblox regression above 100%).
        Every template's pixel size and every stored coordinate here is calibrated at 100%,
        so at 125% templates score as the wrong image (measured best match at 0.80x = 1/1.25)
        and coordinates land on the wrong element. Warned once per change rather than per
        search, because it is a setup problem, not a step failure.
        """
        percent = scale_percent_for_window(self._roblox_hwnd)
        if percent == self._monitor_scale_percent:
            return
        self._monitor_scale_percent = percent
        if percent == 100:
            self._log("Game monitor scaling 100% — templates and coordinates are valid here.")
            return
        self._log(
            f"WARNING: game monitor display scaling is {percent}%, not 100%. Roblox draws its "
            f"UI {percent / 100:.2f}x larger in pixels there, so templates score as the wrong "
            f"image and stored coordinates miss. Set that display to 100% in Windows "
            f"Settings > System > Display > Scale, or keep Roblox on a 100% monitor."
        )

    # # Task mode
    def _in_task_mode(self) -> bool:
        return self._gamemode == TASK_SELECTION

    def _scan_challenges_if_open(
        self, navigate: bool = False, from_gamemode_panel: bool = False
    ) -> tuple[bool, bool]:
        """Read the challenge panel and tell the tracker.

        Returns (panel_was_read, moved_off_the_starting_screen). The second flag matters
        even when the read failed: navigating clicks its way off whatever screen the macro
        was on, so any chain built afterwards must not start from there.

        Two routes, because the panel sits behind different buttons depending on where the
        macro is standing:
        - from the **lobby** (an F1 start): Play, then the Challenges card.
        - from the **gamemode panel** a finished match leaves you on (`from_gamemode_panel`,
          the mid-run re-read after a rotation rolls): change gamemode, then the card.

        Navigating fires input, so `navigate` is only passed from a run the user started.
        Safe on a worker thread: the stats panel is updated through a signal.
        """
        if not self._director.wants_challenges:
            return (False, False)
        if self._roblox_rect() is None:
            return (False, False)
        moved = False
        reads, was_open = self._challenge_scanner.scan_if_open()
        if not was_open and navigate:
            if from_gamemode_panel:
                ok, message = self._nav.change_gamemode()
                self._log(f"  Change gamemode: {message}")
                if ok:
                    moved = True
                    ok, message = self._nav.open_gamemode(CHALLENGE)
                    self._log(f"  Challenge card: {message}")
            else:
                # In a match the lobby's Play button doesn't exist and `match_play` is a
                # different, smaller one, so this route can't work from there.
                if self._nav.in_match():
                    self._log("  In a match — can't open the challenge panel from here.")
                    return (False, False)
                ok, message = self._nav.open_challenges()
                self._log(f"  Open challenges: {message}")
                moved = ok
            if not ok:
                return (False, moved)
            reads, was_open = self._wait_for_challenge_panel()
        self._challenges.note_scan_attempt()
        if not was_open:
            self._log("  Challenge panel not on screen — challenges skipped this round.")
            self._dump_panel_miss(reads)
            return (False, moved)
        self._challenges.note_time()
        self._challenges.note_reads(reads)
        # Same reads on the stats panel, so what the macro believes is visible without
        # reading the log. Through a signal because this method also runs on the macro
        # worker (the mid-run re-read), and a widget touched off the UI thread is the
        # crash this project has paid for before.
        self.challengesRead.emit(list(reads))
        # One line, not four: the per-row detail (raw OCR text, scores) now lives in the
        # stats panel's CHALLENGES group, and repeating it here every scan was noise. The
        # tester's "Scan challenges" row still prints everything.
        # The star readings ride along, because they are what decides "already completed"
        # and the F1 path is where that decision goes wrong. They were added to
        # `ChallengeRead.summary()`, which only the tester row prints — so the number was
        # missing from every log that mattered.
        stars = " ".join(
            f"{read.slot}:"
            + ("?" if read.star_saturation is None else f"{read.star_saturation:.0f}")
            for read in reads
        )
        self._log(f"  Challenges: {self._challenges.summary()} — star sat {stars}")
        return (True, moved)

    def _wait_for_challenge_panel(
        self, timeout: float | None = None
    ) -> tuple[list[ChallengeRead], bool]:
        """Poll until **all three rows** read, not just until the panel is up.

        The rows don't appear together — the panel fades in over a couple of seconds and
        each row's text lands when it lands. Waiting only for `scan_if_open` (which is
        satisfied by *one* row parsing an `n/10`) returned the instant the fastest row
        rendered and reported the other two as `unknown ?`, so the queue skipped two
        perfectly good challenges for having no identifiable map.

        A complete read is every row with a parsed limit **and** a matched map, since a row
        without a map has no `configs/Challenge/<Map>.json` to load and is unusable anyway.
        At the deadline it returns whatever it has — a row that is genuinely unreadable
        must not stall the run, and `scan_if_open`'s flag still says whether to trust any
        of it.

        The budget is deliberately not `search_timeout`: that knob is how long an *image
        search* waits, the user has it at 1.5s, and it has nothing to do with how long this
        game takes to draw a panel.
        """
        budget = CHALLENGE_PANEL_READ_TIMEOUT if timeout is None else float(timeout)
        deadline = time.monotonic() + max(0.0, budget)
        started = time.monotonic()
        while True:
            reads, was_open = self._challenge_scanner.scan_if_open()
            complete = [
                read for read in reads if read.runs_total is not None and read.map_name
            ]
            if was_open and len(complete) == len(reads):
                self._log(
                    f"  Challenge panel fully read after {time.monotonic() - started:.1f}s."
                )
                return (reads, True)
            if time.monotonic() >= deadline:
                if was_open:
                    self._log(
                        f"  Challenge panel: only {len(complete)} of {len(reads)} rows read "
                        f"in {budget:.1f}s — carrying on with what it has."
                    )
                return (reads, was_open)
            time.sleep(self._nav.search_poll)

    def _dump_panel_miss(self, reads: list[ChallengeRead]) -> None:
        """Record what a failed panel read actually saw: raw OCR per row, plus the client.

        Unreadable rows say the panel isn't there; they don't say which screen *is*, and
        that is the missing fact — two runs have now died downstream because the macro
        carried on without knowing where the game was. The PNG lands beside the
        measured-box dumps, so it can be OCR'd offline instead of guessed at.
        """
        for read in reads:
            self._log(
                f"    slot {read.slot} raw limit={read.raw_limit!r} map={read.raw_map!r}"
            )
        rect = self._roblox_rect()
        if rect is None:
            return
        data = self._search_engine.capture_png(rect)
        if data is None:
            self._log("    could not capture the client for the debug dump")
            return
        path = challenge_debug_path("panel_miss")
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "wb") as handle:
                handle.write(data)
        except OSError as exc:
            self._log(f"    could not write the debug dump: {exc}")
            return
        self._log(f"    what it saw: {os.path.relpath(path, self._app_root)}")

    def _refresh_queue_view(self) -> None:
        """Keep the run strip's queue column and the stats panel in step."""
        task_mode = self._in_task_mode()
        self._stats_page.set_task_mode(task_mode)
        if not task_mode:
            self._run_page.show_selectors()
            return
        # The re-roll clock lives in the stats card's CHALLENGES group only — showing it
        # in the run strip as well was the same fact twice.
        self._run_page.show_queue(self._task_store.slots())
        self._refresh_challenge_reset()

    def _on_queue_limit_changed(self, index: int, limit: int) -> None:
        """A limit nudged on the run strip. Same store the Tasks tab writes, so the two
        views can't drift apart."""
        slots = self._task_store.slots()
        if not 0 <= index < len(slots):
            return
        slots[index].limit = int(limit)
        if not self._task_store.save(slots):
            self._log("Could not save the task limit.")
            return
        self._task_editor.load(self._task_store.slots())
        self._log(f"Task {index + 1} run limit set to {limit}.")

    # # Which config the Units page is editing
    def _edit_selection(self) -> tuple[str, str, str]:
        """(gamemode, map, act) of the plan currently open in the Units page.

        The Run strip's selection, unless the Tasks tab pointed the editor at a side
        task — `configs/Challenge/<Map>.json` has no Run strip selection to be reached
        by, because Challenge is never an F1 target.
        """
        override = self._edit_target
        if override is not None:
            return (override.gamemode, override.map_name, override.target)
        return self._run_page.selection()

    def _on_edit_config_requested(self, gamemode: str, map_name: str, act: str) -> None:
        """Tasks tab asked to edit a specific config, side task or not."""
        if not selection_complete(gamemode, map_name, act):
            self._run_page.set_status("Pick a map for that task first.", is_error=True)
            return
        # Switching straight from one side task to another saves the first.
        self._clear_edit_override()
        self._units_page.commit()  # don't lose edits to the plan being replaced
        self._edit_target = MacroTarget(gamemode=gamemode, map_name=map_name, target=act)
        self._plan = self._config_store.load(gamemode, map_name, act)
        self._active_config_path = self._config_store.path_for(gamemode, map_name, act)
        self._units_page.reload()
        self._units_page.set_editing_note(self._edit_target.label())
        # The rail decides the right-hand panel; the page is always "workspace".
        self._ws_rail = "units"
        self._show_page("workspace")
        where = self._edit_target.label()
        self._log(f"Units page now editing {where}.")
        self._run_page.set_status(f"Editing {where}. Pick on the Run strip to go back.")

    def _clear_edit_override(self) -> None:
        """Leave side-task editing, saving it on the way out.

        Every exit runs through here — the banner's Done button and touching the Run
        strip — and both used to discard the edits, because leaving reloads the run
        target's plan over `self._plan`. For the run's own config that is fine, since
        Save is explicit and the plan stays loaded; for a side task the plan is gone the
        moment you leave, so an unsaved edit is unrecoverable. You opened this config on
        purpose from the Tasks tab, so leaving writes it.
        """
        if self._edit_target is None:
            return
        target = self._edit_target
        self._units_page.commit()
        saved = self._config_store.save(
            target.gamemode, target.map_name, target.target, self._plan
        )
        if saved is None:
            self._log(f"Could not save {target.label()} — edits kept in memory only.")
        else:
            self._log(f"Saved {os.path.relpath(saved, self._app_root)}.")
        self._edit_target = None
        self._units_page.set_editing_note("")

    def _on_editing_finished(self) -> None:
        """The Done button on the editing banner: back to the run's own config.

        Reloads the run target's plan rather than only dropping the flag, or the page
        would keep showing the side task's steps while Save wrote them somewhere else.
        """
        if self._edit_target is None:
            return
        # `_clear_edit_override` is what saves it; `_on_target_changed` then reloads the
        # run target's plan over the top.
        self._clear_edit_override()
        self._on_target_changed()
        self._units_page.reload()
        # Back where the trip started: Edit units only exists in Settings > Tasks, so
        # landing on the Units page with the run's config open would leave the user to
        # navigate back themselves.
        self._ws_rail = "settings"
        self._show_page("workspace")
        self._settings_page.show_tab("Tasks")
        self._log("Back to the run's config.")

    # # Target selection
    def _on_target_changed(self) -> None:
        # A Run strip change is the natural "back to normal" from editing a side task.
        self._clear_edit_override()
        gamemode, map_name, target = self._run_page.selection()
        self._stats_page.set_target(gamemode, map_name, target)
        if not selection_complete(gamemode, map_name, target):
            self._active_config_path = None
            self._run_page.set_status("")
            return

        self._plan = self._config_store.load(gamemode, map_name, target)
        self._active_config_path = self._config_store.path_for(gamemode, map_name, target)
        self._units_page.reload()

        if self._config_store.exists(gamemode, map_name, target):
            self._run_page.set_status(f"Loaded: {len(self._plan.enabled_steps())} active steps.")
        else:
            self._run_page.set_status("New config. Press Save to create it.")

    def _on_save_config(self) -> None:
        # Saves what the Units page is showing, which may be a side task's plan.
        gamemode, map_name, target = self._edit_selection()
        if not selection_complete(gamemode, map_name, target):
            # On the Task selector with no side-task config open, there is no unit plan to
            # save — the queue itself already writes on every edit. Say that instead of
            # "select a full target", which reads like the save failed when nothing was
            # lost. `_edit_target` set means a side task *is* open, so a genuine
            # incomplete selection there still warrants the error.
            if self._in_task_mode() and self._edit_target is None:
                self._run_page.set_status("Tasks save automatically — nothing to save here.")
                return
            self._run_page.set_status("Select a full target first.", is_error=True)
            return
        self._units_page.commit()
        saved = self._config_store.save(gamemode, map_name, target, self._plan)
        if saved is None:
            self._run_page.set_status("Save failed.", is_error=True)
            return
        self._active_config_path = saved
        self._log(f"Saved {os.path.relpath(saved, self._app_root)}.")
        self._run_page.set_status(f"Saved {os.path.basename(saved)}.")

    def _on_reset_config(self) -> None:
        self._plan.reset_all()
        self._units_page.reload()
        self._run_page.set_status("Config reset (not yet saved).")
        self._log("Config reset.")

    def _on_import_config(self) -> None:
        gamemode, map_name, target = self._edit_selection()
        if not selection_complete(gamemode, map_name, target):
            self._run_page.set_status("Pick Map and Act before importing.", is_error=True)
            return
        selected, _filter = QFileDialog.getOpenFileName(
            self, "Import config", self._config_store.root, "Config JSON (*.json)"
        )
        if not selected:
            return
        payload = read_json(selected)
        raw_steps = payload.get("Units", [])
        if not isinstance(raw_steps, list):
            self._run_page.set_status("That file has no unit steps.", is_error=True)
            return
        plan = UnitPlan.empty()
        for position, raw in enumerate(raw_steps, start=1):
            if isinstance(raw, dict) and position <= len(plan.steps):
                step = UnitStep.from_payload(raw, fallback_step=position)
                if 1 <= step.step <= len(plan.steps):
                    plan.steps[step.step - 1] = step
        self._plan = plan
        self._units_page.reload()
        self._run_page.set_status(f"Imported {os.path.basename(selected)} (Save to keep).")
        self._log(f"Imported config from {os.path.basename(selected)}.")

    def _on_tasks_changed(self, slots: object) -> None:
        """Save the task queue as it is edited, like Settings and the Route tab."""
        if not isinstance(slots, list):
            return
        if not self._task_store.save(slots):
            self._log("Could not save the task queue.")
            return
        # The run strip shows the same queue while Task is the selection.
        self._refresh_queue_view()

    def _on_challenges_toggled(self, enabled: bool) -> None:
        """Save the challenges toggle. Read into `TaskDirector.challenges` at the next F1,
        so flipping it mid-session doesn't disturb a run already in flight."""
        self._settings.set_run_challenges(enabled)
        self._log(f"Daily challenges {'enabled' if enabled else 'disabled'}.")
        self._refresh_queue_view()


    def _on_camera_once_toggled(self, enabled: bool) -> None:
        self._settings.set_camera_once(enabled)
        # Turning it *on* must not skip the very next match on the strength of a camera set
        # before the toggle existed — earn the skip once first.
        self._camera_is_set = False
        self._log(
            "Camera setup: once per session."
            if enabled
            else "Camera setup: every match (default)."
        )

    def _on_hard_mode_toggled(self, enabled: bool) -> None:
        self._settings.set_hard_mode(enabled)
        self._log(f"Hard Mode (Story) {'enabled' if enabled else 'disabled'}.")

    # # Start position (Settings > Position)
    def _on_position_target(self, gamemode: str, map_name: str, act: str) -> None:
        """Fill the editor for a newly selected target."""
        editor = self._settings_page.position_editor
        editor.set_moves(self._position_store.moves(gamemode, map_name, act))
        source = "your edit" if self._position_store.has_override(gamemode, map_name, act) else "preset"
        self._settings_page.set_position_status(f"Showing the {source} for this target.")

    def _on_position_moves(self, gamemode: str, map_name: str, act: str, moves: object) -> None:
        """Save on every edit: there is no Save button on this tab, and an unsaved
        walk plan would silently not run."""
        if not isinstance(moves, list):
            return
        if not self._position_store.set_moves(gamemode, map_name, act, moves):
            self._settings_page.set_position_status("Pick a Map first.", is_error=True)
            return
        where = " / ".join(part for part in (gamemode, map_name, act) if part)
        self._settings_page.set_position_status(f"Saved {len(moves)} moves for {where}.")

    def _on_position_reset(self, gamemode: str, map_name: str, act: str) -> None:
        self._position_store.clear(gamemode, map_name, act)
        self._on_position_target(gamemode, map_name, act)
        where = " / ".join(part for part in (gamemode, map_name, act) if part)
        self._log(f"Start position for {where} reset to its preset.")

    def _on_delay_changed(self, key: str, value: float) -> None:
        self._delays[key] = value
        self._delays_store.set(key, value)
        self._nav.apply_delays(self._delays)
        self._placer.apply_delays(self._delays)
        self._log(f"Delay '{key}' set to {value:.1f}s.")

    # # Macro control
    def _stop_macro(self, trigger: str) -> None:
        """Stop key. Cooperative: a step in flight may be an AHK script holding a key
        down, and killing it would never send the release."""
        if not self._runner.is_running:
            self._log(f"Stop ({trigger}): the macro isn't running.")
            return
        if self._runner.stop_requested:
            self._log("Stop already requested; waiting for the current step.")
            return
        self._runner.request_stop()
        self._run_page.set_status("Stopping after current step...")
        self._log(f"Stop requested ({trigger}); finishing the current step first.")

    def _toggle_macro(self, trigger: str) -> None:
        """Kept for the Run page's button: one control that does the obvious thing."""
        if self._runner.is_running:
            self._stop_macro(trigger)
            return
        self._start_macro(trigger)

    def _start_macro(self, trigger: str) -> None:
        if self._runner.is_running:
            self._log(f"Start ({trigger}): already running — use the stop key.")
            return

        if self._run_task is not None:
            self._log(f"Macro start blocked ({trigger}): previous run is still winding down.")
            return

        if self._in_task_mode():
            self._start_task_mode(trigger)
            return

        gamemode, map_name, target = self._run_page.selection()
        macro_target = MacroTarget(gamemode=gamemode, map_name=map_name, target=target)
        if not selection_complete(gamemode, map_name, target):
            self._log(f"Macro start blocked ({trigger}): select Gamemode / Map / target first.")
            return

        self._units_page.commit()
        if not self._plan.enabled_steps():
            self._log(f"Macro start blocked ({trigger}): no enabled unit steps.")
            return

        # A normal run plays *only* the selected config, looping it. The task queue is a
        # separate mode (the Task tile on the selector) — feeding it in here meant a Story
        # run switched to whatever the queue held the moment a match ended, which is the
        # "why is it running my task queue when I picked Story" bug. An **empty** director
        # here keeps `_build_match_steps` from appending the `Next task` step, so the match
        # cycle just loops this target as it did before the Tasks tab existed.
        self._director = TaskDirector()
        self._run_plan = None

        steps, error = self._build_run_steps(macro_target)
        if error:
            self._log(f"Macro start blocked ({trigger}): {error}")
            self._run_page.set_status(error)
            return

        # Everything up to here runs once; the match steps repeat per match, so the
        # loop point is where they begin.
        loop_from = len(steps)
        steps += self._build_match_steps()

        if self._roblox_hwnd is not None:
            rbx.activate_window(self._roblox_hwnd)

        self._runner.start(macro_target, steps, loop_from=loop_from)
        self._run_page.set_running(True)
        self._stats.start_macro()
        self._refresh_stats()
        self._log(
            f"Macro started ({trigger}) on {macro_target.label()} — "
            f"{loop_from} lobby steps, {len(steps) - loop_from} repeating."
        )
        self._notify("Macro Started", COLOR_START, [("Trigger", trigger)])

        task = Task(self._run_loop)
        # Same lifetime rule as the tester: without a kept reference the task and
        # its signals can be GC'd before done arrives, and the run never reports.
        task.setAutoDelete(False)
        self._run_task = task
        task.signals.done.connect(self._on_run_finished)  # queued to the UI thread
        self._pool.start(task)

    def _start_task_mode(self, trigger: str) -> None:
        """F1 with Task selected: ask the queue what to play, then run it.

        The first task is started exactly as if it had been picked on the Run strip —
        `_start_queued_run` builds the same lobby chain — and the `Next task` step at the
        end of each match cycle rotates from there. So task mode adds a starting
        decision, not a second way to run.
        """
        self._director = TaskDirector(
            slots=self._task_store.slots(),
            tracker=self._challenges,
            # Challenges are a toggle, not a queue slot — read fresh here so switching it
            # mid-session takes effect on the next F1 without a restart.
            challenges=self._settings.get_run_challenges(),
        )
        if not self._director.is_configured():
            message = "No tasks queued — add them in Settings > Tasks."
            self._log(f"Macro start blocked ({trigger}): {message}")
            self._run_page.set_status(message, is_error=True)
            return

        # Read the challenge panel before deciding, if it happens to be on screen. This
        # is the only place the tracker gets filled during real use so far: open the
        # panel by hand, press F1, and the queue plans around what is actually
        # available. `scan_if_open` refuses a scan taken anywhere else, so pressing F1
        # from a stage can't invent three waiting challenges.
        panel_read, left_lobby = self._scan_challenges_if_open(navigate=True)
        self._challenges.note_scan_attempt()

        decision = self._director.decide()
        self._last_decision = decision
        self._last_won = True
        if decision.is_challenge:
            # Try *every* runnable row, not just the first. The rotation is random, so
            # with only some of the five challenge maps configured the first offered row
            # is often one you can't play — and giving up on the whole challenge task
            # because of that would waste the two rows you can.
            for read in self._challenges.candidates():
                attempt = TaskDecision(kind=DO_CHALLENGE, challenge=read)
                started, why, about_this_row = self._start_challenge_run(trigger, attempt)
                if started:
                    self._last_decision = attempt
                    return
                self._log(f"  Skipping challenge {read.slot}: {why}")
                # Retire the row **only** when the reason is about the row itself — an
                # unidentified map or a missing unit config would fail identically all
                # rotation. A failure to *start* (Roblox gone for a moment, AHK missing, an
                # exception in the starter) says nothing about the row, and marking it
                # anyway skipped a `10/10` challenge with a bright star for the next 30
                # minutes. That was the "it skips an available challenge" report.
                if about_this_row:
                    self._challenges.mark_done(read.slot)
                else:
                    break
            slot = self._director.current_target()
            decision = TaskDecision(kind=DO_TARGET, slot=slot) if slot else TaskDecision()
            self._last_decision = decision
        if decision.kind != DO_TARGET or decision.slot is None:
            message = f"Nothing runnable right now ({decision.reason or 'no target queued'})."
            self._log(f"Macro start blocked ({trigger}): {message}")
            self._run_page.set_status(message, is_error=True)
            return

        slot = decision.slot
        plan = self._config_store.load(slot.gamemode, slot.map_name, slot.act)
        if not plan.enabled_steps():
            where = " / ".join(part for part in (slot.gamemode, slot.map_name, slot.act) if part)
            message = f"{where} has no enabled unit steps."
            self._log(f"Macro start blocked ({trigger}): {message}")
            self._run_page.set_status(message, is_error=True)
            return

        self._run_plan = plan
        target = MacroTarget(
            gamemode=slot.gamemode, map_name=slot.map_name, target=slot.act
        )
        self._log(f"Task queue ({trigger}): {self._director.summary()}")
        # Opening the challenge panel clicked the lobby's Play button, so the lobby is
        # behind us — this chain has to start from the gamemode panel. Without it the
        # first step was `Play`, searching for a button no longer on screen, and the run
        # died with "Play not found" every time challenges were attempted and skipped.
        # Only set on the target path: a challenge run starts from the open panel and
        # wants no entry clicks at all.
        #
        # And only when the panel actually read. A read is the proof of *which* screen
        # the game is on; without it the change-gamemode click is a blind coordinate on
        # an unknown screen, which is how the second attempt died ("Story card not
        # found") after the first died on Play. Stopping with the reason beats clicking
        # somewhere nobody has looked.
        if left_lobby and not panel_read:
            message = (
                "Opened the challenge menu but couldn't read the panel, so the macro "
                "doesn't know which screen the game is on. Go back to the lobby by hand, "
                "then start again."
            )
            self._log(f"Macro start blocked ({trigger}): {message}")
            self._run_page.set_status(message, is_error=True)
            self._run_plan = None
            return
        if left_lobby:
            # The scan left us on the challenge list, so this chain closes it rather than
            # looking for a Play button that is no longer on screen.
            self._entry_screen = ENTRY_CHALLENGE_LIST
        if not self._start_queued_run(target):
            self._run_plan = None
            return
        self._run_page.set_running(True)
        self._stats.start_macro()
        self._refresh_stats()
        self._notify("Macro Started", COLOR_START, [("Trigger", trigger)])

    def _stage_next_after_challenge(self, decision: TaskDecision) -> StepResult:
        """After a challenge, hand over to whatever the queue picked next.

        Staged as a pending switch rather than run inline: the runner is mid-cycle here,
        and `_on_run_finished` is the one place that starts a fresh chain.
        """
        if decision.kind == DO_TARGET and decision.slot is not None:
            slot = decision.slot
            plan = self._config_store.load(slot.gamemode, slot.map_name, slot.act)
            if plan.enabled_steps():
                self._pending_target = MacroTarget(
                    gamemode=slot.gamemode, map_name=slot.map_name, target=slot.act
                )
                self._pending_plan = plan
                # Same reason as the challenge branch: the next outcome must be credited
                # to the task that is about to run, not the one that just finished.
                self._last_decision = decision
                self._runner.request_stop()
                return StepResult.DONE
            self._log(f"  {slot.map_name} has no enabled unit steps — stopping instead.")
        elif decision.is_challenge and decision.challenge is not None:
            # Reaching the list from the gamemode panel *is* built now (Change gamemode ->
            # Open challenge list), so stage the next challenge instead of stopping. The
            # map comes from the last scan; the chain re-reads nothing, so a rotation that
            # rolls over mid-run is caught on the next F1 rather than here.
            read = decision.challenge
            if read.map_name:
                plan = self._config_store.load(CHALLENGE, read.map_name, "")
                if plan.enabled_steps():
                    self._challenge_slot = read.slot
                    self._pending_target = MacroTarget(
                        gamemode=CHALLENGE, map_name=read.map_name, target=""
                    )
                    self._pending_plan = plan
                    # **Remember which decision this run is for.** Without this the next
                    # `note_match` marked the *previous* challenge again and left this one
                    # unmarked, so the queue kept choosing it — the "it still clicked
                    # challenge 1" report.
                    self._last_decision = decision
                    # No "switching to X" line here: `_start_queued_run` logs "now
                    # running X" a moment later, and two lines for one event is noise.
                    self._runner.request_stop()
                    return StepResult.DONE
                # Retire it: no config for this map means it would fail the same way every
                # time this rotation. Without this the next F1 chose the same dead row.
                self._challenges.mark_done(read.slot)
                self._log(
                    f"  Challenge {read.slot} on {read.map_name} has no unit config — "
                    "stopping."
                )
            else:
                self._challenges.mark_done(read.slot)
                self._log(f"  Challenge {read.slot}'s map wasn't identified — stopping.")
        else:
            self._log(f"  Nothing else queued ({decision.reason}) — stopping.")
        self._runner.request_stop()
        return StepResult.DONE

    def _rescan_challenges_after_match(self) -> StepResult:
        """Leave a finished match, re-read the challenge panel, then hand back to the queue.

        The detour a rotation reset needs. Runs on the macro worker (it is a step action),
        so everything here is capture + AHK; the stats panel is updated by signal.

        The target's progress is untouched: `TaskDirector` owns `_done_in_slot` and a
        challenge never increments it, so if the panel turns out to have nothing runnable
        the queue resumes the same target on the run it was up to.
        """
        ok, message = self._nav.leave_match()
        self._log(f"  Checking the challenge panel — leaving match: {message}")
        if not ok:
            # Still on the result screen. Looping this target is a worse outcome than a
            # missed challenge, so carry on rather than fail the run.
            self._log("  Couldn't leave the match; staying on this target.")
            return StepResult.DONE

        # Match Play lands on the gamemode panel; from there the list is change-gamemode
        # then the Challenge card, which is what `from_gamemode_panel` selects.
        self._entry_screen = ENTRY_MODE_PANEL
        return self._reread_challenges_and_stage()

    def _reread_challenges_and_stage(self) -> StepResult:
        """Re-read the challenge panel from the gamemode panel, then hand back to the queue.

        Split out of `_rescan_challenges_after_match` because the **challenge** handover
        needs it too and has already left the match — calling that method again would fire
        Match Play at a screen that is no longer a result screen. Callers must have set
        `_entry_screen = ENTRY_MODE_PANEL` first.
        """
        # Marked before navigating, not after: a panel that can't be read must cost one
        # detour per rotation, not one per match for the rest of the session.
        self._challenges.note_scan_attempt()
        read, moved = self._scan_challenges_if_open(navigate=True, from_gamemode_panel=True)
        if moved:
            # The list is up now, so whatever runs next starts from there — a challenge
            # with no entry clicks at all, a target by closing it first.
            self._entry_screen = ENTRY_CHALLENGE_LIST
        decision = self._director.decide()
        self._log(f"  After re-read: {decision.label()} — {decision.reason}")
        return self._stage_next_after_challenge(decision)

    def _start_challenge_run(self, trigger: str, decision: TaskDecision) -> tuple[bool, str]:
        """Play the challenge this decision picked. (started, why not).

        Needs the panel open and the row's map identified, both of which the scan that
        produced this decision has already established. The plan comes from
        `configs/Challenge/<Map>.json` — the same map's Story config is deliberately *not*
        substituted, because a challenge is a harder fight on that ground and wants its
        own placements.
        """
        read = decision.challenge
        if read is None:
            return (False, "no challenge in the decision", True)
        if not read.map_name:
            return (False, "its map wasn't identified, so there is no config to load", True)

        plan = self._config_store.load(CHALLENGE, read.map_name, "")
        if not plan.enabled_steps():
            return (
                False,
                f"configs/Challenge/{read.map_name}.json has no enabled unit steps "
                "(Settings > Tasks > Edit units)",
                True,
            )

        self._challenge_slot = read.slot
        self._run_plan = plan
        target = MacroTarget(gamemode=CHALLENGE, map_name=read.map_name, target="")
        self._log(
            f"Task queue ({trigger}): challenge {read.slot} on {read.map_name}, "
            f"{read.limit_text} left"
        )
        if not self._start_queued_run(target):
            self._challenge_slot = None
            self._run_plan = None
            # **Not final.** Roblox missing for a moment, AHK absent, an exception inside
            # the run starter — none of that says anything about this row, so the caller
            # must not retire it for the rotation.
            return (False, "the run wouldn't start — see the log", False)
        self._run_page.set_running(True)
        self._stats.start_macro()
        self._refresh_stats()
        self._notify("Macro Started", COLOR_START, [("Trigger", trigger)])
        return (True, "", True)

    def _start_queued_run(self, target: MacroTarget) -> bool:
        """Start the next task's run. Returns False if it couldn't, so the caller
        reports the macro as stopped rather than leaving it looking alive.

        Wrapped: an exception in here used to vanish to stderr, leaving the log ending
        mid-sentence and the UI looking like F1 did nothing. Whatever goes wrong, it goes
        in the log the user can actually see.
        """
        try:
            return self._start_queued_run_inner(target)
        except Exception as exc:  # noqa: BLE001 - the alternative is a silent no-op
            self._log(f"Run start failed for {target.label()}: {exc!r}")
            for line in traceback.format_exc().strip().splitlines()[-4:]:
                self._log(f"    {line}")
            # The runner may already have been started before the throw, which leaves it
            # "running" with no worker driving it — the state that looks like F1 did
            # nothing and then refuses to start again.
            if self._run_task is None and self._runner.is_running:
                self._runner.stop()
                self._log("    runner rolled back to idle.")
            return False

    def _start_queued_run_inner(self, target: MacroTarget) -> bool:
        steps, error = self._build_run_steps(target)
        if error:
            self._log(f"Task switch to {target.label()} blocked: {error}")
            return False

        # Consumed: the entry steps are baked into this chain now, and a later start (F1
        # from the lobby, say) must go back to using Play.
        self._entry_screen = ENTRY_LOBBY
        loop_from = len(steps)
        steps += self._build_match_steps()
        if self._roblox_hwnd is not None:
            rbx.activate_window(self._roblox_hwnd)
        if not self._runner.start(target, steps, loop_from=loop_from):
            self._log("Task switch failed: the runner was still busy.")
            return False

        # The stats panel owns the MAP / Current task cards; `RunPage` has no such method
        # (this line called it on the wrong object and took the whole start with it).
        self._stats_page.set_target(target.gamemode, target.map_name, target.target)
        self._log(f"Task switch: now running {target.label()}.")

        task = Task(self._run_loop)
        task.setAutoDelete(False)
        self._run_task = task
        task.signals.done.connect(self._on_run_finished)
        self._pool.start(task)
        return True

    def _build_run_steps(self, target: MacroTarget) -> tuple[list[MacroStep], str]:
        """Lobby navigation through to a loaded stage with the camera set.

        Returns (steps, error). An error means the selection can't be run yet —
        better to say so than to click through half a sequence.

        If the player joined the stage by hand, the lobby chain is skipped entirely
        and the run starts at the camera. That is one look for the in-match Start
        Game button, not a chain of optional steps: `Select act` and `Start stage`
        click *fixed coordinates*, so letting them fail-and-skip in-match would
        fire clicks into the game world before the camera is even set.
        """
        gamemode = target.gamemode
        stage = target.map_name
        act = target.target

        # Leaving a finished match lands on the gamemode panel, not the lobby, so the
        # chain starts with "change gamemode" instead of the lobby's Play button. Without
        # this the next task's first step was `Play`, which isn't on that screen — the run
        # died there every time a challenge handed over.
        # What it takes to get from wherever the macro is standing to the gamemode cards.
        # Nothing for the lobby: `Play` below does that job and only exists there.
        entry: list[MacroStep] = []
        if self._entry_screen == ENTRY_MODE_PANEL:
            entry.append(
                self._nav_step("Change gamemode", self._nav.change_gamemode, settle=False)
            )
        elif self._entry_screen == ENTRY_CHALLENGE_LIST:
            entry.append(
                self._nav_step(
                    "Close challenge list", self._nav.close_challenge_list, settle=False
                )
            )

        camera_step = self._nav_step(
            "Set camera", lambda: self._camera_setup(wait=True), settle=False
        )
        # After the camera, before anything is placed: some targets need the
        # character walked away from spawn first (Settings > Position).
        after_camera = [camera_step] + self._position_steps(target)

        if self._nav.in_match():
            self._log(
                "Already in a match (Start Game is on screen) — skipping the lobby "
                "chain and starting at the camera."
            )
            return (after_camera, "")

        # A challenge is already reachable when this runs: the panel is open, because
        # deciding to play one required reading it. So its chain is just the three
        # clicks, then the ordinary wait for the stage.
        if gamemode == CHALLENGE and self._challenge_slot is not None:
            slot = self._challenge_slot
            if self._entry_screen == ENTRY_CHALLENGE_LIST:
                # Already looking at the list — reading it is what chose this challenge, so
                # closing it and coming back would be two clicks to end up here again.
                entry = []
            elif self._entry_screen == ENTRY_MODE_PANEL:
                # `entry` already has the change-gamemode click; the card is the second half.
                entry.append(
                    self._nav_step(
                        "Open challenge list",
                        lambda: self._nav.open_gamemode(CHALLENGE),
                        settle=False,
                    )
                )
            return (
                entry
                + [
                    self._nav_step(
                        f"Start challenge {slot} ({stage})",
                        lambda bound=slot: self._nav.start_challenge(bound),
                        settle=False,
                    ),
                    self._nav_step("Stage loaded", self._nav.wait_for_match_ready, settle=False),
                ]
                + after_camera,
                "",
            )

        # Events navigates by a user-authored route instead of the fixed tables,
        # so it replaces the whole Play -> card -> stage -> act -> start chain.
        if is_custom(gamemode):
            route, error = self._route_steps(stage, act)
            if error:
                return ([], error)
            route.append(
                self._nav_step("Stage loaded", self._nav.wait_for_match_ready, settle=False)
            )
            return (route + after_camera, "")

        # settle=False wherever the *next* step is an image search: that search polls
        # until the screen is up (search_timeout), which is a better wait than a
        # fixed sleep and costs nothing when the screen is already there. Only steps
        # followed by a blind coordinate click keep the settle.
        # Play only from the lobby; the other two screens are already past it and `entry`
        # has their own way back to the cards. The card search follows either way, and it
        # is what proves the entry click landed.
        steps = entry + ([
            self._nav_step("Play", self._nav.click_play, settle=False),
        ] if self._entry_screen == ENTRY_LOBBY else []) + [
            self._nav_step(
                f"Open {gamemode}", lambda: self._nav.open_gamemode(gamemode), settle=False
            ),
            self._nav_step(f"Select {stage}", lambda: self._nav.select_stage(gamemode, stage)),
        ]

        if act:
            if act_coord(gamemode, act) is None:
                return ([], f"no act coordinates for {gamemode} / {act} — measure them first")
            steps.append(self._nav_step(f"Select {act}", lambda: self._nav.select_act(gamemode, act)))

        if difficulty_coord(gamemode) is not None:
            difficulty = self._settings.get_expedition_difficulty()
            steps.append(
                self._nav_step(
                    f"Difficulty {difficulty}",
                    lambda: self._nav.set_difficulty(gamemode, difficulty),
                )
            )

        hard_mode = self._settings.get_hard_mode()
        steps += [
            # start_stage ends with its own join wait, and readiness/camera don't
            # want an extra settle on top.
            self._nav_step(
                "Start stage", lambda: self._nav.start_stage(gamemode, hard_mode), settle=False
            ),
            self._nav_step("Stage loaded", self._nav.wait_for_match_ready, settle=False),
        ]
        # Blocking camera: it takes ~8s and anything clicking before it finishes
        # acts on a camera that is still moving. Then the optional walk.
        steps += after_camera
        return (steps, "")

    def _ensure_lobby(self) -> tuple[bool, str]:
        """Get to the lobby, because Events is only reachable from there.

        The Events button lives on the lobby itself, not in the gamemode menu — so unlike
        every other selector, an Events task cannot start from the panel a finished match
        leaves you on. There is no measured "back to lobby" control on that panel either.

        So: look for the Events button first, which costs one match and is all that is
        needed when the queue's Events slot runs first and the player is already in the
        lobby. Only when it isn't there does this re-join the private server — the deep
        link drops the client straight back into the lobby, which is the one route out of
        an arbitrary screen that is known to work.
        """
        ok, message = self._nav.find_events()
        if ok:
            return (True, f"already in the lobby ({message})")
        link = self._settings.get_private_server_link()
        if not link:
            return (
                False,
                "not in the lobby, and no private server link is set to re-join with "
                "(Settings > Main)",
            )
        self._log(f"  Not in the lobby ({message}) — re-joining the private server.")
        # Marshalled to the UI thread: this runs on the macro worker and the deep link
        # goes out through QDesktopServices, which is Qt.
        self.joinServerRequested.emit()
        deadline = time.monotonic() + LOBBY_REJOIN_TIMEOUT
        while True:
            if self._runner.stop_requested:
                return (False, "stopped by user while waiting for the lobby")
            time.sleep(LOBBY_REJOIN_POLL)
            ok, message = self._nav.find_events()
            if ok:
                return (True, f"back in the lobby ({message})")
            if time.monotonic() >= deadline:
                return (
                    False,
                    f"the lobby didn't appear within {LOBBY_REJOIN_TIMEOUT:.0f}s of "
                    f"re-joining ({message})",
                )

    def _route_steps(self, map_name: str, act: str) -> tuple[list[MacroStep], str]:
        """The Events chain: reach the lobby, click Events, then the saved route.

        Validated up front rather than mid-run: a route that clicks three screens
        deep and then fails on a blank image path has already left the game
        somewhere the next attempt can't read.
        """
        steps = self._routes.steps(map_name, act)
        if not steps:
            return ([], f"no route saved for {map_name} / {act} — build one in Run > Route")
        problems = route_problems(steps)
        if problems:
            return ([], "route can't run: " + "; ".join(problems[:3]))

        # Each route step becomes its own MacroStep so the log names what failed and
        # the runner's timeout applies per step rather than to the whole route.
        # The kind of the *next* step decides the settle: a step followed by an
        # image search needs none, because that search polls until the screen is up.
        kinds_after = [step.kind for step in steps[1:]] + [None]  # None = the load poll
        macro_steps = [
            # Before anything else: Events only exists in the lobby, and a queued Events
            # task can be reached from a finished match where it doesn't.
            self._nav_step(
                "Find the lobby",
                self._ensure_lobby,
                settle=False,
                timeout=LOBBY_REJOIN_TIMEOUT + 30.0,
            ),
            self._nav_step(
                "Events",
                self._nav.click_events,
                settle=steps[0].kind not in (KIND_FIND, KIND_EXPECT),
            ),
        ]
        for position, (step, next_kind) in enumerate(zip(steps, kinds_after), start=1):
            macro_steps.append(
                self._nav_step(
                    f"Route {position}: {step.summary()[:60]}",
                    lambda bound=step: self._nav.run_route_step(bound),
                    settle=next_kind not in (KIND_FIND, KIND_EXPECT, None),
                    timeout=self._nav.route_step_budget(step),
                )
            )
        return (macro_steps, "")

    def _position_steps(self, target: MacroTarget) -> list[MacroStep]:
        """The start-position walk for this target, or nothing if it has no plan.

        One step, outside the match loop: like the camera, walking into position is
        a once-per-run setup, not something to redo every wave.
        """
        moves = self._position_store.moves(target.gamemode, target.map_name, target.target)
        usable = [move for move in moves if move.is_actionable()]
        if not usable:
            return []
        seconds = total_hold_ms(usable) / 1000.0
        # The step's timeout has to cover the walking itself plus the per-move AHK
        # overhead, or the runner fails a plan that is merely long.
        budget = seconds + 8.0 * len(usable) + 5.0

        def action() -> StepResult:
            ok, message = self._placer.run_moves(usable)
            self._log(f"  Start position: {message}")
            return StepResult.DONE if ok else StepResult.FAILED

        return [
            MacroStep(
                name=f"Walk to position ({len(usable)} moves)",
                action=action,
                timeout_seconds=budget,
            )
        ]

    # # Stats + notifications
    def _running_target(self) -> tuple[str, str, str]:
        """What is actually being played, not what the Run strip has selected.

        They differ whenever the queue is driving: in Task mode the strip's selection is
        `("Task", "", "")`, so the panel and every Discord embed used to report the map as
        "Task" while the macro was on a challenge or the queue's second target.
        """
        if self._runner.is_running:
            target = self._runner.target
            return (target.gamemode, target.map_name, target.target)
        return self._run_page.selection()

    def _refresh_stats(self) -> None:
        """Redraw the Run panel. UI thread only — workers go through statsChanged."""
        self._stats_page.set_target(*self._running_target())
        self._stats_page.set_stats(self._stats.snapshot())

    def _target_label(self) -> str:
        parts = [part for part in self._running_target() if part]
        return " / ".join(parts) if parts else "-"

    def _stage_label(self) -> str:
        """One line saying what was played: `Challenge · School Grounds · row 3`, or
        `Story / Act 1 · School Grounds`.

        The map used to appear twice in every challenge embed — once as the gamemode/map
        pair and again inside a separate Challenge field — because the two were written at
        different times and neither knew about the other.
        """
        gamemode, map_name, act = self._running_target()
        where = " / ".join(part for part in (gamemode, act) if part) or "-"
        label = f"{where} \u00b7 {map_name}" if map_name else where
        if self._challenge_slot is not None and self._runner.is_running:
            label += f" \u00b7 row {self._challenge_slot}"
        return label

    def _challenge_fields(self) -> list[tuple[str, str]]:
        """All three rows' quotas, and when the maps change.

        Every row, not just the one being played: the point of this field on a phone is
        "how much is left today", and one row's count doesn't answer that. The row in play
        is marked, and its map is already in `_stage_label`, so nothing repeats.
        """
        slot = self._challenge_slot
        if slot is None or not self._runner.is_running:
            return []
        lines = []
        for row in CHALLENGE_SLOTS:
            read = self._challenges.reads.get(row)
            marker = "\u25b8 " if row == slot else "   "  # the row this run is on
            if read is None:
                lines.append(f"{marker}{row}. not read")
                continue
            where = read.map_name or "map unknown"
            left = "?" if read.runs_remaining is None else str(read.runs_remaining)
            lines.append(f"{marker}{row}. {where} — {left} left")
        when = next_interval_at().strftime("%I:%M %p").lstrip("0")
        lines.append(f"new maps {when}")
        return [("Challenges today", "\n".join(lines))]

    def _queue_fields(self) -> list[tuple[str, str]]:
        """How much of the current task is left before the queue moves on.

        Only in task mode, and only for a target: a challenge row's own quota is already in
        `Challenges today`, and a plain gamemode run has no limit to count down. The point
        is answering "is it nearly done with this one" from a phone without opening the app.
        """
        if not self._director.is_configured():
            return []
        decision = self._last_decision
        if decision.kind != DO_TARGET or decision.slot is None:
            return []
        remaining = self._director.runs_left()
        limit = max(1, decision.slot.limit)
        lines = [f"{remaining} of {limit} left on {decision.slot.map_name or 'this target'}"]
        following = self._director.next_target_label()
        if following:
            lines.append(f"then {following}")
        return [("Task progress", "\n".join(lines))]

    def _score_fields(self) -> list[tuple[str, str]]:
        """The run figures every embed carries.

        Three or four fields, not eight. Each one used to be its own labelled line, which
        on a phone was a column of two-word values where the labels outweighed the facts —
        and `Map` plus `Challenge` said the map twice. Grouped by what someone actually
        asks: what was played, how it's going, how long it's been.
        """
        stats = self._stats.snapshot()
        return [
            ("Stage", self._stage_label()),
            *self._challenge_fields(),
            *self._queue_fields(),
            (
                "Record",
                f"{stats.wins}W / {stats.losses}L this session ({stats.win_rate})"
                f" \u00b7 {stats.all_wins}W / {stats.all_losses}L all time"
                f" ({stats.all_win_rate})",
            ),
            (
                "Time",
                f"last match {stats.last_stage_time} \u00b7 macro up {stats.macro_time}",
            ),
        ]

    def _notify(
        self,
        title: str,
        color: int,
        extra: list[tuple[str, str]] | None = None,
        image_png: bytes | None = None,
    ) -> None:
        if not self._webhook.enabled:
            return
        fields = (extra or []) + self._score_fields()
        self._webhook.send(
            title,
            fields,
            color=color,
            footer=f"SloppyKeys {VERSION}",
            image_png=image_png,
        )

    def _result_screenshot(self) -> bytes | None:
        """The Roblox screen at the moment a result was detected, PNG bytes.

        Only the win/loss embeds carry one — the start and end embeds are about the
        session, not a screen. Called from the macro worker, which is fine: this is
        mss + cv2 and a sleep, no Qt.

        The wait matters: the result banner is what the template matched, and the
        rewards below it animate in after that, so capturing immediately caught the
        panel half-drawn (sometimes with rewards, sometimes without). Tunable as
        `result_screenshot_delay` in Settings > Delays.
        """
        if not self._webhook.enabled:
            return None
        pause = float(self._delays.get("result_screenshot_delay", 1.0))
        if pause > 0:
            time.sleep(pause)
        rect = self._roblox_rect()
        if rect is None:
            return None
        shot = self._search_engine.capture_png(rect)
        if shot is None:
            self._log("Result screenshot failed — sending the embed without it.")
        return shot

    def _record_outcome(self, won: bool) -> None:
        """Called from the macro worker: count it, tell the UI, tell Discord."""
        # Read by the "Next task" step, which runs straight after this one.
        self._last_won = won
        # Spend the challenge run *here*, not in `note_match`, for two reasons: the game
        # only charges a run for a win (a loss leaves the count where it was, per the
        # user), and `note_match` runs in the `Next task` step — after this embed is built,
        # so the notification always showed the count from before the run.
        if won and self._challenge_slot is not None:
            self._challenges.note_run_used(self._challenge_slot)
            self.challengesRead.emit(list(self._challenges.reads.values()))
        # Grab the screen before counting: the result screen is up right now, and
        # nothing here changes it, but the capture is what has a deadline.
        shot = self._result_screenshot()
        self._stats.record(won)
        self.statsChanged.emit()
        self._notify(
            "Stage Won" if won else "Stage Lost",
            COLOR_WIN if won else COLOR_LOSS,
            image_png=shot,
        )

    def _outcome_step(self) -> MacroStep:
        """Ends a match cycle: wait for the win or defeat screen, then count it."""

        def action() -> StepResult:
            outcome, message = self._placer.wait_for_outcome()
            self._log(f"  Match result: {message}")
            if outcome == OUTCOME_WON:
                self._record_outcome(True)
                return StepResult.DONE
            if outcome == OUTCOME_LOST:
                self._record_outcome(False)
                return StepResult.DONE
            return StepResult.FAILED

        return MacroStep(
            name="Wait for result", action=action, timeout_seconds=RUN_STEP_TIMEOUT
        )

    def _build_match_steps(self) -> list[MacroStep]:
        """The repeating part of a run: pre-placement units, Start Game, the rest,
        then idle until the win screen.

        Pre-placement steps run before Start Game because that's the only window
        where the wave hasn't started yet. Everything else runs in step order, one
        step fully finished before the next begins.
        """
        # `_run_plan` is set when the task queue switched targets mid-run; otherwise
        # the macro places whatever the Units page has open, as it always has.
        plan = self._run_plan or self._plan
        pre, during = split_steps(plan.enabled_steps())

        steps = [self._placement_step(step) for step in pre]
        steps.append(
            self._nav_step("Start Game", self._start_game, settle=False)
        )
        steps += [self._placement_step(step) for step in during]
        # Ends the cycle: parks the cursor, keep-alive clicks, then counts the win
        # or the loss and notifies Discord.
        steps.append(self._outcome_step())
        # Only with a queue configured: without one the cycle loops on this target
        # exactly as it did before the Tasks tab existed.
        if self._director.is_configured():
            steps.append(self._next_task_step())
        # **Last, after the task decision, on purpose.** Repeat replays *this* stage, so it
        # must not fire when the queue is switching away — and a switching `Next task` has
        # already called `request_stop()`, which the runner honours between steps, so this
        # never runs in that case. When the queue stays (or there is no queue) the cycle
        # loops here and Repeat is exactly right.
        steps.append(self._repeat_step())
        return steps

    def _start_game(self) -> tuple[bool, str]:
        """Park, then find and click Start Game.

        The park is the fix for a measured failure: a pre-placement step leaves the cursor on
        the unit it just placed, Roblox draws a tooltip there, and the tooltip covered the
        button — `Start Game not found (best 0.47 < 0.70)` immediately after
        `placed slot 3 at 571,75`. In-match clicks deliberately don't retreat on their own
        (the cursor belongs on the unit), so the retreat belongs to the step that needs a
        clear view.

        Costs one `move_script`, and only once per match cycle. No wait afterwards: the
        search polls on a deadline, so it picks the button up the moment the tooltip fades.
        Also covers the post-Repeat entry to this step, where the cursor is left on Repeat.
        """
        self._placer.park()
        return self._nav.click_start_game()

    def _repeat_step(self) -> MacroStep:
        """After a win, click Repeat on the victory screen so the next match can start.

        Skipped after a loss: the defeat screen has its own controls, and the only measured
        one is the challenge retry (`LOSS_RETRY_CLICK`). Nothing about the loss path changes
        here.

        Never fails the run. If the template is missing or the button isn't found, the cycle
        falls through to `Start Game`, which polls for `start_game.png` on a deadline — the
        behaviour before this step existed.
        """

        def action() -> StepResult:
            if not self._last_won:
                return StepResult.DONE
            _ok, message = self._nav.click_repeat()
            # DONE either way, deliberately: Start Game is next and it waits on a deadline,
            # so a missed Repeat costs one search instead of ending the run. The log line is
            # how a persistent miss gets noticed.
            self._log(f"  Repeat: {message}")
            return StepResult.DONE

        return MacroStep(name="Repeat", action=action, timeout_seconds=RUN_STEP_TIMEOUT)

    def _next_task_step(self) -> MacroStep:
        """Last step of a match cycle: ask the queue what's next.

        Staying on the same target is the common case and costs nothing — the runner
        just loops as usual. A different target needs the lobby chain again, so this
        asks the runner to stop and `_on_run_finished` starts a fresh run on the new
        target. Switching by restart rather than by rewriting the step list keeps the
        runner as dumb as it is today.
        """

        def action() -> StepResult:
            was_challenge = self._challenge_slot
            self._director.note_match(self._last_decision, self._last_won)
            if was_challenge is not None:
                # `note_match` just marked the row played, which only the *reads* carry
                # into the UI — without this re-emit the finished challenge kept showing
                # "Ready" in the stats panel until the next scan.
                self.challengesRead.emit(list(self._challenges.reads.values()))
            decision = self._director.decide()
            self._last_decision = decision
            self._log(f"  Next task: {decision.label()} — {decision.reason}")

            if was_challenge is not None:
                # A finished challenge never loops. A win used the run up; a loss would
                # almost certainly lose again on the same map and spend another of the
                # day's ten, so `note_match` has already marked it skipped for this
                # rotation. Either way the next thing needs a different screen, so leave
                # the match and let the queue restart on whatever it picked.
                ok, message = self._nav.leave_match()
                # One line for the whole handover instead of three.
                self._log(
                    f"  Challenge {was_challenge} "
                    f"{'won' if self._last_won else 'lost (skipped this rotation)'} — "
                    f"leaving match: {message}"
                )
                self._challenge_slot = None
                # Match Play lands on the gamemode panel; the next chain must start there.
                self._entry_screen = ENTRY_MODE_PANEL if ok else ENTRY_LOBBY
                if not ok:
                    # Still on the result screen; stopping is better than looping a
                    # challenge, which is what this whole branch exists to prevent.
                    return StepResult.FAILED
                # **The maps may have re-rolled during this challenge**, and `decision`
                # above was computed from a tracker `note_time` had just emptied — so it
                # says "target" purely because there are no reads yet, not because the
                # rotation has nothing to offer. Measured: challenge 3 finished at 08:31,
                # four minutes into a run that began at 08:26 in the previous rotation, and
                # the queue handed over to the Events target instead of the three fresh
                # challenges. Re-read before believing that decision. We are already out of
                # the match, hence the shared helper rather than
                # `_rescan_challenges_after_match`, which would click Match Play again.
                if self._director.wants_challenges and self._challenges.needs_rescan():
                    return self._reread_challenges_and_stage()
                return self._stage_next_after_challenge(decision)

            # The maps may have re-rolled while this match was running. `decide()` called
            # `note_time`, which threw the old rotation's reads away, so the only way to
            # know whether there is challenge work now is to go and look — and looking
            # means leaving the match. Without this the queue fell through to its targets
            # after the first reset and never returned to challenges for the rest of the
            # session.
            # `wants_challenges` first: with no challenge slot queued the tracker never
            # holds reads, so `needs_rescan` would be true forever and every match cycle
            # would take a pointless detour.
            if self._director.wants_challenges and self._challenges.needs_rescan():
                return self._rescan_challenges_after_match()

            if decision.is_challenge:
                # Reads survived the match, so the panel is still reachable the same way.
                return self._rescan_challenges_after_match()
            if decision.kind != DO_TARGET or decision.slot is None:
                return StepResult.DONE

            slot = decision.slot
            wanted = MacroTarget(
                gamemode=slot.gamemode, map_name=slot.map_name, target=slot.act
            )
            if wanted.label() == self._runner.target.label():
                return StepResult.DONE

            plan = self._config_store.load(slot.gamemode, slot.map_name, slot.act)
            if not plan.enabled_steps():
                self._log(
                    f"  {wanted.label()} has no enabled unit steps — skipping that task."
                )
                self._director.note_match(decision, True)
                return StepResult.DONE

            self._pending_target = wanted
            self._pending_plan = plan
            self._log(f"  Switching to {wanted.label()} after this match.")
            self._runner.request_stop()
            return StepResult.DONE

        return MacroStep(name="Next task", action=action, timeout_seconds=RUN_STEP_TIMEOUT)

    def _placement_step(self, step: UnitStep) -> MacroStep:
        kind = "sequence" if step.is_sequence() else (step.unit_name or "unit")
        return self._nav_step(
            f"Step {step.step} ({kind})", lambda s=step: self._placer.run_step(s), settle=False
        )

    def _nav_step(
        self, name: str, call, settle: bool = True, timeout: float | None = None
    ) -> MacroStep:
        """Wrap a navigator call (which returns (ok, message)) as a MacroStep.

        The navigator steps already retry internally and wait for screens to
        render, so a False here is a real failure rather than "not yet" — hence
        FAILED and not RETRY.

        `settle` is a blind wait after the step (`image_search_cooldown`). Pass
        False when the next step starts with an image search — it will poll for the
        screen anyway, so sleeping first just adds latency.

        `timeout` overrides the per-step budget. A route step that scrolls a list
        looking for a card can legitimately outlast RUN_STEP_TIMEOUT, and killing a
        healthy step mid-scroll leaves the menu somewhere the next run can't read.
        """

        def action() -> StepResult:
            self.actionChanged.emit(name)
            ok, message = call()
            self._log(f"  {name}: {message or ('ok' if ok else 'failed')}")
            if not ok:
                return StepResult.FAILED
            if settle:
                time.sleep(self._nav.click_settle)
            return StepResult.DONE

        budget = RUN_STEP_TIMEOUT if timeout is None else max(RUN_STEP_TIMEOUT, timeout)
        return MacroStep(name=name, action=action, timeout_seconds=budget)

    def _run_loop(self) -> tuple[bool, str]:
        """Drive the runner on a worker thread until it finishes or is stopped.

        Never call this on the UI thread: a single step can block for a minute
        (stage load) and the camera step alone blocks ~8s, which would freeze the
        window and the hotkey poll that stops it.
        """
        while self._runner.is_running and self._runner.phase is not Phase.FINISHED:
            if self._runner.stop_requested:
                cycles = self._runner.cycle
                self._runner.stop()
                return (True, f"stopped by user after {cycles} match cycles")
            self._runner.tick()
            time.sleep(RUN_TICK_SLEEP)

        cycles = self._runner.cycle
        finished = self._runner.phase is Phase.FINISHED
        self._runner.stop()
        if finished:
            return (True, f"sequence complete after {cycles} match cycles")
        return (False, "a step failed; see the log above")

    def _on_run_finished(self, ok: bool, message: str) -> None:
        self._run_task = None
        # A queued task switch: the run was stopped on purpose at the end of a match
        # cycle, so start the next one instead of reporting the macro as finished. On
        # the UI thread already (the done signal is queued), which is where a run may
        # be started from.
        pending = self._pending_target
        if ok and pending is not None:
            self._pending_target = None
            self._run_plan = self._pending_plan
            self._pending_plan = None
            if self._start_queued_run(pending):
                return
        self._pending_target = None
        self._pending_plan = None
        self._run_plan = None
        self._run_page.set_running(False)
        self._run_page.set_status(message)
        self._log(f"Macro finished: {message}")
        # Notify before stopping the clocks, so the embed still carries the run time.
        self._notify("Macro Ended", COLOR_END, [("Reason", message)])
        self._stats.stop_macro()
        self._stats_page.set_action("Idle")
        self._refresh_stats()

    # # Settings
    def _on_link_committed(self, link: str) -> None:
        self._settings.set_private_server_link(link)
        if not link:
            self._settings_page.set_link_status("Private server link cleared.")
            return
        _uri, error = parse_private_server_link(link)
        if error:
            self._settings_page.set_link_status(error, is_error=True)
        else:
            self._settings_page.set_link_status("Private server link saved.")

    def _on_webhook_committed(self, url: str) -> None:
        clean, error = validate_webhook_url(url)
        if error:
            # Rejected, not stored: a bad URL saved silently would look enabled and
            # never deliver. The log deliberately never contains the URL itself.
            self._settings_page.set_webhook_status(error, is_error=True)
            return
        self._settings.set_discord_webhook(clean)
        if clean:
            self._settings_page.set_webhook_status("Discord webhook saved.")
            self._log("Discord webhook set.")
        else:
            self._settings_page.set_webhook_status("Discord notifications off.")
            self._log("Discord webhook cleared.")

    def _on_webhook_test(self) -> None:
        # Blocking on purpose: a test button that returns "queued" tells you
        # nothing. It's one short POST on the UI thread with a 10s cap.
        ok, message = self._webhook.send(
            "SloppyKeys connected",
            [("Status", "Test message — notifications are working.")],
            color=COLOR_START,
            footer=f"SloppyKeys {VERSION}",
            blocking=True,
        )
        self._settings_page.set_webhook_status(
            f"Test sent ({message})." if ok else f"Test failed: {message}", is_error=not ok
        )
        self._log(f"Discord webhook test: {'ok' if ok else message}")

    def _on_join_server(self) -> None:
        uri, error = parse_private_server_link(self._settings.get_private_server_link())
        if error:
            self._settings_page.set_link_status(error, is_error=True)
            return
        # roblox:// deep link, not the web page: this launches the client and joins
        # the private server directly instead of parking the user in a browser.
        if not QDesktopServices.openUrl(QUrl(uri)):
            self._settings_page.set_link_status(
                "Windows could not open the Roblox link. Is the Roblox client installed?",
                is_error=True,
            )
            return
        # Re-joining reloads the world, so the camera is back to default no matter what it
        # was: the once-per-session skip has to be earned again.
        self._camera_is_set = False
        self._settings_page.set_link_status("Launching Roblox into the private server.")
        # Also reached from the macro worker via `joinServerRequested` when an Events task
        # needs the lobby back, so this line shows up mid-run too.
        self._log("Launching Roblox into the private server via deep link.")

    def _load_profiles(self) -> None:
        self._profiles = self._profile_store.load()
        if self._active_profile_key not in self._profiles:
            self._active_profile_key = next(iter(self._profiles), None)

    def _active_image_path(self) -> str:
        """Storable path of the selected image profile; shown in the Macro Tester."""
        if self._active_profile_key is None:
            return ""
        profile = self._profiles.get(self._active_profile_key)
        if profile is None:
            return ""
        return self._search_engine.to_storable_path(profile.image_path)

    def _on_select_image(self) -> None:
        selected, _filter = QFileDialog.getOpenFileName(
            self,
            "Select search image",
            self._profile_store.images_dir,
            "PNG image (*.png);;All files (*.*)",
        )
        if not selected:
            return
        key = self._profile_store.profile_key(selected)
        if key not in self._profiles:
            self._profiles[key] = ImageProfile(
                name=key,
                image_path=self._search_engine.to_absolute_path(selected),
            )
        self._active_profile_key = key
        self._profile_store.save(self._profiles)
        self._log(f"Search image selected: {os.path.basename(selected)}.")

    def _run_image_search(self) -> tuple[bool, str]:
        """Search the active image profile inside the viewport. Used by the
        Macro Tester's image tester and its VISION test row."""
        if self._active_profile_key is None:
            return (False, "No image selected.")
        profile = self._profiles.get(self._active_profile_key)
        if profile is None:
            return (False, "No image selected.")
        rect = self._viewport.screen_rect()
        match = self._search_engine.find_first([profile], rect)
        if match is None:
            return (False, "No match in the viewport.")
        return (True, f"match {match.score:.3f} at {match.center_x},{match.center_y}")

    def _placement_target(self) -> tuple[str, str, str]:
        """(gamemode, map, act) the placement picker should show a backdrop for.

        The act is included because a Raid map's acts are different areas of the
        same map, so they need their own reference image. Unlike gamemode and map
        it isn't defaulted: a guessed act would show another act's playfield, and
        the lookup already falls back to the per-map reference.
        """
        # Follows the Units page, not the run: while a side task's plan is open, the
        # picker must draw that map's reference image, not the run target's.
        if self._edit_target is not None:
            return (
                self._edit_target.gamemode,
                self._edit_target.map_name,
                self._edit_target.target,
            )
        _g, _m, act = self._run_page.selection()
        return (self._current_gamemode(), self._current_stage(), act)

    # # Selector option providers
    def _maps_for_gamemode(self, gamemode: str) -> list[str]:
        """Maps for the Run strip: the table, or the saved routes for Events."""
        if is_custom(gamemode):
            return self._routes.maps()
        return maps_for(gamemode)

    def _targets_for_map(self, gamemode: str, map_name: str) -> list[str]:
        if is_custom(gamemode):
            return self._routes.acts(map_name) if map_name else []
        return targets_for(gamemode, map_name)

    def _roblox_rect(self) -> tuple[int, int, int, int] | None:
        """Roblox client area in screen coordinates, for image capture/search."""
        hwnd = rbx.find_roblox_window()
        if hwnd is None:
            return None
        origin = rbx.client_to_screen(hwnd, 0, 0)
        size = rbx.client_size(hwnd)
        if origin is None or size is None:
            return None
        return (origin[0], origin[1], size[0], size[1])

    # # Lobby navigation (delegates to LobbyNavigator; testable per step)
    def _current_gamemode(self) -> str:
        return self._gamemode or "Story"

    def _current_stage(self) -> str:
        _g, map_name, _t = self._run_page.selection()
        if map_name:
            return map_name
        maps = self._maps_for_gamemode(self._current_gamemode())
        return maps[0] if maps else ""

    def _test_open_gamemode(self) -> tuple[bool, str]:
        return self._nav.open_gamemode(self._current_gamemode())

    def _current_act(self) -> str:
        _g, _m, target = self._run_page.selection()
        return target or "Act 1"

    def _route_selection(self) -> tuple[str, str, str]:
        """(event, act, error) for the Run strip's current Events selection."""
        gamemode, map_name, act = self._run_page.selection()
        if not is_custom(gamemode):
            return ("", "", f"{gamemode or 'no gamemode'} has no route — pick Events on the selector")
        if not (map_name and act):
            return ("", "", "pick an Event and an Act on the Run strip first")
        return (map_name, act, "")

    def _test_challenge_leg_dry_run(self) -> tuple[bool, str]:
        """What a challenge run *would* do, without doing any of it. Fires no input.

        Prints the row-selection points and the Start point so they can be checked
        against the screen before anything clicks them. The row points are derived from
        the map-name boxes and are an assumption; Start is unmeasured, and this row is
        how you confirm both.
        """
        for slot, point in sorted((s, challenge_row_click(s)) for s in CHALLENGE_SLOTS):
            self._log(f"    step 1, row {slot}: click {point} (centre of its map-name box)")
        self._log(f"    step 2: click {CHALLENGE_SELECT_STAGE} — selects the stage")
        self._log(f"    step 3: click {CHALLENGE_START} — Start, which only exists after step 2")

        reads = self._challenges.reads
        if reads:
            for slot in sorted(reads):
                self._log(f"    last read {reads[slot].summary()}")
        else:
            self._log("    panel not read yet — run 'Scan challenges' first")

        return (
            True,
            f"3 clicks per challenge: row, {CHALLENGE_SELECT_STAGE}, {CHALLENGE_START}",
        )

    def _test_geometry_report(self) -> tuple[bool, str]:
        """Every number image search depends on, plus a capture sanity check.

        For the multi-monitor problem: run it on the display where searching works and
        again where it doesn't, and compare. What it can distinguish, which source
        reading cannot:

        - a wrong *rect* (Win32 and Qt disagreeing about where the window is, the
          classic DPI-awareness symptom) — the printed rects won't line up
        - a wrong *capture* (mss handing back the wrong pixels or a black frame) — the
          brightness figures go to zero or barely vary
        - a monitor mss doesn't know about, or negative virtual-screen coordinates
        """
        lines: list[str] = []
        screen = self.screen()
        if screen is not None:
            geometry = screen.geometry()
            lines.append(
                f"app is on Qt screen '{screen.name()}' at "
                f"({geometry.x()}, {geometry.y()}) {geometry.width()}x{geometry.height()}, "
                f"devicePixelRatio {screen.devicePixelRatio()}, logicalDpi {screen.logicalDotsPerInch()}"
            )
        window_rect = self.geometry()
        lines.append(
            f"our window: ({window_rect.x()}, {window_rect.y()}) "
            f"{window_rect.width()}x{window_rect.height()}"
        )

        hwnd = rbx.find_roblox_window()
        rect = self._roblox_rect()
        if hwnd is None:
            lines.append("Roblox: not found")
        else:
            origin = rbx.client_to_screen(hwnd, 0, 0)
            size = rbx.client_size(hwnd)
            lines.append(f"Roblox client origin {origin}, client size {size}")
            lines.append(f"search rect used: {rect}")
            # The single most important line when comparing monitors: anything but 100%
            # invalidates every template's pixel size and every stored coordinate.
            percent = scale_percent_for_window(hwnd)
            lines.append(
                f"game monitor scaling: {percent}%"
                + ("" if percent == 100 else f"  <-- NOT 100%, this breaks templates and coordinates")
            )

        # Is Roblox actually behind the hole? Ruled out by measurement: negative screen
        # coordinates, AHK's coordinate space and DPI scaling are all fine (both monitors
        # 96 DPI, AHK's MouseGetPos matches Win32 exactly, mss grabs real pixels at
        # left=-1820). What is left is this: if Roblox is *not* under the viewport, our
        # own opaque window is what gets captured and what gets clicked — which looks
        # exactly like "images aren't found, and when they are the clicks land elsewhere".
        # Compare against the **hole**, not the viewport widget. The widget is the hole plus
        # `viewport.BORDER_INSET` (6px) of dashed frame on each side, so a correctly placed
        # Roblox always sits at +6,+6 and is 12px smaller in each axis. An earlier version of
        # this check compared widget-to-client and reported every healthy setup as
        # "MISALIGNED", which sent the user chasing a positioning bug that did not exist.
        hole_rect = self._viewport.screen_rect()
        lines.append(f"viewport hole on screen: {hole_rect}")
        if rect is not None:
            offset = (rect[0] - hole_rect[0], rect[1] - hole_rect[1])
            aligned = offset == (0, 0) and rect[2:] == hole_rect[2:]
            lines.append(
                f"Roblox vs hole: offset {offset}, size match {rect[2:] == hole_rect[2:]}"
                + (
                    " — aligned"
                    if aligned
                    else " — MISALIGNED: Roblox is not under the hole, so capture and clicks "
                    "address the wrong pixels"
                )
            )
        lines.append(
            f"window mask applied: {not self.mask().isEmpty()}, "
            f"viewport visible: {self._viewport.isVisible()}"
        )

        try:
            import mss  # local: only needed for this report

            with mss.mss() as camera:
                for index, monitor in enumerate(camera.monitors):
                    label = "virtual screen" if index == 0 else f"monitor {index}"
                    lines.append(f"mss {label}: {monitor}")
        except Exception as exc:
            lines.append(f"mss monitor list failed: {exc}")

        # Does the capture actually contain the game? A black or flat frame is the
        # signature of grabbing the wrong surface, which looks identical to "the
        # template is wrong" from the log alone.
        if rect is not None:
            image = self._search_engine.capture_bgr(rect)
            if image is None:
                lines.append("capture: FAILED (None)")
            else:
                mean = float(image.mean())
                spread = float(image.std())
                # No sharpness metric here any more. One was added to compare "the window
                # looks clearer on this monitor" between displays, and measurement showed it
                # was noise: successive captures of the *same* monitor varied 8.7% while the
                # two monitors differed by 1.4%. It measured what was on screen at that
                # instant, not the display. mean/variation already catch the case that
                # matters (a blank or wrong surface).
                lines.append(
                    f"capture: {image.shape[1]}x{image.shape[0]}, "
                    f"mean brightness {mean:.1f}, variation {spread:.1f}"
                    + (" — looks blank, this is the problem" if spread < 3.0 else "")
                )
        for line in lines:
            self._log(f"    {line}")
        return (True, "geometry + capture report in the log")

    def _test_map_panel_text(self) -> tuple[bool, str]:
        """Find every string on screen and print where it is. Reads only, no input.

        The measured boxes came off screenshots, and a box that lands on the wrong
        label reads plausible nonsense rather than failing (all three map boxes
        reading "Hard Mode" is what that looks like). This runs OCR with detection on
        over the whole client, so the panel's real layout comes back as coordinates
        that can be pasted straight into `content/challenge.py`.
        """
        rect = self._roblox_rect()
        if rect is None:
            return (False, "Roblox not found — start it first")
        ready, message = self._ocr.available()
        if not ready:
            return (False, message)

        image = self._search_engine.capture_bgr(rect)
        blocks = self._ocr.read_all(image)
        if not blocks:
            return (False, "no text found on screen at all — is the panel open?")
        for block in blocks:
            self._log(f'    {block.region()}  "{block.text}" ({block.score:.2f})')
        return (True, f"{len(blocks)} text blocks — coordinates in the log")

    def _test_ocr_ready(self) -> tuple[bool, str]:
        """Does the OCR engine start, and what does it actually read?

        Two separate failures this untangles: the dependency missing or the models not
        loading (the first line), versus a box pointing at the wrong pixels (the raw
        text per box). Reads only — no clicking. Open the challenge panel first to see
        the second half do anything.
        """
        ready, message = self._ocr.available()
        self._log(f"    engine: {message}")
        if not ready:
            return (False, message)

        rect = self._roblox_rect()
        if rect is None:
            return (True, f"{message}, but Roblox isn't running so nothing was read")
        for name, (x, y, width, height) in challenge_debug_boxes():
            if name.endswith("_star"):
                continue  # a star is a picture, not text
            image = self._search_engine.capture_bgr((rect[0] + x, rect[1] + y, width, height))
            read = self._ocr.read_line(image)
            self._log(f'    {name}: "{read.text}" ({read.score:.2f})')
        return (True, f"{message} — raw text per box in the log")

    def _test_dump_challenge_boxes(self) -> tuple[bool, str]:
        """Write every measured challenge box out as a PNG. No input, no clicking.

        Run this with the challenge panel open, then look in
        `images/challenge/debug/`. Each file is exactly what the scan sees through
        that box, so a coordinate that is off by 20px is obvious instead of showing
        up later as a template that never matches. The map and limit dumps are also
        the raw material the real crops come out of.
        """
        rect = self._roblox_rect()
        if rect is None:
            return (False, "Roblox not found — start it first")

        boxes = challenge_debug_boxes()
        saved = 0
        for name, (x, y, width, height) in boxes:
            # Client-space box -> screen rect, the same conversion the route capture
            # uses, so the pixels are the ones a search would read.
            png = self._search_engine.capture_png((rect[0] + x, rect[1] + y, width, height))
            relative = challenge_debug_path(name)
            if png is None:
                self._log(f"    {name}: capture failed")
                continue
            target = os.path.join(self._app_root, relative)
            try:
                os.makedirs(os.path.dirname(target), exist_ok=True)
                with open(target, "wb") as handle:
                    handle.write(png)
            except OSError as exc:
                self._log(f"    {name}: could not write {relative} ({exc})")
                continue
            saved += 1
            self._log(f"    {name}: {width}x{height} -> {relative}")
        return (
            saved == len(boxes),
            f"dumped {saved} of {len(boxes)} boxes to images/challenge/debug",
        )

    def _test_scan_challenges(self) -> tuple[bool, str]:
        """Report-only read of the three challenge rows. Fires no input.

        Open the challenge panel by hand first — this answers "what is on screen
        now", which is exactly what proves the coordinates before anything clicks.
        """
        if self._roblox_rect() is None:
            return (False, "Roblox not found — start it first")
        reads = self._challenge_scanner.scan()
        self._challenges.note_time()
        self._challenges.note_reads(reads)
        for read in reads:
            self._log(f"    {read.summary()}")

        ready, message = self._ocr.available()
        if not ready:
            self._log(f"    OCR: {message}")
        runnable = [read for read in reads if read.state == STATE_RUNNABLE]
        unknown = [read for read in reads if read.state == STATE_UNKNOWN]
        named = [read for read in reads if read.map_name]
        summary = (
            f"{len(runnable)} runnable, {len(named)}/3 maps identified, "
            f"{len(unknown)} unknown, next rotation {next_interval_at().strftime('%H:%M')}"
        )
        # A pass means every row was read *and* named: unknown state or an
        # unidentified map both mean the macro couldn't pick a config for it.
        return (not unknown and len(named) == len(reads), summary + " — details in the log")

    def _test_route_templates(self) -> tuple[bool, str]:
        """Pure report: no clicks. Which route steps reference a template, and is
        the file actually there? This is what catches a missing events.png or a
        template that was moved after the route was built."""
        map_name, act, error = self._route_selection()
        if error:
            return (False, error)
        steps = self._routes.steps(map_name, act)
        if not steps:
            return (False, f"no route saved for {map_name} / {act}")

        lines: list[str] = []
        missing = 0
        # The Events click comes before any route step, so its template counts too.
        for label, path in [("Events button", events_image())] + [
            (f"step {position}", step.image)
            for position, step in enumerate(steps, start=1)
            if step.image
        ]:
            exists = os.path.isfile(self._search_engine.to_absolute_path(path))
            missing += 0 if exists else 1
            lines.append(f"{label}: {path} {'ok' if exists else 'MISSING'}")

        problems = route_problems(steps)
        if problems:
            lines.append("unrunnable: " + "; ".join(problems))
        summary = f"{len(steps)} steps, {missing} missing template(s)"
        self._log(f"  Route {map_name} / {act}: {summary}")
        for line in lines:
            self._log(f"    {line}")
        return (missing == 0 and not problems, summary + " — details in the log")

    def _test_run_route(self, target: tuple[str, str] | None = None) -> tuple[bool, str]:
        """Walk the saved route once, step by step, logging each result.

        Stops at the first failure rather than pressing on: the whole point of a
        route is that step N+1 only makes sense if step N landed.

        `target` is (event, act) for the Route tab's Test button, which tests the
        route being edited. Without it the Run strip's selection is used, which is
        what the Macro Tester row wants.
        """
        if target is None:
            map_name, act, error = self._route_selection()
            if error:
                return (False, error)
        else:
            map_name, act = target
        steps = self._routes.steps(map_name, act)
        if not steps:
            return (False, f"no route saved for {map_name} / {act}")
        problems = route_problems(steps)
        if problems:
            return (False, "route can't run: " + "; ".join(problems[:3]))

        ok, message = self._nav.click_events()
        self._log(f"  Events: {message}")
        if not ok:
            return (False, f"Events button: {message}")
        for position, step in enumerate(steps, start=1):
            if step.kind not in (KIND_FIND, KIND_EXPECT):
                time.sleep(self._nav.click_settle)
            ok, message = self._nav.run_route_step(step)
            self._log(f"  Route {position} ({step.summary()}): {message}")
            if not ok:
                return (False, f"step {position} failed: {message}")
        return (True, f"ran {len(steps)} steps for {map_name} / {act}")

    def _on_route_test(self, map_name: str, act: str) -> None:
        """Route tab > Test route: run that route once on a worker.

        Its own task rather than the Macro Tester's pool, because the tester window
        may not be open. Refused while the macro is running: two things driving
        input at once lands clicks on whatever screen the other one just changed.
        """
        editor = self._route_editor
        if self._runner.is_running or self._run_task is not None:
            editor.set_testing(False)
            editor.show_note("The macro is running — stop it first.", bad=True)
            return
        if self._route_task is not None:
            editor.show_note("This route is already running.", bad=True)
            return
        if self._roblox_hwnd is not None:
            rbx.activate_window(self._roblox_hwnd)
        self._log(f"Route test: running {map_name} / {act}.")
        editor.show_note(f"Running {map_name} / {act}...")

        task = Task(lambda: self._test_run_route((map_name, act)))
        task.setAutoDelete(False)
        self._route_task = task
        task.signals.done.connect(self._on_route_test_done)  # queued to the UI thread
        self._pool.start(task)

    def _on_route_test_done(self, ok: bool, message: str) -> None:
        self._route_task = None
        self._route_editor.set_testing(False)
        self._route_editor.show_note(message, bad=not ok)
        self._log(f"Route test: {message}")

    def _test_select_stage(self) -> tuple[bool, str]:
        stage = self._current_stage()
        if not stage:
            return (False, "no stage available")
        return self._nav.select_stage(self._current_gamemode(), stage)

    def _test_select_act(self) -> tuple[bool, str]:
        return self._nav.select_act(self._current_gamemode(), self._current_act())

    def _hard_mode_for(self, gamemode: str) -> bool:
        # Hard Mode is Story-only.
        return gamemode == "Story" and self._settings.get_hard_mode()

    def _test_start_stage(self) -> tuple[bool, str]:
        gamemode = self._current_gamemode()
        return self._nav.start_stage(gamemode, self._hard_mode_for(gamemode))

    def _test_set_difficulty(self) -> tuple[bool, str]:
        gamemode = self._current_gamemode()
        return self._nav.set_difficulty(
            gamemode, self._settings.get_expedition_difficulty()
        )

    def _test_run_to_stage(self) -> tuple[bool, str]:
        stage = self._current_stage()
        if not stage:
            return (False, "no stage available")
        return self._nav.run_to_stage(self._current_gamemode(), stage)

    def _test_run_and_start(self) -> tuple[bool, str]:
        target = self._ask_full_target()
        if target is None:
            return (False, "cancelled")
        gamemode, stage = target
        if is_custom(gamemode):
            return (False, f"{gamemode} navigates by a route — use the 'Run route' row")
        maps = maps_for(gamemode)
        if not maps:
            return (False, f"{gamemode} has no maps")
        if not stage:
            stage = random.choice(maps)
        elif stage not in maps:
            # The dialog can't offer a mismatched pair, but don't trust that a
            # coordinate/name reaching the navigator was built by the dialog.
            return (False, f"{stage} is not a {gamemode} map")
        acts = targets_for(gamemode, stage)
        act = random.choice(acts) if acts else ""
        hard = self._hard_mode_for(gamemode)
        difficulty = self._settings.get_expedition_difficulty()
        self._log(
            f"Full test target: {gamemode} / {stage} / {act or '(no act)'}"
            f"{' [hard]' if hard else ''}"
            f"{f' [difficulty {difficulty}]' if not has_targets(gamemode) else ''}."
        )

        # Lobby macro: ends once start_stage has waited out the join delay. A
        # gamemode with no act dimension skips straight from stage to start.
        if act:
            ok, message = self._nav.run_and_start(gamemode, stage, act, hard, difficulty)
        else:
            ok, message = self._nav.run_to_stage_and_start(
                gamemode, stage, hard, difficulty
            )
        if not ok:
            return (False, message)

        # Handover: confirm the stage is actually interactive before acting on it.
        # join_wait is a fixed guess; this waits for proof.
        ok, ready_message = self._nav.wait_for_match_ready()
        if not ok:
            return (False, f"started but not loaded: {ready_message}")

        # Match macro: the camera is the first in-stage step. Blocking, so the
        # chain can't report success while the camera is still moving.
        ok, camera_message = self._camera_setup(wait=True)
        if not ok:
            return (False, f"joined but camera failed: {camera_message}")
        return (True, f"{message} + camera set")

    def _ask_full_target(self) -> tuple[str, str] | None:
        """Ask for the Full run's gamemode and stage. Returns (gamemode, stage)
        where an empty stage means "pick one at random", or None if cancelled.

        Thread-safe: the Full test runs on a worker thread, but a Qt dialog must
        be created on the main thread — marshal it over and block until done.
        The marshal is a queued signal, not QTimer.singleShot: a timer started on
        a QThreadPool worker never fires (no event loop on that thread), which
        left the worker blocked forever and the test row stuck on "running".
        """
        if QThread.currentThread() is self.thread():
            return self._ask_full_target_impl()

        payload: dict[str, object] = {"box": {}, "done": threading.Event()}
        self.askFullTargetRequested.emit(payload)
        # Bounded wait: the UI thread could be blocked or the window closing, and
        # a test worker must never hang the pool for the rest of the session.
        if not payload["done"].wait(timeout=ASK_DIALOG_TIMEOUT):
            return None
        return payload["box"].get("target")

    def _on_ask_full_target_requested(self, payload: dict) -> None:
        """Runs on the UI thread (queued). Builds the dialog, then releases the
        waiting worker — even if the dialog raises, or it would wait out the
        full timeout."""
        try:
            payload["box"]["target"] = self._ask_full_target_impl()
        finally:
            payload["done"].set()

    def _ask_full_target_impl(self) -> tuple[str, str] | None:
        """Modal picker for the Full run test: gamemode plus an optional stage.
        The stage list follows the chosen gamemode, so it can only ever offer a
        stage that gamemode actually has."""
        parent = self._tester if (self._tester and self._tester.isVisible()) else self
        dialog = QDialog(parent)
        dialog.setObjectName("root")
        dialog.setWindowTitle("Full run target")
        dialog.setWindowFlags(
            dialog.windowFlags() | Qt.WindowType.WindowStaysOnTopHint
        )
        dialog.setMinimumWidth(300)
        box = QVBoxLayout(dialog)
        box.setContentsMargins(16, 14, 16, 14)
        box.setSpacing(8)

        label = QLabel("Pick a gamemode and stage. The act is chosen at random.")
        label.setStyleSheet(f"color: {theme.TEXT_DIM}; font-size: 12px;")
        label.setWordWrap(True)
        box.addWidget(label)

        mode_label = QLabel("GAMEMODE")
        mode_label.setObjectName("fieldLabel")
        box.addWidget(mode_label)
        mode_combo = QComboBox()
        # Table-driven gamemodes only: this dialog drives the Play -> card -> stage
        # -> act chain, which a custom gamemode replaces wholesale. Events is run
        # from the "Run route" tester row instead.
        chain_modes = [
            name
            for name in GAMEMODE_NAMES
            if not is_custom(name) and not is_side_task(name)
        ]
        mode_combo.addItems(chain_modes)
        if self._gamemode in chain_modes:
            mode_combo.setCurrentText(self._gamemode)
        box.addWidget(mode_combo)

        stage_label = QLabel("STAGE")
        stage_label.setObjectName("fieldLabel")
        box.addWidget(stage_label)
        stage_combo = QComboBox()
        box.addWidget(stage_combo)

        def refresh_stages() -> None:
            stage_combo.clear()
            stage_combo.addItem(RANDOM_STAGE_LABEL)
            stage_combo.addItems(maps_for(mode_combo.currentText()))

        mode_combo.currentTextChanged.connect(lambda _text: refresh_stages())
        refresh_stages()
        # Preselect whatever the Run page is pointing at, when it still applies.
        current_stage = self._current_stage()
        if current_stage and stage_combo.findText(current_stage) >= 0:
            stage_combo.setCurrentText(current_stage)

        chosen: dict[str, tuple[str, str] | None] = {"target": None}

        def accept() -> None:
            stage = stage_combo.currentText()
            chosen["target"] = (
                mode_combo.currentText(),
                "" if stage == RANDOM_STAGE_LABEL else stage,
            )
            dialog.accept()

        run = QPushButton("Run")
        run.setObjectName("primary")
        run.setFixedHeight(34)
        run.clicked.connect(accept)
        box.addWidget(run)

        cancel = QPushButton("Cancel")
        cancel.setFixedHeight(30)
        cancel.clicked.connect(dialog.reject)
        box.addWidget(cancel)

        dialog.exec()
        return chosen["target"]

    # # Macro Tester
    def _open_macro_tester(self) -> None:
        if self._tester is not None and self._tester.isVisible():
            self._tester.raise_()
            self._tester.activateWindow()
            return
        self._tester = MacroTesterWindow(
            self._build_tests(),
            on_select_image=self._on_select_image,
            on_test_search=self._run_image_search,
            get_image_path=self._active_image_path,
            get_rect=self._roblox_rect,
        )
        self._place_tester(self._tester)
        self._tester.show()
        self._tester.raise_()
        self._tester.activateWindow()
        self._log("Macro Tester opened.")

    def _place_tester(self, tester: QWidget) -> None:
        """Offset from the main window, clamped to the visible screen so the
        tester can't land off-screen when the main window sits near an edge."""
        screen = self.screen() or QApplication.primaryScreen()
        area = screen.availableGeometry()
        x = self.x() + 120
        y = self.y() + 90
        x = max(area.left(), min(x, area.right() - tester.width()))
        y = max(area.top(), min(y, area.bottom() - tester.height()))
        tester.move(x, y)

    def _build_tests(self) -> list[tuple[str, str, str, object]]:
        """Test cases for the Macro Tester. Steps that aren't implemented yet
        report that plainly instead of silently passing."""

        return [
            (
                "ENVIRONMENT",
                "Roblox window found",
                "Locate the Roblox game window",
                self._test_roblox_found,
            ),
            (
                "ENVIRONMENT",
                "Viewport positioned",
                f"Roblox client resized to {theme.VIEWPORT_WIDTH}x{theme.VIEWPORT_HEIGHT}",
                self._test_viewport_size,
            ),
            (
                "LOBBY MACRO",
                "Find Play",
                "Locate the Play button image (no click)",
                self._nav.find_play,
            ),
            (
                "LOBBY MACRO",
                "Click Play",
                "Find + click Play to open the intermission menu",
                self._nav.click_play,
            ),
            (
                "LOBBY MACRO",
                "Find Events",
                "Locate the lobby Events button image (no click)",
                self._nav.find_events,
            ),
            (
                "LOBBY MACRO",
                "Click Events",
                "Find + click Events to open the events list",
                self._nav.click_events,
            ),
            (
                "LOBBY MACRO",
                "Open gamemode",
                "Find + click the selected gamemode's card",
                self._test_open_gamemode,
            ),
            (
                "LOBBY MACRO",
                "Select stage",
                "Scroll to + click the selected stage",
                self._test_select_stage,
            ),
            (
                "LOBBY MACRO",
                "Select act",
                "Click the selected act at its fixed position",
                self._test_select_act,
            ),
            (
                "LOBBY MACRO",
                "Set difficulty",
                "Cycle the difficulty button to the Settings value (Expedition)",
                self._test_set_difficulty,
            ),
            (
                "LOBBY MACRO",
                "Start stage",
                "Hard mode (if on) + confirm + Start, then wait to join",
                self._test_start_stage,
            ),
            # CHALLENGE rows, in the order you'd use them. Every tip starts with where
            # you must be standing: a row that reads the wrong screen reports plausible
            # nonsense rather than failing, so the precondition *is* the instruction.
            (
                "CHALLENGE",
                "1. OCR ready?",
                "ANYWHERE. Starts the OCR engine and prints the raw text of each "
                "challenge box. Reads only. Run this first: it separates 'the OCR "
                "dependency is broken' from 'the boxes are wrong'.",
                self._test_ocr_ready,
            ),
            (
                "CHALLENGE",
                "2. Map challenge panel text",
                "STAND ON: the challenge list (lobby > Play > Challenges), three "
                "challenges visible. OCRs the whole client and logs every line with its "
                "client-space box. Reads only. This is where coordinates come from.",
                self._test_map_panel_text,
            ),
            (
                "CHALLENGE",
                "3. Dump challenge boxes",
                "STAND ON: the challenge list. Screenshots all ten measured boxes to "
                "images/challenge/debug so you can eyeball them. Reads only.",
                self._test_dump_challenge_boxes,
            ),
            (
                "CHALLENGE",
                "4. Scan challenges",
                "STAND ON: the challenge list. The real test — parses each row's limit "
                "and matches its map, logging both plus the raw text. Reads only. A pass "
                "needs all three rows read and identified.",
                self._test_scan_challenges,
            ),
            (
                "CHALLENGE",
                "5. Challenge leg: dry run",
                "STAND ON: the challenge list. Prints the points a challenge run WOULD "
                "click, and the last scan. Clicks nothing. Fails until the Start "
                "coordinate is measured.",
                self._test_challenge_leg_dry_run,
            ),
            (
                "VISION",
                "Geometry + capture report",
                "ANYWHERE, with Roblox running. Window/Roblox rects, mss monitors and a "
                "capture sanity check. Run it on each monitor to compare. Reads only.",
                self._test_geometry_report,
            ),
            (
                "LOBBY MACRO",
                "Check route templates",
                "List the selected Events route's steps and whether each image exists (no input)",
                self._test_route_templates,
            ),
            (
                "LOBBY MACRO",
                "Run route",
                "Run the selected Events route step by step (Events only)",
                self._test_run_route,
            ),
            (
                "MATCH MACRO",
                "Walk to position",
                "Run the Run-page target's start-position plan (Settings > Position)",
                self._test_position_moves,
            ),
            (
                "MATCH MACRO",
                "Already in a match?",
                "One look for Start Game — decides whether F1 skips the lobby chain",
                self._test_in_match,
            ),
            (
                "MATCH MACRO",
                "Stage loaded (Start Game)",
                "Wait for the in-match Start Game button — proves the stage is up",
                self._test_match_ready,
            ),
            (
                "MATCH MACRO",
                "Set camera position",
                "Zoom in (hold I), pitch camera down, zoom out (hold O) via AHK",
                self._test_camera,
            ),

            (
                "MATCH MACRO",
                "Click Start Game",
                "Find + click the in-match Start Game button (starts the wave)",
                self._nav.click_start_game,
            ),
            (
                "MATCH MACRO",
                "Unit panel opens",
                "Click the first enabled step's coordinate and confirm unit_ui.png",
                self._test_unit_panel,
            ),
            (
                "MATCH MACRO",
                "Run first unit step",
                "Wait, place, then priority / upgrades / sell for the first step",
                self._test_first_step,
            ),
            (
                "MATCH MACRO",
                "Auto upgrade step",
                "Open the first step's unit panel and press Auto Upgrade once (it cycles 1-6, 7 = off)",
                self._test_autoupgrade,
            ),
            (
                "MATCH MACRO",
                "Pre-placement order",
                "Show which steps run before Start Game and which after (no input)",
                self._test_preplacement_order,
            ),
            (
                "MATCH MACRO",
                "Wait for win",
                "Park + keep-alive clicks until game_won.png appears",
                self._test_wait_for_win,
            ),
            # Composite chain last: it spans both sections above, so it isn't
            # part of either. Groups render in list order.
            (
                "FULL RUN",
                "Full: lobby -> join -> camera",
                "Play, mode, stage, act, start, wait to join, then set the camera",
                self._test_run_and_start,
            ),
        ]

    def _camera_setup(self, wait: bool) -> tuple[bool, str]:
        """Run the camera sequence. `wait=True` blocks until AHK exits, which is
        what a chain needs — the script takes ~8s (two 3s zoom holds plus the
        pitch drag), and anything that clicks before it finishes is acting on a
        camera that is still moving. Fire-and-forget is only safe standalone."""
        if not self._ahk.available():
            return (False, "AutoHotkey v2 not found")
        if wait and self._camera_is_set and self._settings.get_camera_once():
            # Opt-in only. Skipping is worth ~8s a match, but placement coordinates are
            # stored against one camera angle, so if Roblox *does* reset the camera on a
            # stage load this silently misplaces every unit — a far worse failure than a
            # slow start. Hence the default is off and the user turns it on knowingly.
            return (True, "skipped — camera already set this session (Settings > Main)")
        hwnd = rbx.find_roblox_window()
        if hwnd is None:
            return (False, "Roblox not found")
        size = rbx.client_size(hwnd)
        center = rbx.client_to_screen(hwnd, size[0] // 2, size[1] // 2) if size else None
        if center is None:
            return (False, "could not read Roblox position")
        # Seconds in the store (the whole Delays tab is seconds), milliseconds in the script.
        zoom_ms = int(float(self._delays.get("camera_zoom", 3.0)) * 1000)
        script = camera_setup_script(center[0], center[1], zoom_ms=zoom_ms)
        ok, message = self._ahk.run(script, wait=wait, timeout=CAMERA_TIMEOUT)
        if not ok:
            return (False, message)
        if wait:
            # Only a blocking run proves the sequence finished. A fire-and-forget one is
            # still moving the camera as this returns, so it must not count as "set".
            self._camera_is_set = True
        return (True, "camera set" if wait else "sequence started — watch Roblox")

    def _test_camera(self) -> tuple[bool, str]:
        # Standalone row: don't block, so you can watch Roblox while it runs.
        return self._camera_setup(wait=False)

    def _first_enabled_step(self) -> tuple[UnitStep | None, str]:
        steps = self._plan.enabled_steps()
        if not steps:
            return (None, "no enabled unit steps — set a step's coordinates first")
        return (steps[0], "")

    def _test_unit_panel(self) -> tuple[bool, str]:
        step, error = self._first_enabled_step()
        if step is None:
            return (False, error)
        if step.is_sequence():
            return (False, f"step {step.step} is a sequence, not a unit")
        return self._placer.open_unit_panel(int(step.x or 0), int(step.y or 0))

    def _test_first_step(self) -> tuple[bool, str]:
        step, error = self._first_enabled_step()
        if step is None:
            return (False, error)
        return self._placer.run_step(step)

    def _test_autoupgrade(self) -> tuple[bool, str]:
        """Proves the auto upgrade key reaches the unit panel. One press only: the
        panel's control cycles, so each run steps it up a level and the seventh
        brings it back to off — which is also how a step's Auto upgrade level is
        reached (N presses = level N)."""
        step, error = self._first_enabled_step()
        if step is None:
            return (False, error)
        if step.is_sequence():
            return (False, f"step {step.step} is a sequence, not a unit")
        ok, message = self._placer.open_unit_panel(int(step.x or 0), int(step.y or 0))
        if not ok:
            return (False, message)
        key = self._game_keys.get("autoupgrade", "")
        ok, message = self._placer.press_game_key("autoupgrade")
        if not ok:
            return (False, message)
        return (
            True,
            f"sent '{key}' once to the unit panel — check which auto level it landed on",
        )

    def _test_preplacement_order(self) -> tuple[bool, str]:
        """Pure ordering check: no clicks, no keys. Reports what a run would do."""
        enabled = self._plan.enabled_steps()
        if not enabled:
            return (False, "no enabled unit steps")
        pre, during = split_steps(enabled)
        before = ", ".join(str(step.step) for step in pre) or "none"
        after = ", ".join(str(step.step) for step in during) or "none"
        return (True, f"before Start Game: {before} | after: {after}")

    def _test_wait_for_win(self) -> tuple[bool, str]:
        # Short budget standalone: it answers now, rather than idling for the full
        # in-run timeout while you watch a test row say "running".
        return self._placer.wait_for_win(timeout=WIN_TEST_TIMEOUT)

    def _test_match_ready(self) -> tuple[bool, str]:
        # Short budget standalone: run it in a stage and it answers at once,
        # rather than sitting there for the full chain-length timeout.
        return self._nav.wait_for_match_ready(timeout=MATCH_READY_TEST_TIMEOUT)

    def _test_position_moves(self) -> tuple[bool, str]:
        """Walks the character, so it only makes sense inside a loaded stage."""
        gamemode, map_name, act = self._run_page.selection()
        if not map_name:
            return (False, "select a Map on the Run page first")
        moves = self._position_store.moves(gamemode, map_name, act)
        if not [move for move in moves if move.is_actionable()]:
            where = " / ".join(part for part in (gamemode, map_name, act) if part)
            return (True, f"{where} has no start-position plan — nothing to run")
        return self._placer.run_moves(moves)

    def _test_in_match(self) -> tuple[bool, str]:
        """Both answers are a pass: this row reports which path F1 would take."""
        if self._nav.in_match():
            return (True, "in a match — F1 would skip the lobby and set the camera")
        return (True, "not in a match — F1 would run the full lobby chain")

    def _test_roblox_found(self) -> tuple[bool, str]:
        hwnd = rbx.find_roblox_window()
        if hwnd is None:
            return (False, "not found - is Roblox running?")
        return (True, f"hwnd {hwnd}")

    def _test_viewport_size(self) -> tuple[bool, str]:
        hwnd = self._viewport.attached_hwnd()
        if hwnd is None:
            return (False, "Roblox not attached")
        size = rbx.client_size(hwnd)
        if size is None:
            return (False, "could not read client size")
        expected = (theme.VIEWPORT_WIDTH, theme.VIEWPORT_HEIGHT)
        if size != expected:
            return (False, f"{size[0]}x{size[1]}, expected {expected[0]}x{expected[1]}")
        return (True, f"{size[0]}x{size[1]}")

    # # Hotkeys
    def _poll_hotkeys(self) -> None:
        # Start and stop are separate keys. The start key on a running macro says so
        # rather than stopping it, which is the mistake a single toggle invites.
        self._edge("start_stop", lambda: self._start_macro("hotkey"))
        self._edge("stop", lambda: self._stop_macro("hotkey"))
        self._edge("reload", self._trigger_reload)
        self._edge("open_tester", self._open_macro_tester)
        # No runner.tick() here on purpose: the run loop lives on a worker thread
        # (see _run_loop). Ticking from this 40ms timer would block the UI for the
        # length of every AHK step, including the F1 that stops it.

    def _edge(self, action: str, fire) -> None:
        """Rising-edge detect a keybind and fire once per press."""
        down = self._keybind_pressed(self._keybinds[action])
        if down and not self._kb_down[action]:
            fire()
        self._kb_down[action] = down

    @staticmethod
    def _keybind_pressed(kb: Keybind) -> bool:
        if not is_key_down(kb.vk):
            return False
        if kb.ctrl and not is_key_down(VK_CONTROL):
            return False
        if kb.shift and not is_key_down(VK_SHIFT):
            return False
        if kb.alt and not is_key_down(VK_MENU):
            return False
        return True

    def _trigger_reload(self) -> None:
        self._log("Reloading...")
        QTimer.singleShot(25, self._restart)

    def _on_keybind_changed(self, action: str, keybind: Keybind) -> None:
        self._keybinds[action] = keybind
        self._keybind_store.set(action, keybind)
        self._titlebar.set_hints(self._hint_texts())
        self._log(f"Rebound {ACTIONS.get(action, action)} to {keybind.display()}.")

    def _on_expedition_difficulty_changed(self, value: int) -> None:
        self._settings.set_expedition_difficulty(value)
        self._log(f"Expedition difficulty set to {value}.")

    def _on_game_key_changed(self, action: str, key: str) -> None:
        # Rejected silently while the field is empty or mid-edit; only a valid
        # single character is stored, so a half-typed value can't reach AHK.
        if not self._game_key_store.set(action, key):
            return
        self._game_keys[action] = self._game_key_store.get(action)
        self._log(f"{GAME_ACTIONS.get(action, action)} key set to '{self._game_keys[action]}'.")

    def _hint_texts(self) -> list[str]:
        short = {
            "start_stop": "Start",
            "stop": "Stop",
            "reload": "Reload",
            "open_tester": "Tester",
        }
        return [
            f"{self._keybinds[a].display()} · {short[a]}"
            for a in ("start_stop", "stop", "reload", "open_tester")
        ]

    def _restart(self) -> None:
        """F3. Re-exec the app in place, so a code edit takes effect without re-attaching
        Roblox by hand.

        Frozen, `sys.executable` is `SloppyKeys.exe` and there is no `-m` to give it — the
        module form would have made F3 kill the app and fail to start it again. Untested in
        a build; it is the only sensible reading of `execl` for a onedir exe.
        """
        self._viewport.teardown()
        if getattr(sys, "frozen", False):
            os.execl(sys.executable, sys.executable, *sys.argv[1:])
        os.execl(sys.executable, sys.executable, "-m", "sloppykeys", *sys.argv[1:])

    def changeEvent(self, event) -> None:
        """Re-assert the fixed size when coming back from minimized.

        Restoring a frameless, always-on-top window on Windows can hand back a
        larger size than the fixed one — measured 886 -> 1085 with the window's
        own minimum and maximum both 886, and every layout minimum unchanged. Qt
        applies that restored geometry over setFixedSize, which stretched the page
        and pushed the run strip below the window edge. Nothing in the layout is
        at fault, so the correction belongs here rather than in the layout.
        """
        super().changeEvent(event)
        if event.type() is QEvent.Type.WindowStateChange and not self.isMinimized():
            # Twice on purpose: now, so the wrong size is never painted, and again
            # deferred, because Qt can apply the restored geometry after this event
            # is delivered (measured: without the deferred pass the first restore
            # still came back 1085).
            self._enforce_window_size()
            QTimer.singleShot(0, self._enforce_window_size)

    def resizeEvent(self, event) -> None:
        """Catch the restored-too-large geometry where it actually arrives.

        Windows applies it *after* the state-change event, so correcting only in
        changeEvent left the first restore at 1085. Snapping back here catches
        every route. Safe from looping: the corrective resize produces one more
        resizeEvent whose size already matches, which stops.
        """
        super().resizeEvent(event)
        if not self.isMinimized() and self.size() != QSize(
            theme.WINDOW_WIDTH, theme.WINDOW_HEIGHT
        ):
            QTimer.singleShot(0, self._enforce_window_size)

    def _enforce_window_size(self) -> None:
        if self.isMinimized():
            return
        expected = QSize(theme.WINDOW_WIDTH, theme.WINDOW_HEIGHT)
        if self.size() != expected:
            self.resize(expected)
        # The mask is built from the window rect, and Roblox sits behind the hole,
        # so both have to be re-derived after any size correction.
        self._apply_window_mask()
        self._viewport.reposition()

    # # Window events
    def showEvent(self, event) -> None:
        """Assert the fixed size once, after the native window exists.

        On the user's machine Qt logs, at startup only:
          `Unable to set geometry 1690x1004 ... Resulting geometry: 1690x1098`
        — the same 1098 whether we ask for 886 or 1004, so it is an absolute value Windows
        hands back at creation, not a function of our size. It is **not** the layout:
        `minimumSizeHint()` measures exactly 1690x1004, and Qt's own MINMAXINFO in that
        message already carries the right min and max. Four probe variations (bare widget
        with the same flags, plain window, shorter window, and the real `MainWindow` with
        the app stylesheet applied exactly as `run()` does) all produced the correct size,
        so the cause is **unreproduced** in isolation.

        This is therefore a deliberate patch of the symptom, not the cause: re-assert the
        size the moment the native window exists, so nothing is painted at a size Windows
        invented. Deferred as well as immediate, because Windows can apply its own geometry
        after this event — the same reason `changeEvent` does it twice.

        No `screenChanged` hook here. One existed and re-ran this on every monitor move; it
        caused window glitches and never fixed the drag ghost it was written for (that was
        `DragFullWindows = 0` — see `TitleBar.mousePressEvent`).
        """
        super().showEvent(event)
        self._enforce_window_size()
        QTimer.singleShot(0, self._enforce_window_size)

    def moveEvent(self, event) -> None:
        # Keep Roblox glued to the viewport hole while the window is dragged.
        self._viewport.reposition()
        super().moveEvent(event)

    def closeEvent(self, event) -> None:
        # Ask the worker to stop rather than calling runner.stop() here: the loop
        # owns the runner's state, and clearing its steps from the UI thread
        # mid-tick is a race. The pool would block on destruction anyway, so wait
        # with a bound instead of indefinitely.
        self._runner.request_stop()
        if self._run_task is not None:
            self._pool.waitForDone(CLOSE_WAIT_MS)
        self._viewport.teardown()
        # The tester is its own top-level window; without this it keeps the app alive.
        if self._tester is not None:
            self._tester.close()
            self._tester = None
        super().closeEvent(event)


def _panel(widget: QWidget) -> QWidget:
    """Wrap a page in a bordered, rounded panel card."""
    panel = QWidget()
    panel.setObjectName("page")
    box = QVBoxLayout(panel)
    box.setContentsMargins(0, 0, 0, 0)
    box.addWidget(widget)
    return panel


def _title_button(glyph: str, on_click, danger: bool) -> QLabel:
    button = QLabel(glyph)
    # Shorter than the card it sits in, so its hover fill can't square off the card's
    # rounded corners. It used to be the full strip height, when the strip had no card.
    button.setFixedSize(38, theme.TITLEBAR_CARD_HEIGHT - 8)
    button.setAlignment(Qt.AlignmentFlag.AlignCenter)
    hover = theme.BAD if danger else theme.TEXT
    base = f"font-family: '{theme.ICON_FAMILY}'; font-size: 13px; color: {theme.TEXT_DIM};"
    button.setStyleSheet(base)
    button.setCursor(Qt.CursorShape.PointingHandCursor)

    def enter(_e):
        button.setStyleSheet(base.replace(theme.TEXT_DIM, hover))

    def leave(_e):
        button.setStyleSheet(base)

    def press(_e):
        on_click()

    button.enterEvent = enter
    button.leaveEvent = leave
    button.mousePressEvent = press
    return button


def resolve_app_root() -> str:
    """Where the user's data lives: `images/`, `configs/`, `settings.json`, `log.txt`.

    Frozen (PyInstaller), `__file__` points inside the bundle — read-only, and wiped on
    every launch of a onefile build — so the data has to be resolved from the **exe's own
    folder** instead. Running from source it is the project root, three levels up from this
    module. Getting this wrong doesn't crash: it silently reads an empty `images/` and looks
    like every template is missing.
    """
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _install_crash_log(app_root: str) -> None:
    """Append unhandled exceptions to `crash.txt` next to the app.

    A windowed build has no console, so a traceback from a Qt timer or a worker would go
    nowhere and the app would just vanish. `log.txt` only carries what the app chose to
    log — this catches what it didn't survive. Chained to the existing hook rather than
    replacing it, so a console build still prints as before.
    """
    previous = sys.excepthook

    def hook(kind, value, trace) -> None:
        try:
            with open(os.path.join(app_root, "crash.txt"), "a", encoding="utf-8") as handle:
                handle.write(f"\n=== {datetime.now():%Y-%m-%d %H:%M:%S} ===\n")
                traceback.print_exception(kind, value, trace, file=handle)
        except OSError:
            pass
        previous(kind, value, trace)

    sys.excepthook = hook


def run() -> None:
    app_root = resolve_app_root()
    _install_crash_log(app_root)
    # Render at true 1:1 pixels. The viewport must be an exact physical size for
    # image matching against Roblox, and DPI scaling would blow the fixed window
    # past the screen on a scaled display. Must be set before QApplication.
    os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "0")
    os.environ.setdefault("QT_SCALE_FACTOR", "1")
    app = QApplication(sys.argv)
    app.setStyleSheet(theme.stylesheet())
    window = MainWindow(app_root)
    window.show()
    sys.exit(app.exec())
