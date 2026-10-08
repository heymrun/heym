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
from typing import Any

_MAX_LOG_CHARS = 65536
_MAX_ERROR_CHARS = 16384
_MAIN_REQUIRED = (
    "The code must define a callable named 'main', for example:\n"
    "    def main(params):\n        return {'ok': True}"
)


def _wrap(value: Any) -> Any:
    """Wrap dicts (and dicts inside lists) so they support attribute access."""
    if isinstance(value, DotDict):
        return value
    if isinstance(value, dict):
        return DotDict(value)
    if isinstance(value, list):
        return [_wrap(item) for item in value]
    return value


def unwrap(value: Any) -> Any:
    """Return a plain, JSON-friendly copy of a possibly wrapped value."""
    if isinstance(value, dict):
        return {key: unwrap(item) for key, item in dict.items(value)}
    if isinstance(value, (list, tuple)):
        return [unwrap(item) for item in value]
    return value


# Methods that stay methods even when a key has the same name, as before DotDict was a dict.
_METHODS_FIRST = frozenset({"get", "keys", "to_dict"})


class DotDict(dict):
    """A dict whose keys are also attributes: ``params.rows[0].id``.

    It is a real dict, so code that checks ``isinstance(row, dict)`` (as models often write)
    sees one. A key wins over a dict method of the same name, so ``row.items`` is an ``items``
    column; ``get``, ``keys`` and ``to_dict`` stay methods.
    """

    __slots__ = ()

    def __getattribute__(self, name: str) -> Any:
        if (
            not name.startswith("_")
            and name not in _METHODS_FIRST
            and dict.__contains__(self, name)
        ):
            return _wrap(dict.__getitem__(self, name))
        return super().__getattribute__(name)

    def __getattr__(self, name: str) -> Any:
        available = ", ".join(sorted(str(key) for key in dict.keys(self))) or "none"
        raise AttributeError(
            f"Parameter {name!r} was not provided. Available parameters: {available}."
        )

    def __getitem__(self, key: str) -> Any:
        return _wrap(dict.__getitem__(self, key))

    def __repr__(self) -> str:
        return f"DotDict({dict.__repr__(self)})"

    def get(self, key: str, default: Any = None) -> Any:  # type: ignore[override]
        """Return a parameter by name, or ``default`` when it is absent."""
        if dict.__contains__(self, key):
            return _wrap(dict.__getitem__(self, key))
        return default

    def to_dict(self) -> dict:
        """Return a plain dict copy of the data."""
        return dict(self)


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
