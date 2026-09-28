"""Pure transformation of workflow output into a standardized chart payload.

Shared by the chartOutput executor node and (indirectly) the dashboard data API.
Keep this side-effect free so it stays trivially unit-testable.
"""

from typing import Any

from app.services.markdown_task_list import has_task_items


def _resolve_rows(data: Any, data_path: str | None) -> list:
    """Resolve a list of row dicts (or scalars) from arbitrary upstream output."""
    if data_path:
        node: Any = data
        for part in data_path.split("."):
            if isinstance(node, dict):
                node = node.get(part)
            else:
                node = None
                break
        data = node

    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        if not data:
            return []
        if isinstance(data.get("data"), list):
            return data["data"]
        for value in data.values():
            if isinstance(value, list):
                return value
        return [data]
    return []


def resolve_text_payload(config: dict, data: Any) -> dict[str, Any]:
    """Resolve markdown text and whether dashboard checkboxes may be toggled.

    Checkboxes are interactive only when the message comes from the static
    ``text`` config field (not from ``valueField`` or other upstream fallbacks).
    """
    rows = _resolve_rows(data, config.get("dataPath"))
    text_val: Any = None
    text_interactive = False
    value_field = config.get("valueField")
    static_text = config.get("text")

    if rows and isinstance(rows[0], dict) and value_field:
        upstream = rows[0].get(value_field)
        if upstream is not None:
            text_val = upstream
    if text_val is None and isinstance(data, str):
        text_val = data
    if text_val is None and static_text is not None:
        text_val = static_text
        text_interactive = True
    if text_val is None and rows and isinstance(rows[0], dict):
        for candidate in rows[0].values():
            if isinstance(candidate, str):
                text_val = candidate
                break
    result_text = "" if text_val is None else str(text_val)
    if not text_interactive and has_task_items(result_text):
        text_interactive = True
    return {
        "text": result_text,
        "text_interactive": text_interactive,
    }


def _coerce_number(value: Any) -> Any:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value
    try:
        if isinstance(value, str) and value.strip() != "":
            return float(value) if "." in value else int(value)
    except (ValueError, TypeError):
        pass
    return value


def build_chart_payload(config: dict, data: Any) -> dict:
    """Transform resolved upstream data into a ChartPayload for the given chart type."""
    chart_type = config.get("chartType", "bar")
    title = config.get("title")
    if chart_type == "hitl":
        # The dashboard fills this from the signed-in user's inbox. Upstream rows
        # are ignored so a HITL widget does not need a data source.
        payload: dict = {"type": "hitl"}
        if title:
            payload["title"] = title
        return payload

    rows = _resolve_rows(data, config.get("dataPath"))

    payload: dict = {"type": chart_type}
    if title:
        payload["title"] = title

    url = config.get("url")
    if isinstance(url, str) and url.strip():
        payload["url"] = url.strip()

    if chart_type == "text":
        text_meta = resolve_text_payload(config, data)
        payload["text"] = text_meta["text"]
        payload["text_interactive"] = text_meta["text_interactive"]
        return payload

    if chart_type == "table":
        columns = config.get("columns")
        if not columns:
            columns = list(rows[0].keys()) if rows and isinstance(rows[0], dict) else []
        payload["columns"] = columns
        payload["rows"] = [
            [row.get(col) if isinstance(row, dict) else row for col in columns] for row in rows
        ]
        return payload

    if chart_type in ("numeric", "gauge"):
        value_field = config.get("valueField")
        value: Any = None
        if rows and isinstance(rows[0], dict):
            if value_field:
                value = rows[0].get(value_field)
            else:
                # first numeric field of the first row
                for candidate in rows[0].values():
                    if isinstance(candidate, (int, float)) and not isinstance(candidate, bool):
                        value = candidate
                        break
        elif isinstance(data, dict) and "value" in data:
            value = data["value"]
        elif isinstance(data, (int, float)):
            value = data
        payload["value"] = _coerce_number(value)
        if config.get("unit"):
            payload["unit"] = config["unit"]
        if config.get("decimals") is not None:
            payload["decimals"] = config["decimals"]
        if chart_type == "gauge":
            payload["min"] = _coerce_number(config.get("min", 0))
            payload["max"] = _coerce_number(config.get("max", 100))
        return payload

    if chart_type == "scatter":
        x_field = config.get("xField") or config.get("labelField")
        y_field = config.get("yField") or config.get("valueField", "value")
        points: list = []
        for row in rows:
            if isinstance(row, dict):
                x = _coerce_number(row.get(x_field)) if x_field else None
                y = _coerce_number(row.get(y_field))
                points.append([x, y])
        payload["series"] = [{"name": config.get("seriesName") or y_field, "data": points}]
        return payload

    # pie / bar / line share labels + series
    label_field = config.get("labelField")
    if label_field:
        payload["labels"] = [
            (row.get(label_field) if isinstance(row, dict) else row) for row in rows
        ]
    else:
        payload["labels"] = [
            (row.get(next(iter(row))) if isinstance(row, dict) and row else row) for row in rows
        ]

    series_defs = config.get("series")
    if series_defs:
        payload["series"] = [
            {
                "name": s.get("name", s.get("field", "")),
                "data": [
                    _coerce_number(row.get(s["field"])) if isinstance(row, dict) else None
                    for row in rows
                ],
            }
            for s in series_defs
        ]
    else:
        value_field = config.get("valueField", "value")
        payload["series"] = [
            {
                "name": value_field,
                "data": [
                    _coerce_number(row.get(value_field))
                    if isinstance(row, dict)
                    else _coerce_number(row)
                    for row in rows
                ],
            }
        ]

    if chart_type == "bar":
        payload["orientation"] = config.get("orientation", "vertical")

    if chart_type == "barGauge":
        if config.get("unit"):
            payload["unit"] = config["unit"]
        if config.get("max") is not None:
            payload["max"] = _coerce_number(config["max"])

    return payload
