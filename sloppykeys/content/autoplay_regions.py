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


def match_autoplay_preset(target: str, blocks: list[Any]) -> tuple[Any | None, str]:
    """Find the best matching OCR TextBlock for a target autoplay preset name.

    Returns:
        (matched_block, match_description) or (None, reason)

    Handles:
    - Whitespace and punctuation differences (e.g. 'Preset 5' matching OCR 'Preset5')
    - Case insensitivity (e.g. 'test' matching 'Test' or 'TEST')
    - Token containment (e.g. 'test' matching 'Preset test')
    - Substring containment (with strict digit validation so 'Preset 5' never matches 'Preset 2')
    - Fuzzy matching (difflib SequenceMatcher >= 0.75, strictly requiring matching digits)
    """
    if not target or not blocks:
        return None, "empty target or blocks"

    target_clean = norm_preset_text(target)
    if not target_clean:
        return None, "empty normalized target"

    target_digits = re.findall(r"\d+", target_clean)

    # 1. Exact normalized match (takes highest OCR confidence if multiple)
    exacts = [b for b in blocks if norm_preset_text(getattr(b, "text", "")) == target_clean]
    if exacts:
        best = max(exacts, key=lambda b: getattr(b, "score", 1.0))
        return best, f"exact (matched '{best.text}')"

    # 2. Token match (e.g. 'test' as a distinct word in candidate text)
    target_words = [w.lower() for w in re.split(r"[\s\-_.:;,!?]+", target or "") if w]
    token_matches = []
    for b in blocks:
        cand_text = getattr(b, "text", "")
        cand_clean = norm_preset_text(cand_text)
        cand_digits = re.findall(r"\d+", cand_clean)
        if target_digits != cand_digits:
            continue
        cand_words = [w.lower() for w in re.split(r"[\s\-_.:;,!?]+", cand_text) if w]
        if target_words and all(tw in cand_words for tw in target_words):
            token_matches.append(b)
    if token_matches:
        best = max(token_matches, key=lambda b: getattr(b, "score", 1.0))
        return best, f"token (matched '{best.text}')"

    # 3. Substring match (normalized, requiring same digits)
    sub_matches = []
    for b in blocks:
        cand_text = getattr(b, "text", "")
        cand_clean = norm_preset_text(cand_text)
        # Never match the section header "presets" unless target specifically wants "presets"
        if cand_clean == "presets" and target_clean != "presets":
            continue
        cand_digits = re.findall(r"\d+", cand_clean)
        if target_digits != cand_digits:
            continue
        if (len(target_clean) >= 3 and target_clean in cand_clean) or (
            len(cand_clean) >= 3 and cand_clean in target_clean
        ):
            sub_matches.append(b)
    if sub_matches:
        best = max(sub_matches, key=lambda b: getattr(b, "score", 1.0))
        return best, f"substring (matched '{best.text}')"

    # 4. Fuzzy SequenceMatcher (ratio >= 0.75, requiring matching digits)
    best_fuzzy, best_ratio = None, 0.0
    for b in blocks:
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
