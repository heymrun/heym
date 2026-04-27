import uuid
from datetime import datetime
from enum import Enum

from pydantic import BaseModel, EmailStr, Field, field_validator


def _validate_password_strength(value: str) -> str:
    """Enforce minimum password complexity."""
    if len(value) < 8:
        raise ValueError("Password must be at least 8 characters long")
    if not any(c.isupper() for c in value):
        raise ValueError("Password must contain at least one uppercase letter")
    if not any(c.islower() for c in value):
        raise ValueError("Password must contain at least one lowercase letter")
    if not any(c.isdigit() for c in value):
        raise ValueError("Password must contain at least one digit")
    return value


class UserCreate(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8)
    name: str = Field(min_length=1, max_length=100)

    @field_validator("password")
    @classmethod
    def password_strength(cls, v: str) -> str:
        return _validate_password_strength(v)


class UserLogin(BaseModel):
    email: EmailStr
    password: str


class PasswordChangeRequest(BaseModel):
    current_password: str
    new_password: str = Field(min_length=8)

    @field_validator("new_password")
    @classmethod
    def new_password_strength(cls, v: str) -> str:
        return _validate_password_strength(v)


class UserUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=100)
    user_rules: str | None = Field(None, max_length=4000)


class UserResponse(BaseModel):
    id: uuid.UUID
    email: str
    name: str
    user_rules: str | None = None
    created_at: datetime

    class Config:
        from_attributes = True


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class TokenRefresh(BaseModel):
    refresh_token: str = ""


# Team schemas
class TeamCreate(BaseModel):
    name: str
    description: str | None = None


class TeamUpdate(BaseModel):
    name: str | None = None
    description: str | None = None


class TeamMemberResponse(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    email: str
    name: str
    added_by: str | None = None
    joined_at: datetime


class TeamResponse(BaseModel):
    id: uuid.UUID
    name: str
    description: str | None
    creator_id: uuid.UUID
    creator_email: str
    creator_name: str
    member_count: int
    created_at: datetime


class TeamDetailResponse(TeamResponse):
    members: list[TeamMemberResponse]


class TeamMemberAddRequest(BaseModel):
    email: EmailStr


class TeamShareRequest(BaseModel):
    team_id: uuid.UUID


class TeamShareResponse(BaseModel):
    id: uuid.UUID
    team_id: uuid.UUID
    team_name: str
    shared_at: datetime


class TeamSharedEntityItem(BaseModel):
    id: uuid.UUID
    name: str


class TeamSharedEntitiesResponse(BaseModel):
    workflows: list[TeamSharedEntityItem]
    credentials: list[TeamSharedEntityItem]
    global_variables: list[TeamSharedEntityItem]
    vector_stores: list[TeamSharedEntityItem]
    data_tables: list[TeamSharedEntityItem] = Field(default_factory=list)
    workflow_templates: list[TeamSharedEntityItem]
    node_templates: list[TeamSharedEntityItem]


class WorkflowAuthType(str, Enum):
    anonymous = "anonymous"
    jwt = "jwt"
    header_auth = "header_auth"


class WebhookBodyMode(str, Enum):
    legacy = "legacy"
    generic = "generic"


class WorkflowCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str | None = None


class WorkflowUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=255)
    description: str | None = None
    nodes: list[dict] | None = None
    edges: list[dict] | None = None
    auth_type: WorkflowAuthType | None = None
    auth_header_key: str | None = Field(None, max_length=255)
    auth_header_value: str | None = Field(None, max_length=1024)
    webhook_body_mode: WebhookBodyMode | None = None
    folder_id: uuid.UUID | None = None
    cache_ttl_seconds: int | None = None
    rate_limit_requests: int | None = None
    rate_limit_window_seconds: int | None = None
    sse_enabled: bool | None = None
    sse_node_config: dict | None = None


class WorkflowShareRequest(BaseModel):
    email: EmailStr


