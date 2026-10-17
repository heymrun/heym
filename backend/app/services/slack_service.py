"""Slack Web API calls made with a bot token, and the Block Kit messages Heym sends.

Interactive messages (approvals, buttons, forms) carry a per-pause key in every action
value. A click arrives at `/api/slack/interactions/{credential_id}`, signed with the
credential's signing secret, and the key finds the paused run it answers.
"""

from __future__ import annotations

import re
import secrets
from dataclasses import dataclass
from typing import Any

from app.services import ssrf_guard

SLACK_API_BASE = "https://slack.com/api"
ACTION_APPROVE = "heym_approve"
ACTION_CHANGES = "heym_changes"
ACTION_REJECT = "heym_reject"
ACTION_FORM_OPEN = "heym_form_open"
ACTION_CHOICE_PREFIX = "heym_choice:"
VIEW_CHANGES = "heym_changes"
VIEW_FORM = "heym_form"
FIELD_ACTION = "value"
FORM_FIELD_TYPES = ("text", "multiline", "number", "email", "date", "select")
MAX_BUTTONS = 5
MAX_FORM_FIELDS = 10
_SECTION_LIMIT = 3000
_PLAIN_LABEL_LIMIT = 75
_MODAL_TITLE_LIMIT = 24
_CHANNEL_PAGES = 10

_USER_ID = re.compile(r"^[UW][A-Z0-9]{6,}$")
_CHANNEL_ID = re.compile(r"^[CGD][A-Z0-9]{6,}$")
_USER_MENTION = re.compile(r"^<@([UW][A-Z0-9]+)(?:\|[^>]*)?>$")
_CHANNEL_MENTION = re.compile(r"^<#([CG][A-Z0-9]+)(?:\|[^>]*)?>$")
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_FIELD_NAME = re.compile(r"[^a-z0-9_]+")

OUTCOME_STYLES: dict[str, tuple[str, str]] = {
    "success": (":white_check_mark:", "#16a34a"),
    "failure": (":x:", "#dc2626"),
    "warning": (":warning:", "#d97706"),
    "info": (":information_source:", "#6d28d9"),
}


class SlackApiError(ValueError):
    """Slack refused a call or could not be reached."""


@dataclass(frozen=True)
class SlackBotConfig:
    """The decrypted configuration of a `slack_bot` credential."""

    bot_token: str
    signing_secret: str


def bot_config(config: dict) -> SlackBotConfig:
    """Read a `slack_bot` credential's config, failing when the token is missing."""
    token = str(config.get("bot_token") or "").strip()
    if not token:
        raise SlackApiError("Slack Bot credential requires bot_token")
    return SlackBotConfig(
        bot_token=token, signing_secret=str(config.get("signing_secret") or "").strip()
    )


def new_action_key() -> str:
    """A key that ties an interactive message to the run waiting on it."""
    return secrets.token_urlsafe(18)


def call_slack(token: str, method: str, payload: dict | None = None, *, read: bool = False) -> dict:
    """Call one Web API method. Read methods go as query parameters, writes as JSON."""
    client = ssrf_guard.get_guarded_http_client()
    url = f"{SLACK_API_BASE}/{method}"
    headers = {"Authorization": f"Bearer {token}"}
    try:
        if read:
            response = client.get(url, params=payload or {}, headers=headers)
        else:
            response = client.post(
                url,
                json=payload or {},
                headers={**headers, "Content-Type": "application/json; charset=utf-8"},
            )
    except Exception as exc:  # noqa: BLE001 - surfaced to the node as one message
        raise SlackApiError(f"Slack API unreachable ({method}): {exc}") from exc
    if response.status_code == 429:
        retry_after = response.headers.get("Retry-After", "a few")
        raise SlackApiError(f"Slack rate limit reached ({method}); retry after {retry_after}s")
    try:
        body = response.json()
    except ValueError as exc:
        raise SlackApiError(f"Slack API error ({method}): HTTP {response.status_code}") from exc
    if not isinstance(body, dict) or not body.get("ok"):
        error = body.get("error") if isinstance(body, dict) else None
        detail = str(error or f"HTTP {response.status_code}")
        needed = body.get("needed") if isinstance(body, dict) else None
        if needed:
            detail = f"{detail} (the app needs the {needed} scope)"
        raise SlackApiError(f"Slack API error ({method}): {detail}")
    return body


