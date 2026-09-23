"""Deterministic credential handling for workflows the chat builder generates.

The builder model is told which credentials to use; this pass makes the result safe no
matter what it wrote. Names become ids, foreign or wrong-type ids are dropped, the user's
choices fill empty fields, and a new node's required field nobody decided on is returned
as a need instead of being saved empty.
"""

from __future__ import annotations

import copy
import uuid
from dataclasses import dataclass, field
from typing import Any

from app.db.models import CredentialType
from app.services.credential_catalog import (
    NODE_CREDENTIAL_FIELDS,
    CatalogCredential,
    CredentialField,
    CredentialPromptMode,
)

REQUIRES_CREDENTIALS_INSTRUCTIONS = (
    "The workflow was not saved. Ask one heym-clarify question per service: offer the "
    "existing credentials listed for it, an option to create one, and an option to continue "
    "without a credential. Then call this tool again with credential_choices."
)


@dataclass(frozen=True)
class CredentialChoice:
    """One answer the user gave in chat: a credential by name, or none."""

    credential_type: CredentialType
    credential_name: str
    header_key: str = ""


@dataclass(frozen=True)
class CredentialNeed:
    """A new node's required credential field that no choice covers."""

    node: str
    node_type: str
    field: str
    credential_types: tuple[str, ...]
    existing: tuple[str, ...]


@dataclass
class CredentialPassResult:
    """Nodes after the pass, and the fields that still need a decision."""

    nodes: list[dict[str, Any]]
    needs: list[CredentialNeed] = field(default_factory=list)


def parse_credential_choices(raw: object) -> list[CredentialChoice]:
    """Parse the `credential_choices` tool argument, skipping malformed entries."""
    if not isinstance(raw, list):
        return []
    choices: list[CredentialChoice] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        try:
            credential_type = CredentialType(str(item.get("credential_type") or ""))
        except ValueError:
            continue
        choices.append(
            CredentialChoice(
                credential_type=credential_type,
                credential_name=str(item.get("credential_name") or "").strip(),
                header_key=str(item.get("header_key") or "").strip(),
            )
        )
    return choices


def format_credential_choices(choices: list[CredentialChoice]) -> str:
    """Render choices as builder instructions, or "" when there are none."""
    if not choices:
        return ""
    lines = ["Credential choices the user made:"]
    for choice in choices:
        if not choice.credential_name:
            lines.append(
                f"- {choice.credential_type.value}: no credential (leave the field empty, "
                "send http requests without authentication)"
            )
            continue
        line = f"- {choice.credential_type.value}: use `{choice.credential_name}`"
        if choice.header_key:
            line += f" with header key `{choice.header_key}` for http requests"
        lines.append(line)
    return "\n".join(lines)


def _label(node: dict[str, Any]) -> str:
    data = node.get("data")
    label = data.get("label") if isinstance(data, dict) else None
    return str(label) if label else ""


def _previous_version(
    node: dict[str, Any], previous: list[dict[str, Any]]
) -> dict[str, Any] | None:
    node_type = node.get("type")
    for old in previous:
        if old.get("id") == node.get("id") and old.get("type") == node_type:
            return old
    label = _label(node)
    if not label:
        return None
    for old in previous:
        if old.get("type") == node_type and _label(old) == label:
            return old
    return None


def _canonical_uuid(text: str) -> str:
    try:
        return str(uuid.UUID(text))
    except ValueError:
        return text


def _resolve(
    value: object,
    spec: CredentialField,
    owned_by_id: dict[str, CatalogCredential],
    owned_by_name: dict[str, CatalogCredential],
) -> str:
    if not isinstance(value, str) or not value.strip():
        return ""
    text = value.strip()
    credential = owned_by_id.get(_canonical_uuid(text)) or owned_by_name.get(text)
    if credential is None or credential.type not in spec.types:
        return ""
    return str(credential.id)


def _named_choice_ids(
    spec: CredentialField,
    choices: list[CredentialChoice],
    owned_by_name: dict[str, CatalogCredential],
) -> list[str]:
    ids: list[str] = []
    for choice in choices:
        if choice.credential_type not in spec.types or not choice.credential_name:
            continue
        credential = owned_by_name.get(choice.credential_name)
        if credential is None or credential.type not in spec.types:
            continue
        if str(credential.id) not in ids:
            ids.append(str(credential.id))
    return ids


