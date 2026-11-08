"""Instance administration of user accounts."""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class AdminUserItem(BaseModel):
    id: uuid.UUID
    email: str
    name: str
    created_at: datetime
    last_login_at: datetime | None = None
    is_active: bool
    deactivated_at: datetime | None = None
    is_admin: bool
    sign_in_methods: list[Literal["password", "sso"]]
    mfa_enabled: bool


class AdminUserListResponse(BaseModel):
    items: list[AdminUserItem]
    total: int
    limit: int
    offset: int


class AdminUserActionResponse(BaseModel):
    user: AdminUserItem
    # Workflows whose automatic triggers this action paused or resumed.
    workflows_changed: int = 0
