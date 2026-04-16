"""Mailbox image attachment validation, storage, and serving."""

from __future__ import annotations

import io
import shutil
from pathlib import Path
from typing import Any

import structlog
from PIL import Image

logger = structlog.get_logger()

MAILBOX_DIR = Path("/claude-home/mailbox")
MAX_IMAGE_BYTES = 5 * 1024 * 1024  # 5 MB
ALLOWED_FORMATS: dict[str, str] = {
    "JPEG": ".jpg",
    "PNG": ".png",
    "GIF": ".gif",
    "WEBP": ".webp",
}
MIME_MAP: dict[str, str] = {
    "JPEG": "image/jpeg",
    "PNG": "image/png",
    "GIF": "image/gif",
    "WEBP": "image/webp",
}


def validate_image(data: bytes) -> tuple[str, str, str]:
    """Validate image bytes by magic bytes via Pillow.

    Returns:
        Tuple of (pillow_format, file_extension, mime_type).

    Raises:
        ValueError: If the image is invalid, too large, or unsupported format.
    """
    if len(data) > MAX_IMAGE_BYTES:
        size_mb = len(data) / (1024 * 1024)
        msg = f"Image exceeds 5 MB limit ({size_mb:.1f} MB)"
        raise ValueError(msg)

    try:
        img = Image.open(io.BytesIO(data))
        img.verify()
    except Exception as exc:
        msg = "Invalid or corrupt image file"
        raise ValueError(msg) from exc

    fmt = img.format
    if fmt not in ALLOWED_FORMATS:
        msg = f"Unsupported image format: {fmt}. Allowed: JPEG, PNG, GIF, WEBP"
        raise ValueError(msg)

    return fmt, ALLOWED_FORMATS[fmt], MIME_MAP[fmt]


def sanitize_image(data: bytes, fmt: str) -> bytes:
    """Re-encode image to strip all metadata.

    Removes EXIF, PNG tEXt/iTXt/zTXt chunks, ICC profiles, and any
    other embedded metadata. Returns clean pixel-only image bytes.

    Args:
        data: Raw image bytes (already validated).
        fmt: Pillow format string (JPEG, PNG, GIF, WEBP).

    Returns:
        Re-encoded image bytes with metadata stripped.
    """
    img = Image.open(io.BytesIO(data))

    # Drop ICC profile and other info by not passing it through
    save_kwargs: dict[str, Any] = {}
    if fmt == "JPEG":
        save_kwargs["quality"] = 95
        save_kwargs["optimize"] = True
        save_kwargs["exif"] = b""
    elif fmt == "PNG":
        save_kwargs["optimize"] = True
    elif fmt == "WEBP":
        save_kwargs["quality"] = 95
        save_kwargs["exif"] = b""

    if fmt == "GIF" and getattr(img, "is_animated", False):
        save_kwargs["save_all"] = True

    buf = io.BytesIO()
    img.save(buf, format=fmt, **save_kwargs)
    clean_data = buf.getvalue()

    original_kb = len(data) / 1024
    clean_kb = len(clean_data) / 1024
    stripped_kb = original_kb - clean_kb
    logger.info(
        "image_metadata_stripped",
        format=fmt,
        original_kb=round(original_kb, 1),
        clean_kb=round(clean_kb, 1),
        stripped_kb=round(stripped_kb, 1),
    )

    return clean_data


def store_attachment(username: str, msg_id: str, data: bytes, ext: str) -> str:
    """Save image to the user's attachments directory.

    Returns:
        The filename (e.g., msg_20260312_u_001.jpg).
    """
    attachments_dir = MAILBOX_DIR / username / "attachments"
    attachments_dir.mkdir(parents=True, exist_ok=True)

    # Set group permissions for claude user access
    try:
        import grp

        gid = grp.getgrnam("claude").gr_gid
        shutil.chown(str(attachments_dir), user="root", group=gid)
        attachments_dir.chmod(0o775)
    except (KeyError, OSError):
        pass

    filename = f"{msg_id}{ext}"
    filepath = attachments_dir / filename
    filepath.write_bytes(data)

    try:
        import grp

        gid = grp.getgrnam("claude").gr_gid
        shutil.chown(str(filepath), user="root", group=gid)
        filepath.chmod(0o664)
    except (KeyError, OSError):
        pass

    logger.info(
        "attachment_stored",
        username=username,
        filename=filename,
        size_bytes=len(data),
    )

    return filename


def get_attachment_path(username: str, filename: str) -> Path | None:
    """Resolve and validate an attachment path.

    Returns:
        The path if it exists and is within the expected directory, else None.
    """
    attachments_dir = MAILBOX_DIR / username / "attachments"
    filepath = attachments_dir / filename

    # Prevent path traversal
    try:
        filepath.resolve().relative_to(attachments_dir.resolve())
    except ValueError:
        return None

    if not filepath.is_file():
        return None

    return filepath


def get_mime_type(filename: str) -> str:
    """Derive MIME type from attachment filename extension."""
    ext = Path(filename).suffix.lower()
    ext_to_mime = {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".gif": "image/gif",
        ".webp": "image/webp",
    }
    return ext_to_mime.get(ext, "application/octet-stream")
