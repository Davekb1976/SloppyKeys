"""Visual theme for the PySide6 shell.

Palette follows the logo: cyan -> blue -> violet accents on near-black panels.
Colours are plain hex strings so they drop straight into Qt style sheets.
"""

from __future__ import annotations

# # Window
# Sized around the fixed viewport below, so nothing has to stretch or clip.
# Both numbers are the layout's own measured minimum — keep them equal to it. Surplus
# height shows up as dead space under the run strip (and as a drag outline taller than
# the content); a shortfall clips the strip.
WINDOW_WIDTH = 1690
WINDOW_HEIGHT = 1004
TITLEBAR_HEIGHT = 40
RAIL_WIDTH = 78

# # Viewport — Roblox's client area is resized to exactly this.
#
# **1152x756**, the same client size Cream's Anime Expeditions macro pins Roblox to
# (`core/config.py::FIXED_WIN_W/H` there). Chosen because that macro is in use across many
# machines and monitors at this size, which is the evidence that matters: it is reproducible
# somewhere other than this one PC.
#
# History worth not repeating: this was 816x638, and text came back soft with elements a
# different pixel size than the crops taken from them — chased for a long time as a
# template/tolerance/DPI/monitor bug when it was the window size. It was then dropped to
# 800x599 (Roblox's own minimum), which was crisp but small enough to worry about. If soft
# text or off-scale templates come back at 1152x756, the window size is the first suspect
# again, and VISION > Check template scale is the measurement.
#
# Changing these two numbers **invalidates every stored coordinate and every template**:
# `content/acts.py`, `start_stage.py`, `challenge.py`, `start_position.py`, all of
# `configs/`, `routes.json` and everything in `images/`. Re-capture with the Image Manager
# (Settings > Images).
VIEWPORT_WIDTH = 1152
VIEWPORT_HEIGHT = 756

# # Right column (chips + step detail)
PANEL_MIN_WIDTH = 400
# Bottom strip (process log / current config / actions).
# Height budget: viewport(VIEWPORT_HEIGHT + 12 frame) + 12 spacing + STRIP_HEIGHT must equal
# WINDOW_HEIGHT - TITLEBAR_HEIGHT - 18px body margins. Surplus is a visible gap under the
# strip; a shortfall clips it.
STRIP_HEIGHT = 166

# # Palette
INK_900 = "#07080D"
INK_850 = "#0A0C13"
INK_800 = "#0E1119"
INK_700 = "#141824"
INK_600 = "#1B2030"
INK_500 = "#232A3D"

LINE = "#262D40"
LINE_BRIGHT = "#333C55"

TEXT = "#E7EBF5"
TEXT_DIM = "#9AA4BD"
TEXT_FAINT = "#6B7490"

CYAN = "#22D3EE"
SKY = "#38BDF8"
BLUE = "#3B82F6"
INDIGO = "#6366F1"
VIOLET = "#8B5CF6"
PURPLE = "#A855F7"
PINK = "#F472B6"
ORANGE = "#F97316"

GOOD = "#34D399"
WARN = "#FBBF24"
BAD = "#F87171"

ACCENT = VIOLET
ACCENT_HOVER = "#7C4DE0"

# Accent colour per gamemode.
GAMEMODE_ACCENTS = {"Story": SKY, "Raid": BAD, "Expedition": GOOD}

# Colour per hotbar slot (1-6). The same slot is the same unit, so this is the
# visual identity used for placement dots and the chip's slot caption — spot two
# steps sharing a colour and you know they place the same unit.
#
# Six hues that stay apart at 10px on a near-black panel, and none of them violet
# or purple: those are the app's own accent (buttons, selected chip border, the
# number badge), so a slot wearing them reads as "selected" rather than "slot 2".
# CYAN and SKY were the earlier 1 and 5 and are 15° apart in hue — indistinguishable
# on a chip caption, which is the bug this replaces. BLUE carries slot 5 instead.
SLOT_COLORS = {1: CYAN, 2: PINK, 3: GOOD, 4: WARN, 5: BLUE, 6: ORANGE}
SLOT_COLOR_UNSET = TEXT_FAINT


