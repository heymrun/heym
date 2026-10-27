"""Links a Heym Agent reply carries, always on the configured public origin."""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass

from app.services.chat_eval_mode import suite_url


@dataclass(frozen=True)
class WorkflowLink:
    """A workflow or eval suite the turn created or saved, and its URL on the public origin."""

    name: str
    url: str


_UUID = r"[0-9a-fA-F]{8}-(?:[0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}"
_RELATIVE_WORKFLOW_LINK = re.compile(rf"\]\((/workflows/{_UUID}(?:/{_UUID})?)\)")
_HIDDEN_MARKER = re.compile(r"<!--\s*heym-(?:workflow|eval-suite)-id:.*?-->")


def workflow_editor_url(public_base_url: str, workflow_id: uuid.UUID) -> str:
    """The workflow's editor URL on the public origin.

    `public_base_url` comes from `build_public_base_url`, which never reads request headers
    (GHSA-6rv3-wh25-7pg5), and the id is a parsed UUID, so a client cannot steer the link.
    """
    return f"{public_base_url.rstrip('/')}/workflows/{workflow_id}"


def absolutize_workflow_links(text: str, public_base_url: str) -> str:
    """Point the reply's relative `/workflows/<id>` markdown links at the public origin."""
    base = public_base_url.rstrip("/")
    return _RELATIVE_WORKFLOW_LINK.sub(lambda match: f"]({base}{match.group(1)})", text)


def strip_hidden_markers(content: str) -> str:
    """Drop the hidden HTML comment markers the Chat UI uses for workflow and suite context."""
    return _HIDDEN_MARKER.sub("", content).strip()


def _single_line(name: str | None, fallback: str) -> str:
    """A name kept to one line, so it cannot add lines to the result text."""
    return " ".join(str(name or "").split())[:120] or fallback


def workflow_link(public_base_url: str, workflow_id: uuid.UUID, name: str | None) -> WorkflowLink:
    """A link for the result text; the name is kept to one line so it cannot add lines."""
    return WorkflowLink(
        name=_single_line(name, "Workflow"),
        url=workflow_editor_url(public_base_url, workflow_id),
    )


def eval_suite_link(public_base_url: str, suite_id: uuid.UUID, name: str | None) -> WorkflowLink:
    """The suite on the Evals page, on the public origin; the id is a parsed UUID."""
    return WorkflowLink(
        name=_single_line(name, "Eval suite"), url=suite_url(public_base_url, suite_id)
    )
