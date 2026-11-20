"""Read a chat zip and separate skill bundles from ordinary files.

A skill bundle is a directory that contains ``SKILL.md`` plus every file below it: Python,
extra Markdown, and assets. A binary asset travels as base64, which the agent node stores
as it is. The model sees a short summary. ``apply_skill`` writes the original bytes, so a
later reply cannot drop a file the prompt left out.
"""

from __future__ import annotations

import base64
import binascii
import io
import re
import zipfile
import zlib
from dataclasses import dataclass
from typing import Literal

MAX_ZIP_BYTES = 8 * 1024 * 1024
MAX_UNCOMPRESSED_BYTES = 8 * 1024 * 1024
MAX_FILES = 200
MAX_FILE_BYTES = 1_000_000
PROMPT_FILE_CHARS = 4_000
PROMPT_TOTAL_CHARS = 24_000

_IGNORED_DIRS = {"__MACOSX"}
_IGNORED_NAMES = {".DS_Store"}
_SKILL_MARKDOWN = "skill.md"
# General purpose bit 0: the member is encrypted, and reading it needs a password.
_ENCRYPTED_FLAG = 0x1


@dataclass(frozen=True)
class ArchiveFile:
    """One file from the archive: text as it is, or a binary file as base64."""

    path: str
    content: str
    encoding: Literal["text", "base64"] = "text"


@dataclass(frozen=True)
class SkillBundle:
    """One skill: the ``SKILL.md`` body and the text files that belong with it."""

    name: str
    content: str
    files: tuple[ArchiveFile, ...]
    directory: str
    # Set by the sender of the zip, never read from it: the skill may read Drive files.
    drive_files: bool = False


@dataclass(frozen=True)
class ZipRead:
    """What a zip held: skill bundles, other text files, and notes for the model."""

    skills: tuple[SkillBundle, ...]
    text_files: tuple[ArchiveFile, ...]
    notes: tuple[str, ...]


def decode_zip_payload(content: str) -> bytes | None:
    """Turn a data URL or raw base64 attachment into zip bytes, or None when it is not."""
    payload = content.strip()
    if payload.startswith("data:") and "," in payload:
        payload = payload.split(",", 1)[1]
    try:
        raw = base64.b64decode(payload, validate=True)
    except (binascii.Error, ValueError):
        return None
    if not raw.startswith(b"PK"):
        return None
    return raw


def name_from_frontmatter(content: str) -> str:
    """The ``name`` field of a leading YAML frontmatter block, or an empty string."""
    if not content.startswith("---"):
        return ""
    end = content.find("\n---", 3)
    if end < 0:
        return ""
    for line in content[3:end].splitlines():
        if line.lower().startswith("name:"):
            value = line.split(":", 1)[1].strip().strip("\"'")
            return value
    return ""


def _safe_path(name: str) -> str | None:
    parts = [part for part in name.replace("\\", "/").split("/") if part not in ("", ".")]
    if not parts or any(part == ".." for part in parts):
        return None
    if any(
        part in _IGNORED_DIRS or part in _IGNORED_NAMES or part.startswith("._") for part in parts
    ):
        return None
    return "/".join(parts)


def _read_text(raw: bytes) -> str | None:
    if b"\x00" in raw:
        return None
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return None


def read_zip(raw: bytes) -> ZipRead:
    """Open a zip. A broken or oversized archive comes back as notes and no skills."""
    if len(raw) > MAX_ZIP_BYTES:
        return ZipRead((), (), ("The zip is larger than 8 MB.",))
    try:
        archive = zipfile.ZipFile(io.BytesIO(raw))
    except zipfile.BadZipFile:
        return ZipRead((), (), ("The attachment is not a zip file.",))

    texts: list[ArchiveFile] = []
    binaries: list[ArchiveFile] = []
    skipped: set[str] = set()
    notes: list[str] = []
    total = 0
    with archive:
        members = [info for info in archive.infolist() if not info.is_dir()]
        if len(members) > MAX_FILES:
            return ZipRead((), (), (f"The zip has more than {MAX_FILES} files.",))
        for info in members:
            path = _safe_path(info.filename)
            if path is None:
                continue
            if info.file_size > MAX_FILE_BYTES:
                notes.append(f"Skipped {path}: larger than 1 MB.")
                continue
            total += info.file_size
            if total > MAX_UNCOMPRESSED_BYTES:
                notes.append("Stopped reading: the zip expands past 8 MB.")
                break
            if info.flag_bits & _ENCRYPTED_FLAG:
                notes.append(f"Skipped {path}: the file is password-protected.")
                skipped.add(path)
                continue
            try:
                data = archive.read(info)
            except (zipfile.BadZipFile, zlib.error, NotImplementedError, EOFError):
                notes.append(f"Skipped {path}: the file is damaged or could not be unpacked.")
                skipped.add(path)
                continue
            text = _read_text(data)
            if text is None:
                binaries.append(ArchiveFile(path, base64.b64encode(data).decode(), "base64"))
                continue
            texts.append(ArchiveFile(path, text))

    # A skipped member takes part in grouping as an empty placeholder, so the skill that owns
    # it is known.
    placeholders = [ArchiveFile(path, "", "base64") for path in sorted(skipped)]
    bundles, rest = _skills_from(texts + binaries + placeholders)
    # A skill missing a member it owns is left out: saving it would replace the stored skill
    # and drop the stored copy of that member. Its readable files stay as context.
    skills = []
    for bundle in bundles:
        prefix = f"{bundle.directory}/" if bundle.directory else ""
        missing = [prefix + item.path for item in bundle.files if prefix + item.path in skipped]
        if not missing:
            skills.append(bundle)
            continue
        notes.append(f"Did not read skill {bundle.name}: {', '.join(missing)} could not be read.")
        rest.append(ArchiveFile(f"{prefix}SKILL.md", bundle.content))
        rest.extend(
            ArchiveFile(prefix + item.path, item.content, item.encoding) for item in bundle.files
        )
    rest = [item for item in rest if item.path not in skipped]
    kept_text = [item for item in rest if item.encoding == "text"]
    notes.extend(f"Skipped binary file {item.path}." for item in rest if item.encoding == "base64")
    return ZipRead(tuple(skills), tuple(kept_text), tuple(notes))