_CODE = re.compile(r"(```[\s\S]*?```|`[^`\n]+`)")
_HEADING = re.compile(r"(?m)^[ \t]{0,3}#{1,6}[ \t]+(.+?)[ \t]*#*[ \t]*$")
_RULE = re.compile(r"(?m)^[ \t]*([-*_])(?:[ \t]*\1){2,}[ \t]*$")
_BULLET = re.compile(r"(?m)^([ \t]*)[-*+][ \t]+")
_IMAGE = re.compile(r"!\[([^\]]*)\]\((\S+?)\)")
_LINK = re.compile(r"\[([^\]]+)\]\((\S+?)\)")
_BOLD_ITALIC = re.compile(r"\*\*\*(?=\S)(.+?)(?<=\S)\*\*\*")
_BOLD = re.compile(r"(\*\*|__)(?=\S)(.+?)(?<=\S)\1")
_STRIKE = re.compile(r"~~(?=\S)(.+?)(?<=\S)~~")


def _prose_to_mrkdwn(text: str) -> str:
    text = _HEADING.sub(lambda m: f"*{m.group(1).replace('*', '').strip()}*", text)
    text = _RULE.sub("", text)
    text = _BULLET.sub(lambda m: f"{m.group(1)}• ", text)
    text = _IMAGE.sub(lambda m: f"<{m.group(2)}|{m.group(1) or m.group(2)}>", text)
    text = _LINK.sub(lambda m: f"<{m.group(2)}|{m.group(1)}>", text)
    text = _BOLD_ITALIC.sub(r"*_\1_*", text)
    text = _BOLD.sub(r"*\2*", text)
    return _STRIKE.sub(r"~\1~", text)


def to_slack_mrkdwn(text: str) -> str:
    """Rewrite standard Markdown, as models write it, into Slack's mrkdwn.

    `**bold**` becomes `*bold*`, `[text](url)` becomes `<url|text>`, headings turn bold and
    list markers turn into bullets. Slack's own syntax and code spans are left as they are.
    """
    parts = _CODE.split(text or "")
    return "".join(
        part if index % 2 else _prose_to_mrkdwn(part) for index, part in enumerate(parts)
    )


def post_response_url(response_url: str, payload: dict) -> None:
    """Answer an interaction through its response URL (ephemeral notes, replacements)."""
    if not response_url.startswith("https://hooks.slack.com/"):
        return
    client = ssrf_guard.get_guarded_http_client()
    try:
        client.post(response_url, json=payload)
    except Exception:  # noqa: BLE001 - a note that fails to post changes nothing
        return


def resolve_user_id(token: str, value: str) -> str:
    """A Slack user id from an id, a mention or an email address."""
    text = value.strip()
    mention = _USER_MENTION.match(text)
    if mention:
        return mention.group(1)
    if _USER_ID.match(text):
        return text
    if _EMAIL.match(text):
        body = call_slack(token, "users.lookupByEmail", {"email": text}, read=True)
        user_id = str((body.get("user") or {}).get("id") or "")
        if user_id:
            return user_id
    raise SlackApiError(f"'{text}' is not a Slack user id (U…) or a member's email address")


def open_direct_message(token: str, user_id: str) -> str:
    """The id of the bot's direct message channel with one person."""
    body = call_slack(token, "conversations.open", {"users": user_id})
    channel_id = str((body.get("channel") or {}).get("id") or "")
    if not channel_id:
        raise SlackApiError("Slack did not open a direct message channel")
    return channel_id


def _channel_id_by_name(token: str, name: str) -> str | None:
    cursor = ""
    for _ in range(_CHANNEL_PAGES):
        params = {
            "types": "public_channel,private_channel",
            "exclude_archived": "true",
            "limit": "1000",
        }
        if cursor:
            params["cursor"] = cursor
        try:
            body = call_slack(token, "conversations.list", params, read=True)
        except SlackApiError:
            return None
        for channel in body.get("channels") or []:
            if isinstance(channel, dict) and channel.get("name") == name:
                return str(channel.get("id") or "") or None
        cursor = str((body.get("response_metadata") or {}).get("next_cursor") or "")
        if not cursor:
            return None
    return None


def resolve_target(token: str, value: str) -> str:
    """A conversation id for a channel (#name, id, link) or a person (id, mention, email)."""
    text = str(value or "").strip()
    if not text:
        raise SlackApiError("Slack node requires a channel or a person")
    channel_mention = _CHANNEL_MENTION.match(text)
    if channel_mention:
        return channel_mention.group(1)
    if _CHANNEL_ID.match(text):
        return text
    if _USER_MENTION.match(text) or _USER_ID.match(text) or _EMAIL.match(text):
        return open_direct_message(token, resolve_user_id(token, text))
    name = text.lstrip("#")
    # Without channels:read the name goes as it is; chat.postMessage accepts names too.
    return _channel_id_by_name(token, name) or name


