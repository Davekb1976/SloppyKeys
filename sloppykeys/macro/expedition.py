"""What to do about Expedition's mid-match screens.

Pure decision, the same contract as `macro/tasks.py`: it is told which screens were on
screen this tick and answers with one action. No capture, no clicking, no UI — which is what
makes the part that is easy to get wrong (counting extract offers without double-counting a
screen that is simply still up) testable without a game.

Expedition shows no Victory between waves. Every wave transition is a Continue and then a
smaller Continue on the panel it opens; at some checkpoints that same screen also offers
Extract, and accepting it is how the run ends. So a match is: keep the screen clear, keep
clicking Continue, and take Extract at the offer the task asked for.

The caller reports sightings by name (`CARD`, `START_GAME`, `EXTRACT`, `CONTINUE`) and
performs whatever action comes back. Order inside `decide` is deliberate and load-bearing;
each case says why.
"""

from __future__ import annotations

# # What the caller reports having seen this tick
# The "Select an upgrade!" level-up modal. Nothing else can be trusted while it is up: it
# renders over the buttons underneath, so a Continue behind it is found and unclickable.
CARD = "card"
# The in-match Start Game button, mid-match. It means the round is re-staging.
START_GAME = "start_game"
# Extract offered at a checkpoint, beside its own Continue.
EXTRACT = "extract"
# The plain wave Continue.
CONTINUE = "continue"

# # What to do about it
DISMISS_CARD = "dismiss_card"
RESTART_ROUND = "restart_round"
ACCEPT_EXTRACT = "accept_extract"
DECLINE_EXTRACT = "decline_extract"
CONTINUE_WAVE = "continue_wave"
NOTHING = ""

# How often the caller should look. Four template searches is ~70ms, and a checkpoint waits
# for as long as it takes, so there is nothing to win by looking more often than this — and
# the run loop it shares a thread with has blocks to execute.
CHECK_INTERVAL = 1.0

# How long to wait for the second Continue after a checkpoint click. The panel is arriving
# from a click we just made, and the game can take a few seconds to put it up — but nothing
# else can happen until it does, so this is a deadline rather than a settle.
FOLLOWUP_TIMEOUT = 12.0

# A checkpoint stays on screen across several looks. Anything closer together than this is
# the same offer still up, not a new one, so it must not count twice — miscounting here
# extracts a run early, which is the one mistake that cannot be undone.
SIGHTING_DEBOUNCE = 3.0

# Extraction is not entirely ours to decide: in a party the run carries on while the others
# keep going, so an extract click can simply not take. After this many failed attempts stop
# asking and play the run out rather than spending the whole chain at every checkpoint.
EXTRACT_ATTEMPTS_BEFORE_PLAYING_ON = 3

# The offer to accept when a task does not say. 1 = the first one, i.e. the shortest run.
EXTRACT_AFTER_DEFAULT = 1

# Where to click to dismiss the upgrade card: the centre of the pinned 1152x756 client,
# which is the middle of the three cards. Derived from the viewport rather than measured, so
# it deliberately has no Vision editor row — if the cards ever stop being centred it becomes
# a `content/` table with an accessor, and that is a three-line change.
CARD_DISMISS_CLICK = (576, 378)


def extract_after_from_task(raw: object) -> int:
    """Which extract offer to accept, from the task's own field.

    Anything unusable reads as the default rather than failing the task: this arrives from
    settings.json, and a run that refuses to start over a bad number is worse than a run
    that extracts at the first checkpoint.
    """
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return EXTRACT_AFTER_DEFAULT
    return max(1, value)


class ExpeditionMatch:
    """One Expedition match's mid-run state. Built per match, never reused.

    Per match because every count in here is per match: a queue of five Expedition reps is
    five of these, and carrying a sighting count across them would extract the second run
    the moment it started.
    """

    def __init__(self, extract_after: int = EXTRACT_AFTER_DEFAULT) -> None:
        self.extract_after = max(1, int(extract_after))
        self.sightings = 0
        self.failed_extracts = 0
        self._last_sighting_at = 0.0
        self._restaged = False

    @property
    def playing_on(self) -> bool:
        """Has extraction been tried and refused often enough to stop asking?"""
        return self.failed_extracts >= EXTRACT_ATTEMPTS_BEFORE_PLAYING_ON

    def decide(self, seen: set[str], now: float) -> tuple[str, str]:
        """(action, note) for this tick. `seen` is which screens are up right now."""
        # The card first, always. It covers everything else, so acting on a Continue found
        # behind it clicks the card instead and the log reads as a click that did nothing.
        if CARD in seen:
            return (DISMISS_CARD, "upgrade card is up")

        # Then a mid-match Start Game, because it means the board has been reset and the
        # placements are stale — a checkpoint click would be right but premature.
        if START_GAME in seen:
            return (RESTART_ROUND, "Start Game is up again mid-match")

        # Extract before Continue: the checkpoint that offers Extract also offers a Continue
        # beside it, and checking Continue first would decline the offer without ever
        # counting it, so a task asking for the third offer would play forever.
        if EXTRACT in seen:
            first_look = self._last_sighting_at <= 0.0
            if first_look or now - self._last_sighting_at > SIGHTING_DEBOUNCE:
                self.sightings += 1
            self._last_sighting_at = now
            where = f"offer {self.sightings}/{self.extract_after}"
            if self.playing_on:
                return (DECLINE_EXTRACT, f"{where}, extraction isn't taking — playing on")
            if self.sightings >= self.extract_after:
                return (ACCEPT_EXTRACT, f"{where} — extracting")
            return (DECLINE_EXTRACT, f"{where} — not yet")

        if CONTINUE in seen:
            return (CONTINUE_WAVE, "wave Continue is up")

        return (NOTHING, "")

    def note_extract_failed(self) -> int:
        """An accepted extract did not take. Returns how many tries are left."""
        self.failed_extracts += 1
        return max(0, EXTRACT_ATTEMPTS_BEFORE_PLAYING_ON - self.failed_extracts)

    def note_restage(self) -> bool:
        """True the first time the round re-stages, False after.

        A mid-match Start Game sends the placed units off the board and frees their tiles,
        so the Battle phase has to run again — but only once per match. A chatty popup must
        not be able to rewind the phase repeatedly and leave the placements never finishing.
        """
        if self._restaged:
            return False
        self._restaged = True
        return True
