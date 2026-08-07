"""Tunable timing values.

Stored in settings.json under "delays" (alongside the other settings, without
disturbing them). Editable from Settings > Delays; applied live to the navigator.
"""

from __future__ import annotations

import os

from .store import read_json, update_json

SETTINGS_FILE = "settings.json"
DELAYS_KEY = "delays"

# key -> (label, default seconds), in display order.
# `join_wait` was removed, not renamed: it slept 5s after the lobby Start click, directly
# in front of `wait_for_match_ready`'s 60s poll for the same screen. A stored value is
# ignored harmlessly — `DelaysStore.all` only reads keys this spec declares.
DELAY_SPEC: dict[str, tuple[str, float]] = {
    # Blind wait after a click whose result *cannot* be image-verified — a fixed
    # coordinate click, or a scroll. It has nothing to do with how image search
    # works (that is `search_timeout` + polling), despite the old label saying
    # "image search cooldown"; the key is kept for saved settings.
    # Steps followed by an image search don't use it at all: the search polls until
    # it finds the screen, which is a better wait than any fixed number.
    "image_search_cooldown": ("Wait after an unverifiable click", 0.8),
    # How long the post-match panel gets to finish fading in before `change_gamemode`
    # clicks it. Paid on **both** paths now, searched and fallback: matching
    # `win_change.png` proves the panel is being drawn, not that it is interactive —
    # normalized correlation ignores a uniform brightness scale, so a half-faded panel
    # still scores ~0.93. Clicking then gets the click swallowed, and the failure appears
    # one step later as "Challenge card not found (best 0.42)". Raise this if that recurs;
    # it is the only wait that can help, because no score threshold can see the fade.
    "panel_fade_wait": ("Wait for a panel to fade in", 1.0),
    # How long a search keeps looking for an image it expects. Covers menus that
    # slide/fade in: too low and the macro gives up (or scrolls) before the screen
    # has finished animating.
    "search_timeout": ("Image search wait", 6.0),
    # How long the camera step holds I (zoom right in) and then O (zoom right out). It is
    # **two** holds, so this is the single biggest cost in a run's startup: 3.0s here is ~6s
    # of the ~8s sequence. It has to be long enough to reach each extreme — Roblox zooms at
    # a fixed rate, so "long enough" is a property of that rate, not of this machine, and a
    # value that stops short leaves the camera at the wrong pitch and every stored placement
    # coordinate pointing at the wrong ground. Lower it in steps and watch the camera; if
    # placements start drifting, it is too low.
    "camera_zoom": ("Camera zoom hold (each way)", 3.0),
    # Pause after each placement click/keypress before the next one. Too low and
    # the unit panel hasn't reacted yet when the following key arrives. A placement
    # step pays this four to six times, so it is the biggest single lever on how
    # fast a step feels.
    "placement_settle": ("Placement settle", 0.25),
    # Wait between spotting the win/loss screen and grabbing the Discord
    # screenshot. The result banner matches as soon as it appears, but the rewards
    # under it animate in afterwards, so a capture with no wait catches a
    # half-drawn panel. Raise it if the rewards are still missing.
    "result_screenshot_delay": ("Result screenshot delay", 1.0),
    # How long an Events task waits for the lobby after firing the private-server deep
    # link. Not a settle — a **deadline** on a poll that returns the instant the lobby's
    # Events button appears, so a generous value costs nothing when the join is quick. It
    # has to cover a cold client start: Roblox launching, updating, loading the place and
    # spawning you in, which on a slow disk or connection is minutes rather than seconds.
    # This is the one wait a user cannot shorten by tuning anything else, because none of
    # it is ours to speed up.
    "lobby_rejoin_wait": ("Wait for the lobby after re-joining", 150.0),
}
DEFAULTS: dict[str, float] = {key: default for key, (_label, default) in DELAY_SPEC.items()}


class DelaysStore:
    def __init__(self, app_root: str) -> None:
        self._path = os.path.join(app_root, SETTINGS_FILE)

    def all(self) -> dict[str, float]:
        raw = read_json(self._path).get(DELAYS_KEY, {})
        result = dict(DEFAULTS)
        if isinstance(raw, dict):
            for key in DEFAULTS:
                try:
                    result[key] = float(raw[key])
                except (KeyError, TypeError, ValueError):
                    pass
        return result

    def set(self, key: str, value: float) -> None:
        if key not in DEFAULTS:
            return
        # Atomic read-modify-write: `settings.json` is shared with the task queue, the
        # stats counters (written from the macro worker), keybinds and start positions.
        def mutate(payload: dict) -> None:
            delays = payload.get(DELAYS_KEY)
            if not isinstance(delays, dict):
                delays = {}
            delays[key] = float(value)
            payload[DELAYS_KEY] = delays

        update_json(self._path, mutate)
