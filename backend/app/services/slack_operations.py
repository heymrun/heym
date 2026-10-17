"""The Slack node's operations on a `slack_bot` credential.

Posting operations return where the message landed (`channel`, `ts`, `threadTs`) so a
later step can reply in its thread, update it or react to it. Approvals, buttons and
forms pause the run as a review: a click in Slack, or a decision in Heym, resumes it.
"""

from __future__ import annotations

import re
import time
from datetime import datetime, timezone
from importlib import import_module
from typing import Any

from app.services import slack_service as slack
from app.services.node_execution.base import NodeExecutionContext

DEFAULT_OPERATION = "sendMessage"
WAITING_OPERATIONS = frozenset({"requestApproval", "sendButtons", "sendForm"})
OPERATIONS = frozenset(
    {
        "sendMessage",
        "sendDirectMessage",
        "sendForm",
        "sendButtons",
        "requestApproval",
        "replyInThread",
        "updateMessage",
        "postOutcome",
        "addReaction",
        "deleteMessage",
        "getMessages",
        "findUser",
    }
)
# An outcome can follow an earlier approval: `$approval.approval` picks the card's color.
APPROVAL_OUTCOMES = {"approved": "success", "rejected": "failure", "changes_requested": "warning"}
_SUMMARY_LIMIT = 280
_PROSE_KEYS = frozenset({"message", "slackOutcomeTitle"})
_MAX_HISTORY = 200
_MAX_NAME_LOOKUPS = 25
_MENTION = re.compile(r"<@([UW][A-Z0-9]+)(?:\|[^>]*)?>")


def _text(ctx: NodeExecutionContext, key: str, default: str = "") -> str:
    template = ctx.node_data.get(key, default)
    if template is None or template == "":
        return ""
    value = str(ctx.executor.evaluate_message_template(str(template), ctx.inputs, ctx.node_id))
    # A model's Markdown (`**bold**`, `## Title`) shows as raw symbols in Slack.
    return slack.to_slack_mrkdwn(value) if key in _PROSE_KEYS else value


def _required(ctx: NodeExecutionContext, key: str, label: str) -> str:
    value = _text(ctx, key).strip()
    if not value:
        raise ValueError(f"Slack {label} is required for this operation")
    return value


def _first_line(text: str) -> str:
    line = next((part.strip() for part in text.splitlines() if part.strip()), "")
    return line[:_SUMMARY_LIMIT]


def _post(token: str, channel: str, text: str, *, thread_ts: str = "", **extra: Any) -> dict:
    payload: dict[str, Any] = {"channel": channel, "text": text[:40000], **extra}
    if thread_ts:
        payload["thread_ts"] = thread_ts
    return slack.message_output(slack.call_slack(token, "chat.postMessage", payload), text)


def _pause(
    ctx: NodeExecutionContext,
    *,
    kind: str,
    summary: str,
    draft_text: str,
    posted: dict,
    internals: dict,
) -> object:
    node_result_class = import_module("app.services.workflow_executor").NodeResult
    pending_output = {
        "decision": None,
        "summary": summary,
        "draftText": draft_text,
        "reviewUrl": None,
        "requestId": None,
        "expiresAt": None,
        "shareText": None,
        "shareMarkdown": None,
        **posted,
    }
    original = {**posted, "_slack": {"kind": kind, **internals}}
    return node_result_class(
        node_id=ctx.node_id,
        node_label=ctx.node_label,
        node_type=ctx.node_type,
        status="pending",
        output=pending_output,
        execution_time_ms=(time.time() - ctx.start_time) * 1000,
        metadata={
            "hitl": {
                "summary": summary,
                "draft_text": draft_text,
                "original_agent_output": original,
                "resume_mode": "inject_output",
                "review_mode": f"slack_{kind}",
            }
        },
    )


