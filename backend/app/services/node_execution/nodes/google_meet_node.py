"""Google Meet invitations and Calendar availability node."""

from typing import Any

from fastapi import HTTPException

from app.db.models import CredentialType
from app.db.session import SessionLocal
from app.services.encryption import decrypt_config
from app.services.google_meet_service import GoogleMeetService
from app.services.node_execution.base import NodeExecutionContext


def execute(ctx: NodeExecutionContext) -> object:
    """Resolve dynamic fields and dispatch using an accessible Google Meet credential."""
    credential_id = ctx.node_data.get("credentialId")
    if not credential_id:
        raise HTTPException(400, "Google Meet: select a credential")
    operation = ctx.node_data.get("gmOperation", "read")
    if operation not in {"create", "read", "update", "delete"}:
        raise HTTPException(400, "Google Meet: select a valid operation")

    def resolve(key: str, default: str = "") -> str:
        raw = ctx.node_data.get(key)
        # Empty templates resolve to the entire input in the shared executor.
        if raw is None or raw == "":
            return default
        return ctx.executor.evaluate_message_template(str(raw), ctx.inputs, ctx.node_id).strip()

    with SessionLocal() as db:
        credential = ctx.executor._get_accessible_credential(db, credential_id)
        if not credential or credential.type != CredentialType.google_meet:
            raise HTTPException(
                400, "Google Meet: credential not found, inaccessible or wrong type"
            )
        service = GoogleMeetService(credential_id, decrypt_config(credential.encrypted_config), db)
        calendar_id = resolve("gmCalendarId", "primary") or "primary"
        if operation == "read":
            include_titles = ctx.node_data.get("gmIncludeBusyTitles", False)
            if isinstance(include_titles, str):
                value = include_titles.strip().lower()
                if value not in {"true", "false", ""}:
                    raise HTTPException(
                        400, "Google Meet: Include Busy Event Titles must be true or false"
                    )
                include_titles = value == "true"
            if include_titles is None:
                include_titles = False
            if not isinstance(include_titles, bool):
                raise HTTPException(
                    400, "Google Meet: Include Busy Event Titles must be true or false"
                )
            return service.read_availability(
                calendar_id,
                resolve("gmStartDate"),
                resolve("gmEndDate"),
                (resolve("gmTimeZone", "UTC") or "UTC"),
                include_busy_titles=include_titles,
            )
        if operation == "delete":
            return service.delete_event(calendar_id, resolve("gmEventId"))
        raw_attendees: Any = ctx.node_data.get("gmAttendees", "")
        if isinstance(raw_attendees, list):
            attendees = [
                ctx.executor.evaluate_message_template(item, ctx.inputs, ctx.node_id)
                if isinstance(item, str) and "$" in item
                else item
                for item in raw_attendees
            ]
        else:
            attendees = resolve("gmAttendees")
        return service.save_event(
            operation,
            calendar_id,
            resolve("gmEventId"),
            title=resolve("gmTitle"),
            description=resolve("gmDescription"),
            start=resolve("gmStartTime"),
            end=resolve("gmEndTime"),
            time_zone=(resolve("gmTimeZone", "UTC") or "UTC"),
            attendees=attendees,
            location=resolve("gmLocation"),
        )
