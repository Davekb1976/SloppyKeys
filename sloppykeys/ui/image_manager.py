"""Image Manager: every template the macro looks for, and a one-click re-capture.

Why it exists: `cv2.matchTemplate` is not scale invariant, so a template has to be the
same pixel size as the live client. Changing the viewport (or the game patching its UI)
invalidates the whole `images/` tree at once, and the only reliable fix is re-cropping
from the pixels the matcher actually reads. Before this, that meant dumping the client,
opening an editor, cropping by eye and saving to the right filename — per image.

Here: pick a row, drag a box on the game, done. The crop is taken with
`ImageSearchEngine.capture_png` on the dragged box offset by the client origin — the same
mss path `find_until` matches against — and written straight over that template's path.
No editor, no filename to get right, and no chance of a wrong-scale crop.

The catalog is derived from `content/nav_images.py`, not hand-maintained, so a template
added to the schema shows up here on its own.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Callable

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QAbstractSpinBox,
    QDoubleSpinBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from sloppykeys.core.image_search import (
    CONFIDENCE_MAX,
    CONFIDENCE_USER_MIN,
    DEFAULT_CONFIDENCE,
    apply_confidence_overrides,
    best_score,
    confidence_for,
    confidence_key,
)

from ..content import acts, challenge, start_stage
from ..content import nav_images as nav
from ..content.gamemodes import EVENTS, GAMEMODES
from . import icons, theme
from .macro_tester import RegionOverlay
from .placement_overlay import reference_path

# Anything smaller than this a side is a misdrag, not a template: matching needs
# actual edge content to correlate against.
MIN_BOX = 4
# The overlay was covering Roblox a moment ago. Give the desktop a beat to repaint or
# the crop catches the picker instead of the game.
REPAINT_MS = 150
# Row widths. The whole row has to fit the right-hand panel (`theme.PANEL_MIN_WIDTH` is
# 400, minus the Settings page margins and the scrollbar), so the two fixed columns are
# deliberately small and the text column is what flexes. Thumbnails draw at their true
# pixel size when they fit, so a wrong-size template is visible as one.
THUMB_W = 58
THUMB_H = 30
# Measured: "Capture" needs 81px at `#rowAction`'s font and padding.
BUTTON_W = 84


@dataclass(frozen=True)
class TemplateEntry:
    """One row: a display name and the app-root-relative path it is stored at.

    `full_client` marks a map picture rather than a search template: it is the whole
    playfield used as the placement picker's backdrop, so there is nothing to drag —
    Capture saves the entire client view.
    """

    group: str
    name: str
    path: str
    note: str = ""
    full_client: bool = False


# Gamemodes whose acts each need their own picture. Story's acts share one playfield, so
# it keeps a single file per map; a Raid map's acts are separate areas of that map, and an
# event's acts are separate stages. `load_reference` falls back to the per-map file, so an
# existing per-map picture keeps working either way. Challenge has no rows: it borrows the
# Story picture of the same map.
PER_ACT_MAPS = ("Raid", "Events")
MAP_IMAGE_MODES = ("Story", "Raid", "Expedition", "Events")


def map_image_catalog(
    route_targets: list[tuple[str, str]] | None = None,
) -> list[TemplateEntry]:
    """The placement backdrops — `images/reference/**`, one row per target.

    Events comes from the route store rather than `GAMEMODES` (its events and acts are
    user-authored), so it is passed in as (event, act) pairs.
    """
    entries: list[TemplateEntry] = []
    for name in MAP_IMAGE_MODES:
        gamemode = GAMEMODES.get(name)
        if gamemode is None:
            continue
        group = f"{name} map images"
        if name == EVENTS:
            pairs = route_targets or []
        elif name in PER_ACT_MAPS:
            pairs = [(stage, act) for stage in gamemode.maps for act in gamemode.targets]
        else:
            pairs = [(stage, "") for stage in gamemode.maps]
        for stage, act in pairs:
            path = reference_path(nav.IMAGES_DIR, name, stage, act)
            if path is None:
                continue
            label = f"{stage} · {act}" if act else stage
            entries.append(TemplateEntry(group, label, path, full_client=True))
    return entries


def catalog(route_targets: list[tuple[str, str]] | None = None) -> list[TemplateEntry]:
    """Every image the macro looks at, grouped for display.

    Built from the same functions the navigator calls, so this can't drift from what is
    actually looked for. The in-match menu images are included even though the run chain
    doesn't click them yet — they are real files people have to maintain.
    """
    entries: list[TemplateEntry] = [
        TemplateEntry("Lobby", "Play", nav.play_image(), "opens the gamemode menu"),
        TemplateEntry("Lobby", "Events", nav.events_image(), "the lobby Events button"),
        TemplateEntry(
            "Lobby",
            "Select stage",
            nav.select_stage_image(),
            "clicked before Start — it is what makes Start appear",
        ),
        TemplateEntry(
            "Lobby",
            "Start match",
            nav.start_match_image(),
            "moves per stage, so it is searched not clicked",
        ),
    ]
    for name, gamemode in GAMEMODES.items():
        if gamemode.custom:
            continue
        entries.append(
            TemplateEntry("Gamemode cards", name, nav.gamemode_image(name))
        )
    for name, gamemode in GAMEMODES.items():
        if gamemode.custom or gamemode.side_task:
            continue
        for stage in gamemode.maps:
            entries.append(
                TemplateEntry(f"{name} stages", stage, nav.stage_image(name, stage))
            )
    entries += [
        TemplateEntry("In match", "Start Game", nav.start_game_image(), "proves the stage loaded"),
        TemplateEntry("In match", "Unit panel", nav.unit_ui_image(), "proves a unit click selected"),
        TemplateEntry("In match", "Won", nav.game_won_image(), "the victory screen's text"),
        TemplateEntry("In match", "Lost", nav.game_lost_image()),
        TemplateEntry(
            "In match",
            "Repeat",
            nav.repeat_image(),
            "clicked after a win, before Start Game returns",
        ),
        TemplateEntry(
            "In match",
            "Change gamemode",
            nav.win_change_image(),
            "on the panel a finished match leaves you on",
        ),
        TemplateEntry("In-match menu", "Back to lobby", nav.back_lobby_image()),
        TemplateEntry("In-match menu", "Confirm return", nav.return_lobby_confirm_image()),
        TemplateEntry("In-match menu", "Settings", nav.settings_image()),
        TemplateEntry("In-match menu", "Restart game", nav.restart_game_image()),
        TemplateEntry("In-match menu", "Play (in match)", nav.match_play_image()),
    ]
    entries += map_image_catalog(route_targets)
    return entries


class TemplateRow(QFrame):
    """One template: thumbnail, name, pixel size, Capture, and its match threshold.

    The threshold and its Test button only exist for a *searched* template. A map picture
    (`full_client`) is the placement picker's backdrop and is never matched, so a tolerance
    there would be a control that does nothing.
    """

    captureRequested = Signal(object)  # TemplateEntry
    thresholdChanged = Signal(object, float)  # TemplateEntry, value
    testRequested = Signal(object)  # TemplateEntry

    def __init__(self, entry: TemplateEntry, app_root: str) -> None:
        super().__init__()
        self._entry = entry
        self._app_root = app_root
        self._loading = False
        self.setObjectName("statCard")

        row = QHBoxLayout(self)
        row.setContentsMargins(8, 6, 8, 6)
        row.setSpacing(10)

        self._thumb = QLabel()
        self._thumb.setFixedSize(THUMB_W, THUMB_H)
        self._thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
        row.addWidget(self._thumb)

        # Both labels get setMinimumWidth(1) so neither can push the row wider than the
        # panel. Without it a long name or note becomes the row's minimum width, the row
        # becomes the list's, and Qt's answer to a fixed panel it can't fit is to paint the
        # children past its edge — which cut the Capture button in half. Same fix as
        # `RunPage`'s status label.
        text = QVBoxLayout()
        text.setSpacing(1)
        self._name = QLabel(entry.name)
        self._name.setStyleSheet(f"color: {theme.TEXT}; font-size: 12px; font-weight: 600;")
        self._name.setMinimumWidth(1)
        self._status = QLabel()
        self._status.setWordWrap(True)
        self._status.setMinimumWidth(1)
        text.addWidget(self._name)
        text.addWidget(self._status)
        row.addLayout(text, 1)

        # One stable label. It used to swap Capture/Recapture, which changed the button's
        # width and so the row's — the status line already says whether a file is there.
        self._capture = QPushButton("Capture")
        self._capture.setObjectName("rowAction")
        self._capture.setFixedSize(BUTTON_W, 26)
        self._capture.setToolTip(
            "Saves the whole current Roblox view as this map's picture — stand in the "
            "match, camera set, then click."
            if entry.full_client
            else "Drag a box on the Roblox window. The crop is taken from the same pixels "
            "the matcher reads and overwrites this template."
        )
        self._capture.clicked.connect(lambda: self.captureRequested.emit(entry))

        # Right-hand column rather than one long row: three controls side by side would make
        # the row wider than the panel, and Qt's answer to that is to paint past the edge
        # (see the note above). Everything here stays inside `BUTTON_W`.
        actions = QVBoxLayout()
        actions.setSpacing(3)
        actions.addWidget(self._capture)
        if not entry.full_client:
            tune = QHBoxLayout()
            tune.setSpacing(3)
            self._threshold = QDoubleSpinBox()
            self._threshold.setRange(CONFIDENCE_USER_MIN, CONFIDENCE_MAX)
            self._threshold.setSingleStep(0.01)
            self._threshold.setDecimals(2)
            # **No arrows.** The whole right-hand column must fit `BUTTON_W`, and Qt gives
            # the up/down buttons ~16px out of the field's width — which is what clipped
            # "0.70" to "0.7(". Typing and the scroll wheel both still work, and the tooltip
            # says so. Centred, because a 4-character value in a left-aligned field next to
            # a button looked unfinished.
            self._threshold.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
            self._threshold.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._threshold.setFixedSize(56, 22)
            # Tight padding, overriding the theme's roomier spinbox rule. Between the arrows
            # and that padding the field had ~32px of the 48 for four characters, which is
            # what clipped "0.70" to "0.7(" — the arrows were only half of it.
            self._threshold.setStyleSheet("padding: 0px 2px;")
            self._threshold.setToolTip(
                f"How closely this one template must match ({DEFAULT_CONFIDENCE:.2f} by "
                f"default, floor {CONFIDENCE_USER_MIN:.2f}). Type it or scroll the wheel "
                "over it.\n\nPress the crosshair first: lowering this below a real score "
                "makes the wrong screen match, which is a worse failure than a missed one."
            )
            self._threshold.valueChanged.connect(self._on_threshold)
            # A glyph, not the word "Test": the whole right-hand column has to stay inside
            # `BUTTON_W`, and 54px of spin leaves 27 — which elides "Test" to nothing.
            # Segoe Fluent Icons ships with Windows (`ui/icons.py`), and the tooltip carries
            # the meaning, so this is not an emoji-as-affordance.
            self._test = QPushButton(icons.CROSSHAIR)
            self._test.setObjectName("rowAction")
            # Same height as the spin beside it: mismatched heights were half of why this
            # pair looked wrong. 56 + 3 + 25 = BUTTON_W exactly, so the column still fits.
            self._test.setFixedSize(BUTTON_W - 59, 22)
            self._test.setStyleSheet(f"font-family: '{theme.ICON_FAMILY}'; padding: 0px;")
            self._test.setToolTip(
                "Match this template against the Roblox window right now and report the "
                "best score — the number to set the threshold against."
            )
            self._test.clicked.connect(lambda: self.testRequested.emit(entry))
            tune.addWidget(self._threshold)
            tune.addWidget(self._test)
            actions.addLayout(tune)
        row.addLayout(actions)

        self.refresh()

    def set_threshold(self, value: float) -> None:
        """Show the stored (or default) threshold without echoing back as an edit."""
        if self._entry.full_client:
            return
        self._loading = True
        self._threshold.setValue(float(value))
        self._loading = False

    def _on_threshold(self, value: float) -> None:
        if self._loading:
            return
        self.thresholdChanged.emit(self._entry, float(value))

    @property
    def entry(self) -> TemplateEntry:
        return self._entry

    def refresh(self) -> None:
        """Re-read the file from disk and redraw size + thumbnail."""
        absolute = os.path.join(self._app_root, self._entry.path)
        pixmap = QPixmap(absolute)
        if pixmap.isNull():
            self._thumb.clear()
            self._thumb.setText("—")
            self._thumb.setStyleSheet(f"color: {theme.TEXT_FAINT}; font-size: 14px;")
            self._status.setText(f"missing · {self._entry.path}")
            self._status.setStyleSheet(f"color: {theme.WARN}; font-size: 10px;")
            return
        self._thumb.setStyleSheet("")
        shown = pixmap
        if pixmap.width() > self._thumb.width() or pixmap.height() > self._thumb.height():
            shown = pixmap.scaled(
                self._thumb.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        self._thumb.setPixmap(shown)
        detail = f"{pixmap.width()}x{pixmap.height()}px"
        if self._entry.note:
            detail += f" · {self._entry.note}"
        self._status.setText(detail)
        self._status.setStyleSheet(f"color: {theme.TEXT_FAINT}; font-size: 10px;")


class GeometryRow(QFrame):
    """One measured value: label, current value, whether it's a default, Set and Reset.

    Serves both an OCR box `(x, y, w, h)` and a click point `(x, y)` — same store shape,
    same two buttons, and the tuple length says which it is.
    """

    setRequested = Signal(str)
    clearRequested = Signal(str)

    def __init__(self, key: str, label: str, default: tuple[int, ...]) -> None:
        super().__init__()
        self._key = key
        self._default = default
        self._is_point = len(default) == 2
        self.setObjectName("statCard")

        row = QHBoxLayout(self)
        row.setContentsMargins(8, 6, 8, 6)
        row.setSpacing(8)

        text = QVBoxLayout()
        text.setSpacing(1)
        self._label = QLabel(label)
        self._label.setStyleSheet(f"color: {theme.TEXT}; font-size: 12px; font-weight: 600;")
        self._label.setMinimumWidth(1)
        self._value = QLabel()
        self._value.setWordWrap(True)
        self._value.setMinimumWidth(1)
        text.addWidget(self._label)
        text.addWidget(self._value)
        row.addLayout(text, 1)

        self._set = QPushButton("Pick" if self._is_point else "Set")
        self._set.setObjectName("rowAction")
        self._set.setFixedSize(46, 26)
        self._set.setToolTip(
            "Click the exact pixel on the Roblox window."
            if self._is_point
            else "Drag the box on the Roblox window."
        )
        self._set.clicked.connect(lambda: self.setRequested.emit(key))
        row.addWidget(self._set, 0, Qt.AlignmentFlag.AlignVCenter)

        self._clear = QPushButton("Reset")
        self._clear.setObjectName("rowAction")
        self._clear.setFixedSize(58, 26)
        self._clear.setToolTip("Go back to the built-in value.")
        self._clear.clicked.connect(lambda: self.clearRequested.emit(key))
        row.addWidget(self._clear, 0, Qt.AlignmentFlag.AlignVCenter)

    @property
    def key(self) -> str:
        return self._key

    def show_value(self, value: tuple[int, ...] | None) -> None:
        """`value` is the override, or None when the default is in force.

        "custom" means **actually different from the default**, not merely "an override
        exists". Several points were stored at exactly their default values (they were
        promoted into `content/` from this user's own picks), so every one of them read
        "custom" while clicking the same pixel as the built-in — which looks like the app
        having quietly changed something. Reset stays enabled whenever an override exists,
        because removing it is still a real action.
        """
        current = value or self._default
        differs = value is not None and tuple(value) != tuple(self._default)
        shown = (
            f"{current[0]}, {current[1]}"
            if self._is_point
            else f"{current[0]},{current[1]}  {current[2]}x{current[3]}"
        )
        self._value.setText(f"{shown} · {'custom' if differs else 'default'}")
        self._value.setStyleSheet(
            f"color: {theme.CYAN if differs else theme.TEXT_FAINT}; font-size: 10px;"
        )
        self._clear.setEnabled(value is not None)


class ImageManager(QWidget):
    """The Settings > Vision tab: every image, OCR box and click point the macro uses.

    Owns no capture logic of its own beyond the drag: the pixels come from the engine
    that does the matching, which is the whole point — a template captured any other way
    can be the wrong scale and then never matches at any confidence.

    Four inner tabs rather than one long list: 39 image rows plus 10 boxes plus 14 points is
    far more than the right-hand panel can show, and a single scroll buried the boxes and
    points several screens down.
    """

    TABS = ("Templates", "Map images", "Boxes", "Points")

    def __init__(
        self,
        app_root: str,
        get_rect: Callable[[], tuple[int, int, int, int] | None],
        engine,
        log: Callable[[str], None],
        regions=None,
        routes=None,
        points=None,
        confidence=None,
    ) -> None:
        super().__init__()
        self._app_root = app_root
        self._get_rect = get_rect
        self._engine = engine
        self._log = log
        self._regions = regions
        self._routes = routes
        self._points = points
        self._confidence = confidence
        self._overlay: RegionOverlay | None = None
        self._rows: list[TemplateRow] = []
        self._region_rows: list[GeometryRow] = []
        self._point_rows: list[GeometryRow] = []

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(6)

        head = QHBoxLayout()
        head.setSpacing(6)
        intro = QLabel(
            f"Measured at the pinned {theme.VIEWPORT_WIDTH}x{theme.VIEWPORT_HEIGHT} client "
            f"size — nothing here is valid at another one."
        )
        intro.setWordWrap(True)
        intro.setMinimumWidth(1)
        intro.setStyleSheet(f"color: {theme.TEXT_DIM}; font-size: 11px;")
        head.addWidget(intro, 1)
        head.addWidget(
            self._icon_button(
                icons.REFRESH, "Re-read every file and rebuild the list", self.refresh
            )
        )
        head.addWidget(
            self._icon_button(icons.IMAGE, "Open the images folder", self._open_folder)
        )
        root.addLayout(head)

        self._note = QLabel("")
        self._note.setWordWrap(True)
        self._note.setMinimumWidth(1)
        self._note.setStyleSheet(f"color: {theme.TEXT_FAINT}; font-size: 11px;")
        root.addWidget(self._note)

        bar = QHBoxLayout()
        bar.setSpacing(6)
        self._tab_buttons: list[QPushButton] = []
        for index, name in enumerate(self.TABS):
            btn = QPushButton(name)
            btn.setObjectName("tab")
            btn.setFixedHeight(28)
            btn.clicked.connect(lambda _c=False, i=index: self._set_tab(i))
            bar.addWidget(btn, 1)
            self._tab_buttons.append(btn)
        root.addLayout(bar)

        # One list per tab. Scrolled individually: Qt's answer to an overflowing fixed
        # panel is to paint children past its edge.
        self._stack = QStackedWidget()
        self._lists: list[QVBoxLayout] = []
        for _name in self.TABS:
            body = QWidget()
            column = QVBoxLayout(body)
            column.setContentsMargins(0, 0, 0, 0)
            column.setSpacing(6)
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QFrame.Shape.NoFrame)
            scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            scroll.setWidget(body)
            self._stack.addWidget(scroll)
            self._lists.append(column)
        root.addWidget(self._stack, 1)

        self._fill_lists()
        self._set_tab(0)

    def _icon_button(self, glyph: str, tip: str, on_click) -> QPushButton:
        button = QPushButton(glyph)
        button.setObjectName("rowAction")
        button.setFixedSize(30, 26)
        button.setToolTip(tip)
        button.setStyleSheet(f"font-family: '{theme.ICON_FAMILY}'; padding: 0;")
        button.clicked.connect(on_click)
        return button

    def _set_tab(self, index: int) -> None:
        self._stack.setCurrentIndex(index)
        for position, btn in enumerate(self._tab_buttons):
            btn.setObjectName("tabOn" if position == index else "tab")
            btn.style().unpolish(btn)
            btn.style().polish(btn)

    def _route_targets(self) -> list[tuple[str, str]]:
        """The (event, act) pairs the user has built in Run > Route, for map-image rows."""
        if self._routes is None:
            return []
        return [
            (event, act) for event in self._routes.maps() for act in self._routes.acts(event)
        ]

    def _build_image_rows(self) -> None:
        """Template rows into tab 0, map-image rows into tab 1."""
        headed: set[str] = set()
        for entry in catalog(self._route_targets()):
            index = 1 if entry.full_client else 0
            if entry.group not in headed:
                headed.add(entry.group)
                self._heading(index, entry.group)
            row = TemplateRow(entry, self._app_root)
            row.captureRequested.connect(self._start_capture)
            row.thresholdChanged.connect(self._on_threshold)
            row.testRequested.connect(self._test_template)
            # Seed from the live override set, so the spin shows what a search would use.
            row.set_threshold(confidence_for(entry.path))
            self._lists[index].addWidget(row)
            self._rows.append(row)

    # # Match thresholds
    def _on_threshold(self, entry: TemplateEntry, value: float) -> None:
        """Persist one template's threshold and put it into force immediately.

        Back to the default rather than storing 0.70 for everyone: an override recorded at
        the default value would survive a change to `DEFAULT_CONFIDENCE` and quietly pin
        this template to the old number.
        """
        if self._confidence is None:
            return
        key = confidence_key(entry.path)
        if abs(value - DEFAULT_CONFIDENCE) < 1e-9:
            self._confidence.clear(key)
            self._log(f"Match threshold reset to default: {entry.path}")
            self._set_note(f"{entry.name} is back to the default {DEFAULT_CONFIDENCE:.2f}.")
        elif not self._confidence.set(key, value):
            self._set_note(f"{value:.2f} was rejected as a threshold.", bad=True)
            return
        else:
            self._log(f"Match threshold: {entry.path} = {value:.2f}")
            self._set_note(f"{entry.name} must now score {value:.2f} or better.")
        apply_confidence_overrides(self._confidence.all())

    def _test_template(self, entry: TemplateEntry) -> None:
        """Report this template's best score against the live screen.

        The point of the button: a threshold picked without a measurement is the failure
        mode that got the old global tolerance setting deleted. `best_score` accepts
        anything, so it reports what the screen actually offers, pass or fail.
        """
        if not self._exists(entry):
            self._set_note(f"{entry.path} isn't on disk yet — capture it first.", bad=True)
            return
        if self._get_rect() is None:
            self._set_note("Roblox not found — start it and attach first.", bad=True)
            return
        score = best_score(self._engine, self._get_rect, entry.path)
        needed = confidence_for(entry.path)
        if score is None:
            self._set_note(f"{entry.name}: nothing captured — is Roblox visible?", bad=True)
            return
        verdict = "matches" if score >= needed else "does NOT match"
        self._log(f"Template test: {entry.path} best {score:.3f} vs {needed:.2f}")
        self._set_note(
            f"{entry.name}: best {score:.3f} against {needed:.2f} — {verdict} right now.",
            bad=score < needed,
        )

    def _heading(self, tab: int, text: str) -> None:
        label = QLabel(text.upper())
        label.setStyleSheet(
            f"color: {theme.TEXT_FAINT}; font-size: 10px; font-weight: 700; "
            f"letter-spacing: 1px; margin-top: 4px;"
        )
        self._lists[tab].addWidget(label)

    def _small_note(self, tab: int, text: str) -> None:
        label = QLabel(text)
        label.setWordWrap(True)
        label.setMinimumWidth(1)
        label.setStyleSheet(f"color: {theme.TEXT_FAINT}; font-size: 10px;")
        self._lists[tab].addWidget(label)

    def _build_region_rows(self) -> None:
        """The challenge panel's OCR boxes — tab 2.

        A different kind of thing from a template: these are read *blind* — cropped and
        handed to the recogniser — not matched, so there is nothing to capture and no score
        to report. A box a few pixels off doesn't fail, it returns confident nonsense, which
        is why it has to be user-editable.
        """
        if self._regions is None:
            return
        self._small_note(
            2,
            "Read by OCR, not matched — so a box that is slightly off returns wrong text "
            "rather than nothing. Run CHALLENGE > Dump challenge boxes with the list open "
            "to see what each one currently covers.",
        )
        for key, label, default in challenge.region_specs():
            row = GeometryRow(key, label, default)
            row.setRequested.connect(self._start_region_pick)
            row.clearRequested.connect(self._clear_region)
            self._lists[2].addWidget(row)
            self._region_rows.append(row)
        self._refresh_regions()

    def _build_point_rows(self) -> None:
        """Fixed click points — tab 3.

        Acts and the start sequence are clicked at a coordinate rather than matched, because
        they are rows and buttons on a screen the macro has already confirmed. Nothing
        verifies the click landed on the right one, so a stale point quietly plays the wrong
        act — which is exactly why these need an editor.
        """
        if self._points is None:
            return
        self._small_note(
            3,
            "Only what the macro clicks blind, with nothing to verify it landed right — so a "
            "point that is off plays the act next to the one you picked. Pick the middle of "
            "the row or button. Select Stage and Start aren't here: those are template "
            "searches, so fix them on the Templates tab.",
        )
        self._heading(3, "Act rows")
        for key, label, default in acts.act_specs():
            self._lists[3].addWidget(self._point_row(key, label, default))
        self._heading(3, "Start sequence")
        for key, label, default in start_stage.point_specs():
            self._lists[3].addWidget(self._point_row(key, label, default))
        self._refresh_points()

    def _point_row(self, key: str, label: str, default: tuple[int, int]) -> GeometryRow:
        row = GeometryRow(key, label, default)
        row.setRequested.connect(self._start_point_pick)
        row.clearRequested.connect(self._clear_point)
        self._point_rows.append(row)
        return row

    def _refresh_regions(self) -> None:
        """Push the stored overrides into the rows and into `content.challenge`."""
        if self._regions is None:
            return
        stored = self._regions.all()
        challenge.apply_region_overrides(stored)
        for row in self._region_rows:
            row.show_value(stored.get(row.key))

    def _refresh_points(self) -> None:
        """Push the stored points into the rows and into both content tables.

        Both modules get the whole `points` dict — each only recognises its own keys — so
        `LobbyNavigator` and the Run page's guards read the same value the row shows.
        """
        if self._points is None:
            return
        stored = self._points.all()
        acts.apply_point_overrides(stored)
        start_stage.apply_point_overrides(stored)
        for row in self._point_rows:
            row.show_value(stored.get(row.key))

    def _fill_lists(self) -> None:
        self._build_image_rows()
        self._build_region_rows()
        self._build_point_rows()
        for column in self._lists:
            column.addStretch(1)

    def refresh(self) -> None:
        """Rebuild every list from disk and from the stores.

        A full rebuild rather than a per-row re-read because the Events map rows come from
        `routes.json`: an act added in Run > Route has to appear here without a restart.
        """
        for column in self._lists:
            while column.count():
                item = column.takeAt(0)
                widget = item.widget()
                if widget is not None:
                    widget.deleteLater()
        self._rows.clear()
        self._region_rows.clear()
        self._point_rows.clear()
        self._fill_lists()
        missing = sum(1 for row in self._rows if not self._exists(row.entry))
        total = len(self._rows)
        if missing:
            self._set_note(f"{total - missing} of {total} images present · {missing} missing.")
        else:
            self._set_note(f"All {total} images present.")

    def _exists(self, entry: TemplateEntry) -> bool:
        return os.path.isfile(os.path.join(self._app_root, entry.path))

    def _set_note(self, text: str, bad: bool = False) -> None:
        self._note.setText(text)
        colour = theme.WARN if bad else theme.TEXT_FAINT
        self._note.setStyleSheet(f"color: {colour}; font-size: 11px;")

    # # Capture
    def _start_capture(self, entry: TemplateEntry) -> None:
        if self._overlay is not None:  # one picker at a time
            return
        rect = self._get_rect()
        if rect is None:
            self._set_note("Roblox not found — start it and attach first.", bad=True)
            return
        # A map picture is the whole playfield, so there is no box to drag and no overlay
        # to get in the way of the pixels being captured.
        if entry.full_client:
            self._write(entry, (0, 0, rect[2], rect[3]))
            return

        def done(result) -> None:
            self._overlay = None
            if result is None or result[0] != "region":
                return
            _mode, ax, ay, bx, by = result
            box = (min(ax, bx), min(ay, by), abs(bx - ax), abs(by - ay))
            if box[2] < MIN_BOX or box[3] < MIN_BOX:
                self._set_note("That box is too small to match on. Drag a bigger one.", bad=True)
                return
            QTimer.singleShot(REPAINT_MS, lambda: self._write(entry, box))

        # Keep the reference: a local would be collected mid-pick, taking the callback
        # with it.
        self._overlay = RegionOverlay("region", rect, done)
        self._overlay.show()
        self._overlay.raise_()
        self._overlay.activateWindow()
        self._set_note(f"Drag the box for {entry.name} · Esc to cancel.")

    def _write(self, entry: TemplateEntry, box: tuple[int, int, int, int]) -> None:
        rect = self._get_rect()
        if rect is None:
            self._set_note("Roblox not found — start it and attach first.", bad=True)
            return
        # Client-space box -> screen rect. The overlay is sized to the client area and
        # clamps the drag inside it, so this can't reach past the game window.
        png = self._engine.capture_png(
            (rect[0] + box[0], rect[1] + box[1], box[2], box[3])
        )
        if png is None:
            self._set_note("Could not capture that area.", bad=True)
            return
        target = os.path.join(self._app_root, entry.path)
        try:
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with open(target, "wb") as handle:
                handle.write(png)
        except OSError as exc:
            self._set_note(f"Could not save {entry.path}: {exc}", bad=True)
            return
        for row in self._rows:
            if row.entry.path == entry.path:
                row.refresh()
        # No cache clear needed: the engine's template cache keys on mtime, so the next
        # search picks this up on its own.
        self._log(f"Image saved: {entry.path} ({box[2]}x{box[3]})")
        used_by = "placement picker" if entry.full_client else "next search"
        self._set_note(f"Saved {entry.name} — {box[2]}x{box[3]}px. The {used_by} uses it.")

    # # Regions
    def _start_region_pick(self, key: str) -> None:
        if self._overlay is not None or self._regions is None:
            return
        rect = self._get_rect()
        if rect is None:
            self._set_note("Roblox not found — start it and attach first.", bad=True)
            return

        def done(result) -> None:
            self._overlay = None
            if result is None or result[0] != "region":
                return
            _mode, ax, ay, bx, by = result
            box = (min(ax, bx), min(ay, by), abs(bx - ax), abs(by - ay))
            # The store rejects rather than repairs, so report its answer instead of
            # assuming the save worked.
            if not self._regions.set(key, box):
                self._set_note(
                    f"That box is too small for text ({box[2]}x{box[3]}). Drag a bigger one.",
                    bad=True,
                )
                return
            self._refresh_regions()
            self._log(f"Region saved: {key} = {box[0]},{box[1]} {box[2]}x{box[3]}")
            self._set_note(f"Saved {key} — {box[0]},{box[1]} {box[2]}x{box[3]}.")

        self._overlay = RegionOverlay("region", rect, done)
        self._overlay.show()
        self._overlay.raise_()
        self._overlay.activateWindow()
        self._set_note(f"Drag the box for {key} · Esc to cancel.")

    def _clear_region(self, key: str) -> None:
        if self._regions is None:
            return
        self._regions.clear(key)
        self._refresh_regions()
        self._log(f"Region reset to default: {key}")
        self._set_note(f"{key} is back to the built-in box.")

    # # Points
    def _start_point_pick(self, key: str) -> None:
        if self._overlay is not None or self._points is None:
            return
        rect = self._get_rect()
        if rect is None:
            self._set_note("Roblox not found — start it and attach first.", bad=True)
            return

        def done(result) -> None:
            self._overlay = None
            if result is None or result[0] != "point":
                return
            _mode, x, y = result
            if not self._points.set(key, (x, y)):
                self._set_note(f"{x},{y} was rejected as a click point.", bad=True)
                return
            self._refresh_points()
            self._log(f"Point saved: {key} = {x},{y}")
            self._set_note(f"Saved {key} — {x}, {y}. The next run clicks there.")

        self._overlay = RegionOverlay("point", rect, done)
        self._overlay.show()
        self._overlay.raise_()
        self._overlay.activateWindow()
        self._set_note(f"Click the point for {key} · Esc to cancel.")

    def _clear_point(self, key: str) -> None:
        if self._points is None:
            return
        self._points.clear(key)
        self._refresh_points()
        self._log(f"Point reset to default: {key}")
        self._set_note(f"{key} is back to the built-in point.")

    def _open_folder(self) -> None:
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices

        folder = os.path.join(self._app_root, nav.IMAGES_DIR)
        if not os.path.isdir(folder):
            self._set_note(f"No {nav.IMAGES_DIR} folder next to the app.", bad=True)
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(folder))
