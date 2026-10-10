"""Keep AI-built widget workflows reading ``$page.record`` as the value it is.

A detail page's record is one plain string (``V-1002``), not an object, yet models often
write ``$page.record.id`` or ``$page.record.vendor_id``. Such a path resolves to nothing:
a ``dataTable`` filter then looks for the literal text and the widget shows no rows. The
only thing such a path can mean is the record itself, so the fields are dropped. String
helpers the expression engine has (``$page.record.upper()``, ``.length``) stay.
"""

import re
from typing import Any

from app.services.page_params import MAX_RECORD_LENGTH
from app.services.workflow_executor import DotStr

_PAGE_RECORD_PATH = re.compile(r"\$page\.record((?:\.[A-Za-z_]\w*)+)")


def _without_fields(match: re.Match[str]) -> str:
    """``$page.record`` and its path from the first name a string has, if any."""
    segments = match.group(1)[1:].split(".")
    for index, name in enumerate(segments):
        if hasattr(DotStr, name):
            return "$page.record." + ".".join(segments[index:])
    return "$page.record"


def repair_page_record_paths(value: Any) -> Any:
    """``value`` (a workflow's nodes, or any part of them) with record fields dropped."""
    if isinstance(value, str):
        return _PAGE_RECORD_PATH.sub(_without_fields, value) if "$page.record." in value else value
    if isinstance(value, list):
        return [repair_page_record_paths(item) for item in value]
    if isinstance(value, dict):
        return {key: repair_page_record_paths(item) for key, item in value.items()}
    return value


def example_record(payload: Any, record_field: str) -> str | None:
    """The first record a table widget's cached chart shows in ``record_field``, if any."""
    if not isinstance(payload, dict) or payload.get("type") != "table":
        return None
    columns = payload.get("columns")
    if not isinstance(columns, list) or record_field not in columns:
        return None
    index = columns.index(record_field)
    for row in payload.get("rows") or []:
        if isinstance(row, list) and index < len(row) and row[index] is not None:
            value = str(row[index]).strip()
            if value:
                return value[:MAX_RECORD_LENGTH]
    return None


def detail_page_context(record_fields: list[str], example: str | None) -> str:
    """What a model building a widget on a detail page is told about ``$page.record``."""
    if not record_fields:
        return ""
    field = record_fields[0] if len(record_fields) == 1 else "record column"
    sample = f' such as "{example}"' if example else ""
    return (
        f"This dashboard is a detail page: a clicked table row opens it with the row's "
        f"{' or '.join(record_fields)} value as $page.record, one plain text value{sample}, not "
        f"an object. Show that one record's data by keeping only the rows whose {field} equals "
        f'$page.record, for example a dataTable find with dataTableFilter {{"{record_fields[0]}": '
        f'"$page.record"}}. Never write $page.record.id or $page.record.{record_fields[0]}.'
    )
