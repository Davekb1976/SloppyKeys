"""Run screen right-hand panel: what the macro is doing and how it's going.

Read-only. Everything here is driven by `StatsTracker.snapshot()` plus the current
selection, pushed in from MainWindow — the panel never reads game state itself.

Styling lives in `theme.stylesheet()` (`#statCard`, `#statValue*`), not inline, so
these tiles follow the app's palette like every other surface. All cards share one
neutral look; colour is spent only on values that carry meaning (wins, losses, the
current action), so the eye lands on those rather than on a wall of tinted
borders.

Sections: MAP, CURRENT STATUS, WIN / LOSS, then a tabbed area in the space below
them (Tasks | Route | Currency). The tabs exist because that space was empty and
the Events route builder needs somewhere to live that keeps the viewport and run
strip on screen. Currency is still a placeholder: nothing reads those numbers out
of the game yet.
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from sloppykeys.config.stats import RunStats

from .. import theme

# objectNames for the value label, which is all that varies between tiles.
PLAIN = "statValue"
GOOD = "statValueGood"
BAD = "statValueBad"
ACCENT = "statValueAccent"

TABS = ("Tasks", "Route", "Currency")


class StatCard(QFrame):
    """One caption + value tile, with an optional second line."""

    def __init__(self, caption: str, value: str = "-", tone: str = PLAIN, sub: str = "") -> None:
        super().__init__()
        self.setObjectName("statCard")
        box = QVBoxLayout(self)
        box.setContentsMargins(10, 7, 10, 8)
        box.setSpacing(1)

        caption_label = QLabel(caption.upper())
        caption_label.setObjectName("statCaption")
        self._value = QLabel(value)
        self._value.setObjectName(tone)
        box.addWidget(caption_label)
        box.addWidget(self._value)

        self._sub: QLabel | None = None
        if sub:
            self._sub = QLabel(sub)
            self._sub.setObjectName("statSub")
            box.addWidget(self._sub)

    def set_value(self, text: str) -> None:
        self._value.setText(text)

    def set_sub(self, text: str) -> None:
        if self._sub is not None:
            self._sub.setText(text)


# What a scanned row means, in words someone reading the panel would use. The scanner's
# own vocabulary (`runnable` / `exhausted` / `unknown`) is about *reads*, not about the
# game, and it was showing through to the user.
STATE_WORDS = {
    "ready": ("Ready", theme.GOOD),
    "played": ("Done", theme.TEXT_FAINT),
    "spent": ("No runs left", theme.TEXT_FAINT),
    "unread": ("Couldn't read", theme.WARN),
}


class ChallengeRow(QFrame):
    """One offered challenge: which map, how many runs are left, whether it's playable.

    A tile rather than a line of text with dots in it. Three columns that line up across
    the rows, so the eye can compare them — the old single-string form (`1. King's Tomb ·
    7/10 · runnable`) was ragged and put the least useful part, the raw state word, last.
    """

    def __init__(self, slot: int) -> None:
        super().__init__()
        self.setObjectName("statCard")
        box = QHBoxLayout(self)
        box.setContentsMargins(10, 6, 10, 6)
        box.setSpacing(8)

        number = QLabel(str(slot))
        number.setObjectName("statCaption")
        number.setFixedWidth(10)
        self._map = QLabel("-")
        self._map.setObjectName("statValue")
        self._map.setMinimumWidth(1)
        self._runs = QLabel("")
        self._runs.setObjectName("statSub")
        self._state = QLabel("")
        self._state.setObjectName("statSub")

        box.addWidget(number)
        box.addWidget(self._map)
        box.addStretch(1)
        box.addWidget(self._runs)
        box.addWidget(self._state)
        self.set_unread()

    def set_unread(self) -> None:
        self._map.setText("not read yet")
        self._runs.setText("")
        self._apply_state("unread")

    def set_read(self, map_name: str, runs_left: int | None, key: str) -> None:
        self._map.setText(map_name or "map unknown")
        self._runs.setText("" if runs_left is None else f"{runs_left} left")
        self._apply_state(key)

    def _apply_state(self, key: str) -> None:
        text, colour = STATE_WORDS.get(key, STATE_WORDS["unread"])
        self._state.setText(text)
        # Inline for this one dynamic colour, which is what theme.py's rules allow: the
        # status changes at runtime and there is no sensible static QSS rule for it.
        self._state.setStyleSheet(f"color: {colour};")


class StatsPage(QWidget):
    def __init__(self) -> None:
        """Read-only. The Tasks and Route editors used to be tabs here and now live in
        Settings: this panel is what you watch while the macro works, not somewhere you
        configure things."""
        super().__init__()
        root = QVBoxLayout(self)
        root.setContentsMargins(14, 12, 14, 12)
        root.setSpacing(10)

        root.addLayout(_group("MAP"))
        self._task = StatCard("Current task", "-", ACCENT)
        self._map = StatCard("Map", "-")
        root.addLayout(_grid([(self._task, 0, 0), (self._map, 0, 1)]))

        root.addLayout(_group("CURRENT STATUS"))
        self._action = StatCard("Action", "Idle", ACCENT)
        self._last_run = StatCard("Last run", "-")
        self._macro_time = StatCard("Macro uptime", "0:00:00")
        # The match in progress, with the last finished one underneath — "Stage run time"
        # never said which of the two it meant.
        self._stage_time = StatCard("This match", "0:00:00", sub="last -")
        root.addLayout(
            _grid(
                [
                    (self._action, 0, 0),
                    (self._last_run, 0, 1),
                    (self._macro_time, 1, 0),
                    (self._stage_time, 1, 1),
                ]
            )
        )

        root.addLayout(_group("WIN / LOSS"))
        self._wins = StatCard("Wins", "0", GOOD, sub="all time 0")
        self._losses = StatCard("Losses", "0", BAD, sub="all time 0")
        self._rate = StatCard("Win %", "-", PLAIN, sub="0 / 0")
        self._all_rate = StatCard("All time win %", "-", PLAIN, sub="0 runs")
        root.addLayout(
            _grid(
                [
                    (self._wins, 0, 0),
                    (self._losses, 0, 1),
                    (self._rate, 1, 0),
                    (self._all_rate, 1, 1),
                ]
            )
        )

        # Challenge state, Task mode only. Read-only, like everything else here: what the
        # last scan of the panel saw. The queue itself is edited in Settings > Tasks and
        # shown in the run strip; this is the game's side of it.
        #
        # The countdown sits *in* the heading rather than on its own line below it: it is a
        # property of the whole group, and as a separate line it read as a fourth item
        # competing with the three rows.
        self._challenges = QWidget()
        challenge_box = QVBoxLayout(self._challenges)
        challenge_box.setContentsMargins(0, 0, 0, 0)
        challenge_box.setSpacing(6)
        self._challenge_reset = QLabel("")
        self._challenge_reset.setObjectName("statSub")
        challenge_box.addLayout(_group("CHALLENGES", trailing=self._challenge_reset))
        self._challenge_rows = [ChallengeRow(slot) for slot in (1, 2, 3)]
        for row in self._challenge_rows:
            challenge_box.addWidget(row)
        self._challenges.setVisible(False)
        root.addWidget(self._challenges)

        root.addSpacing(2)
        root.addWidget(_separator())
        root.addLayout(_group("CURRENCY"))
        root.addWidget(_placeholder("Currency tracking is not built yet."), 1)

    # # Public API
    def set_task_mode(self, on: bool) -> None:
        """Show the CHALLENGES group only while the queue is what's running."""
        self._challenges.setVisible(on)

    def set_challenge_reset(self, text: str) -> None:
        """The countdown, shown beside the CHALLENGES heading. Passed in, so this page
        needs no clock of its own."""
        self._challenge_reset.setText(text)

    def set_challenges(self, reads: list | None) -> None:
        """Fill the three rows from the last scan. `None` resets them to "not read".

        Takes whatever `ChallengeScanner` produced rather than reaching for it, so this
        page still knows nothing about capture, OCR or the tracker. The scanner's state
        words are translated here — a panel that says `exhausted` when the row is simply
        one you already played is the UI leaking its own plumbing.
        """
        by_slot = {read.slot: read for read in (reads or [])}
        for index, row in enumerate(self._challenge_rows, start=1):
            read = by_slot.get(index)
            if read is None:
                row.set_unread()
                continue
            row.set_read(read.map_name, read.runs_remaining, _state_key(read))

    def set_target(self, gamemode: str, map_name: str, target: str) -> None:
        parts = [part for part in (gamemode, target) if part]
        self._task.set_value(" / ".join(parts) if parts else "-")
        self._map.set_value(map_name or "-")

    def set_action(self, text: str) -> None:
        self._action.set_value(text or "Idle")

    def set_stats(self, stats: RunStats) -> None:
        self._last_run.set_value(stats.last_run)
        self._macro_time.set_value(stats.macro_time)
        self._stage_time.set_value(stats.stage_time)
        self._stage_time.set_sub(f"last {stats.last_stage_time}")

        self._wins.set_value(str(stats.wins))
        self._wins.set_sub(f"all time {stats.all_wins}")
        self._losses.set_value(str(stats.losses))
        self._losses.set_sub(f"all time {stats.all_losses}")
        self._rate.set_value(stats.win_rate)
        self._rate.set_sub(f"{stats.wins} / {stats.total}")
        self._all_rate.set_value(stats.all_win_rate)
        self._all_rate.set_sub(f"{stats.all_total} total runs")