def resolve_user_list(token: str, value: object) -> list[str]:
    """Slack user ids from a comma or newline separated list of ids, mentions or emails."""
    if isinstance(value, list):
        parts = [str(item) for item in value]
    else:
        parts = re.split(r"[,\n]", str(value or ""))
    return [resolve_user_id(token, part) for part in parts if part.strip()]


def _plain(text: str, limit: int = _PLAIN_LABEL_LIMIT) -> dict:
    return {"type": "plain_text", "text": (text or " ")[:limit], "emoji": True}


def section(text: str) -> dict:
    """A markdown section, cut to Slack's section limit."""
    return {"type": "section", "text": {"type": "mrkdwn", "text": (text or " ")[:_SECTION_LIMIT]}}


def context(text: str) -> dict:
    """A small grey line under a message."""
    return {"type": "context", "elements": [{"type": "mrkdwn", "text": text[:_SECTION_LIMIT]}]}


def approval_blocks(message: str, key: str) -> list[dict]:
    """The message with Approve, Request changes and Reject."""
    return [
        section(message),
        {
            "type": "actions",
            "block_id": "heym_approval",
            "elements": [
                {
                    "type": "button",
                    "action_id": ACTION_APPROVE,
                    "text": _plain("Approve"),
                    "style": "primary",
                    "value": key,
                },
                {
                    "type": "button",
                    "action_id": ACTION_CHANGES,
                    "text": _plain("Request changes"),
                    "value": key,
                },
                {
                    "type": "button",
                    "action_id": ACTION_REJECT,
                    "text": _plain("Reject"),
                    "style": "danger",
                    "value": key,
                },
            ],
        },
    ]


def normalize_buttons(raw: object) -> list[dict]:
    """Up to five buttons with a label, a value and an optional style."""
    buttons: list[dict] = []
    for item in raw if isinstance(raw, list) else []:
        if not isinstance(item, dict):
            continue
        label = str(item.get("label") or "").strip()
        if not label:
            continue
        style = str(item.get("style") or "").strip()
        buttons.append(
            {
                "label": label[:_PLAIN_LABEL_LIMIT],
                "value": str(item.get("value") or label).strip()[:200],
                "style": style if style in ("primary", "danger") else "",
            }
        )
    if not buttons:
        raise SlackApiError("Send message with buttons needs at least one button")
    return buttons[:MAX_BUTTONS]


def button_blocks(message: str, key: str, buttons: list[dict]) -> list[dict]:
    """The message with one button per choice."""
    elements = []
    for index, button in enumerate(buttons):
        element = {
            "type": "button",
            "action_id": f"{ACTION_CHOICE_PREFIX}{index}",
            "text": _plain(button["label"]),
            "value": key,
        }
        if button.get("style"):
            element["style"] = button["style"]
        elements.append(element)
    return [section(message), {"type": "actions", "block_id": "heym_choices", "elements": elements}]


def field_name(label: str, index: int) -> str:
    """A stable output key for a form field without an explicit name."""
    name = _FIELD_NAME.sub("_", label.strip().lower()).strip("_")
    return name or f"field_{index + 1}"


def normalize_form_fields(raw: object) -> list[dict]:
    """Up to ten fields with a unique name, a label, a type and their options."""
    fields: list[dict] = []
    seen: set[str] = set()
    for index, item in enumerate(raw if isinstance(raw, list) else []):
        if not isinstance(item, dict):
            continue
        label = str(item.get("label") or "").strip()
        if not label:
            continue
        name = str(item.get("name") or "").strip() or field_name(label, index)
        if name in seen:
            name = f"{name}_{index + 1}"
        seen.add(name)
        field_type = str(item.get("type") or "text")
        options = item.get("options")
        if isinstance(options, str):
            options = [part.strip() for part in options.split(",")]
        fields.append(
            {
                "name": name,
                "label": label[:2000],
                "type": field_type if field_type in FORM_FIELD_TYPES else "text",
                "required": bool(item.get("required", True)),
                "placeholder": str(item.get("placeholder") or "").strip(),
                "options": [str(option) for option in options or [] if str(option).strip()][:100],
            }
        )
    if not fields:
        raise SlackApiError("Send form needs at least one field")
    return fields[:MAX_FORM_FIELDS]


def form_blocks(message: str, key: str, open_label: str) -> list[dict]:
    """The message with the button that opens the form."""
    return [
        section(message),
        {
            "type": "actions",
            "block_id": "heym_form",
            "elements": [
                {
                    "type": "button",
                    "action_id": ACTION_FORM_OPEN,
                    "text": _plain(open_label or "Open form"),
                    "style": "primary",
                    "value": key,
                }
            ],
        },
    ]


