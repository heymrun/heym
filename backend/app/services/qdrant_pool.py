import logging
from threading import Lock

from qdrant_client import QdrantClient

_clients: dict[str, QdrantClient] = {}
_lock = Lock()
logger = logging.getLogger("qdrant_pool")


def _get_pool_key(host: str, port: int, api_key: str | None) -> str:
    key_hash = hash(api_key) if api_key else "none"
    return f"{host}:{port}:{key_hash}"


def get_qdrant_client(
    host: str,
    port: int,
    api_key: str | None = None,
) -> QdrantClient:
    pool_key = _get_pool_key(host, port, api_key)

    with _lock:
        if pool_key not in _clients:
            if api_key:
                _clients[pool_key] = QdrantClient(
                    host=host,
                    port=port,
                    api_key=api_key,
                )
            else:
                _clients[pool_key] = QdrantClient(
                    host=host,
                    port=port,
                )
            logger.info("Qdrant client pool created for: %s:%s", host, port)

    return _clients[pool_key]


def warm_up_pools() -> int:
    from app.db.models import Credential, CredentialType
    from app.db.session import SessionLocal
    from app.services.encryption import decrypt_config

    initialized = 0

    with SessionLocal() as db:
        qdrant_creds = db.query(Credential).filter(Credential.type == CredentialType.qdrant).all()

        for cred in qdrant_creds:
            try:
                config = decrypt_config(cred.encrypted_config)
                host = config.get("qdrant_host", "localhost")
                port = int(config.get("qdrant_port", 6333))
                api_key = config.get("qdrant_api_key") or None

                if host:
                    client = get_qdrant_client(host=host, port=port, api_key=api_key)
                    client.get_collections()
                    initialized += 1
                    logger.info("Qdrant client pool initialized: %s:%s", host, port)
            except Exception as e:
                logger.warning("Failed to initialize Qdrant pool for %s: %s", cred.name, e)

    return initialized


def close_all_clients() -> None:
    with _lock:
        for client in _clients.values():
            client.close()
        _clients.clear()
