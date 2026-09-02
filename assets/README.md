# assets/

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
the wrong size for the live client. The two templates that match perfectly were
captured from the app's own capture path; the rest were not.

### The workflow that can't go wrong

1. Make sure Roblox's monitor is at **100%** scaling (see below). Nothing else matters until
   this is true.
2. Get the screen you want a template from up in the viewport.
3. **Image Manager (F6)** → find the card for the template, press **+**. It grabs the client
   through the same mss path `find_until` matches against, so the pixel size is right by
   construction, then opens the crop view.
4. **Drag the crop** and save. It writes to the exact filename the card names, creating the
   folder if it needs to — there is no chance of landing in the wrong place.

Nothing in this route can produce the wrong scale, which is why it replaced dumping the
client to the clipboard and cropping in an editor: that route worked, but every step was a
chance to save from the wrong source.

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
Everything in this project is calibrated at 100%: the pinned 1152×756 client, every coordinate
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
low depth on a simple crop is the one case that would bite (0.10 is a real dent against a
0.80 threshold). But if a template is failing, **this is not why**. Check the scale first;
that is worth ~250x more.

## 3. The tolerance is per template, and the default is 0.80

Each template carries its own threshold, on its Image Manager card. The default is **0.80**,
raised from 0.70 after 0.70 was seen accepting the wrong screen where two templates look
alike but mean different things. That trade is deliberate: a false match acts on a screen
that isn't there, while a missed one only retries.

There is deliberately **no global tolerance**. That setting existed and was removed — it
drifted to 0.95 (a good match scores 0.95-1.00, so almost nothing passed) and to 0.57 (false
matches everywhere), and each value broke the next run while looking like a bad template.
Per-template is the replacement, so one stubborn image can't drag the rest down.

A failed search logs the score it reached — `Play not found (best 0.66 < 0.80)`. Read that
number: it says whether the crop is nearly right or nothing like the screen. It is rarely a
reason to lower that template's threshold, because a crop that can't reach the default is
usually the wrong crop; recapture it first.

## Checking your templates

**Image Manager (F6) → the card's `Test` button**, standing on the screen that template
belongs to. It searches the live client and logs either the score and where it matched, or
the best score it reached and the threshold that rejected it. That number is the diagnosis:
`best 0.66 < 0.80` means the crop is nearly right, `best 0.08` means this isn't the screen.

**There is no scale checker.** The old one swept every template from 0.80x to 1.26x and
reported any whose best score peaked somewhere other than 1.00x — the check that caught the
mistake at the top of this file. It went with the Macro Tester and has no replacement, so
step 1 and step 3 above are now the whole defence: capture at 100% scaling, through the
app's own capture path.

Per-folder notes: `lobby/`, `gamemodes/`, `stages/`, `match/`, `events/`, `challenge/` each
have their own README for what belongs there.
