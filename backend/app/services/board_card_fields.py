"""The typed fields of a kanban card, kept inside its ``card_metadata`` JSON.

Assignee, priority, due date, labels and links live under fixed keys, so the Board tab, the
chat tools and Heym Work read and write the same values, and column workflows receive them in
the card's ``metadata``. This module only validates, merges, compares and filters; access
checks (the assignee is a board member, a linked workflow is reachable) stay with the callers.
Heym's frontend mirrors the filter rules in ``frontend/src/lib/boardCardFields.ts``.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

ASSIGNEE_KEY = "assignee_user_id"
PRIORITY_KEY = "priority"
DUE_DATE_KEY = "due_date"
LABELS_KEY = "labels"
LINKS_KEY = "links"
ATTACHMENTS_KEY = "attachments"
FIELD_KEYS = (ASSIGNEE_KEY, PRIORITY_KEY, DUE_DATE_KEY, LABELS_KEY, LINKS_KEY)
RESERVED_KEYS = (*FIELD_KEYS, ATTACHMENTS_KEY)

PRIORITIES = ("low", "medium", "high", "urgent")
MAX_LABELS = 10
MAX_LABEL_LENGTH = 40
MAX_LINKS = 10
ME = "me"
UNASSIGNED = "unassigned"
DUE_WINDOW_DAYS = 7


class CardFieldError(ValueError):
    """A field value a card cannot take; the message is safe to show the user."""


@dataclass(frozen=True)
class CardLinkValue:
    """A link from a card to a workflow, and optionally to one of its executions."""

    workflow_id: uuid.UUID
    execution_id: uuid.UUID | None = None


@dataclass(frozen=True)
class CardFieldValues:
    """The typed fields read from a card's metadata; broken stored values read as empty."""

    assignee_user_id: uuid.UUID | None = None
    priority: str | None = None
    due_date: date | None = None
    labels: tuple[str, ...] = ()
    links: tuple[CardLinkValue, ...] = ()


def normalize_labels(values: Iterable[object]) -> list[str]:
    """Trimmed, non-empty labels without case-insensitive duplicates, in their first order."""
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        label = str(value).strip()
        if not label:
            continue
        if len(label) > MAX_LABEL_LENGTH:
            raise CardFieldError(f"A label can have at most {MAX_LABEL_LENGTH} characters")
        key = label.casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(label)
    if len(out) > MAX_LABELS:
        raise CardFieldError(f"A card can have at most {MAX_LABELS} labels")
    return out


def _uuid(value: object) -> uuid.UUID | None:
    if not value:
        return None
    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError):
        return None


def _date(value: object) -> date | None:
    if isinstance(value, date):
        return value
    if not value:
        return None
    try:
        return date.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


def _links(value: object) -> tuple[CardLinkValue, ...]:
    if not isinstance(value, list):
        return ()
    links: list[CardLinkValue] = []
    for item in value[:MAX_LINKS]:
        if not isinstance(item, Mapping):
            continue
        workflow_id = _uuid(item.get("workflow_id"))
        if workflow_id is None:
            continue
        links.append(CardLinkValue(workflow_id, _uuid(item.get("execution_id"))))
    return tuple(links)


def read_fields(metadata: Mapping[str, Any] | None) -> CardFieldValues:
    """The typed fields stored in ``metadata``."""
    if not isinstance(metadata, Mapping):
        return CardFieldValues()
    priority = metadata.get(PRIORITY_KEY)
    labels = metadata.get(LABELS_KEY)
    return CardFieldValues(
        assignee_user_id=_uuid(metadata.get(ASSIGNEE_KEY)),
        priority=priority if priority in PRIORITIES else None,
        due_date=_date(metadata.get(DUE_DATE_KEY)),
        labels=tuple(label for label in labels if isinstance(label, str))
        if isinstance(labels, list)
        else (),
        links=_links(metadata.get(LINKS_KEY)),
    )


def links_to_metadata(links: Iterable[CardLinkValue]) -> list[dict[str, str | None]]:
    """How links are stored: plain strings, so the JSON column and workflows read them."""
    return [
        {
            "workflow_id": str(link.workflow_id),
            "execution_id": str(link.execution_id) if link.execution_id else None,
        }
        for link in links
    ]


def merge_metadata(
    existing: Mapping[str, Any] | None,
    *,
    raw: Mapping[str, Any] | None = None,
    updates: Mapping[str, Any],
) -> dict[str, Any]:
    """The metadata after a write.

    ``raw`` replaces free-form keys but never the reserved ones (typed fields, attachments),
    which keep their stored values. ``updates`` then sets typed fields; None removes one.
    """
    current = dict(existing or {})
    merged = dict(raw) if raw is not None else dict(current)
    if raw is not None:
        for key in RESERVED_KEYS:
            if key in current:
                merged[key] = current[key]
            else:
                merged.pop(key, None)
    for key, value in updates.items():
        if value is None:
            merged.pop(key, None)
        else:
            merged[key] = value
    return merged


def edit_version(title: str, content: str, metadata: Mapping[str, Any] | None) -> str:
    """A short fingerprint of what people edit on a card: title, content and typed fields.

    Run status, position and attachments do not change it, so a finished run or a reorder
    elsewhere never makes an open editor stale.
    """
    source = metadata if isinstance(metadata, Mapping) else {}
    payload = {
        "title": title,
        "content": content,
        "fields": {key: source.get(key) for key in FIELD_KEYS},
    }
    encoded = json.dumps(payload, sort_keys=True, default=str).encode()
    return hashlib.sha256(encoded).hexdigest()[:16]


@dataclass(frozen=True)
class CardFilter:
    """Which cards a board view or a chat tool asks for; empty fields match everything.

    ``done_column_ids`` are columns whose cards are never overdue (each board's last column).
    """

    assignee: str | None = None
    column_ids: frozenset[uuid.UUID] | None = None
    priority: str | None = None
    due: str | None = None
    label: str | None = None
    run_status: str | None = None
    done_column_ids: frozenset[uuid.UUID] = frozenset()

    def matches(
        self,
        values: CardFieldValues,
        *,
        column_id: uuid.UUID,
        run_status: str,
        user_id: uuid.UUID,
        today: date,
    ) -> bool:
        """Whether a card with these fields, column and run status passes the filter."""
        if self.assignee is not None and not self._assignee_matches(values, user_id):
            return False
        if self.column_ids is not None and column_id not in self.column_ids:
            return False
        if self.priority is not None and values.priority != self.priority:
            return False
        if self.label is not None and self.label.casefold() not in {
            label.casefold() for label in values.labels
        }:
            return False
        if self.run_status is not None and run_status != self.run_status:
            return False
        if self.due is not None and not self._due_matches(values.due_date, column_id, today):
            return False
        return True

    def _assignee_matches(self, values: CardFieldValues, user_id: uuid.UUID) -> bool:
        if self.assignee == UNASSIGNED:
            return values.assignee_user_id is None
        wanted = user_id if self.assignee == ME else _uuid(self.assignee)
        return wanted is not None and values.assignee_user_id == wanted

    def _due_matches(self, due: date | None, column_id: uuid.UUID, today: date) -> bool:
        if due is None:
            return False
        if self.due == "overdue":
            return due < today and column_id not in self.done_column_ids
        if self.due == "today":
            return due == today
        return today <= due < today + timedelta(days=DUE_WINDOW_DAYS)