class WorkflowShareResponse(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    email: EmailStr
    name: str
    mcp_enabled: bool = False
    folder_id: uuid.UUID | None = None
    shared_at: datetime


class WorkflowResponse(BaseModel):
    id: uuid.UUID
    name: str
    description: str | None
    nodes: list[dict]
    edges: list[dict]
    auth_type: WorkflowAuthType
    auth_header_key: str | None
    auth_header_value: str | None
    webhook_body_mode: WebhookBodyMode
    allow_anonymous: bool
    owner_id: uuid.UUID
    folder_id: uuid.UUID | None = None
    cache_ttl_seconds: int | None = None
    rate_limit_requests: int | None = None
    rate_limit_window_seconds: int | None = None
    sse_enabled: bool = False
    sse_node_config: dict | None = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class WorkflowVersionResponse(BaseModel):
    id: uuid.UUID
    workflow_id: uuid.UUID
    version_number: int
    name: str
    description: str | None
    nodes: list[dict]
    edges: list[dict]
    auth_type: WorkflowAuthType
    auth_header_key: str | None
    auth_header_value: str | None
    webhook_body_mode: WebhookBodyMode
    cache_ttl_seconds: int | None = None
    rate_limit_requests: int | None = None
    rate_limit_window_seconds: int | None = None
    created_by_id: uuid.UUID
    created_at: datetime

    class Config:
        from_attributes = True


class VersionChange(BaseModel):
    type: str
    field: str
    old_value: dict | list | str | int | None
    new_value: dict | list | str | int | None


class NodeChange(BaseModel):
    node_id: str
    change_type: str
    old_node: dict | None = None
    new_node: dict | None = None
    changes: list[VersionChange] = []


class EdgeChange(BaseModel):
    edge_id: str | None
    change_type: str
    old_edge: dict | None = None
    new_edge: dict | None = None


class WorkflowVersionDiffResponse(BaseModel):
    version_id: uuid.UUID
    version_number: int
    compared_to_version_id: uuid.UUID | None = None
    compared_to_version_number: int | None = None
    node_changes: list[NodeChange] = []
    edge_changes: list[EdgeChange] = []
    config_changes: list[VersionChange] = []


class RevertVersionRequest(BaseModel):
    confirm: bool = True


class InputFieldSchema(BaseModel):
    key: str
    default_value: str | None = Field(None, serialization_alias="defaultValue")


class OutputNodeSchema(BaseModel):
    label: str
    node_type: str
    output_expression: str | None = None


class WorkflowListResponse(BaseModel):
    id: uuid.UUID
    name: str
    description: str | None
    folder_id: uuid.UUID | None = None
    first_node_type: str | None = None
    scheduled_for_deletion: datetime | None = None
    shared_by_team: str | None = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class WorkflowListWithInputsResponse(BaseModel):
    id: uuid.UUID
    name: str
    description: str | None
    input_fields: list[InputFieldSchema] = []
    output_node: OutputNodeSchema | None = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class WorkflowExecuteRequest(BaseModel):
    inputs: dict = Field(default_factory=dict)
    test_run: bool = False


class NodeResultSchema(BaseModel):
    node_id: str
    node_label: str
    node_type: str
    status: str
    output: dict
    execution_time_ms: float
    error: str | None = None
    metadata: dict = Field(default_factory=dict)


class WorkflowExecuteResponse(BaseModel):
    workflow_id: uuid.UUID
    status: str
    outputs: dict
    node_results: list[NodeResultSchema] = []
    execution_time_ms: float
    execution_history_id: uuid.UUID | None = None


class ExecutionHistoryResponse(BaseModel):
    id: uuid.UUID
    workflow_id: uuid.UUID
    inputs: dict
    outputs: dict
    node_results: list[NodeResultSchema] = []
    status: str
    execution_time_ms: float
    started_at: datetime
    trigger_source: str | None = None

    class Config:
        from_attributes = True


class ExecutionHistoryWithWorkflowResponse(BaseModel):
    id: uuid.UUID
    workflow_id: uuid.UUID | None
    workflow_name: str
    run_type: str = "workflow"  # workflow | dashboard_chat | workflow_assistant
    inputs: dict
    outputs: dict
    node_results: list[NodeResultSchema] = []
    status: str
    execution_time_ms: float
    started_at: datetime
    trigger_source: str | None = None


class ExecutionHistoryListResponse(BaseModel):
    """Lightweight list item without inputs/outputs/node_results."""

    id: uuid.UUID
    workflow_id: uuid.UUID | None
    workflow_name: str
    run_type: str = "workflow"
    started_at: datetime
    status: str
    execution_time_ms: float
    trigger_source: str | None = None


class HistoryListResponse(BaseModel):
    total: int
    items: list[ExecutionHistoryListResponse]


class ActiveExecutionItem(BaseModel):
    """Single currently-running execution visible to the requesting user."""

    execution_id: str
    workflow_id: str
    workflow_name: str
    started_at: datetime


class LLMTraceListItem(BaseModel):
    id: uuid.UUID
    created_at: datetime
    source: str
    request_type: str
    provider: str | None = None
    model: str | None = None
    credential_id: uuid.UUID | None = None
    credential_name: str | None = None
    workflow_id: uuid.UUID | None = None
    workflow_name: str | None = None
    node_id: str | None = None
    node_label: str | None = None
    status: str
    elapsed_ms: float | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None


class LLMTraceDetailResponse(LLMTraceListItem):
    request: dict
    response: dict
    error: str | None = None


class LLMTraceListResponse(BaseModel):
    items: list[LLMTraceListItem]
    total: int
    limit: int
    offset: int


class CredentialType(str, Enum):
    openai = "openai"
    google = "google"
    custom = "custom"
    bearer = "bearer"
    header = "header"
    telegram = "telegram"
    slack = "slack"
    slack_trigger = "slack_trigger"
    imap = "imap"
    smtp = "smtp"
    redis = "redis"
    qdrant = "qdrant"
    grist = "grist"
    rabbitmq = "rabbitmq"
    cohere = "cohere"
    flaresolverr = "flaresolverr"
    google_sheets = "google_sheets"
    bigquery = "bigquery"


class CredentialConfigOpenAI(BaseModel):
    api_key: str


class CredentialConfigGoogle(BaseModel):
    api_key: str


class CredentialConfigCustom(BaseModel):
    base_url: str
    api_key: str


class CredentialConfigBearer(BaseModel):
    bearer_token: str


class CredentialConfigHeader(BaseModel):
    header_key: str
    header_value: str


class CredentialConfigSlack(BaseModel):
    webhook_url: str


class CredentialConfigTelegram(BaseModel):
    bot_token: str
    secret_token: str | None = None


class CredentialCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    type: CredentialType
    config: dict


class CredentialUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=100)
    config: dict | None = None


