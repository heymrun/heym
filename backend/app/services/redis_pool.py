import logging
from threading import Lock
from typing import Optional

import redis

POOL_SIZE = 8

_pools: dict[str, redis.ConnectionPool] = {}
_lock = Lock()
logger = logging.getLogger("redis_pool")


def _get_pool_key(host: str, port: int, db: int, password: Optional[str]) -> str:
    pwd_hash = hash(password) if password else "none"
    return f"{host}:{port}:{db}:{pwd_hash}"


def get_redis_connection(
    host: str = "localhost",
    port: int = 6379,
    db: int = 0,
    password: Optional[str] = None,
) -> redis.Redis:
    pool_key = _get_pool_key(host, port, db, password)

    with _lock:
        if pool_key not in _pools:
            _pools[pool_key] = redis.ConnectionPool(
                host=host,
                port=port,
                db=db,
                password=password,
                max_connections=POOL_SIZE,
                decode_responses=True,
            )

    return redis.Redis(connection_pool=_pools[pool_key])


def warm_up_pools() -> int:
    from app.db.models import Credential, CredentialType
    from app.db.session import SessionLocal
    from app.services.encryption import decrypt_config

    initialized = 0

    with SessionLocal() as db:
        redis_creds = db.query(Credential).filter(Credential.type == CredentialType.redis).all()

        for cred in redis_creds:
            try:
                config = decrypt_config(cred.encrypted_config)
                host = config.get("redis_host", "localhost")
                port = int(config.get("redis_port", 6379))
                password = config.get("redis_password", "") or None
                db_index = int(config.get("redis_db", 0))

                r = get_redis_connection(host=host, port=port, db=db_index, password=password)
                r.ping()
                initialized += 1
                logger.info("Redis pool initialized: %s:%s db=%s", host, port, db_index)
            except Exception as e:
                logger.warning("Failed to initialize Redis pool for %s: %s", cred.name, e)

    return initialized


def close_all_pools() -> None:
    with _lock:
        for pool in _pools.values():
            pool.disconnect()
        _pools.clear()
