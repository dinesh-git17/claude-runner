"""Optimize Telegram images for storage and consumption."""

from __future__ import annotations

import io
from datetime import UTC, datetime
from pathlib import Path

from PIL import Image
from PIL.Image import Resampling

MAX_DIMENSION = 1024
JPEG_QUALITY = 80
IMAGES_DIR = Path("/claude-home/telegram/images")


def optimize_image(raw_bytes: bytes, sender: str) -> Path:
    """Resize and compress an image, saving it as JPEG.

    Maintains aspect ratio while constraining the largest dimension
    to MAX_DIMENSION pixels. Converts all formats to JPEG at
    JPEG_QUALITY compression.

    Args:
        raw_bytes: Raw image bytes downloaded from Telegram.
        sender: Name of the sender (used in filename).

    Returns:
        Path to the saved optimized image.
    """
    IMAGES_DIR.mkdir(parents=True, exist_ok=True)

    raw_img = Image.open(io.BytesIO(raw_bytes))
    img = raw_img.convert("RGB")

    if max(img.size) > MAX_DIMENSION:
        img.thumbnail((MAX_DIMENSION, MAX_DIMENSION), Resampling.LANCZOS)

    now = datetime.now(tz=UTC)
    timestamp = now.strftime("%Y%m%d-%H%M%S")
    date_prefix = now.strftime("%Y-%m-%d")
    filename = f"{date_prefix}-{sender}-{timestamp}.jpg"
    output_path = IMAGES_DIR / filename

    img.save(output_path, format="JPEG", quality=JPEG_QUALITY, optimize=True)

    return output_path
