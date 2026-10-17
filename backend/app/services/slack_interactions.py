"""Answers to Slack approvals, buttons and forms.

A click or a submitted modal finds the review its key belongs to, records who answered
and how on the review itself, and resumes the run. A decision made in Heym instead
replaces the buttons in Slack with a note, so the message does not invite a second answer.
"""

from __future__ import annotations

import asyncio
import copy
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Credential, CredentialType, HITLRequest
from app.db.session import async_session_maker
from app.services import slack_service as slack
from app.services.encryption import decrypt_config
from app.services.hitl_service import build_hitl_resolved_output, claim_hitl_request_for_decision

logger = logging.getLogger("slack_interactions")


@dataclass(frozen=True)
class SlackAnswer:
    """One person's answer, as a review decision plus what the step outputs."""

    decision: str
    answer: dict
    note: str
    edited_text: str | None = None
    refusal_reason: str | None = None


async def bot_credential(db: AsyncSession, credential_id: str) -> slack.SlackBotConfig | None:
    """The bot configuration of a `slack_bot` credential, or None."""
    try:
        cred_uuid = uuid.UUID(str(credential_id))
    except (ValueError, AttributeError):
        return None
    credential = (
        await db.execute(
            select(Credential).where(
                Credential.id == cred_uuid, Credential.type == CredentialType.slack_bot
            )
        )
    ).scalar_one_or_none()
    if credential is None:
        return None
    try:
        return slack.bot_config(decrypt_config(credential.encrypted_config))
    except slack.SlackApiError:
        return None


def internals(hitl_request: HITLRequest) -> dict:
    """What the Slack step stored about its message on the review."""
    stored = hitl_request.original_agent_output or {}
    value = stored.get("_slack") if isinstance(stored, dict) else None
    return value if isinstance(value, dict) else {}


async def find_waiting_request(
    db: AsyncSession, key: str, credential_id: str
) -> HITLRequest | None:
    """The review still waiting on this key, posted with this credential."""
    if not key:
        return None
    rows = (
        await db.execute(
            select(HITLRequest).where(
                HITLRequest.status == "pending",
                HITLRequest.expires_at > datetime.now(timezone.utc),
                HITLRequest.original_agent_output[("_slack", "key")].as_string() == key,
            )
        )
    ).scalars()
    for row in rows:
        if internals(row).get("credentialId") == str(credential_id):
            return row
    return None


def may_answer(hitl_request: HITLRequest, user_id: str) -> bool:
    """Whether this Slack user is allowed to answer; an empty list lets anyone answer."""
    allowed = internals(hitl_request).get("allowedUsers") or []
    return not allowed or user_id in allowed


def user_ref(user: object) -> dict:
    """The Slack user who answered, as the step outputs it."""
    data = user if isinstance(user, dict) else {}
    return {
        "id": str(data.get("id") or ""),
        "name": str(data.get("name") or data.get("username") or ""),
    }


def answer_for_action(hitl_request: HITLRequest, action_id: str, user: dict) -> SlackAnswer | None:
    """The answer a button gives on its own; None for buttons that open a modal."""
    who = f"<@{user['id']}>"
    if action_id == slack.ACTION_APPROVE:
        return SlackAnswer(
            "accept",
            {"approval": "approved", "user": user},
            f":white_check_mark: Approved by {who}",
        )
    if action_id == slack.ACTION_REJECT:
        return SlackAnswer(
            "refuse",
            {"approval": "rejected", "user": user},
            f":no_entry: Rejected by {who}",
            refusal_reason=f"Rejected in Slack by {user['name'] or user['id']}",
        )
    if action_id.startswith(slack.ACTION_CHOICE_PREFIX):
        buttons = internals(hitl_request).get("buttons") or []
        try:
            button = buttons[int(action_id.removeprefix(slack.ACTION_CHOICE_PREFIX))]
        except (ValueError, IndexError):
            return None
        choice = {"label": button.get("label"), "value": button.get("value")}
        return SlackAnswer(
            "accept",
            {"choice": choice, "user": user},
            f":ballot_box_with_check: {who} chose *{choice['label']}*",
        )
    return None


def answer_for_view(hitl_request: HITLRequest, view: dict, user: dict) -> SlackAnswer | None:
    """The answer a submitted modal gives."""
    who = f"<@{user['id']}>"
    callback_id = view.get("callback_id")
    if callback_id == slack.VIEW_CHANGES:
        comment = str(
            slack.read_form_values(view.get("state") or {}, [{"name": "comment"}]).get("comment")
            or ""
        ).strip()
        return SlackAnswer(
            "edit",
            {"approval": "changes_requested", "comment": comment, "user": user},
            f":pencil2: Changes requested by {who}: {comment}",
            edited_text=comment or "Changes requested",
        )
    if callback_id == slack.VIEW_FORM:
        fields = internals(hitl_request).get("fields") or []
        values = slack.read_form_values(view.get("state") or {}, fields)
        return SlackAnswer(
            "accept", {"values": values, "user": user}, f":memo: Form submitted by {who}"
        )
    return None


async def record_answer(db: AsyncSession, hitl_request: HITLRequest, answer: SlackAnswer) -> bool:
    """Resolve the review with this answer. False when someone else answered first."""
    merged = copy.deepcopy(hitl_request.original_agent_output or {})
    merged.setdefault("_slack", {})["answer"] = answer.answer
    claimed = await claim_hitl_request_for_decision(
        db,
        hitl_request,
        decision=answer.decision,
        edited_text=answer.edited_text,
        refusal_reason=answer.refusal_reason,
        original_agent_output=merged,
    )
    if not claimed:
        return False
    hitl_request.original_agent_output = merged
    hitl_request.decision = answer.decision
    hitl_request.edited_text = answer.edited_text
    hitl_request.refusal_reason = answer.refusal_reason
    hitl_request.status = "resolved"
    hitl_request.resolved_at = datetime.now(timezone.utc)
    hitl_request.resume_error = None
    hitl_request.resolved_output = build_hitl_resolved_output(hitl_request)
    await db.commit()
    return True


def replace_buttons(token: str, hitl_request: HITLRequest, note: str) -> None:
    """Swap the message's buttons for a note on how it was answered."""
    stored = hitl_request.original_agent_output or {}
    channel = str(stored.get("channel") or "")
    ts = str(stored.get("ts") or "")
    if not channel or not ts:
        return
    message = str(internals(hitl_request).get("message") or "")
    try:
        slack.call_slack(
            token,
            "chat.update",
            {
                "channel": channel,
                "ts": ts,
                "text": message,
                "blocks": slack.answered_blocks(message, note),
            },
        )
    except slack.SlackApiError as exc:
        logger.warning("Could not update answered Slack message %s: %s", ts, exc)


_HEYM_NOTES = {
    "accept": ":white_check_mark: Answered in Heym",
    "edit": ":pencil2: Changes requested in Heym",
    "refuse": ":no_entry: Rejected in Heym",
}


async def sync_message_after_heym_decision(request_id: uuid.UUID) -> None:
    """After a decision in Heym, take the buttons off the Slack message."""
    async with async_session_maker() as db:
        hitl_request = await db.get(HITLRequest, request_id)
        if hitl_request is None:
            return
        stored = internals(hitl_request)
        config = await bot_credential(db, str(stored.get("credentialId") or ""))
    if config is None:
        return
    note = _HEYM_NOTES.get(hitl_request.decision or "", ":white_check_mark: Answered in Heym")
    await asyncio.to_thread(replace_buttons, config.bot_token, hitl_request, note)
