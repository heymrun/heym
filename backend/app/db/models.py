import uuid
from datetime import datetime
from enum import Enum as PyEnum

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class CredentialType(str, PyEnum):
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


class WorkflowAuthType(str, PyEnum):
    anonymous = "anonymous"
    jwt = "jwt"
    header_auth = "header_auth"


class WebhookBodyMode(str, PyEnum):
    legacy = "legacy"
    generic = "generic"


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    user_rules: Mapped[str | None] = mapped_column(Text, nullable=True)
    mcp_api_key: Mapped[str | None] = mapped_column(
        String(64), nullable=True, unique=True, index=True
    )
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
        "Credential", back_populates="owner", cascade="all, delete-orphan"
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
    sse_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    sse_node_config: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    mcp_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
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
    versions: Mapped[list["WorkflowVersion"]] = relationship(
        "WorkflowVersion", back_populates="workflow", cascade="all, delete-orphan"
    )

    @property
    def allow_anonymous(self) -> bool:
        return self.auth_type == WorkflowAuthType.anonymous


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
    status: Mapped[str] = mapped_column(String(50), nullable=False)
    execution_time_ms: Mapped[float] = mapped_column(nullable=False, default=0.0)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    trigger_source: Mapped[str | None] = mapped_column(String(50), nullable=True, default=None)

    workflow: Mapped["Workflow"] = relationship("Workflow", back_populates="executions")
    hitl_requests: Mapped[list["HITLRequest"]] = relationship(
        "HITLRequest", back_populates="execution_history", cascade="all, delete-orphan"
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

    owner: Mapped["User"] = relationship("User", back_populates="credentials")
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
