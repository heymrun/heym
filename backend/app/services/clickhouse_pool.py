"""Process-wide pool of reusable clickhouse-connect clients.

Creating a fresh ``clickhouse_connect`` client per operation costs ~5 ms
(TCP connect + HTTP session setup). Clients are HTTP-based and thread-safe
(urllib3 connection pool), so we cache one per distinct connection and reuse
it across node executions. Mirrors the grist/qdrant/redis pool pattern.
"""

import logging
from threading import Lock

import clickhouse_connect
from clickhouse_connect.driver.client import Client

CONNECT_TIMEOUT_SECONDS = 15

_clients: dict[str, Client] = {}
_lock = Lock()
logger = logging.getLogger("clickhouse_pool")


def _pool_key(
    *, host: str, port: int, database: str, username: str, password: str, secure: bool
) -> str:
    return f"{host}:{port}:{database}:{username}:{hash(password)}:{secure}"


def get_clickhouse_client(
    *,
    host: str,
    port: int,
    username: str,
    password: str,
    database: str,
    secure: bool,
    connect_timeout: int = CONNECT_TIMEOUT_SECONDS,
) -> Client:
    """Return a cached clickhouse-connect client for the given connection."""
    key = _pool_key(
        host=host,
        port=port,
        database=database,
        username=username,
        password=password,
        secure=secure,
    )
    with _lock:
        client = _clients.get(key)
        if client is None:
            client = clickhouse_connect.get_client(
                host=host,
                port=port,
                username=username,
                password=password,
                database=database,
                secure=secure,
                connect_timeout=connect_timeout,
            )
            _clients[key] = client
            logger.info("ClickHouse client pool created for: %s:%s/%s", host, port, database)
    return client


def warm_up_pools() -> int:
    """Pre-create clients for stored ClickHouse credentials at startup."""
    from app.db.models import Credential, CredentialType
    from app.db.session import SessionLocal
    from app.services.encryption import decrypt_config

    initialized = 0
    with SessionLocal() as db:
        creds = db.query(Credential).filter(Credential.type == CredentialType.clickhouse).all()
        for cred in creds:
            try:
                config = decrypt_config(cred.encrypted_config)
                host = str(config.get("host", "")).strip()
                if not host:
                    continue
                secure = bool(config.get("secure", False))
                raw_port = config.get("port")
                try:
                    port = (
                        int(raw_port) if raw_port not in (None, "") else (8443 if secure else 8123)
                    )
                except (TypeError, ValueError):
                    port = 8443 if secure else 8123
                client = get_clickhouse_client(
                    host=host,
                    port=port,
                    username=str(config.get("username", "") or "default").strip() or "default",
                    password=str(config.get("password", "") or ""),
                    database=str(config.get("database", "") or "default").strip() or "default",
                    secure=secure,
                )
                client.query("SELECT 1")
                initialized += 1
                logger.info("ClickHouse client pool initialized: %s", host)
            except Exception as e:  # noqa: BLE001 - warm-up is best-effort
                logger.warning("Failed to initialize ClickHouse pool for %s: %s", cred.name, e)
    return initialized


def close_all_clients() -> None:
    with _lock:
        for client in _clients.values():
            try:
                client.close()
            except Exception:  # noqa: BLE001 - best-effort cleanup
                pass
        _clients.clear()