def _field_element(field: dict) -> dict:
    field_type = field["type"]
    if field_type == "select" and field["options"]:
        element: dict[str, Any] = {
            "type": "static_select",
            "options": [
                {"text": _plain(option), "value": option[:150]} for option in field["options"]
            ],
        }
    elif field_type == "number":
        element = {"type": "number_input", "is_decimal_allowed": True}
    elif field_type == "email":
        element = {"type": "email_text_input"}
    elif field_type == "date":
        element = {"type": "datepicker"}
    else:
        element = {"type": "plain_text_input", "multiline": field_type == "multiline"}
    element["action_id"] = FIELD_ACTION
    if field["placeholder"] and field_type != "date":
        element["placeholder"] = _plain(field["placeholder"], 150)
    return element


def form_modal(key: str, title: str, fields: list[dict], submit_label: str) -> dict:
    """The modal a person fills in; its submission answers the paused run."""
    return {
        "type": "modal",
        "callback_id": VIEW_FORM,
        "private_metadata": key,
        "title": _plain(title or "Form", _MODAL_TITLE_LIMIT),
        "submit": _plain(submit_label or "Submit", _MODAL_TITLE_LIMIT),
        "close": _plain("Cancel", _MODAL_TITLE_LIMIT),
        "blocks": [
            {
                "type": "input",
                "block_id": field["name"],
                "label": _plain(field["label"], 2000),
                "optional": not field["required"],
                "element": _field_element(field),
            }
            for field in fields
        ],
    }


def changes_modal(key: str) -> dict:
    """The modal that asks what should change before approval."""
    return {
        "type": "modal",
        "callback_id": VIEW_CHANGES,
        "private_metadata": key,
        "title": _plain("Request changes", _MODAL_TITLE_LIMIT),
        "submit": _plain("Send", _MODAL_TITLE_LIMIT),
        "close": _plain("Cancel", _MODAL_TITLE_LIMIT),
        "blocks": [
            {
                "type": "input",
                "block_id": "comment",
                "label": _plain("What should change?"),
                "element": {
                    "type": "plain_text_input",
                    "multiline": True,
                    "action_id": FIELD_ACTION,
                },
            }
        ],
    }


def read_form_values(state: dict, fields: list[dict]) -> dict[str, Any]:
    """The submitted value of each field, by name, from a view's state."""
    values = state.get("values") if isinstance(state, dict) else None
    values = values if isinstance(values, dict) else {}
    result: dict[str, Any] = {}
    for field in fields:
        entry = (values.get(field["name"]) or {}).get(FIELD_ACTION) or {}
        if "selected_option" in entry:
            option = entry.get("selected_option") or {}
            result[field["name"]] = option.get("value")
        elif "selected_date" in entry:
            result[field["name"]] = entry.get("selected_date")
        else:
            result[field["name"]] = entry.get("value")
    return result


def outcome_attachment(status: str, title: str, message: str) -> dict:
    """A colored outcome card: what happened, and the details under it."""
    emoji, color = OUTCOME_STYLES.get(status, OUTCOME_STYLES["info"])
    heading = f"{emoji} *{title.strip()}*" if title.strip() else emoji
    text = f"{heading}\n{message}" if message.strip() else heading
    return {"color": color, "blocks": [section(text)]}


def answered_blocks(message: str, note: str) -> list[dict]:
    """The original message with its buttons replaced by who answered and how."""
    return [section(message), context(note)]


def message_output(body: dict, text: str) -> dict:
    """What a posting operation gives the next step: where the message is."""
    message = body.get("message") if isinstance(body.get("message"), dict) else {}
    ts = str(body.get("ts") or message.get("ts") or "")
    return {
        "channel": str(body.get("channel") or ""),
        "ts": ts,
        "threadTs": str(message.get("thread_ts") or ts),
        "text": text,
    }


_DECISION_APPROVAL = {"accept": "approved", "edit": "changes_requested", "refuse": "rejected"}


def resolved_slack_output(
    output: dict, *, decision: str | None, edited_text: str | None, refusal_reason: str | None
) -> dict:
    """A resumed Slack step's output: the answer, who gave it, and where, without internals."""
    internals = output.pop("_slack", None)
    if not isinstance(internals, dict):
        return output
    answer = internals.get("answer") if isinstance(internals.get("answer"), dict) else {}
    kind = internals.get("kind")
    output["answeredIn"] = "slack" if answer else "heym"
    output["answeredBy"] = answer.get("user")
    if kind == "approval":
        output["approval"] = answer.get("approval") or _DECISION_APPROVAL.get(
            decision or "", "approved"
        )
        output["comment"] = answer.get("comment") or edited_text or refusal_reason or ""
    elif kind == "buttons":
        output["choice"] = answer.get("choice")
    elif kind == "form":
        output["values"] = answer.get("values") or {}
    return output
