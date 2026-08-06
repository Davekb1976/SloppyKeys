"""Text recognition for fixed on-screen boxes, via RapidOCR (ONNX Runtime).

Why OCR at all, when this project matches templates everywhere else: a template
recognises a *picture* of known text. The challenge panel's text is not known ahead
of time — the daily limit counts down and the map rotates with the act appended — so
there is nothing stable to crop. That is the case OCR exists for here.

Why RapidOCR (`rapidocr` + `onnxruntime`, Apache-2.0 / MIT):

- pip-only. Tesseract would mean every user installing a separate binary and having
  it on PATH, which is a support burden for a distributed app.
- The ONNX models ship **inside the wheel**, so recognition is offline and
  deterministic — nothing is fetched at runtime.
- No PyTorch. EasyOCR and PaddleOCR pull ~2GB for the same job.
- `rapidocr-onnxruntime` (the 1.x name) caps at Python <3.13 and this venv is 3.14,
  so 3.x under the `rapidocr` name is the only version that installs here.

Measured on this machine, recognition-only on real game crops: 9-20ms per box after
warm-up, ~1s one-off engine init. Small stylised text comes back *approximately* —
`start_game.png` reads as "Start Ge" — so callers must never require an exact string.
Match against a closed set (see `macro/challenge.match_map_name`) or parse digits with
the usual confusions folded in. `read_line` returns the confidence alongside the text
so a caller can tell a weak read from a clean one.

Recognition-only (`use_det=False`): the boxes are fixed and single-line, so running
detection would only add a way to fail. Everything is upscaled to `REC_HEIGHT`
because the recogniser is trained at that height — measured, it lifted "Events" from
0.87 to 0.96 and fixed a character in "Start Game".

No Qt, no input, safe on a worker thread. Nothing here touches the game.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import cv2  # type: ignore[import-not-found]
import numpy as np  # type: ignore[import-not-found]

# What the PP-OCR recogniser is trained at. Crops are scaled to this height.
REC_HEIGHT = 48
# Below this, treat a read as "nothing there" rather than as text.
MIN_SCORE = 0.30

INSTALL_HINT = "pip install -r requirements.txt (needs rapidocr and onnxruntime)"


@dataclass
class TextRead:
    text: str = ""
    score: float = 0.0

    @property
    def ok(self) -> bool:
        return bool(self.text) and self.score >= MIN_SCORE


@dataclass
class TextBlock:
    """One detected line and where it sits, in the captured image's coordinates."""

    text: str
    score: float
    x: int
    y: int
    width: int
    height: int

    def region(self) -> tuple[int, int, int, int]:
        """As the project's `(x, y, w, h)` region tuple, ready to paste into a table."""
        return (self.x, self.y, self.width, self.height)


class OcrReader:
    """One lazily-built RapidOCR engine.

    Lazy because init costs ~1s and loads three ONNX models: an app launch that never
    opens the challenge panel should not pay for it. Built once and reused, since the
    per-call cost after that is milliseconds.
    """

    def __init__(self) -> None:
        self._engine: Any | None = None
        self._error = ""
        self._tried = False

    # # Availability
    def available(self) -> tuple[bool, str]:
        """(ready, message). Building the engine is the only honest way to answer —
        the import can succeed and the models still fail to load."""
        self._ensure()
        if self._engine is not None:
            return (True, "RapidOCR ready")
        return (False, self._error or "OCR unavailable")

    def _ensure(self) -> None:
        if self._tried:
            return
        self._tried = True
        try:
            # Local import: the app must still start and run every non-OCR feature if
            # the dependency is missing, reporting it instead of failing at launch.
            from rapidocr import RapidOCR  # type: ignore[import-not-found]
        except ImportError as exc:
            self._error = f"RapidOCR not installed ({exc}) — {INSTALL_HINT}"
            return
        # RapidOCR logs three INFO lines per model at init. Useful once, noise in a
        # macro log, and it writes to stdout before our own logging is set up.
        logging.getLogger("RapidOCR").setLevel(logging.WARNING)
        try:
            self._engine = RapidOCR()
        except Exception as exc:  # model load / onnxruntime provider failures
            self._error = f"Could not start RapidOCR: {exc}"

    # # Reading
    def read_line(self, image: np.ndarray | None) -> TextRead:
        """Recognise one line of text in a BGR crop.

        Returns an empty read rather than raising: this sits in a macro step, and a
        failed read is a decision the caller has to make, not an exception to unwind.
        """
        self._ensure()
        if self._engine is None or image is None or image.size == 0:
            return TextRead()
        prepared = self._prepare(image)
        if prepared is None:
            return TextRead()
        try:
            result = self._engine(prepared, use_det=False, use_cls=False, use_rec=True)
        except Exception as exc:  # a bad frame must not take the run down
            self._error = f"OCR failed: {exc}"
            return TextRead()

        texts = getattr(result, "txts", None) or ()
        scores = getattr(result, "scores", None) or ()
        text = str(texts[0]).strip() if texts else ""
        score = float(scores[0]) if scores else 0.0
        return TextRead(text=text, score=score)

    def read_all(self, image: np.ndarray | None) -> list[TextBlock]:
        """Every line of text in a larger image, each with where it was found.

        Detection *on*, unlike `read_line`: this is the diagnostic mode. Point it at a
        whole panel and it answers "what text is here, and at which coordinates",
        which is how a measured box gets corrected against reality instead of against
        a screenshot someone eyeballed. Boxes come back in the image's own coordinate
        space, so a caller that captured a client region can offset them.
        """
        self._ensure()
        if self._engine is None or image is None or image.size == 0:
            return []
        prepared = image
        if prepared.ndim == 2:
            prepared = cv2.cvtColor(prepared, cv2.COLOR_GRAY2BGR)
        elif prepared.shape[2] == 4:
            prepared = cv2.cvtColor(prepared, cv2.COLOR_BGRA2BGR)
        try:
            result = self._engine(prepared)
        except Exception as exc:
            self._error = f"OCR failed: {exc}"
            return []

        texts = getattr(result, "txts", None) or ()
        scores = getattr(result, "scores", None) or ()
        boxes = getattr(result, "boxes", None)
        blocks: list[TextBlock] = []
        for index, text in enumerate(texts):
            score = float(scores[index]) if index < len(scores) else 0.0
            left = top = width = height = 0
            if boxes is not None and index < len(boxes):
                points = np.array(boxes[index]).reshape(-1, 2)
                left, top = int(points[:, 0].min()), int(points[:, 1].min())
                width = int(points[:, 0].max()) - left
                height = int(points[:, 1].max()) - top
            blocks.append(
                TextBlock(
                    text=str(text).strip(),
                    score=score,
                    x=left,
                    y=top,
                    width=width,
                    height=height,
                )
            )
        blocks.sort(key=lambda block: (block.y, block.x))
        return blocks

    def _prepare(self, image: np.ndarray) -> np.ndarray | None:
        """Upscale to the recogniser's training height and force 3-channel BGR."""
        if image.ndim == 2:
            image = cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
        elif image.shape[2] == 4:
            image = cv2.cvtColor(image, cv2.COLOR_BGRA2BGR)
        height = image.shape[0]
        if height <= 0:
            return None
        if height != REC_HEIGHT:
            scale = REC_HEIGHT / height
            # Cubic, not nearest: the source is antialiased game text, and blocky
            # upscaling measurably lost characters.
            image = cv2.resize(image, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
        return image