def _declined(spec: CredentialField, choices: list[CredentialChoice]) -> bool:
    return any(c.credential_type in spec.types and not c.credential_name for c in choices)


def _restore(data: dict[str, Any], name: str, value: object) -> None:
    if value is None:
        data.pop(name, None)
    else:
        data[name] = value


def _need(
    node: dict[str, Any], spec: CredentialField, catalog: list[CatalogCredential]
) -> CredentialNeed:
    return CredentialNeed(
        node=_label(node) or str(node.get("id") or ""),
        node_type=str(node.get("type") or ""),
        field=spec.name,
        credential_types=tuple(sorted(t.value for t in spec.types)),
        existing=tuple(sorted(c.name for c in catalog if c.type in spec.types)),
    )


def apply_generated_credentials(
    nodes: list[dict[str, Any]],
    *,
    catalog: list[CatalogCredential],
    choices: list[CredentialChoice],
    previous_nodes: list[dict[str, Any]] | None,
    mode: CredentialPromptMode,
) -> CredentialPassResult:
    """Make every credential field of a generated workflow safe and deterministic.

    A node that already existed keeps an unchanged value, since that was the user's own
    choice. In OFF mode it keeps its old value whatever the builder wrote, and new nodes
    get no credential. Otherwise a value must be, or name, an owned credential of an
    accepted type; the user's choices fill empty fields; and a new node's required field
    that no choice covers becomes a need.
    """
    owned_by_id = {str(credential.id): credential for credential in catalog}
    owned_by_name = {credential.name: credential for credential in catalog}
    previous = [node for node in previous_nodes or [] if isinstance(node, dict)]
    result = copy.deepcopy(nodes)
    needs: list[CredentialNeed] = []
    for node in result:
        if not isinstance(node, dict):
            continue
        fields = NODE_CREDENTIAL_FIELDS.get(str(node.get("type") or ""), ())
        data = node.get("data")
        if not fields or not isinstance(data, dict):
            continue
        before = _previous_version(node, previous)
        old_data = before.get("data") if before is not None else None
        old_data = old_data if isinstance(old_data, dict) else {}
        for spec in fields:
            unchanged = data.get(spec.name) == old_data.get(spec.name)
            if before is not None and (mode is CredentialPromptMode.OFF or unchanged):
                _restore(data, spec.name, old_data.get(spec.name))
                continue
            if mode is CredentialPromptMode.OFF:
                data[spec.name] = ""
                if spec.required:
                    needs.append(_need(node, spec, catalog))
                continue
            resolved = _resolve(data.get(spec.name), spec, owned_by_id, owned_by_name)
            named = _named_choice_ids(spec, choices, owned_by_name)
            declined = not named and _declined(spec, choices)
            if before is None and len(named) == 1:
                resolved = named[0]
            elif before is None and declined:
                resolved = ""
            elif not resolved and len(named) == 1:
                resolved = named[0]
            if not resolved and before is not None and not declined:
                _restore(data, spec.name, old_data.get(spec.name))
                continue
            data[spec.name] = resolved
            if not resolved and spec.required and before is None and not declined:
                needs.append(_need(node, spec, catalog))
    return CredentialPassResult(nodes=result, needs=needs)


def _need_as_dict(need: CredentialNeed) -> dict[str, Any]:
    return {
        "node": need.node,
        "node_type": need.node_type,
        "field": need.field,
        "credential_types": list(need.credential_types),
        "existing": list(need.existing),
    }


def requires_credentials_payload(needs: list[CredentialNeed]) -> dict[str, Any]:
    """Tool result that asks the chat to collect credential choices before saving."""
    return {
        "status": "requires_credentials",
        "needs": [_need_as_dict(need) for need in needs],
        "instructions": REQUIRES_CREDENTIALS_INSTRUCTIONS,
    }


def credentials_to_assign_payload(needs: list[CredentialNeed]) -> dict[str, Any]:
    """Tell an MCP caller which nodes still need a credential set in the Heym UI."""
    if not needs:
        return {}
    return {
        "credentials_to_assign_in_ui": [
            {
                "node": need.node,
                "node_type": need.node_type,
                "credential_types": list(need.credential_types),
            }
            for need in needs
        ],
        "credentials_note": (
            "Credentials cannot be chosen over MCP. Set these in the Heym UI before running."
        ),
    }
