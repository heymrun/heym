"""Execute Code node Python inside the sandbox container.

This module never runs in the backend process during a workflow run. The
backend reads its source, ships it in the stdin payload, and a short bootstrap
inside the container executes it and calls ``run``. Keeping it dependency-free
(standard library only) is what makes that possible.
"""

from __future__ import annotations

import io
import json
import sys
import traceback
from collections.abc import Iterator, KeysView
from typing import Any

_MAX_LOG_CHARS = 65536
_MAX_ERROR_CHARS = 16384
_MAIN_REQUIRED = (
    "The code must define a callable named 'main', for example:\n"
    "    def main(params):\n        return {'ok': True}"
)


def _wrap(value: Any) -> Any:
    """Wrap dicts (and dicts inside lists) so they support attribute access."""
    if isinstance(value, dict):
        return DotDict(value)
    if isinstance(value, list):
        return [_wrap(item) for item in value]
    return value


def unwrap(value: Any) -> Any:
    """Return a plain, JSON-friendly copy of a possibly wrapped value."""
    if isinstance(value, DotDict):
        return {key: unwrap(item) for key, item in value.to_dict().items()}
    if isinstance(value, dict):
        return {key: unwrap(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [unwrap(item) for item in value]
    return value


class DotDict:
    """Read-only mapping that also supports ``params.key`` attribute access."""

    __slots__ = ("_data",)

    def __init__(self, data: dict) -> None:
        object.__setattr__(self, "_data", data)

    def __getattr__(self, name: str) -> Any:
        try:
            return _wrap(self._data[name])
        except KeyError:
            available = ", ".join(sorted(str(key) for key in self._data)) or "none"
            raise AttributeError(
                f"Parameter {name!r} was not provided. Available parameters: {available}."
            ) from None

    def __getitem__(self, key: str) -> Any:
        return _wrap(self._data[key])

    def __contains__(self, key: object) -> bool:
        return key in self._data

    def __iter__(self) -> Iterator[str]:
        return iter(self._data)

    def __len__(self) -> int:
        return len(self._data)

    def __repr__(self) -> str:
        return f"DotDict({self._data!r})"

    def __eq__(self, other: object) -> bool:
        if isinstance(other, DotDict):
            return self._data == other._data
        return self._data == other

    def keys(self) -> KeysView[str]:
        """Return the parameter names."""
        return self._data.keys()

    def get(self, key: str, default: Any = None) -> Any:
        """Return a parameter by name, or ``default`` when it is absent."""
        if key in self._data:
            return _wrap(self._data[key])
        return default

    def to_dict(self) -> dict:
        """Return the underlying plain dict."""
        return self._data


def _truncate(text: str, limit: int = _MAX_LOG_CHARS) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n... truncated, {len(text) - limit} more characters"


def _format_error(exc: BaseException) -> str:
    rendered = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    return _truncate(rendered, _MAX_ERROR_CHARS)


def execute_payload(payload: dict) -> dict:
    """Run the payload's code and return a result envelope.

    The envelope is either ``{"success": True, "result": ..., "logs": ...}`` or
    ``{"success": False, "error": ..., "logs": ...}``.
    """
    code = str(payload.get("code") or "")
    raw_params = payload.get("params")
    params = raw_params if isinstance(raw_params, dict) else {}

    buffer = io.StringIO()
    original_stdout = sys.stdout
    sys.stdout = buffer
    try:
        namespace: dict[str, Any] = {"__name__": "__heym_code__"}
        exec(compile(code, "<code>", "exec"), namespace)
        main = namespace.get("main")
        if not callable(main):
            raise ValueError(_MAIN_REQUIRED)
        result = unwrap(main(DotDict(params)))
        try:
            json.dumps(result)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"main() returned a value that is not JSON-serializable: {exc}"
            ) from exc
    except (Exception, SystemExit) as exc:
        return {
            "success": False,
            "error": _format_error(exc),
            "logs": _truncate(buffer.getvalue()),
        }
    finally:
        sys.stdout = original_stdout

    return {"success": True, "result": result, "logs": _truncate(buffer.getvalue())}


def run(payload: dict) -> None:
    """Execute the payload and write the JSON envelope to the real stdout."""
    destination = sys.stdout
    destination.write(json.dumps(execute_payload(payload), default=str))
    destination.flush()
