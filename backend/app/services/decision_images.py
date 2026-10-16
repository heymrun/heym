"""Prepare images for a decision model request.

TypeSafe rejects an image outside its limits rather than resizing it, and it does not
apply EXIF orientation. Preparing every image here means a phone photo, a WebP or a
small icon still reaches the model, upright and inside the limits, instead of failing
the whole request with a 400.
"""

from __future__ import annotations

import io
from dataclasses import dataclass

from PIL import Image, ImageOps, UnidentifiedImageError

from app.services.decision_models import DecisionRequestError

MIN_SIDE = 280
MAX_SIDE = 1568
MAX_FILE_BYTES = 16 * 1024 * 1024
JPEG_QUALITY = 90


@dataclass(frozen=True)
class PreparedImage:
    """One image ready to be attached as a request asset."""

    name: str
    format: str  # "jpg" or "png"
    data: bytes
    width: int
    height: int


def _has_alpha(image: Image.Image) -> bool:
    if image.mode in ("RGBA", "LA", "PA"):
        return True
    return image.mode == "P" and "transparency" in image.info


def _resize(image: Image.Image, width: int, height: int) -> Image.Image:
    return image.resize((width, height), Image.Resampling.LANCZOS)


def _pad(image: Image.Image, width: int, height: int) -> Image.Image:
    """Centre the image on a canvas of at least the given size."""
    fill = (255, 255, 255, 0) if image.mode == "RGBA" else (255, 255, 255)
    canvas = Image.new(image.mode, (width, height), fill)
    canvas.paste(image, ((width - image.width) // 2, (height - image.height) // 2))
    return canvas


def _fit(image: Image.Image) -> Image.Image:
    """Bring both sides within MIN_SIDE..MAX_SIDE, keeping the aspect ratio."""
    width, height = image.size
    longest = max(width, height)
    if longest > MAX_SIDE:
        scale = MAX_SIDE / longest
        image = _resize(image, max(1, round(width * scale)), max(1, round(height * scale)))
        width, height = image.size

    shortest = min(width, height)
    if shortest >= MIN_SIDE:
        return image

    scale = MIN_SIDE / shortest
    if round(max(width, height) * scale) <= MAX_SIDE:
        return _resize(
            image,
            max(MIN_SIDE, round(width * scale)),
            max(MIN_SIDE, round(height * scale)),
        )
    # Scaling the short side up would push the long side past the maximum, so pad it.
    return _pad(image, max(width, MIN_SIDE), max(height, MIN_SIDE))


def prepare_image(name: str, raw: bytes) -> PreparedImage:
    """Decode, orient, fit and re-encode one image as PNG (with alpha) or JPEG."""
    try:
        with Image.open(io.BytesIO(raw)) as opened:
            # exif_transpose returns a copy of the current frame, which is the first.
            image = ImageOps.exif_transpose(opened)
            image.load()
    except (UnidentifiedImageError, Image.DecompressionBombError, OSError, ValueError) as exc:
        raise DecisionRequestError(f"Image '{name}' is not a readable image") from exc

    if _has_alpha(image):
        image, file_format, save_format = image.convert("RGBA"), "png", "PNG"
    else:
        image, file_format, save_format = image.convert("RGB"), "jpg", "JPEG"

    image = _fit(image)

    buffer = io.BytesIO()
    if save_format == "JPEG":
        image.save(buffer, format="JPEG", quality=JPEG_QUALITY)
    else:
        image.save(buffer, format="PNG")
    data = buffer.getvalue()
    if len(data) > MAX_FILE_BYTES:
        raise DecisionRequestError(f"Image '{name}' is larger than 16 MiB after preparation")

    return PreparedImage(
        name=name, format=file_format, data=data, width=image.width, height=image.height
    )
