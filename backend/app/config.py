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
    jwt_algorithm: str = "HS256"
    jwt_access_token_expire_minutes: int = 1440
    jwt_refresh_token_expire_days: int = 30
    cors_origins: str = "http://localhost:4017"
    frontend_url: str = "http://localhost:4017"
    allow_register: bool = True
    trust_proxy_headers: bool = False
    timezone: str = ""
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
    # Keep above file_max_size_mb so multipart metadata can fit around a max-size file.
    request_body_max_size_mb: int = 100
    mcp_protocol_max_concurrency: int = 20
    mcp_sse_max_sessions: int = 100
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
