"""A2A 1.0 wire types the Heym Agent serves, as Pydantic models.

Field names are the ProtoJSON (camelCase) names of the A2A 1.0 specification, enums
serialize as their SCREAMING_SNAKE_CASE names, and `wire()` drops unset fields as
ProtoJSON does.
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

A2A_PROTOCOL_VERSION = "1.0"


class A2AModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="ignore")

    def wire(self) -> dict[str, Any]:
        """The JSON object as it travels."""
        return self.model_dump(by_alias=True, exclude_none=True, mode="json")


class Role(str, Enum):
    UNSPECIFIED = "ROLE_UNSPECIFIED"
    USER = "ROLE_USER"
    AGENT = "ROLE_AGENT"


class TaskState(str, Enum):
    UNSPECIFIED = "TASK_STATE_UNSPECIFIED"
    SUBMITTED = "TASK_STATE_SUBMITTED"
    WORKING = "TASK_STATE_WORKING"
    COMPLETED = "TASK_STATE_COMPLETED"
    FAILED = "TASK_STATE_FAILED"
    CANCELED = "TASK_STATE_CANCELED"
    INPUT_REQUIRED = "TASK_STATE_INPUT_REQUIRED"
    REJECTED = "TASK_STATE_REJECTED"
    AUTH_REQUIRED = "TASK_STATE_AUTH_REQUIRED"


TERMINAL_STATES = frozenset(
    {TaskState.COMPLETED, TaskState.FAILED, TaskState.CANCELED, TaskState.REJECTED}
)
INTERRUPTED_STATES = frozenset({TaskState.INPUT_REQUIRED, TaskState.AUTH_REQUIRED})
ACTIVE_STATES = frozenset({TaskState.SUBMITTED, TaskState.WORKING})


class Part(A2AModel):
    text: str | None = None
    data: Any = None
    raw: str | None = None
    url: str | None = None
    filename: str | None = None
    media_type: str | None = None
    metadata: dict[str, Any] | None = None


class Message(A2AModel):
    message_id: str
    context_id: str | None = None
    task_id: str | None = None
    role: Role = Role.UNSPECIFIED
    parts: list[Part] = Field(default_factory=list)
    metadata: dict[str, Any] | None = None
    extensions: list[str] | None = None
    reference_task_ids: list[str] | None = None


class TaskStatus(A2AModel):
    state: TaskState
    message: Message | None = None
    timestamp: str | None = None


class Artifact(A2AModel):
    artifact_id: str
    name: str | None = None
    description: str | None = None
    parts: list[Part]
    metadata: dict[str, Any] | None = None


class Task(A2AModel):
    id: str
    context_id: str
    status: TaskStatus
    artifacts: list[Artifact] | None = None
    history: list[Message] | None = None
    metadata: dict[str, Any] | None = None


class TaskStatusUpdateEvent(A2AModel):
    task_id: str
    context_id: str
    status: TaskStatus
    metadata: dict[str, Any] | None = None


class TaskArtifactUpdateEvent(A2AModel):
    task_id: str
    context_id: str
    artifact: Artifact
    append: bool | None = None
    last_chunk: bool | None = None
    metadata: dict[str, Any] | None = None


class StreamResponse(A2AModel):
    """Exactly one member is set."""

    task: Task | None = None
    message: Message | None = None
    status_update: TaskStatusUpdateEvent | None = None
    artifact_update: TaskArtifactUpdateEvent | None = None


class SendMessageConfiguration(A2AModel):
    accepted_output_modes: list[str] | None = None
    history_length: int | None = None
    return_immediately: bool | None = None
    task_push_notification_config: dict[str, Any] | None = None


class SendMessageRequest(A2AModel):
    tenant: str | None = None
    message: Message
    configuration: SendMessageConfiguration | None = None
    metadata: dict[str, Any] | None = None


class GetTaskRequest(A2AModel):
    tenant: str | None = None
    id: str
    history_length: int | None = None


class ListTasksRequest(A2AModel):
    tenant: str | None = None
    context_id: str | None = None
    status: TaskState | None = None
    page_size: int | None = None
    page_token: str | None = None
    history_length: int | None = None
    status_timestamp_after: str | None = None
    include_artifacts: bool | None = None


class ListTasksResponse(A2AModel):
    tasks: list[Task]
    next_page_token: str | None = None
    page_size: int
    total_size: int


class CancelTaskRequest(A2AModel):
    tenant: str | None = None
    id: str
    metadata: dict[str, Any] | None = None


class SubscribeToTaskRequest(A2AModel):
    tenant: str | None = None
    id: str


class AgentInterface(A2AModel):
    url: str
    protocol_binding: str
    protocol_version: str
    tenant: str | None = None


class AgentProvider(A2AModel):
    organization: str
    url: str


class AgentCapabilities(A2AModel):
    streaming: bool
    push_notifications: bool
    extended_agent_card: bool


class AgentSkill(A2AModel):
    id: str
    name: str
    description: str
    tags: list[str]
    examples: list[str] | None = None
    input_modes: list[str] | None = None
    output_modes: list[str] | None = None


class APIKeySecurityScheme(A2AModel):
    description: str | None = None
    location: str
    name: str


class AuthorizationCodeOAuthFlow(A2AModel):
    authorization_url: str
    token_url: str
    refresh_url: str | None = None
    scopes: dict[str, str] = Field(default_factory=dict)
    pkce_required: bool | None = None


class OAuthFlows(A2AModel):
    authorization_code: AuthorizationCodeOAuthFlow


class OAuth2SecurityScheme(A2AModel):
    description: str | None = None
    flows: OAuthFlows
    oauth2_metadata_url: str | None = None


class SecurityScheme(A2AModel):
    """Exactly one member is set."""

    api_key_security_scheme: APIKeySecurityScheme | None = None
    oauth2_security_scheme: OAuth2SecurityScheme | None = None


class StringList(A2AModel):
    values: list[str] = Field(default_factory=list, alias="list")


class SecurityRequirement(A2AModel):
    schemes: dict[str, StringList]


class AgentCard(A2AModel):
    name: str
    description: str
    supported_interfaces: list[AgentInterface]
    provider: AgentProvider | None = None
    version: str
    documentation_url: str | None = None
    capabilities: AgentCapabilities
    security_schemes: dict[str, SecurityScheme] | None = None
    security_requirements: list[SecurityRequirement] | None = None
    default_input_modes: list[str]
    default_output_modes: list[str]
    skills: list[AgentSkill]
    icon_url: str | None = None
