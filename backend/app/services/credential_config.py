"""Reading the optional numeric fields of a stored credential config."""

from collections.abc import Mapping
from typing import Any


def config_int(config: Mapping[str, Any], key: str, default: int) -> int:
    """`config[key]` as an int; a missing, null or blank value gives `default`.

    The credential dialog saves an optional field the user cleared as "", which `int()`
    refuses. The dialog shows the default for such a field, so that is what it means.
    """
    value = config.get(key)
    if value is None:
        return default
    text = str(value).strip()
    return int(text) if text else default
