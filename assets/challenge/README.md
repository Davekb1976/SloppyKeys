# assets/challenge

The challenge panel is read by **OCR**, not by templates. Its two useful strings both
change: the daily limit counts down, and the map rotates with an act appended
(`Rose Kingdom Act 3`). There is nothing stable to crop, which is exactly the case a
template cannot cover — a template recognises a *picture* of known text.

Where the boxes are: `content/challenge.py`. How the text is read: `core/ocr.py`
(RapidOCR, pinned in `requirements.txt`). The map name is fuzzy-matched to the five
maps a challenge can land on, so an imperfect read still lands on the right map and
"none of them" stays a possible answer.

## Nothing in this folder is searched. Don't capture anything for it.

**You do not need a star image.** The greyed star is detected by **colour**, not by a
template: `STAR_SATURATION_MIN` in `content/challenge.py`, checked against the 90th
percentile of saturation in the star box. There is no file to name, capture or keep in
sync, and `star_used.png` can be deleted whenever.

All three options were scored on the same real panel, each star box tested coloured and
desaturated:

| method | greyed | active star | gap |
|---|---|---|---|
| grayscale template | 0.999 | 0.999 | **none** |
| colour template | 0.999 | 0.828 | 0.171 |
| saturation p90 | 0 | 242 | 242 |

Matching in this project is grayscale, and colour is the *only* difference between an
active star and a greyed one — so the crop matched **every** star at 0.999. A colour match
does separate, but 0.828 for an active star sits right on the engine's default and would
need a hand-picked threshold plus a colour path the engine doesn't have.

Worse than the bad margin: that check ran *first* and returned before reading the limit,
and the limit is what proves the panel is open (`scan_if_open`). So the panel read as "not
on screen" while sitting wide open, which killed every task-mode run. The star check now
runs **last** and only overrides the state, and the scan reports `star sat NN` per row so
the threshold can be checked against a real panel rather than argued about.

`daily_limit_exhausted.png` — the `0/10` crop — is **removed** by the user's call: it only
covered the OCR engine failing to start, and it could say "used up" without ever telling 7
from 8. The limit is read by OCR or it stays unknown, and an unknown row is still worth
attempting.

Nothing else belongs here. There are deliberately **no** map-name templates: five maps
times seven acts would be 35 crops, all of them stale the next patch.

## `debug/`

A PNG of every measured box, written when a region is previewed. Nothing searches this
folder — it exists so you can see what the macro sees through each box. Delete it whenever.

## Checking it

**Open the challenge panel in game first** — lobby → Play → Challenges, with three
challenges visible. Everything below reads the screen as it is; none of it navigates
anywhere, and none of it fires input. A read pointed at the wrong screen reports plausible
nonsense rather than failing, so the precondition is the instruction.

1. **Settings → OCR → Text Regions.** Each challenge box has a row: `Set` re-measures it by
   drawing on a live capture, `Test` prints the raw text that box reads right now. That
   separates "OCR is broken" from "the box points at the wrong pixels", and it is how the
   first hand-measured set was caught reading the `Hard Mode` tag instead of the map name.
   Re-measure after any patch that moves the UI.
2. **Dashboard → Challenge → Scan.** The real test: per row it logs the parsed limit, the
   matched map with its similarity, and the raw text both came from. A pass needs all three
   rows read *and* identified — an unidentified map means the macro can't pick a config for
   it.

The scan searches for no templates at all, so working OCR is the whole dependency.
