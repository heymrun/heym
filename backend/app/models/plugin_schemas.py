"""Pydantic models for plugin manifests and the plugins API.

A plugin *package* (one zip / one installed entry) may expose multiple *nodes*,
each of which becomes a draggable node on the canvas. A node is either an
``action`` or a ``trigger`` and maps to a function in the package's handler
module.

Legacy single-node manifests (top-level ``kind`` + ``fields``) are still accepted
and synthesized into a single node.
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

_PLUGIN_ID_RE = re.compile(r"^[a-z0-9-]+$")
_NODE_KEY_RE = re.compile(r"^[A-Za-z0-9_-]+$")

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


class PluginNodeDef(BaseModel):
    """A single node exposed by a plugin package."""

    key: str
    name: str
    kind: PluginKind
    function: str = ""
    description: str = ""
    icon: str = ""
    fields: list[PluginField] = Field(default_factory=list)
    dsl_hint: str = Field(default="", alias="dslHint")
    doc_slug: str = Field(default="", alias="docSlug")

    model_config = {"populate_by_name": True}

    @field_validator("key")
    @classmethod
    def _validate_key(cls, v: str) -> str:
        if not _NODE_KEY_RE.match(v):
            raise ValueError("Node key must match ^[A-Za-z0-9_-]+$")
        return v

    @model_validator(mode="after")
    def _default_function(self) -> PluginNodeDef:
        if not self.function:
            self.function = "run" if self.kind == "action" else "trigger"
        return self


class PluginManifest(BaseModel):
    id: str
    name: str
    version: str
    description: str = ""
    entry: str = "handler.py"
    dependencies: list[str] = Field(default_factory=list)
    nodes: list[PluginNodeDef] = Field(default_factory=list)
    # Legacy single-node fields (optional; synthesized into `nodes`).
    kind: PluginKind | None = None
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
    def _synthesize_and_validate_nodes(self) -> PluginManifest:
        if not self.nodes:
            if self.kind is None:
                raise ValueError("Plugin manifest must define `nodes` or a top-level `kind`")
            self.nodes = [
                PluginNodeDef(
                    key=self.id,
                    name=self.name,
                    kind=self.kind,
                    fields=self.fields,
                    dsl_hint=self.dsl_hint,
                    doc_slug=self.doc_slug or self.id,
                )
            ]
        keys = [n.key for n in self.nodes]
        if len(keys) != len(set(keys)):
            raise ValueError("Plugin node keys must be unique within a package")
        for node in self.nodes:
            if not node.doc_slug:
                node.doc_slug = self.id
        return self

    def resolved_nodes(self) -> list[PluginNodeDef]:
        return self.nodes

    def get_node(self, key: str) -> PluginNodeDef | None:
        return next((n for n in self.nodes if n.key == key), None)

    def package_kind(self) -> str:
        kinds = {n.kind for n in self.nodes}
        if len(kinds) == 1:
            return next(iter(kinds))
        return "mixed"

    def resolved_doc_slug(self) -> str:
        return self.doc_slug or self.id


class PluginNodeSummary(BaseModel):
    key: str
    name: str
    kind: PluginKind
    description: str
    fields: list[PluginField]
    dsl_hint: str = ""
    doc_slug: str = ""
    has_icon: bool = False


class PluginSummary(BaseModel):
    """Public listing shape returned by GET /api/plugins (one per package)."""

    id: str
    name: str
    version: str
    kind: str
    description: str
    enabled: bool
    nodes: list[PluginNodeSummary]
    has_icon: bool = False


class PluginDoc(BaseModel):
    id: str
    name: str
    doc_slug: str
    markdown: str
