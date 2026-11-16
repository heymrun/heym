"""Substring search over the text of a JSON column."""

import json

from sqlalchemy import String, cast, or_
from sqlalchemy.sql.elements import ColumnElement


def json_text_ilike(column: object, search: str) -> ColumnElement[bool]:
    """Case-insensitive substring match on a JSON column's text, as written or JSON-escaped.

    A PostgreSQL ``json`` column keeps the text it was given, and SQLAlchemy writes it with
    ``json.dumps``, which stores "café" as ``caf\\u00e9``. So the search also tries the
    escaped spelling; without it a word with any character outside ASCII never matches.
    Case folding of an escaped character is not possible, so that half matches its case.
    A ``jsonb`` column stores the characters themselves and needs only a plain ``ILIKE``.
    """
    text = cast(column, String)
    clause = text.ilike(f"%{search}%")
    escaped = json.dumps(search)[1:-1]
    if escaped == search:
        return clause
    # A backslash escapes the next character in a LIKE pattern, so double it.
    return or_(clause, text.ilike(f"%{escaped.replace(chr(92), chr(92) * 2)}%"))
