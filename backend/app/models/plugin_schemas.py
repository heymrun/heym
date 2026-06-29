"""Pydantic models for plugin manifests and the plugins API."""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

_PLUGIN_ID_RE = re.compile(r"^[a-z0-9-]+$")

PluginKind = Literal["action", "trigger"]
PluginFieldType = Literal["string", "number", "boolean", "select"]


class PluginFieldOption(BaseModel):
    label: str
    value: str


class PluginField(BaseModel):
    key: str
    label: str
    type: PluginFieldType = "string"
    required: bool = False
    secret: bool = False
    default: str | float | bool | None = None
    options: list[PluginFieldOption] = Field(default_factory=list)
    dynamic: bool = False
    expression: bool = False


class PluginManifest(BaseModel):
    id: str
    name: str
    version: str
    kind: PluginKind
    description: str = ""
    entry: str = "handler.py"
    dependencies: list[str] = Field(default_factory=list)
    fields: list[PluginField] = Field(default_factory=list)
    dsl_hint: str = Field(default="", alias="dslHint")
    doc_slug: str = Field(default="", alias="docSlug")

    model_config = {"populate_by_name": True}

    @field_validator("id")
    @classmethod
    def _validate_id(cls, v: str) -> str:
        if not _PLUGIN_ID_RE.match(v):
            raise ValueError("Plugin id must match ^[a-z0-9-]+$")
        return v

    @model_validator(mode="after")
    def _default_doc_slug(self) -> PluginManifest:
        if not self.doc_slug:
            self.doc_slug = self.id
        return self

    def resolved_doc_slug(self) -> str:
        return self.doc_slug or self.id


class PluginSummary(BaseModel):
    """Public listing shape returned by GET /api/plugins."""

    id: str
    name: str
    version: str
    kind: PluginKind
    description: str
    enabled: bool
    fields: list[PluginField]
    dsl_hint: str = ""
    doc_slug: str = ""
    has_icon: bool = False


class PluginDoc(BaseModel):
    id: str
    name: str
    doc_slug: str
    markdown: str
