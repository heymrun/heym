"""Natural language -> AlertDraft.

Structured JSON rather than tool calling: there is exactly one output shape and
no multi-turn negotiation, so tool calling would add a round trip for nothing.

Parsing is deliberately salvaging rather than all-or-nothing. A vague request
produces a partial draft plus a note about what is still undecided, and the
wizard opens on the first step that needs input. Only an answer with nothing
usable in it leaves the wizard on step one. Whatever the model produces still
has to survive ``AlertCreate`` on save, so a partial draft cannot create an
alert the API would reject.
"""

from __future__ import annotations

import json
import re
import uuid
from typing import Any

from pydantic import ValidationError

from app.models.alert_schemas import DEFAULT_CONFIG_BY_TYPE, AlertDraft, parse_alert_config

_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)


def build_draft_system_prompt(workflows: list[tuple[uuid.UUID, str]]) -> str:
    listing = "\n".join(f"- {name} (id: {wf_id})" for wf_id, name in workflows) or "- (none)"
    return f"""You turn a plain-English monitoring request into a Heym alert definition.

Reply with ONE JSON object and nothing else. No prose, no code fence, no explanation.

Alert types, and the config each one requires:

1. error_threshold - fires when failed runs in a window reach a count.
   config: {{"window_minutes": int, "threshold_count": int}}
2. workflow_duration - fires when run duration in a window reaches a ceiling.
   config: {{"window_minutes": int, "threshold_ms": number,
             "aggregation": "max"|"avg"|"p95", "min_samples": int}}
3. token_cost - fires when LLM spend in a window reaches a ceiling.
   config: {{"window_minutes": int, "metric": "total_tokens"|"usd", "threshold": number}}
4. execution_count - fires when run count in a window reaches a ceiling.
   config: {{"window_minutes": int, "threshold_count": int}}

Top-level fields:
  name          short, specific, human readable
  description   optional one line
  alert_type    one of the four above
  scope         "workflow" for one workflow, "system" for all of the user's workflows
  workflow_id   REQUIRED when scope is "workflow", omitted when scope is "system"
  config        matching the type above
  renotify_mode "on_recovery" (notify once until it recovers) or "cooldown"
  cooldown_minutes  REQUIRED when renotify_mode is "cooldown"
  notify_workflow_id  an EXISTING workflow to run when the alert fires, from the list below
  create_notify_workflow  true to create a new workflow to run on fire, false for none
  filled_fields list of the field names you inferred rather than were told

What should happen when the alert fires, in order of preference:
  - The request names an existing workflow to run -> set notify_workflow_id, omit
    create_notify_workflow.
  - The request wants to be notified somehow (Slack, email, a message, "tell me",
    "let me know") but names no existing workflow -> set create_notify_workflow: true.
  - The request explicitly wants nothing to run, or only wants the firing recorded
    -> set create_notify_workflow: false.
  - The request says nothing about it -> omit both and let the wizard decide.

Workflows this user can pick from:
{listing}

Fill in everything the request supports and OMIT what it does not. A partial answer
is wanted: the user completes the rest in the wizard. Never invent a workflow_id.
If the request names no workflow, or names one you cannot match to exactly one entry
above, leave workflow_id out and keep the fields you are sure about.

Reply in plain prose only when the request says nothing you can act on at all.
"""


_ALERT_TYPES = frozenset(DEFAULT_CONFIG_BY_TYPE)
_SCOPES = frozenset({"workflow", "system"})
_RENOTIFY_MODES = frozenset({"on_recovery", "cooldown"})


def _as_uuid(value: Any) -> uuid.UUID | None:
    if isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(str(value))
    except (ValueError, AttributeError, TypeError):
        return None


def _salvage_config(alert_type: str, raw: Any) -> dict[str, Any]:
    """Complete a partial config with the type's defaults.

    A model that answers only "in 10 minutes" still produces a usable condition:
    its keys win over the defaults, and anything that fails validation falls back
    to the defaults rather than discarding the whole draft.
    """
    defaults = DEFAULT_CONFIG_BY_TYPE[alert_type]
    if not isinstance(raw, dict):
        return dict(defaults)

    merged = {**defaults, **{k: v for k, v in raw.items() if k != "alert_type"}}
    try:
        parse_alert_config(alert_type, merged)
    except (ValidationError, ValueError):
        return dict(defaults)
    return merged


def parse_draft_response(raw: str) -> tuple[AlertDraft | None, str | None]:
    """Return (draft, clarification).

    Both may be set at once. A partial answer still becomes a draft so the wizard
    can move forward with what the model worked out, while the clarification says
    what is left to decide. Only an answer with nothing usable in it returns
    ``draft=None``, which keeps the wizard on step one showing the question.
    """
    text = (raw or "").strip()
    if not text:
        return None, "The model returned an empty response."

    fenced = _FENCE_RE.search(text)
    if fenced:
        text = fenced.group(1).strip()

    if not text.startswith("{"):
        return None, raw.strip()

    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return None, raw.strip()

    if not isinstance(payload, dict):
        return None, raw.strip()

    fields: dict[str, Any] = {}
    missing: list[str] = []

    alert_type = payload.get("alert_type")
    if alert_type in _ALERT_TYPES:
        fields["alert_type"] = alert_type
        fields["config"] = _salvage_config(alert_type, payload.get("config"))
    else:
        missing.append("which kind of threshold to watch")

    scope = payload.get("scope")
    if scope in _SCOPES:
        fields["scope"] = scope

    workflow_id = _as_uuid(payload.get("workflow_id"))
    if workflow_id is not None and scope != "system":
        fields["workflow_id"] = workflow_id
    elif fields.get("scope") == "workflow":
        missing.append("which workflow to watch")

    notify_workflow_id = _as_uuid(payload.get("notify_workflow_id"))
    if notify_workflow_id is not None:
        fields["notify_workflow_id"] = notify_workflow_id

    create_notify = payload.get("create_notify_workflow")
    if isinstance(create_notify, bool):
        # An existing workflow wins: creating a second one would leave an empty
        # workflow nobody asked for.
        fields["create_notify_workflow"] = create_notify and notify_workflow_id is None

    renotify_mode = payload.get("renotify_mode")
    if renotify_mode in _RENOTIFY_MODES:
        fields["renotify_mode"] = renotify_mode
    cooldown = payload.get("cooldown_minutes")
    if isinstance(cooldown, int) and not isinstance(cooldown, bool) and cooldown > 0:
        fields["cooldown_minutes"] = cooldown
    elif renotify_mode == "cooldown":
        missing.append("how often to keep notifying")

    name = payload.get("name")
    if isinstance(name, str) and name.strip():
        fields["name"] = name.strip()
    else:
        missing.append("a name")

    description = payload.get("description")
    if isinstance(description, str) and description.strip():
        fields["description"] = description.strip()

    filled = payload.get("filled_fields")
    if isinstance(filled, list):
        fields["filled_fields"] = [str(item) for item in filled if isinstance(item, str)]

    if not fields:
        return None, raw.strip()

    try:
        draft = AlertDraft(**fields)
    except ValidationError as exc:
        return None, f"Could not build an alert from that request: {exc.errors()[0]['msg']}"

    clarification = f"Still needed: {', '.join(missing)}." if missing else None
    return draft, clarification
