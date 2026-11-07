"""Members' profile pictures.

A member uploads a photo on their profile; it's turned the right way up, cropped to a square, shrunk to
256 px and saved as a fresh JPEG, which also drops anything hidden in the original (camera details, GPS
location). Pictures are only served to signed-in members. An officer, or an admin in admin mode, can
remove one. Without a picture, a coloured circle with the member's initials is shown.
"""
from __future__ import annotations

import hashlib
import io

from .club import DATA

SIZE = 256
MAX_UPLOAD = 8 * 1024 * 1024  # bytes
FORMATS = {"JPEG", "PNG", "WEBP", "MPO"}  # MPO: some phone cameras


def _dir():
    d = DATA / "avatars"
    d.mkdir(parents=True, exist_ok=True)
    return d


def path(mid: str):
    return _dir() / f"{mid}.jpg"


def save(mid: str, data: bytes) -> None:
    """Check, square up and store a picture. Raises ValueError with a message for the member."""
    from PIL import Image, ImageOps, UnidentifiedImageError
    if not data:
        raise ValueError("Pick a picture first.")
    if len(data) > MAX_UPLOAD:
        raise ValueError("That picture is too big (8 MB at most).")
    try:
        img = Image.open(io.BytesIO(data))
        if img.format not in FORMATS:
            raise ValueError("Use a JPEG, PNG or WebP picture.")
        if img.width * img.height > 60_000_000:
            raise ValueError("That picture is too big.")
        img = ImageOps.exif_transpose(img)
    except UnidentifiedImageError:
        raise ValueError("That file isn't a picture we can read. Use a JPEG, PNG or WebP.")
    img = ImageOps.fit(img.convert("RGB"), (SIZE, SIZE), Image.LANCZOS, centering=(0.5, 0.4))
    out = io.BytesIO()
    img.save(out, "JPEG", quality=85, optimize=True)  # a new file: no EXIF, no location
    p = path(mid)
    tmp = p.with_suffix(".tmp")
    tmp.write_bytes(out.getvalue())
    tmp.chmod(0o600)
    tmp.replace(p)


def remove(mid: str) -> bool:
    p = path(mid)
    if p.exists():
        p.unlink()
        return True
    return False


def url(mid: str | None) -> str | None:
    """The picture's address, changing whenever the picture does (so browsers can cache it)."""
    if not mid:
        return None
    p = path(mid)
    if not p.exists():
        return None
    return f"/avatars/{mid}.jpg?v={int(p.stat().st_mtime)}"


def hue(mid: str) -> int:
    """A steady colour per member for the initials circle."""
    return int(hashlib.sha1(mid.encode()).hexdigest()[:4], 16) % 360
