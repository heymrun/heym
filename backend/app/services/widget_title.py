"""Short dashboard widget titles: a few words that say what a widget shows.

The widget builder names a widget's workflow. A model that names it after the request, or does
not name it at all, leaves a sentence with a data table's id in it, and that sentence became the
card's title. ``widget_title`` keeps the first few words of a name without ids.
"""

import re

MAX_TITLE_WORDS = 4
MAX_TITLE_LENGTH = 80
DEFAULT_WIDGET_TITLE = "Widget"

_UUID = r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
_ID_GROUP = re.compile(rf"\([^()]*(?:dataTableId|{_UUID})[^()]*\)", re.IGNORECASE)
_ID = re.compile(rf"(?:dataTableId\s*[:=]?\s*)?{_UUID}|dataTableId", re.IGNORECASE)
_EDGE = "\"'`.,:;!?-–— "


def _clean(candidate: str | None) -> str:
    text = _ID_GROUP.sub(" ", str(candidate or ""))
    text = _ID.sub(" ", text).replace("_", " ")
    title = " ".join(text.split()[:MAX_TITLE_WORDS]).strip(_EDGE)[:MAX_TITLE_LENGTH].rstrip()
    return title[:1].upper() + title[1:]


def widget_title(*candidates: str | None) -> str:
    """The first candidate that still says something without its ids, as a card title.

    Ids and ``dataTableId`` mentions are dropped, underscores read as spaces, and at most four
    words are kept. ``DEFAULT_WIDGET_TITLE`` when no candidate says anything.
    """
    for candidate in candidates:
        title = _clean(candidate)
        if title:
            return title
    return DEFAULT_WIDGET_TITLE
