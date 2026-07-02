from __future__ import annotations

from app.services.node_execution.base import NodeExecutionContext


def execute(ctx: NodeExecutionContext) -> object:
    """Execute the redis node."""
    self = ctx.executor
    node_id = ctx.node_id
    inputs = ctx.inputs
    node_data = ctx.node_data

    from app.services.redis_pool import get_redis_connection

    credential_id = node_data.get("credentialId")
    if not credential_id:
        raise ValueError("Redis node requires a credential")

    operation = node_data.get("redisOperation", "")
    if not operation:
        raise ValueError("Redis node requires an operation")

    key_template = node_data.get("redisKey", "")
    value_template = node_data.get("redisValue", "")
    ttl = node_data.get("redisTtl")

    redis_key = self.evaluate_message_template(key_template, inputs, node_id)

    from app.db.session import SessionLocal
    from app.services.encryption import decrypt_config

    redis_config: dict = {}
    with SessionLocal() as db:
        cred = self._get_accessible_credential(db, credential_id)
        if cred:
            redis_config = decrypt_config(cred.encrypted_config)

    redis_host = redis_config.get("redis_host", "localhost")
    redis_port = int(redis_config.get("redis_port", 6379))
    redis_password = redis_config.get("redis_password", "") or None
    redis_db = int(redis_config.get("redis_db", 0))

    r = get_redis_connection(
        host=redis_host,
        port=redis_port,
        db=redis_db,
        password=redis_password,
    )

    if operation == "set":
        redis_value = self.evaluate_message_template(value_template, inputs, node_id)
        if ttl and int(ttl) > 0:
            r.setex(redis_key, int(ttl), redis_value)
            output = {"success": True, "key": redis_key, "ttl": int(ttl)}
        else:
            r.set(redis_key, redis_value)
            output = {"success": True, "key": redis_key, "ttl": None}
    elif operation == "get":
        value = r.get(redis_key)
        output = {
            "value": value,
            "exists": value is not None,
            "key": redis_key,
        }
    elif operation == "hasKey":
        exists = r.exists(redis_key) > 0
        output = {"exists": exists, "key": redis_key}
    elif operation == "deleteKey":
        deleted = r.delete(redis_key) > 0
        output = {"deleted": deleted, "key": redis_key}
    else:
        raise ValueError(f"Unknown Redis operation: {operation}")
    return output
