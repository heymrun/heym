"""Request and response models for the Heym Work integration."""

import re
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

_NONCE_PATTERN = r"^[A-Za-z0-9_-]{16,128}$"
_DETAIL_KEY = re.compile(r"[a-z_]{1,32}")
_RESERVED_DETAIL_KEYS = {
    "action",
    "outcome",
    "actor",
    "actor_id",
    "actor_email",
    "target_type",
    "target_id",
    "target_name",
    "source",
}


class WorkIntegrationConfigResponse(BaseModel):
    enabled: bool
    work_url: str
    key_set: bool
    key_rotated_at: datetime | None
    last_seen_at: datetime | None
    last_work_version: str
    last_license_status: str

    @classmethod
    def from_row(cls, row: Any) -> "WorkIntegrationConfigResponse":
        """Build the admin payload. The key is reported, never returned."""
        return cls(
            enabled=row.enabled,
            work_url=row.work_url,
            key_set=bool(row.key_hash),
            key_rotated_at=row.key_rotated_at,
            last_seen_at=row.last_seen_at,
            last_work_version=row.last_work_version,
            last_license_status=row.last_license_status,
        )


class WorkIntegrationConfigUpdate(BaseModel):
    enabled: bool | None = None
    work_url: str | None = Field(default=None, max_length=512)


class WorkKeyResponse(BaseModel):
    key: str
    config: WorkIntegrationConfigResponse


class WorkHandshakeRequest(BaseModel):
    nonce: str = Field(pattern=_NONCE_PATTERN)
    work_version: str = Field(default="", max_length=32)
    install_id: str = Field(default="", max_length=64)
    license_status: str = Field(default="", max_length=16)


class WorkHandshakeResponse(BaseModel):
    heym_version: str
    sso_enabled: bool
    sso_button_label: str
    password_login: Literal["allowed", "admins_only"]
    registration_allowed: bool
    work_url: str


class WorkUserSummary(BaseModel):
    id: str
    email: str
    name: str


class WorkTokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    user: WorkUserSummary
    # Shown once, after an enrolment that happened during this sign-in.
    recovery_codes: list[str] | None = None


class WorkSsoExchangeRequest(BaseModel):
    code: str = Field(min_length=16, max_length=128)


class WorkRefreshRequest(BaseModel):
    refresh_token: str = Field(min_length=16)


class WorkAuditRequest(BaseModel):
    action: str = Field(pattern=r"^work\.[a-z_]{2,48}$")
    outcome: Literal["success", "failure", "denied"] = "success"
    actor_id: str | None = Field(default=None, max_length=64)
    target_type: str | None = Field(default=None, max_length=64)
    target_id: str | None = Field(default=None, max_length=128)
    target_name: str | None = Field(default=None, max_length=256)
    detail: dict[str, str | int | bool] = Field(default_factory=dict)

    @field_validator("detail")
    @classmethod
    def _bounded_detail(cls, value: dict[str, str | int | bool]) -> dict[str, str | int | bool]:
        if len(value) > 10:
            raise ValueError("At most 10 detail fields.")
        for key in value:
            if not _DETAIL_KEY.fullmatch(key) or key in _RESERVED_DETAIL_KEYS:
                raise ValueError(f"Detail key not allowed: {key}")
        return value
