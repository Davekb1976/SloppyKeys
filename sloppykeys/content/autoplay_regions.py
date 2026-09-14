"""OCR boxes read for the Auto Play Settings dialog.

Editable in Settings > Vision (OCR tab), stored in `settings.json` under
`vision_regions` with the `autoplay_` prefix.

Read through `autoplay_presets_region()`, never the default directly.
"""

from __future__ import annotations

import difflib
import re
from typing import Any

# Default region for the Autoplay presets area on 1152x756 viewport:
# (x, y, w, h) in client space. Presets list in modal (777, 470, 372, 179).
AUTOPLAY_PRESETS_DEFAULT_REGION = (777, 470, 372, 179)

_OVERRIDES: dict[str, tuple[int, int, int, int]] = {}

KEY_PREFIX = "autoplay_"


def region_key(kind: str) -> str:
    """The `vision_regions` storage key for one box."""
    return f"{KEY_PREFIX}{kind}"


def apply_region_overrides(overrides: dict[str, tuple[int, int, int, int]]) -> None:
    """Replace the override set. Called at startup and after every edit.

    Takes the whole `vision_regions` dict; keys belonging to other tables simply never
    match. Whole-set replacement rather than a merge, so clearing one really clears it.
    """
    _OVERRIDES.clear()
    _OVERRIDES.update(overrides)


def autoplay_presets_region() -> tuple[int, int, int, int]:
    """The box scanned for Auto Play presets. Honours the user's override."""
    return _OVERRIDES.get(region_key("presets"), AUTOPLAY_PRESETS_DEFAULT_REGION)


def region_specs() -> list[tuple[str, str, tuple[int, int, int, int]]]:
    """(key, label, default) for everything the OCR tab can edit here."""
    return [
        (region_key("presets"), "Autoplay presets", AUTOPLAY_PRESETS_DEFAULT_REGION),
    ]


def norm_preset_text(s: str) -> str:
    """Normalize a preset string: lowercase, stripping whitespace and punctuation."""
    return re.sub(r"[\s\-_.:;,!?\'\"()\[\]{}]+", "", s or "").lower()


def merge_multiline_blocks(blocks: list[Any]) -> list[Any]:
    """Group vertically adjacent lines within the same button card into combined blocks.

    In Roblox, long preset names wrap onto multiple lines inside the button card (e.g.
    'copyofporta' on line 1 and 'ls' on line 2). This groups vertically adjacent
    lines within the same card column so multi-line names match as a single preset.
    """
    candidates = list(blocks)
    n = len(blocks)
    from sloppykeys.core.ocr import TextBlock

    # Form 2-line combinations
    two_lines = []
    for i in range(n):
        b1 = blocks[i]
        b1_y = getattr(b1, "y", 0)
        b1_h = getattr(b1, "height", getattr(b1, "h", 0))
        b1_x = getattr(b1, "x", 0)
        b1_w = getattr(b1, "width", getattr(b1, "w", 0))
        for j in range(n):
            if i == j:
                continue
            b2 = blocks[j]
            b2_y = getattr(b2, "y", 0)
            b2_h = getattr(b2, "height", getattr(b2, "h", 0))
            b2_x = getattr(b2, "x", 0)
            b2_w = getattr(b2, "width", getattr(b2, "w", 0))

            # b1 above b2, vertical gap <= 12 pixels, horizontally aligned in same column
            if b1_y < b2_y and (b2_y - (b1_y + b1_h)) <= 12:
                c1_x = b1_x + b1_w / 2
                c2_x = b2_x + b2_w / 2
                if abs(c1_x - c2_x) < 40:
                    nx = min(b1_x, b2_x)
                    ny = min(b1_y, b2_y)
                    nw = max(b1_x + b1_w, b2_x + b2_w) - nx
                    nh = max(b1_y + b1_h, b2_y + b2_h) - ny
                    comb = TextBlock(
                        text=f"{getattr(b1, 'text', '')} {getattr(b2, 'text', '')}",
                        score=min(getattr(b1, "score", 1.0), getattr(b2, "score", 1.0)),
                        x=nx,
                        y=ny,
                        width=nw,
                        height=nh,
                    )
                    candidates.append(comb)
                    two_lines.append((comb, j))

    # Form 3-line combinations if needed
    for comb, last_j in two_lines:
        b1_y = comb.y
        b1_h = comb.height
        b1_x = comb.x
        b1_w = comb.width
        for k in range(n):
            if k == last_j:
                continue
            b3 = blocks[k]
            b3_y = getattr(b3, "y", 0)
            b3_h = getattr(b3, "height", getattr(b3, "h", 0))
            b3_x = getattr(b3, "x", 0)
            b3_w = getattr(b3, "width", getattr(b3, "w", 0))
            if b1_y < b3_y and (b3_y - (b1_y + b1_h)) <= 12:
                c1_x = b1_x + b1_w / 2
                c3_x = b3_x + b3_w / 2
                if abs(c1_x - c3_x) < 40:
                    nx = min(b1_x, b3_x)
                    ny = min(b1_y, b3_y)
                    nw = max(b1_x + b1_w, b3_x + b3_w) - nx
                    nh = max(b1_y + b1_h, b3_y + b3_h) - ny
                    candidates.append(TextBlock(
                        text=f"{comb.text} {getattr(b3, 'text', '')}",
                        score=min(comb.score, getattr(b3, "score", 1.0)),
                        x=nx,
                        y=ny,
                        width=nw,
                        height=nh,
                    ))

    return candidates


