"""Files of this sandbox session, importable as ``heym_files`` inside the sandbox.

Inputs are read-only under ``/input``. Anything written to ``out_dir()`` is saved
to Heym Drive after the call. ``/work`` keeps scratch files for the session.

Shipped in the stdin payload; standard library only.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

INPUT_DIR = Path("/input")
OUT_DIR = Path("/work/out")
_MANIFEST = "_manifest.json"


def list_files() -> list[dict[str, Any]]:
    """Inputs of this session: id, name, mime, size, path."""
    try:
        data = json.loads((INPUT_DIR / _MANIFEST).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    return [dict(entry) for entry in data if isinstance(entry, dict)]


def path(name_or_id: str) -> str:
    """Local path of an input, by Drive id or file name (exact, then case-insensitive)."""
    wanted = str(name_or_id or "").strip()
    files = list_files()
    for match in (
        lambda f: f.get("id") == wanted,
        lambda f: f.get("name") == wanted,
        lambda f: str(f.get("name") or "").lower() == wanted.lower(),
    ):
        hits = [f for f in files if match(f)]
        if hits:
            return str(hits[-1]["path"])
    available = ", ".join(str(f.get("name")) for f in files) or "none"
    raise FileNotFoundError(
        f"{wanted!r} is not in this session. Available: {available}. "
        "Pass the file in the tool's `files` argument to mount it."
    )


def out_dir() -> str:
    """Directory whose files are saved to Heym Drive after the call."""
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    return str(OUT_DIR)