def _waiting(ctx: NodeExecutionContext, token: str, credential_id: str, operation: str) -> object:
    channel = slack.resolve_target(token, _required(ctx, "slackChannel", "channel or person"))
    message = _required(ctx, "message", "message")
    thread_ts = _text(ctx, "slackThreadTs").strip()
    allowed = slack.resolve_user_list(token, ctx.node_data.get("slackAllowedUsers") or "")
    key = slack.new_action_key()
    internals: dict[str, Any] = {
        "key": key,
        "credentialId": str(credential_id),
        "allowedUsers": allowed,
        "message": message,
    }
    if operation == "requestApproval":
        posted = _post(
            token,
            channel,
            message,
            thread_ts=thread_ts,
            blocks=slack.approval_blocks(message, key),
        )
        return _pause(
            ctx,
            kind="approval",
            summary=_first_line(message) or "Approval requested in Slack",
            draft_text=message,
            posted=posted,
            internals=internals,
        )
    if operation == "sendButtons":
        buttons = slack.normalize_buttons(ctx.node_data.get("slackButtons"))
        internals["buttons"] = buttons
        posted = _post(
            token,
            channel,
            message,
            thread_ts=thread_ts,
            blocks=slack.button_blocks(message, key, buttons),
        )
        choices = ", ".join(button["label"] for button in buttons)
        return _pause(
            ctx,
            kind="buttons",
            summary=f"Waiting for a choice in Slack: {_first_line(message)}",
            draft_text=f"{message}\n\nChoices: {choices}",
            posted=posted,
            internals=internals,
        )
    fields = slack.normalize_form_fields(ctx.node_data.get("slackFormFields"))
    title = _text(ctx, "slackFormTitle").strip() or "Form"
    internals.update(
        {
            "fields": fields,
            "formTitle": title,
            "submitLabel": _text(ctx, "slackSubmitLabel").strip(),
        }
    )
    posted = _post(
        token,
        channel,
        message,
        thread_ts=thread_ts,
        blocks=slack.form_blocks(message, key, f"Open {title}"[:75]),
    )
    labels = ", ".join(field["label"] for field in fields)
    return _pause(
        ctx,
        kind="form",
        summary=f"Waiting for a form in Slack: {title}",
        draft_text=f"{message}\n\nFields: {labels}",
        posted=posted,
        internals=internals,
    )


def _get_messages(ctx: NodeExecutionContext, token: str) -> dict:
    channel = slack.resolve_target(token, _required(ctx, "slackChannel", "channel"))
    thread_ts = _text(ctx, "slackThreadTs").strip()
    try:
        limit = max(1, min(int(_text(ctx, "slackLimit") or 20), _MAX_HISTORY))
    except ValueError:
        limit = 20
    params = {"channel": channel, "limit": str(limit)}
    if thread_ts:
        body = slack.call_slack(
            token, "conversations.replies", {**params, "ts": thread_ts}, read=True
        )
    else:
        body = slack.call_slack(token, "conversations.history", params, read=True)
    messages = [
        {
            "ts": item.get("ts"),
            "threadTs": item.get("thread_ts"),
            "user": item.get("user") or item.get("bot_id"),
            "text": item.get("text", ""),
            "replyCount": item.get("reply_count", 0),
        }
        for item in body.get("messages") or []
        if isinstance(item, dict)
    ]
    return {
        "channel": channel,
        "messages": messages,
        "count": len(messages),
        "transcript": _transcript(token, messages),
    }


def _display_names(token: str, user_ids: list[str]) -> dict[str, str]:
    names: dict[str, str] = {}
    for user_id in user_ids[:_MAX_NAME_LOOKUPS]:
        try:
            user = slack.call_slack(token, "users.info", {"user": user_id}, read=True).get("user")
        except slack.SlackApiError:
            continue
        profile = (user or {}).get("profile") or {}
        name = profile.get("display_name") or profile.get("real_name") or (user or {}).get("name")
        if name:
            names[user_id] = str(name)
    return names


def _transcript(token: str, messages: list[dict]) -> str:
    """The messages oldest first, one per line, with people's names, for a model to read."""
    ordered = sorted(messages, key=lambda item: float(item.get("ts") or 0))
    user_ids = list(
        dict.fromkeys(
            str(m["user"])
            for m in ordered
            if str(m.get("user") or "")[:1] in "UW" and m.get("user")
        )
    )
    names = _display_names(token, user_ids)
    lines = []
    for item in ordered:
        when = datetime.fromtimestamp(float(item.get("ts") or 0), tz=timezone.utc)
        who = names.get(str(item.get("user")), str(item.get("user") or "bot"))
        text = _MENTION.sub(
            lambda m: "@" + names.get(m.group(1), m.group(1)), str(item.get("text") or "")
        )
        lines.append(f"[{when:%Y-%m-%d %H:%M}] {who}: {text}")
    return "\n".join(lines)