def match_autoplay_preset(target: str, blocks: list[Any]) -> tuple[Any | None, str]:
    """Find the best matching OCR TextBlock for a target autoplay preset name.

    Returns:
        (matched_block, match_description) or (None, reason)

    Handles:
    - Multi-line wrapped preset labels inside button cards (e.g. 'copyofporta' + 'ls')
    - Whitespace and punctuation differences (e.g. 'Preset 5' matching OCR 'Preset5')
    - Case insensitivity (e.g. 'test' matching 'Test' or 'TEST')
    - Token containment (e.g. 'test' matching 'Preset test')
    - Substring containment (strict prefix/coverage validation so 'copy of portals' never matches 'Portals')
    - Fuzzy matching (difflib SequenceMatcher >= 0.75, strictly requiring matching digits)
    """
    if not target or not blocks:
        return None, "empty target or blocks"

    target_clean = norm_preset_text(target)
    if not target_clean:
        return None, "empty normalized target"

    target_digits = re.findall(r"\d+", target_clean)
    all_blocks = merge_multiline_blocks(blocks)

    # 1. Exact normalized match (highest OCR score, then longest candidate text)
    exacts = [b for b in all_blocks if norm_preset_text(getattr(b, "text", "")) == target_clean]
    if exacts:
        best = max(exacts, key=lambda b: (getattr(b, "score", 1.0), len(getattr(b, "text", ""))))
        return best, f"exact (matched '{best.text}')"

    # 2. Token match (all target words appear as distinct tokens in candidate)
    target_words = [w.lower() for w in re.split(r"[\s\-_.:;,!?]+", target or "") if w]
    token_matches = []
    for b in all_blocks:
        cand_text = getattr(b, "text", "")
        cand_clean = norm_preset_text(cand_text)
        cand_digits = re.findall(r"\d+", cand_clean)
        if target_digits != cand_digits:
            continue
        cand_words = [w.lower() for w in re.split(r"[\s\-_.:;,!?]+", cand_text) if w]
        if target_words and all(tw in cand_words for tw in target_words):
            token_matches.append(b)
    if token_matches:
        best = max(token_matches, key=lambda b: (getattr(b, "score", 1.0), len(getattr(b, "text", ""))))
        return best, f"token (matched '{best.text}')"

    # 3. Substring match (normalized, requiring matching digits)
    # Only allowed if:
    # - target is a full substring of candidate (e.g. target="portals", cand="portals_hard")
    # - OR candidate is a valid prefix covering >= 60% of target (e.g. truncated line 1)
    sub_matches = []
    for b in all_blocks:
        cand_text = getattr(b, "text", "")
        cand_clean = norm_preset_text(cand_text)
        if cand_clean == "presets" and target_clean != "presets":
            continue
        cand_digits = re.findall(r"\d+", cand_clean)
        if target_digits != cand_digits:
            continue
        if (len(target_clean) >= 3 and target_clean in cand_clean) or (
            len(cand_clean) >= 4 and target_clean.startswith(cand_clean) and (len(cand_clean) / len(target_clean) >= 0.60)
        ):
            sub_matches.append(b)
    if sub_matches:
        best = max(sub_matches, key=lambda b: (len(norm_preset_text(getattr(b, "text", ""))), getattr(b, "score", 1.0)))
        return best, f"substring (matched '{best.text}')"

    # 4. Fuzzy SequenceMatcher (ratio >= 0.75, strictly requiring matching digits)
    best_fuzzy, best_ratio = None, 0.0
    for b in all_blocks:
        cand_text = getattr(b, "text", "")
        cand_clean = norm_preset_text(cand_text)
        if cand_clean == "presets" and target_clean != "presets":
            continue
        cand_digits = re.findall(r"\d+", cand_clean)
        if target_digits != cand_digits:
            continue
        ratio = difflib.SequenceMatcher(None, target_clean, cand_clean).ratio()
        if ratio > best_ratio:
            best_ratio = ratio
            best_fuzzy = b
    if best_fuzzy is not None and best_ratio >= 0.75:
        return best_fuzzy, f"fuzzy ratio {best_ratio:.2f} (matched '{best_fuzzy.text}')"

    return None, "not found"
