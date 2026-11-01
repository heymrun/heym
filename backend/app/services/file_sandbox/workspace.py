"""Host-side workspace of the file sandbox.

Layout, all under one base directory that is never mounted itself::

    <base>/in/      backend-only; Drive copies plus ``_manifest.json``  -> /input (ro)
    <base>/work/    sandbox-writable scratch; ``out/`` holds new files -> /work (rw)
    <base>/meta.json  owner and last use, read only by the backend

``in`` and ``work`` are siblings, so the sandbox can never write into the input
tree. The backend reads ``work`` in exactly one place, ``collect_outputs``, and
does so through a directory descriptor with ``O_NOFOLLOW`` so a planted link or a
swapped directory cannot point it at a host file.
"""

from __future__ import annotations

import json
import mimetypes
import os
import shutil
import stat
import tempfile
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from app.services.code_python_executor import _is_containerized, _workspace_mount_point
from app.services.file_sandbox.limits import (
    MAX_OUTPUT_FILE_BYTES,
    MAX_OUTPUT_FILES,
    MAX_WORKSPACE_BYTES,
)
from app.services.file_sandbox.manifest import DriveFileRef
from app.services.file_storage import _normalize_storage_filename

INPUT_MOUNT = "/input"
WORK_MOUNT = "/work"
OUT_DIRNAME = "out"
MANIFEST_NAME = "_manifest.json"
_META_NAME = "meta.json"
_SANDBOX_SUBDIR = "_file-sandbox"
_MAX_OUTPUT_TOTAL_BYTES = 2 * MAX_OUTPUT_FILE_BYTES

_locks: dict[Path, threading.Lock] = {}
_locks_guard = threading.Lock()


class WorkspaceQuotaError(RuntimeError):
    """The workspace would grow past ``MAX_WORKSPACE_BYTES``."""


@dataclass(frozen=True)
class CollectedFile:
    """One output file read out of ``/work/out``."""

    name: str
    data: bytes
    mime: str


def sandbox_root() -> Path:
    """Where workspaces live: a temp dir natively, the shared volume in containers."""
    if not _is_containerized():
        return Path(tempfile.gettempdir()) / "heym-file-sandbox"
    return _workspace_mount_point() / _SANDBOX_SUBDIR


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_name(name: str) -> str:
    try:
        return _normalize_storage_filename(name)
    except ValueError:
        return "file"


