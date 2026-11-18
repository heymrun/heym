import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class MemoryNodeResponse(BaseModel):
    id: uuid.UUID
    entity_name: str
    entity_type: str
    properties: dict = Field(default_factory=dict)
    confidence: float
    created_at: datetime
    updated_at: datetime


class MemoryEdgeResponse(BaseModel):
    id: uuid.UUID
    source_node_id: uuid.UUID
    target_node_id: uuid.UUID
    relationship_type: str
    properties: dict = Field(default_factory=dict)
    confidence: float
    created_at: datetime
    updated_at: datetime


class MemoryGraphResponse(BaseModel):
    nodes: list[MemoryNodeResponse]
    edges: list[MemoryEdgeResponse]


class NodeCreateRequest(BaseModel):
    entity_name: str = Field(min_length=1, max_length=255)
    entity_type: str = Field(min_length=1, max_length=50)
    properties: dict = Field(default_factory=dict)
    confidence: float = 1.0


class NodeUpdateRequest(BaseModel):
    entity_name: str | None = Field(default=None, max_length=255)
    entity_type: str | None = Field(default=None, max_length=50)
    properties: dict | None = None
    confidence: float | None = None


class EdgeCreateRequest(BaseModel):
    source_entity_name: str = Field(min_length=1)
    target_entity_name: str = Field(min_length=1)
    relationship_type: str = Field(min_length=1, max_length=100)
    properties: dict = Field(default_factory=dict)
    confidence: float = 1.0


class EdgeUpdateRequest(BaseModel):
    relationship_type: str | None = Field(default=None, max_length=100)
    properties: dict | None = None
    confidence: float | None = None


class MemoryAiInsertRequest(BaseModel):
    """Text to extract entities and relationships from, with the agent's own model."""

    text: str = Field(min_length=1, max_length=24000)
    credential_id: uuid.UUID
    model: str = Field(min_length=1, max_length=200)


class MemoryAiInsertResponse(BaseModel):
    """The graph after the insert, read in the same transaction that wrote it."""

    graph: MemoryGraphResponse
    entities_applied: int
    relationships_applied: int


class MemoryClearResponse(BaseModel):
    deleted_nodes: int
    deleted_edges: int
