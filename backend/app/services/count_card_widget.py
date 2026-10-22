"""A count card: how many rows of a data table have one value in a column, built without AI.

Heym Work puts one card per status on a page made from a data table. The card is a ``text``
widget whose markdown is one HTML block with the number, styled inline with the theme's color
variables so it reads in both themes and in both apps. The widget's title names the value, so
it shows wherever the dashboard puts titles.
"""

import json
import re
import uuid
from typing import Any

COUNT_NODE_LABEL = "rowCount"
CARD_FIELD = "html"

# A filter value is read as a message template, so `$name` in it would be resolved.
_TEMPLATE_REF = re.compile(r"\$[A-Za-z_]")

_NUMBER_STYLE = (
    "font-size:2.25rem;line-height:1.1;font-weight:500;"
    "font-variant-numeric:tabular-nums;color:hsl(var(--foreground))"
)


def countable_value(value: str) -> bool:
    """False for a value the dataTable filter would read as an expression."""
    return not _TEMPLATE_REF.search(value)


def count_card_html() -> str:
    """The card's markdown: one HTML block with the count the run fills in."""
    return f'<div style="{_NUMBER_STYLE}">${COUNT_NODE_LABEL}.count</div>'


def count_card_nodes(
    table_id: uuid.UUID, column: str, value: str
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """The card's graph: count the rows whose ``column`` is ``value``, then show the card."""
    count_id, card_id, chart_id = (str(uuid.uuid4()) for _ in range(3))
    nodes: list[dict[str, Any]] = [
        {
            "id": count_id,
            "type": "dataTable",
            "position": {"x": 0, "y": 0},
            "data": {
                "label": COUNT_NODE_LABEL,
                "dataTableId": str(table_id),
                "dataTableOperation": "count",
                "dataTableFilter": json.dumps({column: value}),
            },
        },
        {
            "id": card_id,
            "type": "set",
            "position": {"x": 320, "y": 0},
            "data": {
                "label": "card",
                "mappings": [{"key": CARD_FIELD, "value": count_card_html()}],
            },
        },
        {
            "id": chart_id,
            "type": "chartOutput",
            "position": {"x": 640, "y": 0},
            "data": {"label": "chart", "chartType": "text", "valueField": CARD_FIELD},
        },
    ]
    edges = [
        {"id": str(uuid.uuid4()), "source": count_id, "target": card_id},
        {"id": str(uuid.uuid4()), "source": card_id, "target": chart_id},
    ]
    return nodes, edges
