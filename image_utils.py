"""Image loading, normalisation and sanity checks for Face Skin AI.

Everything that touches raw user bytes lives here so the Streamlit app never
sees a half-valid image. The pipeline is:

    bytes -> load_image() -> RGB PIL image (EXIF-rotated, alpha flattened, capped size)
          -> assess_quality() -> QualityReport (does this even look like skin?)
"""

from __future__ import annotations

import io
import logging
import threading
from dataclasses import dataclass, field

import numpy as np
from PIL import Image, ImageOps, UnidentifiedImageError

log = logging.getLogger(__name__)

MAX_UPLOAD_BYTES = 15 * 1024 * 1024  # reject absurdly large uploads early
MAX_SIDE = 1600  # longest side after downscaling (model input is 224px anyway)
MIN_SIDE = 64  # shortest side we consider usable

# --- hostile-input limits ---------------------------------------------------
# The browser's extension filter is not a security control: anyone can rename a file.
# Only these decoders are ever allowed to touch user bytes, decided by file CONTENT.
# (Pillow can also open GIF, TIFF, BMP, WebP, ICO, PPM... and, where Ghostscript is
# installed, PostScript/EPS, a long-standing source of vulnerabilities.)
ALLOWED_FORMATS = ("JPEG", "PNG")
# A tiny file can declare a gigantic canvas (a 435 KB PNG grew the process by ~1 GB in
# testing), so the declared size is checked from the header BEFORE any pixels are
# decoded. JPEGs are decoded at reduced size (draft mode), so they can be larger.
MAX_PIXELS = {"JPEG": 100_000_000, "PNG": 25_000_000}
Image.MAX_IMAGE_PIXELS = 100_000_000  # Pillow's own guard, aligned with the above
# At most this many images are decoded at the same moment, which bounds peak memory.
MAX_CONCURRENT_DECODES = 2
DECODE_WAIT_SECONDS = 8
_decode_slots = threading.BoundedSemaphore(MAX_CONCURRENT_DECODES)

# Skin-tone detection in YCrCb space (classic Chai & Ngan range, widened a little
# so darker skin tones and warm lighting still count as skin).
_CR_RANGE = (133, 180)
_CB_RANGE = (70, 130)
# Calibrated on ~450 labelled face photos from the project datasets: at 0.05 only
# 0.4% of genuine photos are flagged, while a higher value starts to catch dim
# or dark-skinned faces. Do not raise it without re-measuring.
MIN_SKIN_RATIO = 0.05
MIN_CONTRAST = 12.0  # luminance std-dev; below this the image is basically flat
GRAYSCALE_SATURATION = 10  # mean HSV saturation (0-255) below this = black & white


class ImageError(ValueError):
    """Raised for uploads we cannot use. The message is safe to show to users."""


@dataclass(frozen=True)
class QualityReport:
    skin_ratio: float
    contrast: float
    ok: bool
    reasons: list[str] = field(default_factory=list)


def _decode(data: bytes) -> Image.Image:
    """Decode with the strictest settings. Raises :class:`ImageError` on anything odd."""
    friendly = ImageError(
        "This file could not be read as an image. Please upload a JPG or PNG photo."
    )
    try:
        # formats= restricts which decoders may run; content decides, not the filename.
        img = Image.open(io.BytesIO(data), formats=ALLOWED_FORMATS)
        fmt, (width, height) = img.format, img.size  # header only, no pixels decoded yet
        if width * height > MAX_PIXELS.get(fmt, 0):
            raise ImageError(
                f"This image is too large to process ({width * height / 1e6:.0f} megapixels). "
                f"Please use a photo under {MAX_PIXELS[fmt] // 1_000_000} megapixels."
            )
        if fmt == "JPEG":
            # Let the decoder produce a smaller image straight away instead of a full-size one.
            scale = MAX_SIDE / max(width, height)
            if scale < 1:
                img.draft("RGB", (max(1, int(width * scale)), max(1, int(height * scale))))
        img.load()  # force full decode so truncated files fail here, not later
        return img
    except ImageError:
        raise  # our own message; ImageError subclasses ValueError, so don't mask it below
    except Image.DecompressionBombError:
        raise ImageError("This image has too many pixels to process safely.") from None
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError):
        raise friendly from None
    except Exception:  # malformed input must never crash a session; details go to the log only
        log.warning("Unexpected decoder failure on an upload", exc_info=True)
        raise friendly from None


def load_image(data: bytes) -> Image.Image:
    """Decode user bytes into a clean RGB image or raise :class:`ImageError`."""
    if not data:
        raise ImageError("The file is empty.")
    if len(data) > MAX_UPLOAD_BYTES:
        raise ImageError(
            f"The file is too large ({len(data) / 1_048_576:.1f} MB). "
            f"Please upload an image under {MAX_UPLOAD_BYTES // 1_048_576} MB."
        )

    if not _decode_slots.acquire(timeout=DECODE_WAIT_SECONDS):
        raise ImageError("The service is busy right now. Please try again in a moment.")
    try:
        img = _decode(data)
    finally:
        _decode_slots.release()

    # Phones store rotation in EXIF; without this the face may be sideways.
    img = ImageOps.exif_transpose(img)

    # RGBA / LA / palette-with-transparency: flatten onto white. A plain
    # convert("RGB") would leave transparent pixels black, and feeding RGBA to
    # the network crashes it (4 channels vs 3).
    if img.mode in ("RGBA", "LA") or (
        img.mode == "P" and "transparency" in img.info
    ):
        rgba = img.convert("RGBA")
        background = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
        img = Image.alpha_composite(background, rgba).convert("RGB")
    else:
        img = img.convert("RGB")  # also handles CMYK, L, P, I;16 ...

    if min(img.size) < MIN_SIDE:
        raise ImageError(
            f"The image is too small ({img.width}x{img.height}px). "
            f"Please use a photo at least {MIN_SIDE}px on each side."
        )

    if max(img.size) > MAX_SIDE:
        img.thumbnail((MAX_SIDE, MAX_SIDE), Image.LANCZOS)

    return img


def assess_quality(img: Image.Image) -> QualityReport:
    """Cheap heuristic check that the picture plausibly shows skin.

    This is deliberately lenient: close-ups of a cheek or nose contain no face
    outline, so a face detector would wrongly reject them, and colour-based skin
    detection is biased against dark skin and dim light. We only flag images that
    are flat/blank or colour photos with almost no skin-coloured pixels. Black &
    white photos skip the colour test because it cannot be evaluated on them.

    Known limit: skin-coloured non-skin subjects (e.g. a tabby cat or food) pass.
    The confidence tiers and the disclaimer in the UI cover that case.
    """
    small = img.copy()
    small.thumbnail((160, 160))
    ycc = np.asarray(small.convert("YCbCr"), dtype=np.float32)
    y, cb, cr = ycc[..., 0], ycc[..., 1], ycc[..., 2]

    skin = (
        (cr >= _CR_RANGE[0])
        & (cr <= _CR_RANGE[1])
        & (cb >= _CB_RANGE[0])
        & (cb <= _CB_RANGE[1])
    )
    skin_ratio = float(skin.mean())
    contrast = float(y.std())
    saturation = float(np.asarray(small.convert("HSV"))[..., 1].mean())
    is_grayscale = saturation < GRAYSCALE_SATURATION

    reasons: list[str] = []
    if contrast < MIN_CONTRAST:
        reasons.append("the image looks blank or has almost no detail")
    if not is_grayscale and skin_ratio < MIN_SKIN_RATIO:
        reasons.append("very little skin was detected in the photo")

    return QualityReport(skin_ratio, contrast, not reasons, reasons)
