"""Outlook Calendar availability and Teams invitations node."""

from typing import Any

from fastapi import HTTPException

from app.db.models import CredentialType
from app.db.session import SessionLocal
from app.services.encryption import decrypt_config
from app.services.exchange_server.calendar import ExchangeCalendarService
from app.services.exchange_server.connection import is_ews
from app.services.node_execution.base import NodeExecutionContext
from app.services.outlook_calendar_service import LABEL, OutlookCalendarService

OPERATIONS = frozenset({"read", "create", "update", "delete"})


def _option(ctx: NodeExecutionContext, key: str, name: str, default: bool) -> bool:
    """A checkbox an Agent may also fill, so ``"true"``/``"false"`` strings are accepted."""
    raw = ctx.node_data.get(key)
    if raw is None or raw == "":
        return default
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, str) and raw.strip().lower() in {"true", "false"}:
        return raw.strip().lower() == "true"
    raise HTTPException(400, f"{LABEL}: {name} must be true or false")


def execute(ctx: NodeExecutionContext) -> object:
    """Resolve dynamic fields and dispatch using an accessible Outlook Calendar credential."""
    credential_id = ctx.node_data.get("credentialId")
    if not credential_id:
        raise HTTPException(400, f"{LABEL}: select a credential")
    operation = ctx.node_data.get("ocOperation") or "read"
    if operation not in OPERATIONS:
        raise HTTPException(400, f"{LABEL}: select a valid operation")

    def resolve(key: str, default: str = "") -> str:
        raw = ctx.node_data.get(key)
        # Empty templates resolve to the entire input in the shared executor.
        if raw is None or raw == "":
            return default
        return ctx.executor.evaluate_message_template(str(raw), ctx.inputs, ctx.node_id).strip()

    with SessionLocal() as db:
        credential = ctx.executor._get_accessible_credential(db, credential_id)
        if not credential or credential.type != CredentialType.outlook_calendar:
            raise HTTPException(400, f"{LABEL}: credential not found, inaccessible or wrong type")
        config = decrypt_config(credential.encrypted_config)
        service: OutlookCalendarService | ExchangeCalendarService = (
            ExchangeCalendarService(config)
            if is_ews(config)
            else OutlookCalendarService(str(credential_id), config, db)
        )
        time_zone = resolve("ocTimeZone", "UTC") or "UTC"
        calendar_id = resolve("ocCalendarId", "primary") or "primary"
        if operation == "read":
            return service.read_availability(
                calendar_id,
                resolve("ocStartDate"),
                resolve("ocEndDate"),
                time_zone,
                include_busy_details=_option(
                    ctx, "ocIncludeBusyDetails", "Include Busy Event Details", False
                ),
            )
        if operation == "delete":
            return service.delete_event(resolve("ocEventId"))
        raw_attendees: Any = ctx.node_data.get("ocAttendees", "")
        if isinstance(raw_attendees, list):
            attendees: str | list[Any] = [
                ctx.executor.evaluate_message_template(item, ctx.inputs, ctx.node_id)
                if isinstance(item, str) and "$" in item
                else item
                for item in raw_attendees
            ]
        else:
            attendees = resolve("ocAttendees")
        return service.save_event(
            operation,
            calendar_id,
            resolve("ocEventId"),
            title=resolve("ocTitle"),
            description=resolve("ocDescription"),
            start=resolve("ocStartTime"),
            end=resolve("ocEndTime"),
            time_zone=time_zone,
            attendees=attendees,
            location=resolve("ocLocation"),
            teams_meeting=_option(ctx, "ocTeamsMeeting", "Add Teams meeting", True),
        )
