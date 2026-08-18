---
name: game-window
description: Position, cover, reveal or capture the live Roblox window that rides on top of the app. Covers the inverted topmost layering, the follow loop, why a modal shows the empty slot, hiding the game off the Dashboard, and the measured dead ends (cut-out hole, SetParent, colour key, caption drag, Tauri). Use when the game sits in the wrong place or off-screen, when a capture returns the wrong pixels, when something must appear over the game slot, or when changing window size, DPI or topmost state.
---
# The Roblox window on top of the app

`coding-standards.md` keeps the four invariants resident (`IsIconic` guard, `ClientToScreen`
origin, slot from the page, reveal before capture) and the dead-end names. This is the evidence
behind them. Everything here was measured on WebView2; do not re-derive it.

## The layering is inverted

Roblox stays its **own top-level window** — never reparented. It rides the **topmost** band with
its frame stripped, positioned over the game slot, *above* our normal-band window. Visually it sits
inside the UI; structurally nothing is parented, so quitting the app cannot take the game down.

The frame is restored on the way out
(`roblox_window.py::position_window_to_client_rect`), and `bridge.py::_follow_loop` keeps position
in step as our window moves.

Consequences that surprise people:

- **`IsIconic` guards every position sync.** A minimized window reports coordinates near −32000;
  without the guard the sync flings Roblox off-screen and it looks lost.
- **The client origin comes from `ClientToScreen`**, never arithmetic on window rects — border and
  caption widths are not what you assume under DWM.
- **The slot position comes from the page**, which reports its placeholder's
  `getBoundingClientRect()` to the backend. A constant here drifts from the stylesheet silently.
- **Window size is set from Win32 *after* the frame comes off**, clamped to the work area.
  pywebview sizes the form while it still has a frame, so the client area lands short and the log
  panel clips. The window opens centred on the **primary** screen — a shorter secondary clips it.

## Covering, hiding, revealing

- **A modal covers the game and shows the empty slot behind itself.** The game paints over all DOM
  content, so there is no live game behind a modal. Faking one by grabbing a still per modal open
  was built and removed: it cost a capture and a reveal for a picture nobody needed. Design modals
  to own their space instead.
- **Off the Dashboard the game is covered, not hidden.** `set_topmost(False)` alone is not enough —
  `HWND_NOTOPMOST` lands it at the top of the *normal* band, still above the page. Tuck it directly
  beneath our window with `set_window_below`. `SW_HIDE` works but removes its taskbar button, which
  users read as the game having vanished.
- **A capture must reveal the game first**, and that happens inside the bridge (`_game_revealed`),
  not at each call site. mss grabs a screen *rectangle*, so a covered window yields our own pixels.
  A capture called from the page must complete **before** the call returns, or the page switches
  screens and hides the game first — an un-awaited `set_game_visible(false)` landing inside the
  backend's own reveal is how the point picker captured our own UI.

## Dead ends — measured, do not retry

- **The cut-out hole.** The old Qt window punched one with `QWidget.setMask` and put Roblox behind.
  On WebView2 `SetWindowRgn` is *accepted* and `GetWindowRgnBox` reports the hole, but WebView2
  composites through DirectComposition, which ignores GDI window regions — the page keeps painting
  over the slot. This is why the layering is inverted instead.
- **`SetParent` reparenting** — DPI and focus flakiness, and the child dies with the parent.
- **Colour-key transparency (`LWA_COLORKEY`)**.
- **Handing the frameless window to the OS caption-drag loop with `WM_NCLBUTTONDOWN`** — WebView2
  holds the mouse capture in its own process, so the move loop never sees a mouse move.
- **The Tauri 2 / WebView2 stack** — DirectComposition can't host the window.
- **Process DPI-awareness variants** — byte-identical rects.

## Before changing anything here

Measure. Write a throwaway probe that prints the real rects and DPI, read the numbers, then form
the hypothesis — and read the attribute back afterwards, because many Win32/DWM calls silently
no-op. You cannot see the rendered result: the user is the sensor for anything visual.

**Never change the 1152×756 viewport** to fix a layout problem. Every coordinate, template and
recorded route in the repo was captured at that size.
