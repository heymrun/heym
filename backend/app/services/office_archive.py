"""The size guard for Office files (.docx, .xlsx), which are zip archives."""

from __future__ import annotations

import io
import zipfile

# zipfile stops decompressing an entry at its declared size, so the declared total bounds
# what parsing can unpack.
MAX_UNPACKED_BYTES = 256 * 1024 * 1024


class ArchiveTooLargeError(ValueError):
    """The archive unpacks past MAX_UNPACKED_BYTES."""


def ensure_unpacked_size(data: bytes) -> None:
    """Refuse an archive that unpacks past MAX_UNPACKED_BYTES, before any of it is parsed.

    Raises zipfile.BadZipFile when `data` is not a zip archive.
    """
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        unpacked = sum(info.file_size for info in archive.infolist())
    if unpacked > MAX_UNPACKED_BYTES:
        raise ArchiveTooLargeError(f"unpacks to {unpacked} bytes")