def _find_user(ctx: NodeExecutionContext, token: str) -> dict:
    user_id = slack.resolve_user_id(token, _required(ctx, "slackUser", "person"))
    user = slack.call_slack(token, "users.info", {"user": user_id}, read=True).get("user") or {}
    profile = user.get("profile") or {}
    return {
        "id": user.get("id", user_id),
        "name": user.get("name", ""),
        "realName": profile.get("real_name") or user.get("real_name", ""),
        "displayName": profile.get("display_name", ""),
        "email": profile.get("email", ""),
        "title": profile.get("title", ""),
        "timezone": user.get("tz", ""),
        "isBot": bool(user.get("is_bot")),
    }


def run_bot_operation(ctx: NodeExecutionContext, credential_id: str, config: dict) -> object:
    """Run the node's operation with the credential's bot token."""
    token = slack.bot_config(config).bot_token
    operation = str(ctx.node_data.get("slackOperation") or DEFAULT_OPERATION)
    if operation not in OPERATIONS:
        raise ValueError(f"Unknown Slack operation: {operation}")
    if operation in WAITING_OPERATIONS:
        return _waiting(ctx, token, credential_id, operation)

    if operation == "sendMessage":
        channel = slack.resolve_target(token, _required(ctx, "slackChannel", "channel"))
        return _post(
            token,
            channel,
            _required(ctx, "message", "message"),
            thread_ts=_text(ctx, "slackThreadTs").strip(),
        )
    if operation == "sendDirectMessage":
        user_id = slack.resolve_user_id(token, _required(ctx, "slackUser", "person"))
        channel = slack.open_direct_message(token, user_id)
        return {**_post(token, channel, _required(ctx, "message", "message")), "user": user_id}
    if operation == "replyInThread":
        channel = slack.resolve_target(token, _required(ctx, "slackChannel", "channel"))
        thread_ts = _required(ctx, "slackThreadTs", "thread timestamp")
        extra = {"reply_broadcast": True} if ctx.node_data.get("slackBroadcast") else {}
        return _post(
            token, channel, _required(ctx, "message", "message"), thread_ts=thread_ts, **extra
        )
    if operation == "postOutcome":
        channel = slack.resolve_target(token, _required(ctx, "slackChannel", "channel"))
        status = _text(ctx, "slackOutcomeStatus").strip() or "success"
        status = APPROVAL_OUTCOMES.get(status, status)
        title = _text(ctx, "slackOutcomeTitle")
        message = _text(ctx, "message")
        fallback = f"{title}\n{message}".strip() or "Outcome"
        posted = _post(
            token,
            channel,
            fallback,
            thread_ts=_text(ctx, "slackThreadTs").strip(),
            attachments=[slack.outcome_attachment(status, title, message)],
        )
        return {**posted, "status": status}
    if operation == "getMessages":
        return _get_messages(ctx, token)
    if operation == "findUser":
        return _find_user(ctx, token)

    channel = slack.resolve_target(token, _required(ctx, "slackChannel", "channel"))
    if operation == "updateMessage":
        message = _required(ctx, "message", "message")
        body = slack.call_slack(
            token,
            "chat.update",
            {
                "channel": channel,
                "ts": _required(ctx, "slackMessageTs", "message timestamp"),
                "text": message,
                "blocks": [slack.section(message)],
            },
        )
        return slack.message_output(body, message)
    if operation == "addReaction":
        ts = _required(ctx, "slackMessageTs", "message timestamp")
        emoji = _required(ctx, "slackEmoji", "emoji").strip(":")
        slack.call_slack(
            token, "reactions.add", {"channel": channel, "timestamp": ts, "name": emoji}
        )
        return {"channel": channel, "ts": ts, "emoji": emoji}
    ts = _required(ctx, "slackMessageTs", "message timestamp")
    slack.call_slack(token, "chat.delete", {"channel": channel, "ts": ts})
    return {"channel": channel, "ts": ts, "deleted": True}
