import uuid
from datetime import datetime
from decimal import Decimal
from enum import Enum as PyEnum

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    event,
    func,
)
from sqlalchemy.dialects.postgresql import JSON, JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class CredentialType(str, PyEnum):
    openai = "openai"
    codex = "codex"
    google = "google"
    github = "github"
    jira = "jira"
    linear = "linear"
    custom = "custom"
    bearer = "bearer"
    header = "header"
    discord = "discord"
    discord_trigger = "discord_trigger"
    telegram = "telegram"
    slack = "slack"
    slack_trigger = "slack_trigger"
    imap = "imap"
    smtp = "smtp"
    redis = "redis"
    qdrant = "qdrant"
    pgvector = "pgvector"
    grist = "grist"
    rabbitmq = "rabbitmq"
    cohere = "cohere"
    flaresolverr = "flaresolverr"
    google_sheets = "google_sheets"
    bigquery = "bigquery"
    supabase = "supabase"
    notion = "notion"
    sentry = "sentry"
    s3 = "s3"
    elevenlabs = "elevenlabs"
    clickhouse = "clickhouse"
    opencode = "opencode"
    google_drive = "google_drive"
    rag = "rag"


class WorkflowAuthType(str, PyEnum):
    anonymous = "anonymous"
    jwt = "jwt"
    header_auth = "header_auth"


class WebhookBodyMode(str, PyEnum):
    legacy = "legacy"
    generic = "generic"


class User(Base):
    __tablename__ = "users"
    __table_args__ = (Index("ix_users_sso_identity", "sso_issuer", "sso_subject", unique=True),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    hashed_password: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Identity as asserted by the external OIDC provider. (issuer, subject) is the
    # authoritative account key; it survives an email change at the provider.
    sso_issuer: Mapped[str | None] = mapped_column(String(512), nullable=True)
    sso_subject: Mapped[str | None] = mapped_column(String(255), nullable=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    user_rules: Mapped[str | None] = mapped_column(Text, nullable=True)
    mcp_api_key: Mapped[str | None] = mapped_column(
        String(64), nullable=True, unique=True, index=True
    )
    tts_credential_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("credentials.id", ondelete="SET NULL"),
        nullable=True,
    )
    tts_voice_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    preferred_credential_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("credentials.id", ondelete="SET NULL"),
        nullable=True,
    )
    preferred_model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    # Exposes the dashboard chat engine as the `heym_chat` tool on the global MCP server.
    mcp_chat_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    mcp_chat_credential_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("credentials.id", ondelete="SET NULL"),
        nullable=True,
    )
    mcp_chat_model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    workflows: Mapped[list["Workflow"]] = relationship(
        "Workflow", back_populates="owner", cascade="all, delete-orphan"
    )
    workflow_shares: Mapped[list["WorkflowShare"]] = relationship(
        "WorkflowShare", back_populates="user", cascade="all, delete-orphan"
    )
    credentials: Mapped[list["Credential"]] = relationship(
        "Credential",
        back_populates="owner",
        cascade="all, delete-orphan",
        foreign_keys="Credential.owner_id",
    )
    folders: Mapped[list["Folder"]] = relationship(
        "Folder", back_populates="owner", cascade="all, delete-orphan"
    )
    vector_stores: Mapped[list["VectorStore"]] = relationship(
        "VectorStore", back_populates="owner", cascade="all, delete-orphan"
    )
    vector_store_shares: Mapped[list["VectorStoreShare"]] = relationship(
        "VectorStoreShare", back_populates="user", cascade="all, delete-orphan"
    )
    eval_suites: Mapped[list["EvalSuite"]] = relationship(
        "EvalSuite", back_populates="owner", cascade="all, delete-orphan"
    )
    global_variables: Mapped[list["GlobalVariable"]] = relationship(
        "GlobalVariable", back_populates="owner", cascade="all, delete-orphan"
    )
    global_variable_shares: Mapped[list["GlobalVariableShare"]] = relationship(
        "GlobalVariableShare", back_populates="user", cascade="all, delete-orphan"
    )

    # Data Tables
    data_tables: Mapped[list["DataTable"]] = relationship(
        "DataTable", back_populates="owner", cascade="all, delete-orphan"
    )
    data_table_shares: Mapped[list["DataTableShare"]] = relationship(
        "DataTableShare", back_populates="user", cascade="all, delete-orphan"
    )

    # Teams
    created_teams: Mapped[list["Team"]] = relationship(
        "Team", back_populates="creator", cascade="all, delete-orphan"
    )
    team_memberships: Mapped[list["TeamMember"]] = relationship(
        "TeamMember",
        back_populates="user",
        cascade="all, delete-orphan",
        foreign_keys="TeamMember.user_id",
    )
    mcp_servers: Mapped[list["MCPServer"]] = relationship(
        "MCPServer", back_populates="owner", cascade="all, delete-orphan"
    )


class MCPServer(Base):
    __tablename__ = "mcp_servers"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    api_key: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    # Exposes the dashboard chat engine as the `heym_chat` tool on this named server.
    chat_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    chat_credential_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("credentials.id", ondelete="SET NULL"),
        nullable=True,
    )
    chat_model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    owner: Mapped["User"] = relationship("User", back_populates="mcp_servers")
    server_workflows: Mapped[list["MCPServerWorkflow"]] = relationship(
        "MCPServerWorkflow", back_populates="server", cascade="all, delete-orphan"
    )


class MCPServerWorkflow(Base):
    __tablename__ = "mcp_server_workflows"

    mcp_server_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("mcp_servers.id", ondelete="CASCADE"), primary_key=True
    )
    workflow_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workflows.id", ondelete="CASCADE"), primary_key=True
    )

    server: Mapped["MCPServer"] = relationship("MCPServer", back_populates="server_workflows")
    workflow: Mapped["Workflow"] = relationship("Workflow")


class Team(Base):
    __tablename__ = "teams"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    creator_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    creator: Mapped["User"] = relationship("User", back_populates="created_teams")
    members: Mapped[list["TeamMember"]] = relationship(
        "TeamMember", back_populates="team", cascade="all, delete-orphan"
    )


