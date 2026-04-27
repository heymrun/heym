import os

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings


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
    secret_key: str = "your-super-secret-key-change-in-production-min-32-chars"
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
    app_version: str = ""

    @property
    def resolved_version(self) -> str:
        """Get version from env var, VERSION file, or default."""
        if self.app_version:
            return self.app_version
        return _read_version()

    @field_validator("app_version", mode="before")
    @classmethod
    def validate_app_version(cls, v: str | None) -> str:
        if v:
            return v
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
        if not v:
            raise ValueError(
                "ENCRYPTION_KEY environment variable is required. "
                "Generate a strong random key: "
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
