import io

import numpy as np
import pytest
from PIL import Image

from image_utils import (
    MAX_SIDE,
    MAX_UPLOAD_BYTES,
    ImageError,
    assess_quality,
    load_image,
)


def _encode(img: Image.Image, fmt="PNG", **kw) -> bytes:
    buf = io.BytesIO()
    img.save(buf, fmt, **kw)
    return buf.getvalue()


def _skin(size=(200, 200)) -> Image.Image:
    """Skin-toned patch with shading, like a lit face (flat colour is 'blank')."""
    base = np.array([205, 150, 125], dtype=np.float32)
    shade = np.linspace(0.55, 1.1, size[1], dtype=np.float32)[None, :, None]
    arr = np.clip(base * np.broadcast_to(shade, (*size, 3)), 0, 255).astype("uint8")
    return Image.fromarray(arr)


@pytest.mark.parametrize("mode", ["RGBA", "LA", "L", "CMYK", "P", "I;16"])
def test_every_mode_becomes_rgb(mode):
    src = _skin()
    img = src.convert("L").convert("I;16") if mode == "I;16" else src.convert(mode)
    # Only JPEG and PNG are accepted formats; CMYK is only realistic as a JPEG.
    out = load_image(_encode(img, "JPEG" if mode == "CMYK" else "PNG"))
    assert out.mode == "RGB"


def test_transparent_pixels_become_white_not_black():
    rgba = Image.new("RGBA", (100, 100), (0, 0, 0, 0))
    out = load_image(_encode(rgba))
    assert out.getpixel((50, 50)) == (255, 255, 255)


def test_exif_rotation_is_applied():
    img = Image.new("RGB", (200, 100), "red")
    exif = img.getexif()
    exif[274] = 6  # rotate 90 CW when displayed
    out = load_image(_encode(img, "JPEG", exif=exif))
    assert out.size == (100, 200)


@pytest.mark.parametrize("data", [b"", b"not an image", b"\xff\xd8\xff garbage"])
def test_garbage_raises_friendly_error(data):
    with pytest.raises(ImageError):
        load_image(data)


def test_truncated_file_raises_friendly_error():
    data = _encode(_skin(), "JPEG")
    with pytest.raises(ImageError):
        load_image(data[: len(data) // 2])


def test_too_small_and_too_large():
    with pytest.raises(ImageError, match="too small"):
        load_image(_encode(Image.new("RGB", (12, 12))))
    with pytest.raises(ImageError, match="too large"):
        load_image(b"0" * (MAX_UPLOAD_BYTES + 1))


def test_huge_image_is_downscaled():
    out = load_image(_encode(Image.new("RGB", (MAX_SIDE * 2, 900), (200, 150, 120)), "JPEG"))
    assert max(out.size) == MAX_SIDE


def test_skin_photo_passes():
    assert assess_quality(_skin()).ok


def test_blank_image_is_flagged():
    q = assess_quality(Image.new("RGB", (200, 200), "white"))
    assert not q.ok and any("blank" in r for r in q.reasons)


def test_non_skin_colour_photo_is_flagged():
    green = Image.fromarray(
        np.clip(np.random.default_rng(1).normal([40, 140, 60], 25, (200, 200, 3)), 0, 255).astype("uint8")
    )
    assert not assess_quality(green).ok


def test_black_and_white_face_is_not_flagged():
    """Colour-based skin detection cannot judge grayscale, so it must not reject it."""
    assert assess_quality(_skin().convert("L").convert("RGB")).ok


# --- hostile-input hardening -------------------------------------------------

import threading
import time

import image_utils

POSTSCRIPT = (b"%!PS-Adobe-3.0 EPSF-3.0\n%%BoundingBox: 0 0 300 300\n"
              b"/Helvetica findfont 40 scalefont setfont 10 100 moveto (hi) show\nshowpage\n")


@pytest.mark.parametrize("fmt", ["GIF", "BMP", "TIFF", "WEBP", "ICO", "PPM"])
def test_formats_other_than_jpeg_and_png_are_rejected_by_content(fmt):
    # Renaming a file to photo.jpg must not matter: the decoder is chosen by content.
    img = _skin((64, 64))
    with pytest.raises(ImageError, match="could not be read"):
        load_image(_encode(img, fmt))


def test_postscript_is_never_handed_to_a_decoder():
    # On servers with Ghostscript installed, Pillow would run it on EPS input.
    with pytest.raises(ImageError, match="could not be read"):
        load_image(POSTSCRIPT)


def test_pixel_cap_is_checked_from_the_header_before_decoding():
    # A small file that declares a huge canvas. It must be refused quickly and
    # without allocating the pixels (the earlier version grew ~1 GB on a 435 KB file).
    big = Image.new("L", (6000, 5000), 128)  # 30 MP > the 25 MP PNG cap
    data = _encode(big, "PNG", compress_level=9)
    assert len(data) < 1_000_000
    start = time.perf_counter()
    with pytest.raises(ImageError, match="too large to process"):
        load_image(data)
    assert time.perf_counter() - start < 1.0


def test_large_jpeg_is_decoded_at_reduced_size_and_capped():
    big = Image.new("RGB", (6000, 4000), (200, 150, 120))  # 24 MP JPEG: allowed
    out = load_image(_encode(big, "JPEG", quality=60))
    assert max(out.size) <= MAX_SIDE


def test_image_error_is_not_masked_by_the_generic_handler():
    # ImageError subclasses ValueError; the size message must survive the except clauses.
    with pytest.raises(ImageError) as exc:
        load_image(_encode(Image.new("L", (6000, 5000), 1), "PNG"))
    assert "megapixels" in str(exc.value)


def test_concurrent_decodes_are_bounded(monkeypatch):
    seen, peak, lock = [0], [0], threading.Lock()
    real = image_utils._decode

    def slow_decode(data):
        with lock:
            seen[0] += 1
            peak[0] = max(peak[0], seen[0])
        time.sleep(0.15)
        try:
            return real(data)
        finally:
            with lock:
                seen[0] -= 1

    monkeypatch.setattr(image_utils, "_decode", slow_decode)
    data = _encode(_skin(), "PNG")
    threads = [threading.Thread(target=load_image, args=(data,)) for _ in range(8)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert peak[0] <= image_utils.MAX_CONCURRENT_DECODES


def test_busy_server_gives_a_friendly_error(monkeypatch):
    monkeypatch.setattr(image_utils, "_decode_slots", threading.BoundedSemaphore(0))
    monkeypatch.setattr(image_utils, "DECODE_WAIT_SECONDS", 0.05)
    with pytest.raises(ImageError, match="busy"):
        load_image(_encode(_skin(), "PNG"))