class CredentialResponse(BaseModel):
    id: uuid.UUID
    name: str
    type: CredentialType
    masked_value: str | None = None
    header_key: str | None = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class CredentialListResponse(BaseModel):
    id: uuid.UUID
    name: str
    type: CredentialType
    masked_value: str | None = None
    header_key: str | None = None
    created_at: datetime
    is_shared: bool = False
    shared_by: str | None = None
    shared_by_team: str | None = None

    class Config:
        from_attributes = True


class CredentialForIntellisense(BaseModel):
    name: str
    type: CredentialType


class CredentialShareRequest(BaseModel):
    email: EmailStr


class CredentialShareResponse(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    email: str
    name: str
    shared_at: datetime


class GlobalVariableCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    value: str | int | float | bool | list | dict = Field(default="")
    value_type: str = Field(default="auto", max_length=20)


class GlobalVariableUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=255)
    value: str | int | float | bool | list | dict | None = None
    value_type: str | None = Field(None, max_length=20)


class GlobalVariableResponse(BaseModel):
    id: uuid.UUID
    name: str
    value: str | int | float | bool | list | dict
    value_type: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class GlobalVariableListResponse(BaseModel):
    id: uuid.UUID
    name: str
    value: str | int | float | bool | list | dict
    value_type: str
    created_at: datetime
    updated_at: datetime
    is_shared: bool = False
    shared_by: str | None = None
    shared_by_team: str | None = None

    class Config:
        from_attributes = True