def _skills_from(files: list[ArchiveFile]) -> tuple[list[SkillBundle], list[ArchiveFile]]:
    marks = [
        item
        for item in files
        if item.encoding == "text" and item.path.rsplit("/", 1)[-1].lower() == _SKILL_MARKDOWN
    ]
    if not marks:
        return [], files
    bundles: list[SkillBundle] = []
    used: set[str] = set()
    for mark in marks:
        directory = mark.path.rsplit("/", 1)[0] if "/" in mark.path else ""
        prefix = f"{directory}/" if directory else ""
        nested = [
            other.path.rsplit("/", 1)[0]
            for other in marks
            if other is not mark and other.path.startswith(prefix) and "/" in other.path
        ]
        owned = []
        for item in files:
            if item.path == mark.path or not item.path.startswith(prefix):
                continue
            if item.path.rsplit("/", 1)[-1].lower() == _SKILL_MARKDOWN:
                continue
            relative = item.path[len(prefix) :]
            if any(relative.startswith(f"{folder[len(prefix) :]}/") for folder in nested):
                continue
            owned.append(item)
        name = name_from_frontmatter(mark.content) or (
            directory.rsplit("/", 1)[-1] if directory else "skill"
        )
        relative = tuple(
            ArchiveFile(
                item.path[len(prefix) :] if prefix else item.path, item.content, item.encoding
            )
            for item in owned
        )
        bundles.append(
            SkillBundle(
                name=name or "skill", content=mark.content, files=relative, directory=directory
            )
        )
        used.add(mark.path)
        used.update(item.path for item in owned)
    rest = [item for item in files if item.path not in used]
    return bundles, rest


def _clip(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + "\n...[truncated]"


ZIP_BLOCK_HEADER = "[ATTACHED ZIP: "
SKILL_ZIP_NOTE = (
    "This zip contains a skill. Call apply_skill to put it on an agent. "
    "Do not paste these files into save_workflow or into your reply; the server "
    "keeps the original files, including Python the summary cuts short."
)
_SKILL_LINE = re.compile(r"^Skill (.+?)\. Other files: ", re.MULTILINE)


def skill_names_in_zip_block(block: str) -> list[str]:
    """The skills a stored ``prompt_for_zip`` block names, so a later turn knows them too."""
    head, _, _rest = block.partition("\nSKILL.md:\n")
    if SKILL_ZIP_NOTE not in head:
        return []
    return [match.group(1) for match in _SKILL_LINE.finditer(block)]


def prompt_for_zip(name: str, reading: ZipRead) -> str:
    """The user-message block for a zip. File bytes the tool will write are not required here."""
    lines = [f"{ZIP_BLOCK_HEADER}{name}]"]
    lines.extend(reading.notes)
    if reading.skills:
        lines.append(SKILL_ZIP_NOTE)
        for skill in reading.skills:
            paths = ", ".join(item.path for item in skill.files) or "none"
            lines.append(f"Skill {skill.name}. Other files: {paths}.")
            lines.append("SKILL.md:")
            lines.append(_clip(skill.content, PROMPT_FILE_CHARS))
            for item in skill.files:
                if item.path.lower().endswith(".py"):
                    lines.append(f"--- {item.path} ---")
                    lines.append(_clip(item.content, PROMPT_FILE_CHARS))
    else:
        lines.append(
            "This zip has no SKILL.md. It is context for the conversation only. "
            "Do not call apply_skill for it."
        )
    for item in reading.text_files:
        lines.append(f"--- {item.path} ---")
        lines.append(_clip(item.content, PROMPT_FILE_CHARS))
    text = "\n".join(lines)
    if len(text) > PROMPT_TOTAL_CHARS:
        text = text[:PROMPT_TOTAL_CHARS] + "\n...[truncated]"
    return text
