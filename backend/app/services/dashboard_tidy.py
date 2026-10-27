"""Tidy a dashboard: its widgets, in their order, in rows on the 12-column grid.

The arrangement the Dashboard tab's Tidy up button makes (``frontend/src/lib/dashboardTidy.ts``):
rows hold two or three widgets at random, with a trailing one or two, every widget is
``TIDY_ROW_HEIGHT`` rows tall, and the widgets in a row share its width. A fixed ``per_row``
gives every row that many widgets at the same width instead.
"""

import random
from collections.abc import Callable
from dataclasses import dataclass

GRID_COLUMNS = 12
TIDY_ROW_HEIGHT = 5
MAX_PER_ROW = 4
# Random rows that come out as the dashboard already is are drawn again, this many times at most.
_ATTEMPTS = 8


@dataclass(frozen=True)
class TidyLayout:
    """Widgets per row, top to bottom, and each widget's new grid layout in order."""

    rows: list[int]
    layouts: list[dict[str, int]]


def _row_sizes(count: int, per_row: int | None, rand: Callable[[], float]) -> list[int]:
    if per_row is not None:
        return [min(per_row, count - start) for start in range(0, count, per_row)]
    rows: list[int] = []
    remaining = count
    while remaining > 0:
        if remaining <= 2:
            rows.append(remaining)
            break
        size = 2 if rand() < 0.5 else 3
        rows.append(size)
        remaining -= size
    return rows


def _layouts(rows: list[int], per_row: int | None) -> list[dict[str, int]]:
    layouts: list[dict[str, int]] = []
    for index, size in enumerate(rows):
        width = GRID_COLUMNS // (per_row or size)
        y = index * TIDY_ROW_HEIGHT
        layouts.extend(
            {"x": column * width, "y": y, "w": width, "h": TIDY_ROW_HEIGHT}
            for column in range(size)
        )
    return layouts


def tidy_layouts(
    current: list[dict[str, int]],
    per_row: int | None = None,
    rand: Callable[[], float] = random.random,
) -> TidyLayout:
    """New layouts for widgets now laid out as ``current``, in the same order.

    Random rows differ from ``current`` whenever the widget count allows another arrangement,
    so tidying again changes the dashboard.
    """
    for _ in range(_ATTEMPTS):
        rows = _row_sizes(len(current), per_row, rand)
        layouts = _layouts(rows, per_row)
        if per_row is not None or layouts != current:
            break
    return TidyLayout(rows, layouts)
