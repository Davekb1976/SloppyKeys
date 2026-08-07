"""Runnable checks for the delay fields that show seconds and store milliseconds.

Every timing value on disk is an integer of milliseconds — the macro sleeps in ms and
`configs/`, `routes.json` and `settings.json` all hold ms. Only the field is seconds. Two
things can go wrong quietly: the field's resolution rounds a stored value the moment it is
displayed (at one decimal a 250ms default becomes 300ms), and a unit step's blank delay
becomes "0", which makes `_has_data` treat all 72 steps as worth writing.

No framework, no capture, no input. Offscreen Qt, temp app root:
`.venv\\Scripts\\python.exe tests\\test_seconds_fields.py`
"""

from __future__ import annotations

import json
import os
import sys
import tempfile

os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["QT_ENABLE_HIGHDPI_SCALING"] = "0"
os.environ["QT_SCALE_FACTOR"] = "1"

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtWidgets import QApplication  # noqa: E402

from sloppykeys.content.units import UnitStep  # noqa: E402
from sloppykeys.ui.widgets import SecondsSpin  # noqa: E402
from sloppykeys.ui.window import MainWindow  # noqa: E402

app = QApplication([])

# # A stored value survives being displayed
spin = SecondsSpin(60000)
for ms in (0, 50, 100, 250, 300, 500, 750, 1000, 2500, 3000, 12340, 30000, 60000):
    spin.set_ms(ms)
    assert spin.ms() == ms, f"{ms}ms displayed as {spin.value()}s came back as {spin.ms()}"

# Finer than two decimals resolve snaps to 10ms, and no further. Nothing the app writes
# is affected: every default and step it uses is a multiple of 50ms.
spin.set_ms(12345)
assert spin.ms() == 12350, spin.ms()

# Junk and out-of-range clamp rather than raising — the value comes off disk.
spin.set_ms("nonsense")
assert spin.ms() == 0
spin.set_ms(10**9)
assert spin.ms() == 60000, spin.ms()
spin.set_ms(-500)
assert spin.ms() == 0, spin.ms()

with tempfile.TemporaryDirectory() as root:
    # Never the real app root: the live settings.json holds the private-server link and
    # the webhook URL. `auto_update` off so nothing asks GitHub.
    with open(os.path.join(root, "settings.json"), "w", encoding="utf-8") as handle:
        json.dump({"auto_update": False}, handle)
    window = MainWindow(root)
    detail = window._units_page._detail

    # # Every delay input in the app is one of these, in seconds
    fields = {
        "units wait": detail._wait,
        "units sell_wait": detail._sell_wait,
        "sequence hold": detail._sequence._hold,
        "sequence wait": detail._sequence._wait,
        "route wait": window._route_editor._wait,
        "position hold": window._settings_page.position_editor._hold,
    }
    for name, field in fields.items():
        assert isinstance(field, SecondsSpin), f"{name} is a {type(field).__name__}"
        assert field.suffix() == " s", f"{name} suffix is {field.suffix()!r}"
        assert field.decimals() == 2, f"{name} has {field.decimals()} decimals"
        # A field narrower than its widest value elides silently, so measure rather than
        # eyeball it. Arrows cost ~16px and are hidden on the narrow ones.
        widest = f"{field.maximum():.2f} s"
        arrows = field.buttonSymbols() != field.ButtonSymbols.NoButtons
        needed = field.fontMetrics().horizontalAdvance(widest) + (16 if arrows else 0) + 8
        assert field.width() >= needed, f"{name} clips: {field.width()} < {needed}"

    # # A unit step's delay is stored as text, and stays blank at zero
    step = UnitStep(step=1)
    detail.load(step)
    detail._wait.set_ms(2500)
    assert step.wait == "2500", repr(step.wait)
    detail._sell_wait.set_ms(750)
    assert step.sell_wait == "750", repr(step.sell_wait)
    detail._wait.set_ms(0)
    assert step.wait == "", f"zero must store blank, got {step.wait!r}"

    # Loading a blank step must leave it blank, or every one of the 72 looks like data.
    blank = UnitStep(step=2)
    detail.load(blank)
    assert blank.as_payload() == UnitStep(step=2).as_payload(), blank.as_payload()

print("seconds fields: OK")