class GlobalVariableShareRequest(BaseModel):
    email: EmailStr


class GlobalVariableShareResponse(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    email: str
    name: str
    shared_at: datetime


class GlobalVariableBulkDeleteRequest(BaseModel):
    ids: list[uuid.UUID] = Field(min_length=1)


class LLMModel(BaseModel):
    id: str
    name: str
    is_reasoning: bool = False
    supports_batch: bool = False
    batch_support_reason: str | None = None


class FolderCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    parent_id: uuid.UUID | None = None


class FolderUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=255)
    parent_id: uuid.UUID | None = None


class FolderResponse(BaseModel):
    id: uuid.UUID
    name: str
    parent_id: uuid.UUID | None = None
    owner_id: uuid.UUID
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class FolderWithContentsResponse(BaseModel):
    id: uuid.UUID
    name: str
    parent_id: uuid.UUID | None = None
    owner_id: uuid.UUID
    created_at: datetime
    updated_at: datetime
    children: list["FolderResponse"] = []
    workflows: list[WorkflowListResponse] = []

    class Config:
        from_attributes = True


class FolderTreeResponse(BaseModel):
    id: uuid.UUID
    name: str
    parent_id: uuid.UUID | None = None
    children: list["FolderTreeResponse"] = []
    workflows: list[WorkflowListResponse] = []

    class Config:
        from_attributes = True


class MoveWorkflowRequest(BaseModel):
    folder_id: uuid.UUID | None = None


class CredentialConfigQdrant(BaseModel):
    qdrant_host: str
    qdrant_port: int = 6333
    qdrant_api_key: str | None = None
    openai_api_key: str


class CredentialConfigGrist(BaseModel):
    api_key: str
    server_url: str


class CredentialConfigRabbitmq(BaseModel):
    rabbitmq_host: str
    rabbitmq_port: int = 5672
    rabbitmq_username: str
    rabbitmq_password: str
    rabbitmq_vhost: str = "/"


class VectorStoreCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str | None = None
    credential_id: uuid.UUID
    collection_name: str | None = Field(None, min_length=1, max_length=255)


class VectorStoreUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=255)
    description: str | None = None


class VectorStoreStatsResponse(BaseModel):
    vector_count: int
    points_count: int
    status: str


class VectorStoreResponse(BaseModel):
    id: uuid.UUID
    name: str
    description: str | None
    collection_name: str
    owner_id: uuid.UUID
    credential_id: uuid.UUID
    created_at: datetime
    updated_at: datetime
    stats: VectorStoreStatsResponse | None = None

    class Config:
        from_attributes = True


class VectorStoreListResponse(BaseModel):
    id: uuid.UUID
    name: str
    description: str | None
    collection_name: str
    created_at: datetime
    updated_at: datetime
    is_shared: bool = False
    shared_by: str | None = None
    shared_by_team: str | None = None
    stats: VectorStoreStatsResponse | None = None

    class Config:
        from_attributes = True


class VectorStoreShareRequest(BaseModel):
    email: EmailStr