class TeamMember(Base):
    __tablename__ = "team_members"
    __table_args__ = (UniqueConstraint("team_id", "user_id", name="uq_team_member"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    team_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("teams.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    added_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    team: Mapped["Team"] = relationship("Team", back_populates="members")
    user: Mapped["User"] = relationship(
        "User", back_populates="team_memberships", foreign_keys=[user_id]
    )
    added_by: Mapped["User | None"] = relationship("User", foreign_keys=[added_by_id])


class Folder(Base):
    __tablename__ = "folders"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    icon: Mapped[str | None] = mapped_column(String(64), nullable=True)
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("folders.id", ondelete="CASCADE"), nullable=True, index=True
    )
    owner_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    owner: Mapped["User"] = relationship("User", back_populates="folders")
    parent: Mapped["Folder | None"] = relationship(
        "Folder", remote_side="Folder.id", back_populates="children"
    )
    children: Mapped[list["Folder"]] = relationship(
        "Folder", back_populates="parent", cascade="all, delete-orphan"
    )
    workflows: Mapped[list["Workflow"]] = relationship(
        "Workflow", back_populates="folder", cascade="all, delete-orphan"
    )


class Workflow(Base):
    __tablename__ = "workflows"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    kind: Mapped[str] = mapped_column(String(32), default="workflow", nullable=False, index=True)
    nodes: Mapped[dict] = mapped_column(JSON, default=list)
    edges: Mapped[dict] = mapped_column(JSON, default=list)
    auth_type: Mapped[WorkflowAuthType] = mapped_column(
        Enum(WorkflowAuthType, name="workflow_auth_type"),
        default=WorkflowAuthType.jwt,
        nullable=False,
    )
    auth_header_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    auth_header_value: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    webhook_body_mode: Mapped[WebhookBodyMode] = mapped_column(
        Enum(WebhookBodyMode, name="webhook_body_mode"),
        default=WebhookBodyMode.legacy,
        nullable=False,
    )
    cache_ttl_seconds: Mapped[int | None] = mapped_column(nullable=True)
    rate_limit_requests: Mapped[int | None] = mapped_column(nullable=True)
    rate_limit_window_seconds: Mapped[int | None] = mapped_column(nullable=True)
    http_method: Mapped[str] = mapped_column(
        String(8), default="POST", server_default="POST", nullable=False
    )
    sse_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    sse_node_config: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    mcp_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    auto_recover_runs: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    error_workflow_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workflows.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    minutes_saved_per_run: Mapped[float | None] = mapped_column(Float, nullable=True)
    workflow_timeout_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    scheduled_for_deletion: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    portal_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    portal_slug: Mapped[str | None] = mapped_column(String(255), nullable=True, unique=True)
    portal_stream_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    portal_file_upload_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    portal_file_config: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    owner_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    folder_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("folders.id", ondelete="SET NULL"), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    owner: Mapped["User"] = relationship("User", back_populates="workflows")
    folder: Mapped["Folder | None"] = relationship("Folder", back_populates="workflows")
    executions: Mapped[list["ExecutionHistory"]] = relationship(
        "ExecutionHistory", back_populates="workflow", cascade="all, delete-orphan"
    )
    shares: Mapped[list["WorkflowShare"]] = relationship(
        "WorkflowShare", back_populates="workflow", cascade="all, delete-orphan"
    )
    portal_users: Mapped[list["WorkflowPortalUser"]] = relationship(
        "WorkflowPortalUser", back_populates="workflow", cascade="all, delete-orphan"
    )
    portal_sessions: Mapped[list["PortalSession"]] = relationship(
        "PortalSession", back_populates="workflow", cascade="all, delete-orphan"
    )
    hitl_requests: Mapped[list["HITLRequest"]] = relationship(
        "HITLRequest", back_populates="workflow", cascade="all, delete-orphan"
    )
    codex_followup_requests: Mapped[list["CodexFollowupRequest"]] = relationship(
        "CodexFollowupRequest", back_populates="workflow", cascade="all, delete-orphan"
    )
    versions: Mapped[list["WorkflowVersion"]] = relationship(
        "WorkflowVersion", back_populates="workflow", cascade="all, delete-orphan"
    )
    analysis_note: Mapped["WorkflowAnalysisNote | None"] = relationship(
        "WorkflowAnalysisNote",
        back_populates="workflow",
        cascade="all, delete-orphan",
        uselist=False,
    )

    @property
    def allow_anonymous(self) -> bool:
        return self.auth_type == WorkflowAuthType.anonymous


class WorkflowAnalysisNote(Base):
    __tablename__ = "workflow_analysis_notes"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workflow_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workflows.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    content: Mapped[str] = mapped_column(Text, default="", nullable=False)
    revision: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    updated_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    workflow: Mapped["Workflow"] = relationship("Workflow", back_populates="analysis_note")
    updated_by: Mapped["User | None"] = relationship("User")


class WorkflowVersion(Base):
    __tablename__ = "workflow_versions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workflow_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workflows.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    nodes: Mapped[dict] = mapped_column(JSON, default=list, nullable=False)
    edges: Mapped[dict] = mapped_column(JSON, default=list, nullable=False)
    auth_type: Mapped[WorkflowAuthType] = mapped_column(
        Enum(WorkflowAuthType, name="workflow_auth_type"),
        nullable=False,
    )
    auth_header_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    auth_header_value: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    webhook_body_mode: Mapped[WebhookBodyMode] = mapped_column(
        Enum(WebhookBodyMode, name="webhook_body_mode"),
        default=WebhookBodyMode.legacy,
        nullable=False,
    )
    cache_ttl_seconds: Mapped[int | None] = mapped_column(nullable=True)
    rate_limit_requests: Mapped[int | None] = mapped_column(nullable=True)
    rate_limit_window_seconds: Mapped[int | None] = mapped_column(nullable=True)
    created_by_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )

    workflow: Mapped["Workflow"] = relationship("Workflow", back_populates="versions")
    created_by: Mapped["User"] = relationship("User")


class Dashboard(Base):
    __tablename__ = "dashboards"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    owner_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False, default="Dashboard")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    widgets: Mapped[list["DashboardWidget"]] = relationship(
        "DashboardWidget", back_populates="dashboard", cascade="all, delete-orphan"
    )


