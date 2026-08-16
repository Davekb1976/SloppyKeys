# images/

Search templates. Read this before capturing another one — the two mistakes below cost a
whole debugging session each, and neither of them looks like a capture problem from the log.

## 1. Never crop from a Roblox screenshot. Capture from the macro's own view.

`cv2.matchTemplate` is **not scale invariant**. A template even 15% off in pixel size cannot
match, and it fails *intermittently* rather than cleanly — which reads as "the tolerance is
wrong" and sends you tuning a number that can never help.

Measured on this project's own images against the live client:

| template | at 1.00x | best | at scale |
|---|---|---|---|
| `lobby/play.png` | 0.545 | 0.798 | **0.80x** |
| `lobby/events.png` | 0.492 | 0.844 | **0.86x** |
| `gamemodes/story.png` | 0.411 | 0.466 | **0.80x** |
| `match/start_game.png` | 0.998 | 0.998 | 1.00x ✓ |
| `match/settings.png` | 1.000 | 1.000 | 1.00x ✓ |

`0.80` is exactly `1/1.25` — a **125% display-scaling factor**. Roblox's own screenshot
function multiplies its output by the Windows display scale, so anything cropped from it is
the wrong size for the live 800×599 client. The two templates that match perfectly were
captured from the app's own capture path; the rest were not.

### The workflow that can't go wrong

1. Make sure Roblox's monitor is at **100%** scaling (see below). Nothing else matters until
   this is true.
2. Get the screen you want a template from up in the viewport.
3. **Macro Tester → VISION → Dump client for cropping.** It copies the client straight to the
   **clipboard** and also writes `images/debug/client.png`, both through the same mss path
   `find_until` matches against, so the pixel size is right by construction. It warns if the
   monitor isn't at 100%.
4. **Ctrl+V into your editor**, crop, save at **24 or 32-bit**. (The file is there too if you
   prefer opening it.)
5. **Macro Tester → VISION → Check template scale** to confirm it reads 1.00x.

The screenshot *tool* is not really the issue — any capture of the framebuffer (Snipping
Tool, PrintScreen) gives the same pixels **when the monitor is at 100%**. Roblox's own
screenshot is worse than those because it additionally multiplies by the display scale. But
on a scaled monitor every route is wrong, which is why step 1 comes first and step 3 exists.

### Why the scale is off: Roblox on a monitor above 100% display scaling

Roblox is per-monitor DPI aware, so on a scaled display it draws its UI **larger in physical
pixels** — and it has a standing quality regression there, so the result is bigger *and*
blurry. That is the "one monitor looks clearer than the other" effect, and it is in the
captured pixels, not just on the glass: the same `Start Game` button comes back with different
letter spacing on each monitor.

At 125% a button is 1.25x its calibrated size, so a template cropped there peaks at
`1/1.25 = 0.80x` — exactly what was measured — and every stored coordinate misses too.

**Keep Roblox on a display set to 100%** (Windows Settings → System → Display → Scale).
Everything in this project is calibrated at 100%: the pinned 800×599 client, every coordinate
in `content/`, every template's pixel size. The app warns in the log when Roblox is on a
scaled monitor, and **Geometry + capture report** prints `game monitor scaling: N%`.

## 2. Bit depth: prefer 24/32-bit, but it is a **minor** issue

Saving at a reduced colour depth runs quantization (palette reduction, sometimes dithering),
which rewrites pixel values. Measured on this project's own templates, pasted into a frame so
depth was the only variable:

| export | worst score drop | median |
|---|---|---|
| 256 colours (normal 8-bit) | **0.0003** | 0.0000 |
| 16 colours | ~0.010 | — |
| 4 colours + dithering | **0.105** | 0.037 |
| wrong *scale* (for comparison) | **0.253** | — |

So a normal 8-bit save is harmless — these crops have few colours to begin with, and matching
is grayscale and mean-normalised, which absorbs tiny shifts. Three files here are palette
exports (`match/back_lobby.png`, `match/return_lobby_confirm.png`, `match/settings.png`) and
they still match at 1.000.

Set 24/32-bit anyway, because it costs nothing and removes a variable — Auto choosing a *very*
low depth on a simple crop is the one case that would bite (0.10 is a real dent when the
threshold is 0.70). But if a template is failing, **this is not why**. Check the scale first;
that is worth ~250x more.

## 3. There is no tolerance to tune

The match threshold is a fixed **0.70** and is not configurable. A user-facing "match
tolerance" existed and was removed: it drifted to 0.95 (a good match scores 0.95-1.00, so
almost nothing passed) and to 0.57 (false matches), and each value broke the next run while
looking like a bad template.

A failed search logs the score it reached — `Play not found (best 0.66 < 0.70)`. Read that
number: it says whether the crop is nearly right or nothing like the screen. It is never a
reason to lower a threshold, because the fix for a template that can't reach 0.70 is to
recapture it.

## Checking your templates


**Macro Tester → VISION → Check template scale**, standing on the screen the templates belong
to. It matches every template from 0.80x to 1.26x and reports any whose best score is not at
1.00x, plus any 8-bit PNG. A template that isn't on the current screen is reported as
inconclusive rather than broken, so run it once per screen.

Per-folder notes: `lobby/`, `gamemodes/`, `stages/`, `match/`, `events/`, `challenge/` each
have their own README for what belongs there.