class VectorStoreShareResponse(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    email: str
    name: str
    shared_at: datetime


class VectorStoreUploadResponse(BaseModel):
    chunks_processed: int
    points_inserted: int


class FileCheckItem(BaseModel):
    filename: str
    file_size: int


class CheckDuplicatesRequest(BaseModel):
    files: list[FileCheckItem]


class DuplicateFile(BaseModel):
    filename: str
    file_size: int
    chunk_count: int


class CheckDuplicatesResponse(BaseModel):
    duplicates: list[DuplicateFile]


class CredentialConfigCohere(BaseModel):
    api_key: str


class VectorStoreItem(BaseModel):
    id: str
    text: str
    source: str | None = None
    metadata: dict = Field(default_factory=dict)


class VectorStoreSourceGroup(BaseModel):
    source: str
    file_size: int | None = None
    chunk_count: int
    items: list[VectorStoreItem] = Field(default_factory=list)


class VectorStoreItemsResponse(BaseModel):
    sources: list[VectorStoreSourceGroup]
    total_items: int


class MCPToolInputProperty(BaseModel):
    type: str = "string"
    description: str | None = None


class MCPToolInputSchema(BaseModel):
    type: str = "object"
    properties: dict[str, MCPToolInputProperty] = Field(default_factory=dict)
    required: list[str] = Field(default_factory=list)


class MCPTool(BaseModel):
    name: str
    description: str | None = None
    inputSchema: MCPToolInputSchema = Field(default_factory=MCPToolInputSchema)  # noqa: N815


class MCPToolsListResponse(BaseModel):
    tools: list[MCPTool] = Field(default_factory=list)


class MCPFetchToolItem(BaseModel):
    name: str
    description: str


class MCPFetchToolsResponse(BaseModel):
    tools: list[MCPFetchToolItem] = Field(default_factory=list)


class MCPToolCallRequest(BaseModel):
    name: str
    arguments: dict = Field(default_factory=dict)


class MCPTextContent(BaseModel):
    type: str = "text"
    text: str


class MCPToolResult(BaseModel):
    content: list[MCPTextContent] = Field(default_factory=list)
    isError: bool = False  # noqa: N815


class MCPJSONRPCRequest(BaseModel):
    jsonrpc: str = "2.0"
    id: int | str | None = None
    method: str
    params: dict = Field(default_factory=dict)


class MCPJSONRPCResponse(BaseModel):
    jsonrpc: str = "2.0"
    id: int | str
    result: dict | None = None
    error: dict | None = None

    model_config = {"exclude_none": True}


class MCPServerCapabilities(BaseModel):
    tools: dict = Field(default_factory=lambda: {"listChanged": True})


class MCPServerInfo(BaseModel):
    name: str = "heym-mcp"
    version: str = "1.0.0"


class MCPInitializeResult(BaseModel):
    protocolVersion: str = "2024-11-05"  # noqa: N815
    capabilities: MCPServerCapabilities = Field(default_factory=MCPServerCapabilities)
    serverInfo: MCPServerInfo = Field(default_factory=MCPServerInfo)  # noqa: N815


class MCPWorkflowItem(BaseModel):
    id: uuid.UUID
    name: str
    description: str | None = None
    mcp_enabled: bool = False
    input_fields: list[InputFieldSchema] = Field(default_factory=list)

    class Config:
        from_attributes = True


class MCPConfigResponse(BaseModel):
    mcp_api_key: str | None = None
    mcp_endpoint_url: str
    workflows: list[MCPWorkflowItem] = Field(default_factory=list)


class MCPToggleRequest(BaseModel):
    mcp_enabled: bool


class MCPRegenerateKeyResponse(BaseModel):
    mcp_api_key: str


class PortalFileFieldConfig(BaseModel):
    file_upload_enabled: bool = False
    allowed_types: list[str] = Field(default_factory=lambda: ["text"])
    max_size_mb: int = 5


class PortalSettingsUpdate(BaseModel):
    portal_enabled: bool | None = None
    portal_slug: str | None = Field(None, min_length=1, max_length=255, pattern=r"^[a-z0-9-]+$")
    portal_stream_enabled: bool | None = None
    portal_file_upload_enabled: bool | None = None
    portal_file_config: dict[str, PortalFileFieldConfig] | None = None


class PortalSettingsResponse(BaseModel):
    portal_enabled: bool
    portal_slug: str | None
    portal_stream_enabled: bool
    portal_file_upload_enabled: bool
    portal_file_config: dict
    input_fields: list[InputFieldSchema] = Field(default_factory=list)

    class Config:
        from_attributes = True


class PortalUserCreate(BaseModel):
    username: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=4)


class PortalUserResponse(BaseModel):
    id: uuid.UUID
    username: str
    created_at: datetime

    class Config:
        from_attributes = True


class PortalLoginRequest(BaseModel):
    username: str
    password: str


class PortalLoginResponse(BaseModel):
    session_token: str
    expires_at: datetime


