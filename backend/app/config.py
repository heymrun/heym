import os

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings

# Known placeholder values that must not be used in production
_SECRET_KEY_PLACEHOLDER = "your-super-secret-key-change-in-production-min-32-chars"
_ENCRYPTION_KEY_PLACEHOLDER = "change_this_to_a_random_32_byte_hex_value"


def _read_version() -> str:
    """Read version from VERSION file."""
    try:
        version_path = os.path.join(os.path.dirname(__file__), "..", "..", "VERSION")
        with open(version_path) as f:
            return f.read().strip()
    except Exception:
        return "0.1.0"


class Settings(BaseSettings):
    database_url: str = ""
    postgres_host: str = "localhost"
    postgres_port: int = 6543
    postgres_user: str = "postgres"
    postgres_password: str = "postgres"
    postgres_db: str = "heym"
    secret_key: str = ""

    @field_validator("secret_key")
    @classmethod
    def _validate_secret_key(cls, v: str) -> str:
        """Refuse to start if SECRET_KEY is missing, a known placeholder, or too short."""
        if not v or v == _SECRET_KEY_PLACEHOLDER:
            raise ValueError(
                "SECRET_KEY must be set to a cryptographically random value. "
                "Generate one with: python -c 'import secrets; print(secrets.token_urlsafe(32))'"
            )
        if len(v) < 32:
            raise ValueError(
                f"SECRET_KEY must be at least 32 characters long (got {len(v)}). "
                "Generate one with: python -c 'import secrets; print(secrets.token_urlsafe(32))'"
            )
        return v

    encryption_key: str = ""
    # Keys accepted for decryption only, comma-separated. During a rotation this holds the
    # new key while it is introduced, then the old key once the new one is ENCRYPTION_KEY.
    encryption_keys_extra: str = ""
    # Accept ENCRYPTION_KEY as this database's key even though nothing stored decrypts with
    # it: the way out for an install whose key changed before key checking existed.
    accept_current_encryption_key: bool = Field(
        default=False, validation_alias="HEYM_ACCEPT_CURRENT_ENCRYPTION_KEY"
    )
    jwt_algorithm: str = "HS256"
    jwt_access_token_expire_minutes: int = 1440
    jwt_refresh_token_expire_days: int = 30
    cors_origins: str = "http://localhost:4017"
    frontend_url: str = "http://localhost:4017"
    allow_register: bool = True
    trust_proxy_headers: bool = False
    timezone: str = ""
    # How late a cron slot may still run. Protects against a scheduler that was
    # paused (leadership handoff, restart, host suspend) firing a whole backlog.
    cron_misfire_grace_seconds: int = 600
    oauth_access_token_expire_seconds: int = 3600
    oauth_refresh_token_expire_days: int = 30
    oauth_auth_code_expire_minutes: int = 10
    oauth_issuer: str = (
        ""  # Public OAuth issuer URL (e.g. https://api.example.com). Empty = use request.base_url
    )
    docs_dir: str = ""  # Path to docs content. Empty = use frontend/src/docs/content
    file_storage_dir: str = "./data/files"
    file_max_size_mb: int = 99
    docker_logs_enabled: bool = False
    docker_logs_allowed_emails: str = ""
    plugins_enabled: bool = Field(default=False, validation_alias="HEYM_PLUGINS_ENABLED")
    plugin_admin_emails: str = Field(default="", validation_alias="HEYM_PLUGIN_ADMIN_EMAILS")
    # Instance administrators. Comma-separated emails. These accounts manage all workflows,
    # configure SSO and
    # may always sign in with a password, which is the break-glass path when SSO is
    # misconfigured. An empty value grants nobody.
    admin_emails: str = Field(default="", validation_alias="HEYM_ADMIN_EMAILS")
    # Turns on two-factor sign-in: every password sign-in asks for an authenticator code,
    # and an account without one enrols at its next sign-in. SSO sign-in is never affected.
    require_mfa: bool = Field(default=False, validation_alias="HEYM_REQUIRE_MFA")
    # Execution history and LLM traces older than this are deleted daily. 0 keeps everything.
    data_retention_days: int = Field(default=90, ge=0, validation_alias="HEYM_DATA_RETENTION_DAYS")
    # Load distribution across instances sharing this database. The role defaults to
    # "main" so an existing single-instance deployment keeps behaving as main with no
    # configuration change.
    instance_id: str = Field(default="", validation_alias="HEYM_INSTANCE_ID")
    instance_name: str = Field(default="", validation_alias="HEYM_INSTANCE_NAME")
    instance_role: str = Field(default="main", validation_alias="HEYM_INSTANCE_ROLE")
    cluster_enabled: bool = Field(default=False, validation_alias="HEYM_CLUSTER_ENABLED")
    # Credentials declared as labelled Kubernetes Secrets (services/k8s_credentials).
    # Off by default: turning it on needs list/watch on Secrets in the namespace below.
    k8s_credentials: bool = Field(default=False, validation_alias="HEYM_K8S_CREDENTIALS")
    # Empty means the namespace Heym itself runs in.
    k8s_credentials_namespace: str = Field(
        default="", validation_alias="HEYM_K8S_CREDENTIALS_NAMESPACE"
    )
    db_pool_size: int = Field(default=10, validation_alias="HEYM_DB_POOL_SIZE")
    db_max_overflow: int = Field(default=20, validation_alias="HEYM_DB_MAX_OVERFLOW")
    db_sync_pool_size: int = Field(default=5, validation_alias="HEYM_DB_SYNC_POOL_SIZE")
    db_sync_max_overflow: int = Field(default=10, validation_alias="HEYM_DB_SYNC_MAX_OVERFLOW")
    plugins_dir: str = Field(default="data/plugins", validation_alias="HEYM_PLUGINS_DIR")
    # Custom Playwright code runs arbitrary Python in the backend process. It is OFF by
    # default; an operator must opt in explicitly. Step-based Playwright nodes are unaffected.
    playwright_custom_code_enabled: bool = Field(
        default=False, validation_alias="HEYM_PLAYWRIGHT_CUSTOM_CODE_ENABLED"
    )
    codex_cli_command: str = Field(default="codex", validation_alias="HEYM_CODEX_CLI_COMMAND")
    codex_workspace_dir: str = Field(
        default="./data/codex-workspaces", validation_alias="HEYM_CODEX_WORKSPACE_DIR"
    )
    codex_network_access: bool = Field(default=False, validation_alias="HEYM_CODEX_NETWORK_ACCESS")
    # Git identity for Codex commits. The avatar shown next to it on GitHub is derived from the
    # email (a matching GitHub account, else Gravatar) — point the email at a branded one to
    # display a logo.
    codex_git_author_name: str = Field(
        default="Heym Codex", validation_alias="HEYM_CODEX_GIT_AUTHOR_NAME"
    )
    codex_git_author_email: str = Field(
        default="support@heym.run", validation_alias="HEYM_CODEX_GIT_AUTHOR_EMAIL"
    )
    # OpenCode Go coding-agent node. Like Codex, execution isolation is chosen by the CLI command:
    # local dev (run.sh) leaves it as the host `opencode` binary, while Docker deployments set
    # HEYM_OPENCODE_CLI_COMMAND=/usr/local/bin/heym-opencode-docker (a wrapper that runs OpenCode in
    # a hardened sibling container sharing the workspace named volume). All git/GitHub work is
    # host-side, so the GitHub token is never placed inside the OpenCode process/container.
    opencode_cli_command: str = Field(
        default="opencode", validation_alias="HEYM_OPENCODE_CLI_COMMAND"
    )
    opencode_workspace_dir: str = Field(
        default="./data/opencode-workspaces", validation_alias="HEYM_OPENCODE_WORKSPACE_DIR"
    )
    opencode_git_author_name: str = Field(
        default="Heym OpenCode", validation_alias="HEYM_OPENCODE_GIT_AUTHOR_NAME"
    )
    opencode_git_author_email: str = Field(
        default="support@heym.run", validation_alias="HEYM_OPENCODE_GIT_AUTHOR_EMAIL"
    )
    # Shared SSRF egress guard for user-controlled HTTP/WebSocket targets and
    # credential-derived integration URLs. When false (default), guarded targets
    # may only reach public addresses. Trusted self-hosted instances that
    # intentionally call internal services can opt out instance-wide.
    http_allow_private_urls: bool = Field(
        default=False, validation_alias="HEYM_HTTP_ALLOW_PRIVATE_URLS"
    )
    # ChatGPT-subscription OAuth (PKCE) for the Codex node. Defaults mirror the public OpenAI
    # Codex CLI client; override via env if OpenAI changes the client id or endpoints.
    codex_oauth_client_id: str = Field(
        default="app_EMoamEEZ73f0CkXaXp7hrann", validation_alias="HEYM_CODEX_OAUTH_CLIENT_ID"
    )
    codex_oauth_issuer: str = Field(
        default="https://auth.openai.com", validation_alias="HEYM_CODEX_OAUTH_ISSUER"
    )
    codex_oauth_redirect_uri: str = Field(
        default="http://localhost:1455/auth/callback",
        validation_alias="HEYM_CODEX_OAUTH_REDIRECT_URI",
    )
    # Keep above file_max_size_mb so multipart metadata can fit around a max-size file.
    request_body_max_size_mb: int = 100
    mcp_protocol_max_concurrency: int = 20
    mcp_sse_max_sessions: int = 100
    # SSRF egress guard for MCP http(s)/SSE transports. By default the server
    # refuses to open sse/streamable_http MCP connections whose host resolves to
    # a loopback, private, link-local (incl. 169.254.169.254 cloud metadata), or
    # otherwise non-public address. Self-hosted operators who intentionally run
    # internal MCP servers can opt out with HEYM_MCP_ALLOW_PRIVATE_URLS=true.
    mcp_allow_private_urls: bool = Field(
        default=False, validation_alias="HEYM_MCP_ALLOW_PRIVATE_URLS"
    )
    # Isolation for MCP `stdio` servers, which start a process from a command in
    # the node configuration. Deliberately separate from HEYM_PYTHON_TOOL_SANDBOX:
    # an operator who picks `subprocess` there for Python tool compatibility must
    # not silently lose MCP stdio isolation as a side effect. `auto` requires
    # Docker and fails closed without it; `subprocess` is an explicit,
    # host-executing opt-out for trusted single-user setups.
    mcp_stdio_sandbox: str = Field(default="auto", validation_alias="HEYM_MCP_STDIO_SANDBOX")
    app_version: str = ""

    # OpenTelemetry tracing (disabled by default -> zero overhead).
    # Env var names use the HEYM_OTEL_ prefix to keep a dedicated namespace.
    otel_enabled: bool = Field(default=False, validation_alias="HEYM_OTEL_ENABLED")
    otel_exporter_otlp_endpoint: str = Field(
        default="", validation_alias="HEYM_OTEL_EXPORTER_OTLP_ENDPOINT"
    )
    otel_exporter_otlp_headers: str = Field(
        default="", validation_alias="HEYM_OTEL_EXPORTER_OTLP_HEADERS"
    )
    otel_service_name: str = Field(default="heym", validation_alias="HEYM_OTEL_SERVICE_NAME")
    otel_traces_sampler_ratio: float = Field(
        default=1.0, validation_alias="HEYM_OTEL_TRACES_SAMPLER_RATIO"
    )
    otel_capture_node_io: bool = Field(default=False, validation_alias="HEYM_OTEL_CAPTURE_NODE_IO")
    llm_pricing_sync_enabled: bool = Field(
        default=True, validation_alias="HEYM_LLM_PRICING_SYNC_ENABLED"
    )

    @property
    def resolved_version(self) -> str:
        """Get version from env var, VERSION file, or default."""
        if self.app_version:
            return self.app_version
        return _read_version()

    @model_validator(mode="after")
    def ensure_database_url(self) -> "Settings":
        if self.database_url:
            return self

        self.database_url = (
            "postgresql+asyncpg://"
            f"{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )
        return self

    @field_validator("encryption_key")
    @classmethod
    def encryption_key_must_be_set(cls, v: str) -> str:
        """Refuse to start if ENCRYPTION_KEY is absent or still the known-compromised default."""
        if not v or v == _ENCRYPTION_KEY_PLACEHOLDER:
            raise ValueError(
                "ENCRYPTION_KEY environment variable is required and must not be the "
                "placeholder value. Generate a strong random key: "
                'python -c "import secrets; print(secrets.token_hex(32))"'
            )
        return v

    @field_validator("encryption_keys_extra")
    @classmethod
    def encryption_keys_extra_are_real_keys(cls, v: str) -> str:
        """Drop empty entries and refuse the placeholder, as for ENCRYPTION_KEY.

        Without dropping them, a trailing comma would add the empty string as a key that
        decrypts: every key goes through the same sha256 derivation, empty or not.
        """
        keys = [key.strip() for key in v.split(",") if key.strip()]
        if _ENCRYPTION_KEY_PLACEHOLDER in keys:
            raise ValueError(
                "ENCRYPTION_KEYS_EXTRA must not contain the placeholder value "
                f"{_ENCRYPTION_KEY_PLACEHOLDER!r}."
            )
        return ",".join(keys)

    @property
    def encryption_keys(self) -> list[str]:
        """ENCRYPTION_KEY first, then each extra key once. Encryption uses only the first."""
        keys = [self.encryption_key]
        for key in self.encryption_keys_extra.split(","):
            if key and key not in keys:
                keys.append(key)
        return keys

    @model_validator(mode="after")
    def k8s_credentials_refuse_subprocess_sandboxes(self) -> "Settings":
        """Refuse Kubernetes credentials while user code can run inside the backend container.

        The ServiceAccount token that reads Secrets is a file in this container, so a
        `subprocess` sandbox could read it however well it scrubs the environment.
        `auto` and `docker` fail closed instead of falling back to a subprocess.
        """
        if not self.k8s_credentials:
            return self
        modes = {
            "HEYM_PYTHON_TOOL_SANDBOX": os.environ.get("HEYM_PYTHON_TOOL_SANDBOX", ""),
            "HEYM_PLAYWRIGHT_SANDBOX": os.environ.get("HEYM_PLAYWRIGHT_SANDBOX", ""),
            "HEYM_MCP_STDIO_SANDBOX": os.environ.get("HEYM_MCP_STDIO_SANDBOX")
            or self.mcp_stdio_sandbox,
        }
        offending = sorted(
            name for name, value in modes.items() if str(value).strip().lower() == "subprocess"
        )
        if offending:
            raise ValueError(
                "HEYM_K8S_CREDENTIALS cannot be enabled while "
                f"{', '.join(offending)}=subprocess: user code would run next to the "
                "ServiceAccount token that reads Secrets. Use auto or docker."
            )
        return self

    @property
    def effective_timezone(self) -> str:
        if self.timezone:
            return self.timezone
        return os.environ.get("TZ", "UTC")

    @property
    def cors_origins_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",")]

    class Config:
        env_file = (".env", "../.env")
        extra = "ignore"


settings = Settings()