def slot_color(slot: int | None) -> str:
    return SLOT_COLORS.get(slot, SLOT_COLOR_UNSET) if slot else SLOT_COLOR_UNSET

# # Fonts
FAMILY = "Segoe UI"
MONO = "Consolas"
ICON_FAMILY = "Segoe Fluent Icons"

# # Logs
LOG_MAX_LINES = 250


def stylesheet() -> str:
    """Global QSS applied to the whole app."""
    return f"""
    * {{
        font-family: "{FAMILY}";
        color: {TEXT};
        font-size: 13px;
    }}
    QWidget#root {{ background: {INK_900}; }}
    /* The titlebar itself is only the drag strip — transparent, so the card inside it
       reads as a sibling of the rail and the page rather than a full-bleed band. Its
       total height stays TITLEBAR_HEIGHT: the window height budget depends on it. */
    QWidget#titlebar {{ background: transparent; }}
    QFrame#titlebarCard {{
        background: {INK_850};
        border: 1px solid {LINE};
        border-radius: 10px;
    }}
    QWidget#rail {{
        background: {INK_850};
        border: 1px solid {LINE};
        border-radius: 10px;
    }}
    QWidget#page {{
        background: {INK_800};
        border: 1px solid {LINE};
        border-radius: 10px;
    }}

    QLabel#brand {{ color: #FFFFFF; font-size: 16px; font-weight: 800; }}
    QLabel#version {{
        color: {TEXT_DIM};
        background: {INK_700};
        border: 1px solid {LINE};
        border-radius: 12px;
        padding: 0 12px;
        font-size: 10px;
    }}
    QLabel#hint {{
        color: {TEXT_DIM};
        background: {INK_700};
        border: 1px solid {LINE};
        border-radius: 12px;
        padding: 0 14px;
        font-size: 10px;
    }}
    QLabel#groupHead {{ color: {TEXT_FAINT}; font-size: 10px; font-weight: 800; }}
    QLabel#numBadge {{
        background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 {VIOLET}, stop:1 {PURPLE});
        color: #FFFFFF;
        border-radius: 17px;
        font-size: 15px;
        font-weight: 800;
    }}
    QLabel#sizePill {{
        background: {INK_700};
        border: 1px solid {GOOD};
        border-radius: 11px;
        padding: 0 12px;
        color: {GOOD};
        font-size: 11px;
        font-weight: 800;
    }}
    /* Session clock, pinned to the bottom of the rail. Same tile treatment as the
       stat cards so the rail's foot matches the panels beside it. */
    /* 11px, not 13: the rail interior is RAIL_WIDTH minus its 6px margins, and the value
       reaches `H:MM:SS` after an hour — it had room in the titlebar and does not here. */
    QLabel#session {{ color: {CYAN}; font-size: 11px; font-weight: 800; }}
    QLabel#sessionCap {{ color: {TEXT_FAINT}; font-size: 8px; font-weight: 800; }}
    QFrame#railSession {{
        background: {INK_800};
        border: 1px solid {LINE};
        border-radius: 8px;
    }}
    QLabel#h1 {{ font-size: 15px; font-weight: 700; }}
    QLabel#section {{ color: {TEXT_DIM}; font-size: 11px; font-weight: 700; }}
    QLabel#status {{ color: {TEXT_DIM}; font-size: 12px; }}
    QLabel#fieldLabel {{ color: {TEXT_FAINT}; font-size: 10px; font-weight: 700; }}

    QPushButton {{
        background: {INK_700};
        border: 1px solid {LINE};
        border-radius: 8px;
        padding: 8px 14px;
        color: {TEXT};
    }}
    QPushButton:hover {{ background: {INK_600}; border-color: {LINE_BRIGHT}; }}
    QPushButton:pressed {{ background: {INK_500}; }}
    QPushButton#primary {{
        background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {VIOLET}, stop:1 {PURPLE});
        border: none;
        color: #FFFFFF;
        font-weight: 700;
    }}
    QPushButton#primary:hover {{
        background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {ACCENT_HOVER}, stop:1 {PURPLE});
    }}

    QComboBox {{
        background: {INK_850};
        border: 1px solid {LINE};
        border-radius: 8px;
        padding: 6px 10px;
        color: {TEXT};
    }}
    QComboBox:hover {{ border-color: {LINE_BRIGHT}; }}
    QComboBox::drop-down {{ border: none; width: 22px; }}
    QComboBox QAbstractItemView {{
        background: {INK_800};
        border: 1px solid {LINE_BRIGHT};
        selection-background-color: {VIOLET};
        color: {TEXT};
        outline: none;
    }}

    QLineEdit {{
        background: {INK_850};
        border: 1px solid {LINE};
        border-radius: 8px;
        padding: 6px 10px;
        color: {TEXT};
    }}
    QLineEdit:focus {{ border-color: {VIOLET}; }}

    QDoubleSpinBox, QSpinBox {{
        background: {INK_850};
        border: 1px solid {LINE};
        border-radius: 8px;
        padding: 5px 8px;
        color: {TEXT};
    }}
    QDoubleSpinBox:focus, QSpinBox:focus {{ border-color: {VIOLET}; }}
    /* No step arrows. They ate 16px of every spin box's width, and these fields are
       narrow by necessity (a run limit, a timeout, a hold in ms sit inside list rows),
       so the arrows were clipping the value they were meant to change — the run limit
       could not show three digits. Typing still works, and so does the mouse wheel and
       Up/Down; nothing is lost but the two-pixel-tall click targets nobody could hit. */
    QDoubleSpinBox::up-button, QDoubleSpinBox::down-button,
    QSpinBox::up-button, QSpinBox::down-button {{ width: 0; border: none; }}

    QCheckBox {{ color: {TEXT_DIM}; spacing: 8px; }}
    QCheckBox::indicator {{
        width: 16px; height: 16px;
        border: 1px solid {LINE_BRIGHT};
        border-radius: 4px;
        background: {INK_850};
    }}
    QCheckBox::indicator:checked {{ background: {VIOLET}; border-color: {VIOLET}; }}

    QPlainTextEdit#log {{
        background: {INK_900};
        border: none;
        border-radius: 6px;
        color: {TEXT_DIM};
        font-family: "{MONO}";
        font-size: 11px;
    }}

    QScrollArea {{ background: transparent; border: none; }}
    QScrollArea > QWidget > QWidget {{ background: transparent; }}
    QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px 1px; }}
    QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 1px 2px; }}
    QScrollBar::handle:vertical {{ background: {INK_600}; border-radius: 4px; min-height: 30px; }}
    QScrollBar::handle:horizontal {{ background: {INK_600}; border-radius: 4px; min-width: 30px; }}
    QScrollBar::handle:hover {{ background: {INK_500}; }}
    QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; background: transparent; }}
    QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
    QScrollBar::corner, QAbstractScrollArea::corner {{ background: transparent; }}

    /* Step cards */
    QFrame#stepCard {{
        background: {INK_850};
        border: 1px solid {LINE};
        border-radius: 10px;
    }}
    QFrame#stepCard:hover {{ border-color: {LINE_BRIGHT}; }}
    QFrame#stepCardOn {{
        background: {INK_850};
        border: 1px solid {VIOLET};
        border-radius: 10px;
    }}
    QFrame#stepCardOn:hover {{ border-color: {PURPLE}; }}
    QFrame#cardHead {{
        background: {INK_700};
        border-top-left-radius: 10px;
        border-top-right-radius: 10px;
    }}

    /* Index pill buttons */
    QPushButton#pill {{
        background: {INK_700};
        border: 1px solid {LINE};
        border-radius: 15px;
        padding: 4px 0;
        min-width: 30px;
        color: {TEXT_DIM};
        font-weight: 700;
    }}
    QPushButton#pill:hover {{ background: {INK_600}; border-color: {LINE_BRIGHT}; color: {TEXT}; }}
    QPushButton#pillOn {{
        background: {VIOLET};
        border: 1px solid {VIOLET};
        border-radius: 15px;
        padding: 4px 0;
        min-width: 30px;
        color: #FFFFFF;
        font-weight: 700;
    }}
    QPushButton#iconBtn {{ font-family: "{ICON_FAMILY}"; }}

    /* Settings tab bar */
    QPushButton#tab {{
        background: {INK_800};
        border: 1px solid {LINE};
        border-radius: 8px;
        padding: 7px 18px;
        color: {TEXT_DIM};
        font-weight: 700;
        font-size: 12px;
    }}
    QPushButton#tab:hover {{ background: {INK_700}; border-color: {LINE_BRIGHT}; color: {TEXT}; }}
    /* A button that lives inside a narrow list row. `#tab` looks right but its
       `padding: 7px 18px` is 36px of horizontal padding, which clipped its own label in a
       fixed-width row button. Same look, room for the text. */
    QPushButton#rowAction {{
        background: {INK_800};
        color: {TEXT_DIM};
        border: 1px solid {LINE};
        border-radius: 8px;
        padding: 4px 10px;
        font-size: 11px;
        font-weight: 600;
    }}
    QPushButton#rowAction:hover {{
        background: {INK_600}; border-color: {LINE_BRIGHT}; color: {TEXT};
    }}
    QPushButton#tabOn {{
        background: {INK_700};
        border: 1px solid {VIOLET};
        border-radius: 8px;
        padding: 7px 18px;
        color: {PURPLE};
        font-weight: 800;
        font-size: 12px;
    }}

    /* Test row (Macro Tester) */
    QFrame#testRow {{
        background: {INK_850};
        border: 1px solid {LINE};
        border-radius: 8px;
    }}
    QFrame#testRow:hover {{ border-color: {LINE_BRIGHT}; }}
    QLabel#testResult {{ font-size: 11px; font-weight: 700; }}

    /* Titlebar selected-gamemode button */
    QPushButton#gamemodePill {{
        background: {INK_700};
        border: 1px solid {VIOLET};
        border-radius: 15px;
        padding: 6px 18px;
        color: {TEXT};
        font-weight: 800;
        font-size: 13px;
    }}
    QPushButton#gamemodePill:hover {{ background: {INK_600}; border-color: {PURPLE}; }}

    /* Separator lines */
    QFrame#sep {{ background: {LINE}; border: none; max-height: 1px; min-height: 1px; }}
    QFrame#vsep {{ background: {LINE}; border: none; max-width: 1px; min-width: 1px; }}

    /* Step chips (Units grid) */
    QFrame#stepChip {{
        background: {INK_800};
        border: 1px solid {LINE};
        border-radius: 12px;
    }}
    QFrame#stepChip:hover {{ background: {INK_700}; border-color: {INDIGO}; }}
    QFrame#stepChipOn {{
        background: {INK_700};
        border: 2px solid {PURPLE};
        border-radius: 12px;
    }}
    QLabel#chipNum {{ font-size: 15px; font-weight: 800; color: {TEXT}; }}
    QLabel#chipBadge {{
        background: {INK_600};
        color: {PURPLE};
        border-radius: 11px;
        padding: 0 12px;
        font-size: 11px;
        font-weight: 800;
    }}

    /* Bordered section box (run strip columns) */
    QFrame#sectionBox {{
        background: {INK_850};
        border: 1px solid {LINE};
        border-radius: 10px;
    }}
    QLabel#chipSub {{ color: {TEXT_FAINT}; font-size: 10px; }}

    /* Run screen stat tiles. One neutral card style for all of them: colour is
       reserved for the few values that mean something (a win, a loss), so a
       glance finds those instead of a rainbow of borders. */
    QFrame#statCard {{
        background: {INK_800};
        border: 1px solid {LINE};
        border-radius: 8px;
    }}
    QFrame#statCard QLabel {{ border: none; background: transparent; }}
    QLabel#statCaption {{
        color: {TEXT_FAINT};
        font-size: 9px;
        font-weight: 800;
        letter-spacing: 1px;
    }}
    QLabel#statValue {{ color: {TEXT}; font-size: 15px; font-weight: 800; }}
    QLabel#statValueGood {{ color: {GOOD}; font-size: 15px; font-weight: 800; }}
    QLabel#statValueBad {{ color: {BAD}; font-size: 15px; font-weight: 800; }}
    QLabel#statValueAccent {{ color: {ACCENT}; font-size: 15px; font-weight: 800; }}
    QLabel#statSub {{ color: {TEXT_FAINT}; font-size: 10px; }}

    /* Detail editor scroll area */
    QScrollArea#detail {{ background: transparent; border: none; }}
    """
