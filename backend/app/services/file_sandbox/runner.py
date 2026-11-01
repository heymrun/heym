"""Bootstrap of one file-sandbox call, executed inside the container.

Never imported by the backend at run time: its source travels in the stdin
payload, like ``code_runner.py``, and must stay standard-library only. The
modules the call needs (``heym_files``, ``heym_inspector``, ``heym_ocr``) travel the same way
and are registered in ``sys.modules`` before anything else runs.

Exactly one JSON envelope is written, to a duplicate of the original stdout.
File descriptor 1 is pointed at stderr first, so a subprocess or ``os.write(1)``
in user code cannot corrupt the envelope.
"""

from __future__ import annotations

import io
import json
import os
import sys
import traceback
import types
from typing import Any

_MAX_STDOUT_CHARS = 20_000
_MAX_ERROR_CHARS = 8_000


class _BoundedBuffer(io.TextIOBase):
    """Keeps the first characters written and counts the rest."""

    def __init__(self, limit: int) -> None:
        self._parts: list[str] = []
        self._kept = 0
        self.dropped = 0
        self._limit = limit

    def writable(self) -> bool:
        return True

    def write(self, text: str) -> int:
        room = self._limit - self._kept
        if room > 0:
            piece = text[:room]
            self._parts.append(piece)
            self._kept += len(piece)
        self.dropped += max(0, len(text) - max(room, 0))
        return len(text)

    def getvalue(self) -> str:
        return "".join(self._parts)


def _install_modules(modules: dict[str, str]) -> None:
    for name, source in modules.items():
        module = types.ModuleType(name)
        module.__file__ = f"<heym:{name}>"
        # Registered first: dataclasses look their module up while the source runs.
        sys.modules[name] = module
        exec(compile(source, f"{name}.py", "exec"), module.__dict__)


def _clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[:limit] + "\n... truncated"


def run(payload: dict[str, Any]) -> None:
    """Run one ``inspect``, ``python`` or ``code_node`` call and write its envelope."""
    _install_modules(payload.get("modules") or {})
    if payload.get("mode") == "code_node":
        # A Code node with files: the Code runner writes its own envelope.
        runner: dict[str, Any] = {"__name__": "__heym_runner__"}
        exec(compile(payload["code_runner"], "code_runner.py", "exec"), runner)
        runner["run"](payload)
        return
    envelope_fd = os.dup(1)
    os.dup2(2, 1)

    buffer = _BoundedBuffer(_MAX_STDOUT_CHARS)
    real_stdout, real_stderr = sys.stdout, sys.stderr
    sys.stdout = sys.stderr = buffer
    envelope: dict[str, Any]
    try:
        if payload.get("mode") == "inspect":
            inspector = sys.modules["heym_inspector"]
            target = payload.get("target") or {}
            result = inspector.inspect(
                target.get("path"),
                name=target.get("name"),
                mime=target.get("mime"),
                options=payload.get("options") or {},
            )
            envelope = {"success": True, "result": result}
        else:
            namespace: dict[str, Any] = {"__name__": "__main__"}
            exec(compile(payload.get("code") or "", "<run_python>", "exec"), namespace)
            envelope = {"success": True, "result": None}
    except SystemExit as exc:
        ok = exc.code in (None, 0)
        envelope = {"success": ok, "result": None}
        if not ok:
            envelope["error"] = f"SystemExit: {exc.code}"
    except BaseException:
        envelope = {"success": False, "error": _clip(traceback.format_exc(), _MAX_ERROR_CHARS)}
    finally:
        sys.stdout, sys.stderr = real_stdout, real_stderr

    envelope["stdout"] = buffer.getvalue()
    envelope["stdout_dropped_chars"] = buffer.dropped
    with os.fdopen(envelope_fd, "w", encoding="utf-8") as out:
        out.write(json.dumps(envelope, default=str))