class FileWorkspace:
    """Inputs, scratch and outputs of one session (a chat or one node execution)."""

    def __init__(self, base: Path, *, owner_id: uuid.UUID) -> None:
        self.base = base
        self.owner_id = owner_id
        self.in_dir = base / "in"
        self.work_dir = base / "work"
        self.out_dir = self.work_dir / OUT_DIRNAME

    @classmethod
    def for_run(cls, owner_id: uuid.UUID) -> FileWorkspace:
        """A workspace for one Agent or Code node execution."""
        return cls(sandbox_root() / "runs" / uuid.uuid4().hex, owner_id=owner_id)

    @classmethod
    def for_chat(cls, user_id: uuid.UUID, conversation_id: uuid.UUID) -> FileWorkspace:
        """A conversation's workspace. Keyed by user too, so a forged id stays in-account."""
        base = sandbox_root() / "chats" / user_id.hex / conversation_id.hex
        return cls(base, owner_id=user_id)

    @property
    def lock(self) -> threading.Lock:
        """Calls in one workspace run one at a time."""
        with _locks_guard:
            return _locks.setdefault(self.base, threading.Lock())

    def exists(self) -> bool:
        return self.base.is_dir()

    def ensure(self) -> None:
        """Create the layout; the sandbox user (65534) needs write access to ``work``."""
        self.in_dir.mkdir(parents=True, exist_ok=True)
        os.chmod(self.in_dir, 0o755)
        self.work_dir.mkdir(parents=True, exist_ok=True)
        os.chmod(self.work_dir, 0o777)
        self._ensure_out_dir()
        meta = self._read_meta()
        if not meta:
            meta = {"owner_id": str(self.owner_id), "created_at": _now()}
        meta["last_used_at"] = _now()
        self._write_meta(meta)
        if not (self.in_dir / MANIFEST_NAME).exists():
            self._write_manifest([])

    def _ensure_out_dir(self) -> None:
        # The sandbox may have removed or replaced out/; never follow what is there.
        if self.out_dir.is_symlink() or (self.out_dir.exists() and not self.out_dir.is_dir()):
            self.out_dir.unlink()
        self.out_dir.mkdir(exist_ok=True)
        os.chmod(self.out_dir, 0o777)

    def _read_meta(self) -> dict:
        try:
            data = json.loads((self.base / _META_NAME).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return data if isinstance(data, dict) else {}

    def _write_meta(self, meta: dict) -> None:
        (self.base / _META_NAME).write_text(json.dumps(meta), encoding="utf-8")

    def last_used_at(self) -> datetime | None:
        raw = self._read_meta().get("last_used_at")
        try:
            return datetime.fromisoformat(str(raw)) if raw else None
        except ValueError:
            return None

    def inputs(self) -> list[dict]:
        """Index of the Drive copies in this workspace, as the sandbox sees them."""
        try:
            data = json.loads((self.in_dir / MANIFEST_NAME).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        return (
            [entry for entry in data if isinstance(entry, dict)] if isinstance(data, list) else []
        )

    def _write_manifest(self, entries: list[dict]) -> None:
        path = self.in_dir / MANIFEST_NAME
        path.write_text(json.dumps(entries, default=str), encoding="utf-8")
        os.chmod(path, 0o644)

    def input_ids(self) -> set[uuid.UUID]:
        ids: set[uuid.UUID] = set()
        for entry in self.inputs():
            try:
                ids.add(uuid.UUID(str(entry.get("id"))))
            except ValueError:
                continue
        return ids

    def add_inputs(self, refs: list[DriveFileRef]) -> list[dict]:
        """Copy each file in once; return the index entries for ``refs``.

        Raises:
            WorkspaceQuotaError: the copies would push the workspace past its quota.
        """
        entries = self.inputs()
        present = {str(entry.get("id")): entry for entry in entries}
        missing = [ref for ref in refs if str(ref.id) not in present]
        incoming = sum(int(ref.size or 0) for ref in missing)
        if missing and self.usage_bytes() + incoming > MAX_WORKSPACE_BYTES:
            raise WorkspaceQuotaError(
                "The workspace would exceed 2 GB with these files. Clear the workspace "
                "or work with fewer files."
            )
        for ref in missing:
            if ref.storage_path is None:
                raise FileNotFoundError(f"File content is missing from storage: {ref.name}")
            name = _safe_name(ref.name)
            target_dir = self.in_dir / ref.id.hex
            target_dir.mkdir(exist_ok=True)
            os.chmod(target_dir, 0o755)
            target = target_dir / name
            shutil.copyfile(ref.storage_path, target)
            os.chmod(target, 0o644)
            entry = {**ref.public(), "path": f"{INPUT_MOUNT}/{ref.id.hex}/{name}"}
            entries.append(entry)
            present[str(ref.id)] = entry
        if missing:
            self._write_manifest(entries)
        return [present[str(ref.id)] for ref in refs]

    def prune(self, keep_ids: set[uuid.UUID]) -> list[str]:
        """Delete copies of files the owner no longer reaches; return their names."""
        kept: list[dict] = []
        removed: list[str] = []
        for entry in self.inputs():
            try:
                file_id = uuid.UUID(str(entry.get("id")))
            except ValueError:
                continue
            if file_id in keep_ids:
                kept.append(entry)
                continue
            shutil.rmtree(self.in_dir / file_id.hex, ignore_errors=True)
            removed.append(str(entry.get("name") or file_id))
        if removed:
            self._write_manifest(kept)
        return removed

    def usage_bytes(self) -> int:
        """Bytes used by inputs and scratch. Links count as themselves, never their target."""
        total = 0
        for directory in (self.in_dir, self.work_dir):
            for root, dirs, files in os.walk(directory, followlinks=False):
                for name in files + dirs:
                    try:
                        total += os.lstat(os.path.join(root, name)).st_size
                    except OSError:
                        continue
        return total

    def work_summary(self, limit: int = 20) -> list[dict]:
        """Top-level scratch entries with sizes, for the model's view of the session."""
        entries: list[dict] = []
        try:
            with os.scandir(self.work_dir) as it:
                for item in it:
                    if item.name == OUT_DIRNAME:
                        continue
                    try:
                        info = item.stat(follow_symlinks=False)
                    except OSError:
                        continue
                    entries.append({"path": f"{WORK_MOUNT}/{item.name}", "size": info.st_size})
                    if len(entries) >= limit:
                        break
        except OSError:
            return []
        return entries

    def collect_outputs(self) -> tuple[list[CollectedFile], list[str]]:
        """Read and remove regular files directly under ``work/out``.

        Rejected (and left in place): links, hardlinks, directories, special files,
        unreadable or oversized files, and names that are not plain file names.
        """
        collected: list[CollectedFile] = []
        rejected: list[str] = []
        try:
            dir_fd = os.open(self.out_dir, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        except OSError:
            self._ensure_out_dir()
            return collected, ["out/ was replaced and has been reset"]
        total = 0
        try:
            for name in sorted(os.listdir(dir_fd)):
                if len(collected) >= MAX_OUTPUT_FILES:
                    rejected.append(f"{name}: more than {MAX_OUTPUT_FILES} files in one call")
                    continue
                reason, data = self._read_output(dir_fd, name)
                if reason is not None:
                    rejected.append(f"{name}: {reason}")
                    continue
                assert data is not None
                if total + len(data) > _MAX_OUTPUT_TOTAL_BYTES:
                    rejected.append(f"{name}: outputs of one call are limited to 200 MB")
                    continue
                total += len(data)
                os.unlink(name, dir_fd=dir_fd)
                mime = mimetypes.guess_type(name)[0] or "application/octet-stream"
                collected.append(CollectedFile(name=name, data=data, mime=mime))
        finally:
            os.close(dir_fd)
        return collected, rejected

    @staticmethod
    def _read_output(dir_fd: int, name: str) -> tuple[str | None, bytes | None]:
        try:
            if _normalize_storage_filename(name) != name:
                return "not a plain file name", None
        except ValueError:
            return "not a plain file name", None
        try:
            info = os.lstat(name, dir_fd=dir_fd)
        except OSError:
            return "unreadable", None
        if not stat.S_ISREG(info.st_mode):
            return "only regular files are collected", None
        if info.st_nlink > 1:
            return "hard links are not collected", None
        if info.st_size > MAX_OUTPUT_FILE_BYTES:
            return "larger than 100 MB", None
        try:
            fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=dir_fd)
        except OSError:
            return "unreadable", None
        try:
            opened = os.fstat(fd)
            if (opened.st_ino, opened.st_dev) != (info.st_ino, info.st_dev) or not stat.S_ISREG(
                opened.st_mode
            ):
                return "changed while being read", None
            chunks: list[bytes] = []
            remaining = MAX_OUTPUT_FILE_BYTES + 1
            while remaining > 0:
                chunk = os.read(fd, min(1024 * 1024, remaining))
                if not chunk:
                    break
                chunks.append(chunk)
                remaining -= len(chunk)
        finally:
            os.close(fd)
        data = b"".join(chunks)
        if len(data) > MAX_OUTPUT_FILE_BYTES:
            return "larger than 100 MB", None
        return None, data

    def touch(self) -> None:
        meta = self._read_meta()
        if meta:
            meta["last_used_at"] = _now()
            self._write_meta(meta)

    def delete(self) -> None:
        """Remove the whole workspace. ``rmtree`` removes links without following them."""
        shutil.rmtree(self.base, ignore_errors=True)
        with _locks_guard:
            _locks.pop(self.base, None)
