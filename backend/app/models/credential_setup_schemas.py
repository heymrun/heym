"""Schemas for the credential form page an MCP chat turn opens."""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class CredentialSetupResponse(BaseModel):
    """One credential form request, as its page shows it. Never a credential value."""

    id: uuid.UUID
    action: Literal["create", "update"]
    credential_type: str
    suggested_name: str | None = None
    credential_id: uuid.UUID | None = None
    reason: str | None = None
    status: Literal["pending", "completed", "declined", "expired"]
    expires_at: datetime
    completed_at: datetime | None = None


class CredentialSetupComplete(BaseModel):
    """The credential the user saved on the form."""

    credential_id: uuid.UUID
