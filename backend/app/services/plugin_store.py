"""Filesystem + dependency handling for installed plugins."""

from __future__ import annotations

import io
import json
import logging
import os
import shutil
import subprocess
import zipfile
from pathlib import Path
from typing import BinaryIO

from app.models.plugin_schemas import PluginManifest

logger = logging.getLogger(__name__)

MAX_ZIP_BYTES = 20 * 1024 * 1024  # 20 MiB
MAX_UNCOMPRESSED_BYTES = 100 * 1024 * 1024


class PluginInstallError(Exception):
    """Raised when a plugin zip is invalid or installation fails."""


def _safe_members(zf: zipfile.ZipFile, dest_root: Path) -> list[zipfile.ZipInfo]:
    members: list[zipfile.ZipInfo] = []
    total = 0
    resolved_root = dest_root.resolve()
    for info in zf.infolist():
        name = info.filename
        if name.endswith("/"):
            continue
        target = (dest_root / name).resolve()
        try:
            target.relative_to(resolved_root)
        except ValueError:
            raise PluginInstallError(f"Unsafe path in zip: {name}")
        total += info.file_size
        if total > MAX_UNCOMPRESSED_BYTES:
            raise PluginInstallError("Plugin archive too large when uncompressed")
        members.append(info)
    return members


def extract_and_validate(zip_bytes: bytes, plugins_dir: Path) -> PluginManifest:
    """Validate a plugin zip, extract it to plugins_dir/<id>, install deps.

    Returns the parsed manifest. Raises PluginInstallError on any problem and
    removes a partially extracted directory.
    """
    if len(zip_bytes) > MAX_ZIP_BYTES:
        raise PluginInstallError("Plugin archive exceeds size limit")

    try:
        zf = zipfile.ZipFile(io.BytesIO(zip_bytes))
    except zipfile.BadZipFile as exc:
        raise PluginInstallError("Not a valid zip archive") from exc

    with zf:
        names = set(zf.namelist())
        if "plugin.json" not in names:
            raise PluginInstallError("plugin.json missing from archive")
        try:
            manifest = PluginManifest.model_validate(json.loads(zf.read("plugin.json")))
        except PluginInstallError:
            raise
        except Exception as exc:
            raise PluginInstallError(f"Invalid plugin.json: {exc}") from exc
        if manifest.entry not in names:
            raise PluginInstallError(f"Entry file '{manifest.entry}' missing from archive")

        target = plugins_dir / manifest.id
        # Validate member paths before touching the filesystem so a zip-slip
        # attempt cannot leave a stray directory behind.
        members = _safe_members(zf, target)

        if target.exists():
            shutil.rmtree(target)
        target.mkdir(parents=True, exist_ok=True)
        try:
            for info in members:
                out = target / info.filename
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_bytes(zf.read(info))
            if manifest.dependencies:
                _install_dependencies(manifest.dependencies)
        except Exception:
            shutil.rmtree(target, ignore_errors=True)
            raise

    return manifest


def _install_dependencies(dependencies: list[str]) -> None:
    """Install pip dependencies into the running instance (admin-gated)."""
    cmd = ["uv", "pip", "install", *dependencies]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    except (OSError, subprocess.SubprocessError) as exc:
        raise PluginInstallError(f"Dependency install failed: {exc}") from exc
    if result.returncode != 0:
        raise PluginInstallError(f"Dependency install failed: {result.stderr.strip()}")


def _lock_dependency_file(lock_file: BinaryIO) -> None:
    if os.name == "nt":
        import msvcrt

        lock_file.seek(0, os.SEEK_END)
        if lock_file.tell() == 0:
            lock_file.write(b"\0")
            lock_file.flush()
        lock_file.seek(0)
        msvcrt.locking(lock_file.fileno(), msvcrt.LK_LOCK, 1)
        return

    import fcntl

    fcntl.flock(lock_file, fcntl.LOCK_EX)


def _unlock_dependency_file(lock_file: BinaryIO) -> None:
    if os.name == "nt":
        import msvcrt

        lock_file.seek(0)
        msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)
        return

    import fcntl

    fcntl.flock(lock_file, fcntl.LOCK_UN)


def ensure_dependencies_installed(dependencies: list[str]) -> None:
    """Best-effort dependency install used on startup; never raises.

    In container deployments the backend image filesystem is ephemeral, so pip
    packages installed when a plugin was first added are lost on recreate. Calling
    this on startup restores them. Idempotent for native runs.
    """
    if not dependencies:
        return
    # The release image runs uvicorn with multiple workers, so this can be called
    # from several processes at once against the same venv. Serialize with a file
    # lock so only one worker installs at a time (the rest then no-op quickly).
    try:
        lock_path = plugins_root() / ".deps.lock"
        lock_path.touch(exist_ok=True)
        with open(lock_path, "r+b") as lock_file:
            _lock_dependency_file(lock_file)
            try:
                _install_dependencies(dependencies)
            finally:
                _unlock_dependency_file(lock_file)
    except PluginInstallError as exc:
        logger.warning("Plugin dependency reinstall failed: %s", exc)
    except (ImportError, OSError) as exc:
        logger.warning("Plugin dependency reinstall could not acquire lock: %s", exc)


def remove_plugin_dir(plugin_id: str, plugins_dir: Path) -> None:
    shutil.rmtree(plugins_dir / plugin_id, ignore_errors=True)


def plugins_root() -> Path:
    from app.config import settings

    root = Path(settings.plugins_dir)
    root.mkdir(parents=True, exist_ok=True)
    return root