class PortalInfoResponse(BaseModel):
    workflow_name: str
    workflow_description: str | None
    requires_auth: bool
    stream_enabled: bool
    file_upload_enabled: bool
    file_config: dict
    input_fields: list[InputFieldSchema] = Field(default_factory=list)


class ChatMessage(BaseModel):
    role: str
    content: str


class PortalExecuteRequest(BaseModel):
    inputs: dict = Field(default_factory=dict)
    conversation_history: list[ChatMessage] = Field(default_factory=list)


class HITLPublicResponse(BaseModel):
    request_id: uuid.UUID
    workflow_name: str
    agent_label: str
    summary: str
    original_draft_text: str
    status: str
    decision: str | None = None
    edited_text: str | None = None
    refusal_reason: str | None = None
    resolved_output: dict = Field(default_factory=dict)
    expires_at: datetime
    resolved_at: datetime | None = None


class HITLDecisionRequest(BaseModel):
    action: str = Field(pattern=r"^(accept|edit|refuse)$")
    edited_text: str | None = None
    refusal_reason: str | None = None


class HITLDecisionResponse(BaseModel):
    request_id: uuid.UUID
    status: str


class AnalyticsStatsResponse(BaseModel):
    total_executions: int
    success_count: int
    error_count: int
    success_rate: float
    error_rate: float
    avg_latency_ms: float
    p50_latency_ms: float
    p95_latency_ms: float
    p99_latency_ms: float
    total_executions_24h: int
    success_count_24h: int
    error_count_24h: int
    avg_latency_24h_ms: float


class TimeSeriesMetricsResponse(BaseModel):
    time_buckets: list[str]
    executions: list[int]
    successes: list[int]
    errors: list[int]
    avg_latency_ms: list[float]


class WorkflowBreakdownItem(BaseModel):
    workflow_id: uuid.UUID
    workflow_name: str
    execution_count: int
    success_count: int
    error_count: int
    success_rate: float
    error_rate: float
    avg_latency_ms: float


class WorkflowBreakdownResponse(BaseModel):
    items: list[WorkflowBreakdownItem] = Field(default_factory=list)


# ── Templates ────────────────────────────────────────────────────────────────


class TemplateVisibility(str, Enum):
    everyone = "everyone"
    specific_users = "specific_users"


class WorkflowTemplateCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str | None = None
    tags: list[str] = Field(default_factory=list)
    nodes: list[dict] = Field(default_factory=list)
    edges: list[dict] = Field(default_factory=list)
    canvas_snapshot: str | None = None
    visibility: TemplateVisibility = TemplateVisibility.everyone
    shared_with: list[str] = Field(default_factory=list)
    shared_with_teams: list[str] = Field(default_factory=list)


class WorkflowTemplateResponse(BaseModel):
    id: uuid.UUID
    author_id: uuid.UUID
    author_name: str | None = None
    name: str
    description: str | None = None
    tags: list[str]
    nodes: list[dict]
    edges: list[dict]
    canvas_snapshot: str | None = None
    visibility: TemplateVisibility
    shared_with: list[str]
    shared_with_teams: list[str] = Field(default_factory=list)
    use_count: int
    created_at: datetime

    class Config:
        from_attributes = True


class NodeTemplateCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str | None = None
    tags: list[str] = Field(default_factory=list)
    node_type: str = Field(min_length=1, max_length=100)
    node_data: dict = Field(default_factory=dict)
    visibility: TemplateVisibility = TemplateVisibility.everyone
    shared_with: list[str] = Field(default_factory=list)
    shared_with_teams: list[str] = Field(default_factory=list)


class NodeTemplateResponse(BaseModel):
    id: uuid.UUID
    author_id: uuid.UUID
    author_name: str | None = None
    name: str
    description: str | None = None
    tags: list[str]
    node_type: str
    node_data: dict
    visibility: TemplateVisibility
    shared_with: list[str]
    shared_with_teams: list[str] = Field(default_factory=list)
    use_count: int
    created_at: datetime

    class Config:
        from_attributes = True


class UpdateWorkflowTemplateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    tags: list[str] | None = None
    visibility: TemplateVisibility | None = None
    shared_with: list[str] | None = None
    shared_with_teams: list[str] | None = None


class UpdateNodeTemplateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    tags: list[str] | None = None
    visibility: TemplateVisibility | None = None
    shared_with: list[str] | None = None
    shared_with_teams: list[str] | None = None


class CreateTemplateRequest(BaseModel):
    kind: str = Field(..., pattern="^(workflow|node)$")
    workflow: WorkflowTemplateCreate | None = None
    node: NodeTemplateCreate | None = None


class TemplateListResponse(BaseModel):
    workflow_templates: list[WorkflowTemplateResponse] = Field(default_factory=list)
    node_templates: list[NodeTemplateResponse] = Field(default_factory=list)


# ---------- Generated Files ----------


class GeneratedFileResponse(BaseModel):
    id: uuid.UUID
    filename: str
    mime_type: str
    size_bytes: int
    workflow_id: uuid.UUID | None = None
    source_node_label: str | None = None
    download_url: str = ""
    created_at: datetime


class FileAccessTokenResponse(BaseModel):
    id: uuid.UUID
    token: str
    download_url: str = ""
    basic_auth_enabled: bool = False
    expires_at: datetime | None = None
    download_count: int = 0
    max_downloads: int | None = None
    created_at: datetime


class CreateFileShareRequest(BaseModel):
    expires_hours: int | None = None
    basic_auth_password: str | None = None
    max_downloads: int | None = None


class FileListResponse(BaseModel):
    files: list[GeneratedFileResponse] = Field(default_factory=list)
    total: int = 0


# ---------- Data Tables ----------


class DataTableColumnDef(BaseModel):
    id: uuid.UUID = Field(default_factory=uuid.uuid4)
    name: str = Field(min_length=1, max_length=255)
    type: str = Field(default="string", pattern=r"^(string|number|boolean|date|json)$")
    required: bool = False
    defaultValue: object = None  # noqa: N815
    unique: bool = False
    order: int = 0


class DataTableCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str | None = None
    columns: list[DataTableColumnDef] = Field(default_factory=list)


class DataTableUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=255)
    description: str | None = None
    columns: list[DataTableColumnDef] | None = None


class DataTableResponse(BaseModel):
    id: uuid.UUID
    name: str
    description: str | None = None
    columns: list[dict] = Field(default_factory=list)
    owner_id: uuid.UUID
    row_count: int = 0
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class DataTableListResponse(BaseModel):
    id: uuid.UUID
    name: str
    description: str | None = None
    column_count: int = 0
    row_count: int = 0
    owner_id: uuid.UUID
    is_shared: bool = False
    shared_by: str | None = None
    shared_by_team: str | None = None
    permission: str | None = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class DataTableRowCreate(BaseModel):
    data: dict = Field(default_factory=dict)


class DataTableRowUpdate(BaseModel):
    data: dict = Field(default_factory=dict)


class DataTableRowResponse(BaseModel):
    id: uuid.UUID
    table_id: uuid.UUID
    data: dict = Field(default_factory=dict)
    created_by: uuid.UUID | None = None
    updated_by: uuid.UUID | None = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class DataTableShareRequest(BaseModel):
    email: EmailStr
    permission: str = Field(default="read", pattern=r"^(read|write)$")


class DataTableShareResponse(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    email: str
    name: str
    permission: str
    shared_at: datetime


class DataTableTeamShareRequest(BaseModel):
    team_id: uuid.UUID
    permission: str = Field(default="read", pattern=r"^(read|write)$")


class DataTableTeamShareResponse(BaseModel):
    id: uuid.UUID
    team_id: uuid.UUID
    team_name: str
    permission: str
    shared_at: datetime


class DataTableImportResponse(BaseModel):
    imported: int = 0
    errors: list[dict] = Field(default_factory=list)
    total: int = 0


class ScheduleEvent(BaseModel):
    workflow_id: uuid.UUID
    workflow_name: str
    description: str | None = None
    scheduled_at: datetime


class ScheduleListResponse(BaseModel):
    events: list[ScheduleEvent]
    total: int
