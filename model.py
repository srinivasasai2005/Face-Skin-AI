"""Model loading and inference for Face Skin AI."""

from __future__ import annotations

import io
import pathlib
import platform
import threading
import warnings
from dataclasses import dataclass
from functools import lru_cache

from image_utils import QualityReport, assess_quality, load_image
from security import sha256_hex, verify_sha256

MODEL_PATH = pathlib.Path(__file__).with_name("export.pkl")
# export.pkl is a Python pickle: loading it RUNS CODE. If anyone could swap the file
# (a compromised repo, deploy pipeline or server), they would run code next to every
# user's photo. So we pin its fingerprint and refuse to load anything else.
# After deliberately replacing the model, update this value with:  python model.py
MODEL_SHA256 = "3f92d06cd73cdfb8d09dc8e121ddeca020ae24b20f9d5081b26e24456106cfae"

# Confidence tiers for the top prediction (softmax probability).
HIGH_CONFIDENCE = 0.70
LOW_CONFIDENCE = 0.40

# Only conditions at least this likely get product suggestions, so a 0.06% "Chapped
# Lips" never produces a shopping link for a rosacea photo.
MIN_RECOMMEND_PROB = 0.10
MAX_RECOMMENDATIONS = 3

# fastai's learner mutates internal state during predict(); serialise calls so two
# simultaneous Streamlit sessions cannot interleave them.
_predict_lock = threading.Lock()
# At most this many analyses may be running or waiting for the lock. Beyond that new
# requests are refused immediately instead of piling up (memory and CPU exhaustion).
MAX_QUEUED_ANALYSES = 8
_queue_slots = threading.BoundedSemaphore(MAX_QUEUED_ANALYSES)


class BusyError(RuntimeError):
    """Too many analyses are in flight; the caller should ask the user to retry."""


@dataclass(frozen=True)
class Prediction:
    label: str
    probability: float


@dataclass(frozen=True)
class Analysis:
    """Everything the UI needs, in plain picklable types (safe for st.cache_data)."""

    predictions: list[Prediction]  # all classes, most likely first
    quality: QualityReport

    @property
    def top(self) -> Prediction:
        return self.predictions[0]

    @property
    def confidence_tier(self) -> str:
        p = self.top.probability
        if p >= HIGH_CONFIDENCE:
            return "high"
        if p >= LOW_CONFIDENCE:
            return "moderate"
        return "low"

    @property
    def recommend(self) -> list[Prediction]:
        """Predictions that deserve product suggestions, most likely first."""
        if not self.quality.ok:
            return []
        picked = [p for p in self.predictions if p.probability >= MIN_RECOMMEND_PROB]
        # Always suggest something for the top finding, even when it is diffuse.
        picked = picked or self.predictions[:1]
        return picked[:MAX_RECOMMENDATIONS]


@lru_cache(maxsize=1)
def get_learner():
    """Load the exported fastai learner once per process (82 MB, slow to load)."""
    # The model was exported on Windows; make its pickled paths loadable elsewhere.
    if platform.system() != "Windows":
        pathlib.WindowsPath = pathlib.PosixPath  # type: ignore[misc,assignment]

    from fastai.vision.all import load_learner  # heavy import, keep it lazy

    # Read the file once, check THOSE bytes, then load THOSE bytes. Re-opening the path
    # after the check would let the file be swapped in between (check-then-use race).
    model_bytes = MODEL_PATH.read_bytes()
    verify_sha256(model_bytes, MODEL_SHA256, "The model file")  # raises IntegrityError

    with warnings.catch_warnings():
        # fastai warns on every load that pickles are unsafe; we verified this one above.
        warnings.filterwarnings("ignore", message=".*insecure pickle.*")
        return load_learner(io.BytesIO(model_bytes), cpu=True)


def analyze_bytes(data: bytes) -> Analysis:
    """Full pipeline for raw upload bytes.

    Raises ``ImageError`` for unusable files and ``BusyError`` when overloaded.
    """
    import numpy as np
    from fastai.vision.all import PILImage

    if not _queue_slots.acquire(blocking=False):
        raise BusyError("Too many analyses are running")
    try:
        img = load_image(data)
        quality = assess_quality(img)

        learn = get_learner()
        vocab = list(learn.dls.vocab)
        with _predict_lock, learn.no_bar():
            _, _, probs = learn.predict(PILImage.create(np.asarray(img)))
    finally:
        _queue_slots.release()

    ranked = sorted(
        (Prediction(label, float(p)) for label, p in zip(vocab, probs)),
        key=lambda p: p.probability,
        reverse=True,
    )
    return Analysis(predictions=ranked, quality=quality)


if __name__ == "__main__":
    # Prints the fingerprint to paste into MODEL_SHA256 after deliberately replacing the model.
    print(sha256_hex(MODEL_PATH.read_bytes()))