# # Builders
def _grid(items: list[tuple[QWidget, int, int]]) -> QGridLayout:
    grid = QGridLayout()
    grid.setSpacing(8)
    for widget, row, column in items:
        grid.addWidget(widget, row, column)
    return grid


def _group(title: str, trailing: QWidget | None = None) -> QHBoxLayout:
    """A section heading and its rule. `trailing` puts one widget after the rule, for a
    fact that belongs to the whole section rather than to any row in it."""
    row = QHBoxLayout()
    row.setSpacing(8)
    label = QLabel(title)
    label.setObjectName("groupHead")
    line = QFrame()
    line.setObjectName("sep")
    row.addWidget(label)
    row.addWidget(line, 1)
    if trailing is not None:
        row.addWidget(trailing)
    return row


def _state_key(read) -> str:
    """Scanner state -> one of `STATE_WORDS`.

    Zero runs left is the day's quota gone (refills at 20:00); anything else exhausted is
    a row already played this rotation, which is a different thing to tell someone.
    """
    # First: the macro's own memory beats the panel's appearance. A row played this rotation
    # still *looks* runnable (bright star, runs left), so without this it read "Ready" right
    # after the macro finished it.
    if getattr(read, "played", False):
        return "played"
    if read.runs_remaining == 0:
        return "spent"
    if read.state == "exhausted":
        return "played"
    if read.state == "runnable":
        return "ready"
    return "unread"


