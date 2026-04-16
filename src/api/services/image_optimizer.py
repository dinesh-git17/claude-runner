"""Optimize Telegram images for Claudie's consumption."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from PIL import Image

MAX_DIMENSION = 1024
JPEG_QUALITY = 80
IMAGES_DIR = Path("/claude-home/telegram/images")


def optimize_image(raw_bytes: bytes, sender: str) -> Path:
    """Resize and compress an image, saving it as JPEG.

    Args:
        raw_bytes: Raw image bytes downloaded from Telegram.
        sender: Name of the sender (used in filename).

    Returns:
        Path to the saved optimized image.
    """
    import io

    IMAGES_DIR.mkdir(parents=True, exist_ok=True)

    img = Image.open(io.BytesIO(raw_bytes))
    img = img.convert("RGB")

    if max(img.size) > MAX_DIMENSION:
        img.thumbnail((MAX_DIMENSION, MAX_DIMENSION), Image.LANCZOS)

    timestamp = datetime.now(tz=UTC).strftime("%Y%m%d-%H%M%S")
    filename = f"{datetime.now(tz=UTC).strftime('%Y-%m-%d')}-{sender}-{timestamp}.jpg"
    output_path = IMAGES_DIR / filename

    img.save(output_path, format="JPEG", quality=JPEG_QUALITY, optimize=True)

    return output_path