class DashboardWidget(Base):
    __tablename__ = "dashboard_widgets"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    dashboard_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("dashboards.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    workflow_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workflows.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False, default="Untitled")
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    chart_type: Mapped[str] = mapped_column(String(32), nullable=False, default="bar")
    layout: Mapped[dict] = mapped_column(JSON, default=lambda: {"x": 0, "y": 0, "w": 4, "h": 4})
    cache_ttl_seconds: Mapped[int] = mapped_column(Integer, default=300, nullable=False)
    position: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    cached_payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    cached_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cached_workflow_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    dashboard: Mapped["Dashboard"] = relationship("Dashboard", back_populates="widgets")
    workflow: Mapped["Workflow"] = relationship("Workflow")


class WorkflowShare(Base):
    __tablename__ = "workflow_shares"
    __table_args__ = (UniqueConstraint("workflow_id", "user_id", name="uq_workflow_share"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workflow_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workflows.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    mcp_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    folder_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("folders.id", ondelete="SET NULL"), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    workflow: Mapped["Workflow"] = relationship("Workflow", back_populates="shares")
    user: Mapped["User"] = relationship("User", back_populates="workflow_shares")
    folder: Mapped["Folder | None"] = relationship("Folder")


class WorkflowTeamShare(Base):
    __tablename__ = "workflow_team_shares"
    __table_args__ = (UniqueConstraint("workflow_id", "team_id", name="uq_workflow_team_share"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workflow_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workflows.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    team_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("teams.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    workflow: Mapped["Workflow"] = relationship("Workflow")
    team: Mapped["Team"] = relationship("Team")


class ExecutionHistory(Base):
    __tablename__ = "execution_history"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workflow_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workflows.id"), nullable=False
    )
    inputs: Mapped[dict] = mapped_column(JSON, default=dict)
    outputs: Mapped[dict] = mapped_column(JSON, default=dict)
    node_results: Mapped[list] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    execution_time_ms: Mapped[float] = mapped_column(nullable=False, default=0.0)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
    trigger_source: Mapped[str | None] = mapped_column(
        String(50), nullable=True, default=None, index=True
    )
    recovered: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    executed_by_instance_id: Mapped[str | None] = mapped_column(
        String(128), nullable=True, index=True
    )
    executed_by_instance_name: Mapped[str | None] = mapped_column(String(128), nullable=True)

    workflow: Mapped["Workflow"] = relationship("Workflow", back_populates="executions")
    hitl_requests: Mapped[list["HITLRequest"]] = relationship(
        "HITLRequest", back_populates="execution_history", cascade="all, delete-orphan"
    )
    codex_followup_requests: Mapped[list["CodexFollowupRequest"]] = relationship(
        "CodexFollowupRequest", back_populates="execution_history", cascade="all, delete-orphan"
    )


@event.listens_for(ExecutionHistory, "before_insert")
def stamp_execution_history_attribution(
    _mapper: object, _connection: object, target: ExecutionHistory
) -> None:
    """Stamp every newly persisted workflow run with its executing instance."""
    from app.services.cluster.attribution import attribution_fields

    fields = attribution_fields()
    if target.executed_by_instance_id is None:
        target.executed_by_instance_id = fields["executed_by_instance_id"]
    if target.executed_by_instance_name is None:
        target.executed_by_instance_name = fields["executed_by_instance_name"]


class ActiveWorkflowExecution(Base):
    """Cross-worker registry of executions that are currently running."""

    __tablename__ = "active_workflow_executions"

    execution_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    workflow_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workflows.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    worker_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    heartbeat_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    cancel_requested_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    inputs: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    running_node_ids: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    node_results: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    trigger_source: Mapped[str | None] = mapped_column(String(50), nullable=True)
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    recoverable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, index=True)
    executed_by_instance_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    executed_by_instance_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class WorkflowAnalyticsSnapshot(Base):
    __tablename__ = "workflow_analytics_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "workflow_id",
            "owner_id",
            "bucket_start",
            name="uq_workflow_analytics_snapshot_scope",
            # NULLS NOT DISTINCT: treat NULL as equal so sub-workflow rows
            # (owner_id=None) and deleted-workflow rows (workflow_id=None)
            # are correctly deduplicated on upsert (PostgreSQL 15+).
            postgresql_nulls_not_distinct=True,
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workflow_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workflows.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    owner_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    workflow_name_snapshot: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    bucket_start: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    total_executions: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    success_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    latency_sample_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_latency_ms: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    max_latency_ms: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    last_run_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    workflow: Mapped["Workflow | None"] = relationship("Workflow")
    owner: Mapped["User | None"] = relationship("User")


class LLMTrace(Base):
    __tablename__ = "llm_traces"
    __table_args__ = (Index("ix_llm_traces_user_created", "user_id", "created_at"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    credential_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("credentials.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    workflow_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workflows.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    source: Mapped[str] = mapped_column(String(50), nullable=False)
    request_type: Mapped[str] = mapped_column(String(100), nullable=False)
    provider: Mapped[str | None] = mapped_column(String(50), nullable=True)
    model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    node_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    node_label: Mapped[str | None] = mapped_column(String(255), nullable=True)
    request: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    response: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    prompt_tokens: Mapped[int | None] = mapped_column(nullable=True)
    completion_tokens: Mapped[int | None] = mapped_column(nullable=True)
    total_tokens: Mapped[int | None] = mapped_column(nullable=True)
    elapsed_ms: Mapped[float | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    user: Mapped["User"] = relationship("User")
    credential: Mapped["Credential | None"] = relationship("Credential")
    workflow: Mapped["Workflow | None"] = relationship("Workflow")


class LLMPricing(Base):
    __tablename__ = "llm_pricing"
    __table_args__ = (
        UniqueConstraint("provider", "model", "operator", name="uq_llm_pricing_pmo"),
        Index("ix_llm_pricing_model", "model"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    model: Mapped[str] = mapped_column(String(200), nullable=False)
    operator: Mapped[str] = mapped_column(String(20), nullable=False, default="equals")
    input_per_1m_usd: Mapped[Decimal] = mapped_column(Numeric(12, 6), nullable=False)
    output_per_1m_usd: Mapped[Decimal] = mapped_column(Numeric(12, 6), nullable=False)
    source: Mapped[str] = mapped_column(String(20), nullable=False, default="helicone")
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class LLMPricingOverride(Base):
    __tablename__ = "llm_pricing_override"
    __table_args__ = (
        UniqueConstraint("user_id", "model", name="uq_llm_pricing_override_user_model"),
        Index("ix_llm_pricing_override_user", "user_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    provider: Mapped[str | None] = mapped_column(String(50), nullable=True)
    model: Mapped[str] = mapped_column(String(200), nullable=False)
    input_per_1m_usd: Mapped[Decimal] = mapped_column(Numeric(12, 6), nullable=False)
    output_per_1m_usd: Mapped[Decimal] = mapped_column(Numeric(12, 6), nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    base_pricing_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("llm_pricing.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    user: Mapped["User"] = relationship("User")
    base_pricing: Mapped["LLMPricing | None"] = relationship("LLMPricing")


class RunHistory(Base):
    """Chat and assistant run history (dashboard chat, workflow assistant)."""

    __tablename__ = "run_history"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    run_type: Mapped[str] = mapped_column(
        String(50), nullable=False
    )  # dashboard_chat | workflow_assistant
    workflow_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workflows.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    trigger_source: Mapped[str | None] = mapped_column(String(50), nullable=True)
    inputs: Mapped[dict] = mapped_column(JSON, default=dict)
    outputs: Mapped[dict] = mapped_column(JSON, default=dict)
    steps: Mapped[list] = mapped_column(JSON, default=list)  # tool call steps for chat runs
    status: Mapped[str] = mapped_column(String(50), nullable=False)
    execution_time_ms: Mapped[float] = mapped_column(nullable=False, default=0.0)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    user: Mapped["User"] = relationship("User")
    workflow: Mapped["Workflow | None"] = relationship("Workflow")


class GlobalVariable(Base):
    __tablename__ = "global_variables"
    __table_args__ = (UniqueConstraint("owner_id", "name", name="uq_global_variable_name"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    owner_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    value: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    value_type: Mapped[str] = mapped_column(String(20), nullable=False, default="string")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    owner: Mapped["User"] = relationship("User", back_populates="global_variables")
    shares: Mapped[list["GlobalVariableShare"]] = relationship(
        "GlobalVariableShare", back_populates="global_variable", cascade="all, delete-orphan"
    )


class GlobalVariableShare(Base):
    __tablename__ = "global_variable_shares"
    __table_args__ = (
        UniqueConstraint("global_variable_id", "user_id", name="uq_global_variable_share"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    global_variable_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("global_variables.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    global_variable: Mapped["GlobalVariable"] = relationship(
        "GlobalVariable", back_populates="shares"
    )
    user: Mapped["User"] = relationship("User", back_populates="global_variable_shares")


class GlobalVariableTeamShare(Base):
    __tablename__ = "global_variable_team_shares"
    __table_args__ = (
        UniqueConstraint("global_variable_id", "team_id", name="uq_global_variable_team_share"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    global_variable_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("global_variables.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    team_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("teams.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    global_variable: Mapped["GlobalVariable"] = relationship("GlobalVariable")
    team: Mapped["Team"] = relationship("Team")


class Credential(Base):
    __tablename__ = "credentials"
    __table_args__ = (UniqueConstraint("owner_id", "name", name="uq_credential_name"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    owner_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    type: Mapped[CredentialType] = mapped_column(
        Enum(CredentialType, name="credential_type"), nullable=False
    )
    encrypted_config: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    owner: Mapped["User"] = relationship(
        "User", back_populates="credentials", foreign_keys="Credential.owner_id"
    )
    shares: Mapped[list["CredentialShare"]] = relationship(
        "CredentialShare", back_populates="credential", cascade="all, delete-orphan"
    )


class CredentialShare(Base):
    __tablename__ = "credential_shares"
    __table_args__ = (UniqueConstraint("credential_id", "user_id", name="uq_credential_share"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    credential_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("credentials.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    credential: Mapped["Credential"] = relationship("Credential", back_populates="shares")
    user: Mapped["User"] = relationship("User")


class CredentialTeamShare(Base):
    __tablename__ = "credential_team_shares"
    __table_args__ = (
        UniqueConstraint("credential_id", "team_id", name="uq_credential_team_share"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    credential_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("credentials.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    team_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("teams.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    credential: Mapped["Credential"] = relationship("Credential")
    team: Mapped["Team"] = relationship("Team")


class VectorStore(Base):
    __tablename__ = "vector_stores"
    __table_args__ = (UniqueConstraint("owner_id", "name", name="uq_vector_store_name"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    collection_name: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    owner_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    credential_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("credentials.id", ondelete="CASCADE"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    owner: Mapped["User"] = relationship("User", back_populates="vector_stores")
    credential: Mapped["Credential"] = relationship("Credential")
    shares: Mapped[list["VectorStoreShare"]] = relationship(
        "VectorStoreShare", back_populates="vector_store", cascade="all, delete-orphan"
    )


class VectorStoreShare(Base):
    __tablename__ = "vector_store_shares"
    __table_args__ = (UniqueConstraint("vector_store_id", "user_id", name="uq_vector_store_share"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    vector_store_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("vector_stores.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    vector_store: Mapped["VectorStore"] = relationship("VectorStore", back_populates="shares")
    user: Mapped["User"] = relationship("User", back_populates="vector_store_shares")


class VectorStoreTeamShare(Base):
    __tablename__ = "vector_store_team_shares"
    __table_args__ = (
        UniqueConstraint("vector_store_id", "team_id", name="uq_vector_store_team_share"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    vector_store_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("vector_stores.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    team_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("teams.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    vector_store: Mapped["VectorStore"] = relationship("VectorStore")
    team: Mapped["Team"] = relationship("Team")


class DataTable(Base):
    __tablename__ = "data_tables"
    __table_args__ = (UniqueConstraint("owner_id", "name", name="uq_data_table_name"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    columns: Mapped[list] = mapped_column(JSON, default=list)
    owner_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    owner: Mapped["User"] = relationship("User", back_populates="data_tables")
    rows: Mapped[list["DataTableRow"]] = relationship(
        "DataTableRow", back_populates="table", cascade="all, delete-orphan"
    )
    shares: Mapped[list["DataTableShare"]] = relationship(
        "DataTableShare", back_populates="data_table", cascade="all, delete-orphan"
    )
    team_shares: Mapped[list["DataTableTeamShare"]] = relationship(
        "DataTableTeamShare", back_populates="data_table", cascade="all, delete-orphan"
    )


class DataTableRow(Base):
    __tablename__ = "data_table_rows"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    table_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("data_tables.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    data: Mapped[dict] = mapped_column(JSON, default=dict)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    updated_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    table: Mapped["DataTable"] = relationship("DataTable", back_populates="rows")


class DataTableShare(Base):
    __tablename__ = "data_table_shares"
    __table_args__ = (UniqueConstraint("table_id", "user_id", name="uq_data_table_share"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    table_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("data_tables.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    permission: Mapped[str] = mapped_column(String(10), nullable=False, default="read")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    data_table: Mapped["DataTable"] = relationship("DataTable", back_populates="shares")
    user: Mapped["User"] = relationship("User", back_populates="data_table_shares")


class DataTableTeamShare(Base):
    __tablename__ = "data_table_team_shares"
    __table_args__ = (UniqueConstraint("table_id", "team_id", name="uq_data_table_team_share"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    table_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("data_tables.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    team_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("teams.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    permission: Mapped[str] = mapped_column(String(10), nullable=False, default="read")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    data_table: Mapped["DataTable"] = relationship("DataTable", back_populates="team_shares")
    team: Mapped["Team"] = relationship("Team")


class WorkflowPortalUser(Base):
    __tablename__ = "workflow_portal_users"
    __table_args__ = (
        UniqueConstraint("workflow_id", "username", name="uq_portal_user_workflow_username"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workflow_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workflows.id", ondelete="CASCADE"), nullable=False
    )
    username: Mapped[str] = mapped_column(String(100), nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    workflow: Mapped["Workflow"] = relationship("Workflow", back_populates="portal_users")


class PortalSession(Base):
    __tablename__ = "portal_sessions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    token: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    workflow_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workflows.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    username: Mapped[str] = mapped_column(String(100), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    workflow: Mapped["Workflow"] = relationship("Workflow", back_populates="portal_sessions")


class HITLRequest(Base):
    __tablename__ = "hitl_requests"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workflow_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workflows.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    execution_history_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("execution_history.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    public_token: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    workflow_name: Mapped[str] = mapped_column(String(255), nullable=False)
    agent_node_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    agent_label: Mapped[str] = mapped_column(String(255), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    original_draft_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    original_agent_output: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    resolved_output: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    execution_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending", index=True)
    decision: Mapped[str | None] = mapped_column(String(20), nullable=True)
    edited_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    refusal_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    resume_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    workflow: Mapped["Workflow"] = relationship("Workflow", back_populates="hitl_requests")
    execution_history: Mapped["ExecutionHistory"] = relationship(
        "ExecutionHistory", back_populates="hitl_requests"
    )


class CodexFollowupRequest(Base):
    __tablename__ = "codex_followup_requests"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workflow_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workflows.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    execution_history_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("execution_history.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    public_token: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    workflow_name: Mapped[str] = mapped_column(String(255), nullable=False)
    codex_node_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    codex_label: Mapped[str] = mapped_column(String(255), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    question: Mapped[str] = mapped_column(Text, nullable=False, default="")
    task_prompt: Mapped[str] = mapped_column(Text, nullable=False, default="")
    repository_url: Mapped[str] = mapped_column(Text, nullable=False, default="")
    base_branch: Mapped[str] = mapped_column(String(255), nullable=False, default="main")
    branch_name: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    thread_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    workspace_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    original_output: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    resolved_output: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    execution_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending", index=True)
    answer_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    resume_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    answered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    workflow: Mapped["Workflow"] = relationship(
        "Workflow", back_populates="codex_followup_requests"
    )
    execution_history: Mapped["ExecutionHistory"] = relationship(
        "ExecutionHistory", back_populates="codex_followup_requests"
    )


class OAuthClient(Base):
    __tablename__ = "oauth_clients"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    client_id: Mapped[str] = mapped_column(String(128), unique=True, index=True, nullable=False)
    client_secret_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    client_name: Mapped[str] = mapped_column(String(255), nullable=False)
    redirect_uris: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    grant_types: Mapped[list] = mapped_column(
        JSON, nullable=False, default=lambda: ["authorization_code"]
    )
    response_types: Mapped[list] = mapped_column(JSON, nullable=False, default=lambda: ["code"])
    scope: Mapped[str] = mapped_column(String(255), nullable=False, default="mcp")
    is_confidential: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class OAuthAuthorizationCode(Base):
    __tablename__ = "oauth_authorization_codes"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    code: Mapped[str] = mapped_column(String(128), unique=True, index=True, nullable=False)
    client_id: Mapped[str] = mapped_column(String(128), nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    redirect_uri: Mapped[str] = mapped_column(Text, nullable=False)
    scope: Mapped[str] = mapped_column(String(255), nullable=False)
    code_challenge: Mapped[str | None] = mapped_column(String(128), nullable=True)
    code_challenge_method: Mapped[str | None] = mapped_column(String(10), nullable=True)
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    used: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    user: Mapped["User"] = relationship("User")


class OAuthAccessToken(Base):
    __tablename__ = "oauth_access_tokens"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    access_token: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    refresh_token: Mapped[str | None] = mapped_column(
        String(255), unique=True, index=True, nullable=True
    )
    client_id: Mapped[str] = mapped_column(String(128), nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    scope: Mapped[str] = mapped_column(String(255), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    refresh_token_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    revoked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    user: Mapped["User"] = relationship("User")


class RefreshToken(Base):
    """Tracks issued JWT refresh tokens so they can be revoked on rotation."""

    __tablename__ = "refresh_tokens"

    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    revoked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    user: Mapped["User"] = relationship("User")


class WorkflowExecutionToken(Base):
    """Scoped JWT stored for display and revocation; valid for one workflow's execute endpoints."""

    __tablename__ = "workflow_execution_tokens"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    jti: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), unique=True, nullable=False, index=True
    )
    token: Mapped[str] = mapped_column(Text, nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    workflow_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workflows.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    user: Mapped["User"] = relationship("User")
    workflow: Mapped["Workflow"] = relationship("Workflow")


class TemplateKind(str, PyEnum):
    workflow = "workflow"
    node = "node"


class TemplateVisibility(str, PyEnum):
    everyone = "everyone"
    specific_users = "specific_users"


class WorkflowTemplate(Base):
    __tablename__ = "workflow_templates"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    author_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    tags: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    nodes: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    edges: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    canvas_snapshot: Mapped[str | None] = mapped_column(Text, nullable=True)
    visibility: Mapped[TemplateVisibility] = mapped_column(
        Enum(TemplateVisibility, name="template_visibility"),
        default=TemplateVisibility.everyone,
        nullable=False,
    )
    shared_with: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    shared_with_teams: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    use_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    author: Mapped["User"] = relationship("User")


class NodeTemplate(Base):
    __tablename__ = "node_templates"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    author_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    tags: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    node_type: Mapped[str] = mapped_column(String(100), nullable=False)
    node_data: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    visibility: Mapped[TemplateVisibility] = mapped_column(
        Enum(TemplateVisibility, name="template_visibility"),
        default=TemplateVisibility.everyone,
        nullable=False,
    )
    shared_with: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    shared_with_teams: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    use_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    author: Mapped["User"] = relationship("User")


class EvalSuite(Base):
    __tablename__ = "eval_suites"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    owner_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    system_prompt: Mapped[str] = mapped_column(Text, nullable=False, default="")
    scoring_method: Mapped[str] = mapped_column(String(50), nullable=False, default="exact_match")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    owner: Mapped["User"] = relationship("User", back_populates="eval_suites")
    test_cases: Mapped[list["EvalTestCase"]] = relationship(
        "EvalTestCase",
        back_populates="suite",
        cascade="all, delete-orphan",
        order_by="EvalTestCase.order_index",
    )
    runs: Mapped[list["EvalRun"]] = relationship(
        "EvalRun", back_populates="suite", cascade="all, delete-orphan"
    )


class EvalTestCase(Base):
    __tablename__ = "eval_test_cases"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    suite_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("eval_suites.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    input: Mapped[str] = mapped_column(Text, nullable=False, default="")
    expected_output: Mapped[str] = mapped_column(Text, nullable=False, default="")
    input_mode: Mapped[str] = mapped_column(String(20), nullable=False, default="text")
    expected_mode: Mapped[str] = mapped_column(String(20), nullable=False, default="text")
    order_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    suite: Mapped["EvalSuite"] = relationship("EvalSuite", back_populates="test_cases")
    run_results: Mapped[list["EvalRunResult"]] = relationship(
        "EvalRunResult",
        back_populates="test_case",
        cascade="save-update",
        passive_deletes=True,
    )


class EvalRun(Base):
    __tablename__ = "eval_runs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    suite_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("eval_suites.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    system_prompt_snapshot: Mapped[str] = mapped_column(Text, nullable=False, default="")
    models: Mapped[dict] = mapped_column(JSON, nullable=False, default=list)
    scoring_method: Mapped[str] = mapped_column(String(50), nullable=False, default="exact_match")
    temperature: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    reasoning_effort: Mapped[str | None] = mapped_column(String(20), nullable=True)
    max_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    suite: Mapped["EvalSuite"] = relationship("EvalSuite", back_populates="runs")
    results: Mapped[list["EvalRunResult"]] = relationship(
        "EvalRunResult", back_populates="run", cascade="all, delete-orphan"
    )


class EvalRunResult(Base):
    __tablename__ = "eval_run_results"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("eval_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    test_case_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("eval_test_cases.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    model_id: Mapped[str] = mapped_column(String(255), nullable=False)
    input_snapshot: Mapped[str] = mapped_column(Text, nullable=False, default="")
    expected_output_snapshot: Mapped[str] = mapped_column(Text, nullable=False, default="")
    actual_output: Mapped[str] = mapped_column(Text, nullable=False, default="")
    score: Mapped[str] = mapped_column(String(20), nullable=False, default="fail")
    explanation: Mapped[str | None] = mapped_column(Text, nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tokens_used: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    run_order: Mapped[int | None] = mapped_column(Integer, nullable=True)

    run: Mapped["EvalRun"] = relationship("EvalRun", back_populates="results")
    test_case: Mapped["EvalTestCase"] = relationship("EvalTestCase", back_populates="run_results")


class GeneratedFile(Base):
    __tablename__ = "generated_files"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    owner_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    workflow_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workflows.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    execution_history_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("execution_history.id", ondelete="SET NULL"),
        nullable=True,
    )
    filename: Mapped[str] = mapped_column(String(512), nullable=False)
    storage_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(255), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    source_node_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source_node_label: Mapped[str | None] = mapped_column(String(255), nullable=True)
    metadata_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    access_tokens: Mapped[list["FileAccessToken"]] = relationship(
        "FileAccessToken", back_populates="file", cascade="all, delete-orphan"
    )
    team_shares: Mapped[list["FileTeamShare"]] = relationship(
        "FileTeamShare", back_populates="file", cascade="all, delete-orphan"
    )


class FileTeamShare(Base):
    __tablename__ = "file_team_shares"
    __table_args__ = (UniqueConstraint("file_id", "team_id", name="uq_file_team_share"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    file_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("generated_files.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    team_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("teams.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    file: Mapped["GeneratedFile"] = relationship("GeneratedFile", back_populates="team_shares")
    team: Mapped["Team"] = relationship("Team")


class FileAccessToken(Base):
    __tablename__ = "file_access_tokens"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    file_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("generated_files.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    token: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    basic_auth_username: Mapped[str | None] = mapped_column(String(255), nullable=True)
    basic_auth_password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    download_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_downloads: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    created_by_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )

    file: Mapped["GeneratedFile"] = relationship("GeneratedFile", back_populates="access_tokens")


class FileUploadSlot(Base):
    """A single-use, TTL-bounded capability slot for a multipart file upload
    that triggers a workflow run (see fileUploadTrigger node)."""

    __tablename__ = "file_upload_slots"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workflow_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workflows.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    max_size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    allowed_mime: Mapped[list | None] = mapped_column(JSON, nullable=True)
    trigger_node_id: Mapped[str] = mapped_column(String(64), nullable=False)
    trigger_node_label: Mapped[str | None] = mapped_column(String(255), nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    uploaded_file_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("generated_files.id", ondelete="SET NULL"),
        nullable=True,
    )
    run_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    mint_source: Mapped[str] = mapped_column(String(16), nullable=False, default="http")


class FileUploadAudit(Base):
    """Append-only audit trail for file-intake mint and upload attempts."""

    __tablename__ = "file_upload_audit"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    slot_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True, index=True)
    workflow_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True, index=True
    )
    event: Mapped[str] = mapped_column(String(32), nullable=False)
    client_ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(512), nullable=True)
    file_name: Mapped[str | None] = mapped_column(String(512), nullable=True)
    file_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    mime: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class WorkflowResponseCache(Base):
    """Cross-worker cache for workflow HTTP/curl endpoint responses.

    Backed by Postgres so all uvicorn workers share the same cache; an
    in-process dict would only hit when the request lands on the same worker.
    """

    __tablename__ = "workflow_response_cache"

    cache_key: Mapped[str] = mapped_column(String(64), primary_key=True)
    workflow_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workflows.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    outputs: Mapped[dict] = mapped_column(JSON, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class CronSlotClaim(Base):
    """One row per cron slot that has already been claimed for execution.

    Every uvicorn worker runs its own scheduler and only the leader ticks, so a
    leadership handoff used to hand a worker with stale in-memory state a whole
    backlog of "missed" slots. The unique constraint makes the claim the single
    source of truth: a slot runs once, whichever worker inserts the row first.
    """

    __tablename__ = "cron_slot_claims"
    __table_args__ = (
        UniqueConstraint("workflow_id", "node_id", "slot_at", name="uq_cron_slot_claim"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workflow_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workflows.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    node_id: Mapped[str] = mapped_column(String(255), nullable=False)
    slot_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    claimed_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class HeymEvent(Base):
    """Append-only log of platform events that workflows can subscribe to.

    ``workflow_id`` deliberately carries no foreign key: a ``workflow.deleted``
    event names a row that no longer exists, and a cascade would delete the very
    event that reports the deletion.
    """

    __tablename__ = "heym_events"
    __table_args__ = (UniqueConstraint("dedupe_key", name="uq_heym_event_dedupe_key"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    payload: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    owner_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True, index=True
    )
    workflow_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True, index=True
    )
    dedupe_key: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )


class HeymEventClaim(Base):
    """One row per (event, subscribing node) pair that has already been delivered.

    Same contract as ``CronSlotClaim``: in-memory state is per worker, so the only
    place that can answer "has anyone delivered this yet?" is Postgres. The unique
    constraint makes the first inserter the sole deliverer, across workers,
    containers, and machines.
    """

    __tablename__ = "heym_event_claims"
    __table_args__ = (
        UniqueConstraint("event_id", "workflow_id", "node_id", name="uq_heym_event_claim"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    event_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("heym_events.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    workflow_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    node_id: Mapped[str] = mapped_column(String(255), nullable=False)
    claimed_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    claimed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )


class AgentMemoryNode(Base):
    """Knowledge-graph entity for an agent node (canvas) within a workflow."""

    __tablename__ = "agent_memory_nodes"
    __table_args__ = (
        Index("ix_agent_memory_nodes_workflow_canvas", "workflow_id", "canvas_node_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workflow_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workflows.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    canvas_node_id: Mapped[str] = mapped_column(String(128), nullable=False)
    entity_name: Mapped[str] = mapped_column(String(255), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(50), nullable=False)
    properties: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class AgentMemoryEdge(Base):
    """Relationship between two agent memory entities."""

    __tablename__ = "agent_memory_edges"
    __table_args__ = (
        Index("ix_agent_memory_edges_workflow_canvas", "workflow_id", "canvas_node_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workflow_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workflows.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    canvas_node_id: Mapped[str] = mapped_column(String(128), nullable=False)
    source_node_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agent_memory_nodes.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    target_node_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agent_memory_nodes.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    relationship_type: Mapped[str] = mapped_column(String(100), nullable=False)
    properties: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class DashboardConversation(Base):
    __tablename__ = "dashboard_conversations"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False, default="New Chat")
    # Where the conversation originated: "chat" (the Chat tab) or "mcp" (the heym_chat MCP tool).
    source: Mapped[str] = mapped_column(String(20), nullable=False, default="chat")
    is_pinned: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_running: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    has_unread: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    last_credential_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("credentials.id", ondelete="SET NULL"), nullable=True
    )
    last_model: Mapped[str | None] = mapped_column(String(255), nullable=True)
    queue_paused_by_message_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("dashboard_messages.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    messages: Mapped[list["DashboardMessage"]] = relationship(
        "DashboardMessage",
        back_populates="conversation",
        cascade="all, delete-orphan",
        foreign_keys="DashboardMessage.conversation_id",
    )
    queue_items: Mapped[list["DashboardChatQueueItem"]] = relationship(
        "DashboardChatQueueItem", back_populates="conversation", cascade="all, delete-orphan"
    )


class DashboardMessage(Base):
    __tablename__ = "dashboard_messages"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("dashboard_conversations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    tool_calls: Mapped[list | None] = mapped_column(JSONB, nullable=True, default=None)

    conversation: Mapped["DashboardConversation"] = relationship(
        "DashboardConversation",
        back_populates="messages",
        foreign_keys=[conversation_id],
    )


class DashboardChatQueueItem(Base):
    __tablename__ = "dashboard_chat_queue_items"
    __table_args__ = (
        Index(
            "ix_dashboard_chat_queue_items_conv_created_id", "conversation_id", "created_at", "id"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("dashboard_conversations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    credential_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("credentials.id", ondelete="CASCADE"),
        nullable=False,
    )
    model: Mapped[str] = mapped_column(String(255), nullable=False)
    attachment: Mapped[dict | None] = mapped_column(JSONB, nullable=True, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    conversation: Mapped["DashboardConversation"] = relationship(
        "DashboardConversation", back_populates="queue_items"
    )


class DashboardChatQuickPrompts(Base):
    __tablename__ = "dashboard_chat_quick_prompts"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    prompts: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class Plugin(Base):
    __tablename__ = "plugins"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    plugin_id: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    version: Mapped[str] = mapped_column(String(50), nullable=False)
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    manifest: Mapped[dict] = mapped_column(JSONB, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    installed_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class Board(Base):
    __tablename__ = "boards"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    owner_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False, default="Board")
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    mapper_model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    mapper_credential_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("credentials.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    columns: Mapped[list["BoardColumn"]] = relationship(
        "BoardColumn",
        back_populates="board",
        cascade="all, delete-orphan",
        order_by="BoardColumn.position",
    )
    cards: Mapped[list["BoardCard"]] = relationship(
        "BoardCard", back_populates="board", cascade="all, delete-orphan"
    )
    shares: Mapped[list["BoardShare"]] = relationship(
        "BoardShare", back_populates="board", cascade="all, delete-orphan"
    )
    team_shares: Mapped[list["BoardTeamShare"]] = relationship(
        "BoardTeamShare", back_populates="board", cascade="all, delete-orphan"
    )


class BoardShare(Base):
    __tablename__ = "board_shares"
    __table_args__ = (UniqueConstraint("board_id", "user_id", name="uq_board_share"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    board_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("boards.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    permission: Mapped[str] = mapped_column(String(10), nullable=False, default="read")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    board: Mapped["Board"] = relationship("Board", back_populates="shares")
    user: Mapped["User"] = relationship("User")


class BoardTeamShare(Base):
    __tablename__ = "board_team_shares"
    __table_args__ = (UniqueConstraint("board_id", "team_id", name="uq_board_team_share"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    board_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("boards.id", ondelete="CASCADE"), nullable=False, index=True
    )
    team_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("teams.id", ondelete="CASCADE"), nullable=False, index=True
    )
    permission: Mapped[str] = mapped_column(String(10), nullable=False, default="read")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    board: Mapped["Board"] = relationship("Board", back_populates="team_shares")
    team: Mapped["Team"] = relationship("Team")


class BoardColumn(Base):
    __tablename__ = "board_columns"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    board_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("boards.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    color: Mapped[str | None] = mapped_column(String(32), nullable=True)
    ai_instructions: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    board: Mapped["Board"] = relationship("Board", back_populates="columns")
    workflows: Mapped[list["BoardColumnWorkflow"]] = relationship(
        "BoardColumnWorkflow",
        back_populates="column",
        cascade="all, delete-orphan",
        order_by="BoardColumnWorkflow.position",
    )


class BoardColumnWorkflow(Base):
    __tablename__ = "board_column_workflows"
    __table_args__ = (
        UniqueConstraint("column_id", "workflow_id", name="uq_board_column_workflow"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    column_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("board_columns.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    workflow_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workflows.id", ondelete="CASCADE"), nullable=False
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    column: Mapped["BoardColumn"] = relationship("BoardColumn", back_populates="workflows")
    workflow: Mapped["Workflow"] = relationship("Workflow")


class BoardCard(Base):
    __tablename__ = "board_cards"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    board_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("boards.id", ondelete="CASCADE"), nullable=False, index=True
    )
    column_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("board_columns.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    run_status: Mapped[str] = mapped_column(String(20), nullable=False, default="idle")
    card_metadata: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    board: Mapped["Board"] = relationship("Board", back_populates="cards")
    activities: Mapped[list["BoardCardActivity"]] = relationship(
        "BoardCardActivity",
        back_populates="card",
        cascade="all, delete-orphan",
        order_by="BoardCardActivity.created_at",
        foreign_keys="BoardCardActivity.card_id",
    )
    runs: Mapped[list["BoardCardRun"]] = relationship(
        "BoardCardRun",
        back_populates="card",
        cascade="all, delete-orphan",
        order_by="BoardCardRun.started_at",
    )


class BoardCardRun(Base):
    __tablename__ = "board_card_runs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    card_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("board_cards.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    column_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("board_columns.id", ondelete="CASCADE"), nullable=False
    )
    workflow_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workflows.id", ondelete="SET NULL"), nullable=True
    )
    workflow_name: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    chain_position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    chain_length: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="running", index=True)
    execution_history_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("execution_history.id", ondelete="SET NULL"), nullable=True
    )
    active_execution_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True, index=True
    )
    output: Mapped[dict] = mapped_column(JSON, default=dict)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    card: Mapped["BoardCard"] = relationship("BoardCard", back_populates="runs")


class BoardCardActivity(Base):
    __tablename__ = "board_card_activities"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    card_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("board_cards.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    kind: Mapped[str] = mapped_column(String(20), nullable=False, default="event")
    author_type: Mapped[str] = mapped_column(String(20), nullable=False, default="system")
    author_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    data: Mapped[dict] = mapped_column(JSON, default=dict)
    run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("board_card_runs.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )

    card: Mapped["BoardCard"] = relationship(
        "BoardCard", back_populates="activities", foreign_keys=[card_id]
    )


class Alert(Base):
    __tablename__ = "alerts"
    __table_args__ = (Index("ix_alerts_enabled_next_check", "enabled", "next_check_at"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    owner_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    alert_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    scope: Mapped[str] = mapped_column(String(20), nullable=False, default="workflow")
    workflow_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workflows.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    config: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, index=True)
    notify_workflow_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workflows.id", ondelete="SET NULL"), nullable=True
    )
    state: Mapped[str] = mapped_column(String(20), nullable=False, default="ok")
    renotify_mode: Mapped[str] = mapped_column(String(20), nullable=False, default="on_recovery")
    cooldown_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    check_interval_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=60)
    next_check_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )
    last_evaluated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_triggered_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_observed_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    owner: Mapped["User"] = relationship("User")
    workflow: Mapped["Workflow | None"] = relationship("Workflow", foreign_keys=[workflow_id])
    notify_workflow: Mapped["Workflow | None"] = relationship(
        "Workflow", foreign_keys=[notify_workflow_id]
    )
    events: Mapped[list["AlertEvent"]] = relationship(
        "AlertEvent", back_populates="alert", cascade="all, delete-orphan"
    )
    shares: Mapped[list["AlertShare"]] = relationship(
        "AlertShare", back_populates="alert", cascade="all, delete-orphan"
    )


class AlertEvent(Base):
    __tablename__ = "alert_events"
    __table_args__ = (Index("ix_alert_events_alert_triggered", "alert_id", "triggered_at"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    alert_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("alerts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    triggered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )
    observed_value: Mapped[float] = mapped_column(Float, nullable=False)
    threshold_value: Mapped[float] = mapped_column(Float, nullable=False)
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    window_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    context: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    notify_execution_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    notify_status: Mapped[str | None] = mapped_column(String(20), nullable=True)

    alert: Mapped["Alert"] = relationship("Alert", back_populates="events")


class AlertShare(Base):
    __tablename__ = "alert_shares"
    __table_args__ = (UniqueConstraint("alert_id", "user_id", name="uq_alert_share"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    alert_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("alerts.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    alert: Mapped["Alert"] = relationship("Alert", back_populates="shares")
    user: Mapped["User"] = relationship("User")


class AlertTeamShare(Base):
    __tablename__ = "alert_team_shares"
    __table_args__ = (UniqueConstraint("alert_id", "team_id", name="uq_alert_team_share"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    alert_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("alerts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    team_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("teams.id", ondelete="CASCADE"), nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    alert: Mapped["Alert"] = relationship("Alert")
    team: Mapped["Team"] = relationship("Team")


# The SSO configuration is instance-wide, so the table holds exactly one row addressed
# by this constant. Upserting a fixed key removes the read-then-insert race.
SSO_SETTINGS_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")


class SsoSettings(Base):
    __tablename__ = "sso_settings"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=lambda: SSO_SETTINGS_ID
    )
    enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    issuer: Mapped[str] = mapped_column(String(512), default="", nullable=False)
    client_id: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    encrypted_client_secret: Mapped[str | None] = mapped_column(Text, nullable=True)
    scopes: Mapped[str] = mapped_column(String(255), default="openid email profile", nullable=False)
    # The provider's name lives in data, never in code.
    button_label: Mapped[str] = mapped_column(
        String(64), default="Sign in with SSO", nullable=False
    )
    auto_provision_users: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    allowed_email_domains: Mapped[str] = mapped_column(String(512), default="", nullable=False)
    password_login_disabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    last_test_ok: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    last_test_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class ClusterInstance(Base):
    """One Heym deployment sharing this database. Upserted by all its processes."""

    __tablename__ = "cluster_instances"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    role: Mapped[str] = mapped_column(String(16), nullable=False, default="worker")
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    weight: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # False means "never given a weight": eligible for one automatic seeding.
    weight_configured: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    version: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    schema_revision: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    keys_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    docker_ok: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    db_latency_ms: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    heartbeat_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class WorkflowRunQueue(Base):
    """A background run waiting for, or claimed by, one instance."""

    __tablename__ = "workflow_run_queue"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workflow_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workflows.id", ondelete="CASCADE"), nullable=False
    )
    execution_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, unique=True)
    placement: Mapped[str] = mapped_column(String(16), nullable=False)
    target_instance_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    status: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
    inputs: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    trigger_source: Mapped[str | None] = mapped_column(String(50), nullable=True)
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    credentials_owner_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    test_run: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    timeout_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    return_on_chart_output: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    enqueued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    not_after: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    claimed_by_process: Mapped[str | None] = mapped_column(String(128), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)


class ClusterDispatchState(Base):
    """A single row holding per-instance assignment counters, locked on assignment."""

    __tablename__ = "cluster_dispatch_state"

    id: Mapped[str] = mapped_column(String(16), primary_key=True, default="singleton")
    counters: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    automatic_weighting: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