def _separator() -> QFrame:
    """The divider between the read-only stats and the tabbed area below them.
    Reuses the `#sep` rule the group headings already use."""
    line = QFrame()
    line.setObjectName("sep")
    line.setFixedHeight(1)
    return line


def _placeholder(text: str) -> QWidget:
    """A tab with nothing behind it yet, named as missing rather than drawn empty."""
    page = QWidget()
    box = QVBoxLayout(page)
    box.setContentsMargins(0, 6, 0, 0)
    label = QLabel(text)
    label.setWordWrap(True)
    label.setObjectName("statSub")
    box.addWidget(label)
    box.addStretch(1)
    return page


def _scrolled(inner: QWidget) -> QScrollArea:
    """Let a tall tab scroll instead of forcing the panel taller than the window.

    Measured: the stat cards plus the route editor's own minimum come to ~837px
    against ~828px of panel. Qt resolves that overflow by painting children past
    the panel edge (the fixed window can't grow), so the tab area is bounded here
    and scrolls when it runs out of room.
    """
    area = QScrollArea()
    area.setWidgetResizable(True)
    area.setFrameShape(QFrame.Shape.NoFrame)
    area.setWidget(inner)
    # 0 lets the layout give this away entirely; the stat cards above are fixed,
    # so whatever height is left over is what the tab gets.
    area.setMinimumHeight(0)
    return area
