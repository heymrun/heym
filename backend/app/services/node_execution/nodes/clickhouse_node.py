from __future__ import annotations

from app.services.node_execution.base import NodeExecutionContext


def execute(ctx: NodeExecutionContext) -> object:
    """Execute the clickhouse node."""
    self = ctx.executor
    node_id = ctx.node_id
    inputs = ctx.inputs
    node_data = ctx.node_data

    import json as _json

    from app.db.session import SessionLocal
    from app.services.clickhouse_service import ClickHouseService
    from app.services.encryption import decrypt_config

    credential_id = node_data.get("credentialId")
    if not credential_id:
        raise ValueError("ClickHouse node requires a credential")

    ch_config: dict = {}
    with SessionLocal() as db:
        cred = self._get_accessible_credential(db, credential_id)
        if cred:
            ch_config = decrypt_config(cred.encrypted_config)
    if not ch_config:
        raise ValueError("ClickHouse credential not found or invalid")

    operation = str(node_data.get("clickhouseOperation", "") or "").strip()
    if not operation:
        raise ValueError("ClickHouse node requires an operation")

    service = ClickHouseService(ch_config)

    def _resolve(field: str, default: str = "") -> str:
        return self.evaluate_message_template(
            str(node_data.get(field, default) or default), inputs, node_id
        ).strip()

    def _resolve_filters() -> dict:
        raw = self.evaluate_message_template(
            str(node_data.get("clickhouseFilter", "{}") or "{}"), inputs, node_id
        )
        parsed = _json.loads(raw or "{}")
        if not isinstance(parsed, dict):
            raise ValueError("clickhouseFilter must be a JSON object")
        return parsed

    def _resolve_limit(default: int = 100) -> int:
        raw = _resolve("clickhouseLimit", str(default))
        try:
            return int(float(raw or default))
        except (TypeError, ValueError):
            return default

    def _resolve_rows() -> list:
        input_mode = str(node_data.get("clickhouseInputMode", "raw") or "raw").strip()
        if input_mode == "selective":
            mappings = node_data.get("clickhouseMappings", []) or []
            row: dict = {}
            for mapping in mappings:
                key = str(mapping.get("key", "") or "")
                if not key:
                    continue
                row[key] = self.evaluate_message_template(
                    str(mapping.get("value", "")), inputs, node_id
                )
            return [row]
        raw = self.evaluate_message_template(
            str(node_data.get("clickhouseData", "[]") or "[]"), inputs, node_id
        )
        parsed = _json.loads(raw or "[]")
        if isinstance(parsed, dict):
            return [parsed]
        if not isinstance(parsed, list):
            raise ValueError("clickhouseData must be a JSON array or object")
        return parsed

    if operation == "query":
        sql = self.evaluate_message_template(
            str(node_data.get("clickhouseQuery", "") or ""), inputs, node_id
        ).strip()
        return service.query(sql)
    if operation == "find":
        return service.find(
            _resolve("clickhouseTable"),
            filters=_resolve_filters(),
            limit=_resolve_limit(),
            sort=_resolve("clickhouseSort"),
        )
    if operation == "getAll":
        return service.get_all(_resolve("clickhouseTable"), limit=_resolve_limit())
    if operation == "count":
        return service.count(_resolve("clickhouseTable"), filters=_resolve_filters())
    if operation == "getById":
        return service.get_by_id(_resolve("clickhouseTable"), _resolve("clickhouseRowId"))
    if operation == "insert":
        return service.insert(_resolve("clickhouseTable"), _resolve_rows())
    if operation == "upsert":
        return service.upsert(_resolve("clickhouseTable"), _resolve_rows())
    if operation == "update":
        raw_data = self.evaluate_message_template(
            str(node_data.get("clickhouseData", "{}") or "{}"), inputs, node_id
        )
        data = _json.loads(raw_data or "{}")
        if not isinstance(data, dict):
            raise ValueError("clickhouseData must be a JSON object for update")
        return service.update(_resolve("clickhouseTable"), data=data, filters=_resolve_filters())
    if operation == "remove":
        return service.remove(_resolve("clickhouseTable"), filters=_resolve_filters())
    raise ValueError(f"Unknown ClickHouse operation: {operation}")
