import logging
from threading import Lock

import httpx

from app.http_identity import HEYM_USER_AGENT

POOL_SIZE = 8
CONNECTION_TIMEOUT = 30.0


class GristAPIError(Exception):
    def __init__(self, status_code: int, message: str, details: str | None = None):
        self.status_code = status_code
        self.message = message
        self.details = details
        super().__init__(
            f"Grist API Error ({status_code}): {message}" + (f" - {details}" if details else "")
        )


def check_grist_response(response: httpx.Response) -> None:
    if response.status_code >= 400:
        try:
            error_body = response.json()
            if isinstance(error_body, dict):
                error_msg = error_body.get("error", error_body.get("message", str(error_body)))
            else:
                error_msg = str(error_body)
        except Exception:
            error_msg = response.text or response.reason_phrase

        raise GristAPIError(
            status_code=response.status_code,
            message=f"Request failed: {response.request.method} {response.request.url.path}",
            details=error_msg,
        )


_clients: dict[str, httpx.Client] = {}
_lock = Lock()
logger = logging.getLogger("grist_pool")


def _get_pool_key(server_url: str, api_key: str) -> str:
    key_hash = hash(api_key)
    return f"{server_url}:{key_hash}"


def get_grist_client(server_url: str, api_key: str) -> httpx.Client:
    pool_key = _get_pool_key(server_url, api_key)

    with _lock:
        if pool_key not in _clients:
            limits = httpx.Limits(
                max_connections=POOL_SIZE,
                max_keepalive_connections=POOL_SIZE,
            )
            _clients[pool_key] = httpx.Client(
                base_url=server_url,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                    "User-Agent": HEYM_USER_AGENT,
                },
                limits=limits,
                timeout=CONNECTION_TIMEOUT,
            )
            logger.info("Grist client pool created for: %s", server_url)

    return _clients[pool_key]


def warm_up_pools() -> int:
    from app.db.models import Credential, CredentialType
    from app.db.session import SessionLocal
    from app.services.encryption import decrypt_config

    initialized = 0

    with SessionLocal() as db:
        grist_creds = db.query(Credential).filter(Credential.type == CredentialType.grist).all()

        for cred in grist_creds:
            try:
                config = decrypt_config(cred.encrypted_config)
                server_url = config.get("server_url", "").rstrip("/")
                api_key = config.get("api_key", "")

                if server_url and api_key:
                    client = get_grist_client(server_url, api_key)
                    response = client.get("/api/orgs")
                    response.raise_for_status()
                    initialized += 1
                    logger.info("Grist client pool initialized: %s", server_url)
            except Exception as e:
                logger.warning("Failed to initialize Grist pool for %s: %s", cred.name, e)

    return initialized


def close_all_clients() -> None:
    with _lock:
        for client in _clients.values():
            client.close()
        _clients.clear()
