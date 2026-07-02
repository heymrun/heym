from __future__ import annotations

from importlib import import_module

from app.services.node_execution.base import NodeExecutionContext


def execute(ctx: NodeExecutionContext) -> object:
    """Execute the supabase node."""
    _workflow_executor = import_module("app.services.workflow_executor")
    _EXECUTION_CONTEXT_INPUT_KEY = _workflow_executor._EXECUTION_CONTEXT_INPUT_KEY  # noqa: N806
    _coerce_boolean = _workflow_executor._coerce_boolean
    self = ctx.executor
    node_id = ctx.node_id
    inputs = ctx.inputs
    node_data = ctx.node_data

    from app.db.session import SessionLocal
    from app.services.encryption import decrypt_config
    from app.services.supabase_service import SupabaseService

    credential_id = node_data.get("credentialId")
    if not credential_id:
        raise ValueError("Supabase node requires a credential")

    supabase_config: dict = {}
    with SessionLocal() as db:
        cred = self._get_accessible_credential(db, credential_id)
        if cred:
            supabase_config = decrypt_config(cred.encrypted_config)

    if not supabase_config:
        raise ValueError("Supabase credential not found or invalid")
    if not str(supabase_config.get("supabase_url", "")).strip():
        raise ValueError("Supabase credential requires supabase_url")
    if not str(supabase_config.get("supabase_key", "")).strip():
        raise ValueError("Supabase credential requires supabase_key")

    operation = str(node_data.get("supabaseOperation", "") or "").strip()
    if not operation:
        raise ValueError("Supabase node requires an operation")

    raw_schema_template = str(node_data.get("supabaseSchema", "") or "").strip()
    raw_schema = (
        self.evaluate_message_template(
            raw_schema_template,
            inputs,
            node_id,
        ).strip()
        if raw_schema_template
        else ""
    )
    schema = raw_schema or str(supabase_config.get("supabase_schema", "public")).strip() or "public"
    table = self.evaluate_message_template(
        str(node_data.get("supabaseTable", "") or ""),
        inputs,
        node_id,
    ).strip()
    if not table:
        raise ValueError("Supabase table is required")

    service = SupabaseService(supabase_config)

    def _resolve_supabase_auto_map_source() -> object:
        upstream_inputs = {
            key: value for key, value in inputs.items() if key != _EXECUTION_CONTEXT_INPUT_KEY
        }
        if not upstream_inputs:
            raise ValueError("Supabase auto-map requires exactly one upstream input object")
        if len(upstream_inputs) != 1:
            raise ValueError("Supabase auto-map requires exactly one upstream input source")
        return next(iter(upstream_inputs.values()))

    def _parse_ignored_fields(field_name: str) -> set[str]:
        raw_value = str(node_data.get(field_name, "") or "").strip()
        if not raw_value:
            return set()
        return {part.strip() for part in raw_value.split(",") if part.strip()}

    if operation == "select":
        columns = (
            self.evaluate_message_template(
                str(node_data.get("supabaseSelectColumns", "*") or "*"),
                inputs,
                node_id,
            ).strip()
            or "*"
        )
        raw_filters = self.evaluate_message_template(
            str(node_data.get("supabaseFilter", "{}") or "{}"),
            inputs,
            node_id,
        )
        filters = SupabaseService.parse_json_object(raw_filters, "supabaseFilter")
        raw_limit = self.evaluate_message_template(
            str(node_data.get("supabaseLimit", "100") or "100"),
            inputs,
            node_id,
        ).strip()
        try:
            limit = int(float(raw_limit or "100"))
        except (TypeError, ValueError):
            limit = 100
        if limit < 0:
            limit = 100
        raw_order_by_template = str(node_data.get("supabaseOrderBy", "") or "").strip()
        raw_order_by = (
            self.evaluate_message_template(
                raw_order_by_template,
                inputs,
                node_id,
            )
            if raw_order_by_template
            else ""
        )
        ascending = _coerce_boolean(node_data.get("supabaseAscending"), default=True)
        output = service.select_rows(
            table,
            schema=schema,
            columns=columns,
            filters=filters,
            limit=limit,
            order_by=raw_order_by,
            ascending=ascending,
        )
    elif operation == "insert":
        input_mode = str(node_data.get("supabaseRowsInputMode", "raw") or "raw").strip()
        if input_mode == "auto":
            rows = SupabaseService.normalize_auto_map_rows(
                _resolve_supabase_auto_map_source(),
                ignored_fields=_parse_ignored_fields("supabaseIgnoredInputFields"),
            )
        else:
            raw_rows = self.evaluate_message_template(
                str(node_data.get("supabaseRows", "[]") or "[]"),
                inputs,
                node_id,
            )
            rows = SupabaseService.parse_json_rows(raw_rows, "supabaseRows")
        output = service.insert_rows(table, rows, schema=schema, upsert=False)
    elif operation == "upsert":
        input_mode = str(node_data.get("supabaseRowsInputMode", "raw") or "raw").strip()
        if input_mode == "auto":
            rows = SupabaseService.normalize_auto_map_rows(
                _resolve_supabase_auto_map_source(),
                ignored_fields=_parse_ignored_fields("supabaseIgnoredInputFields"),
            )
        else:
            raw_rows = self.evaluate_message_template(
                str(node_data.get("supabaseRows", "[]") or "[]"),
                inputs,
                node_id,
            )
            rows = SupabaseService.parse_json_rows(raw_rows, "supabaseRows")
        raw_on_conflict_template = str(node_data.get("supabaseOnConflict", "") or "").strip()
        raw_on_conflict = (
            self.evaluate_message_template(
                raw_on_conflict_template,
                inputs,
                node_id,
            )
            if raw_on_conflict_template
            else ""
        )
        output = service.insert_rows(
            table,
            rows,
            schema=schema,
            upsert=True,
            on_conflict=raw_on_conflict,
        )
    elif operation == "update":
        raw_filters = self.evaluate_message_template(
            str(node_data.get("supabaseFilter", "{}") or "{}"),
            inputs,
            node_id,
        )
        data_input_mode = str(node_data.get("supabaseDataInputMode", "raw") or "raw").strip()
        if data_input_mode == "auto":
            data = SupabaseService.normalize_auto_map_object(
                _resolve_supabase_auto_map_source(),
                ignored_fields=_parse_ignored_fields("supabaseIgnoredInputFields"),
            )
        else:
            raw_data = self.evaluate_message_template(
                str(node_data.get("supabaseData", "{}") or "{}"),
                inputs,
                node_id,
            )
            data = SupabaseService.parse_json_object(raw_data, "supabaseData")
        filters = SupabaseService.parse_json_object(raw_filters, "supabaseFilter")
        output = service.update_rows(table, data, schema=schema, filters=filters)
    elif operation == "delete":
        raw_filters = self.evaluate_message_template(
            str(node_data.get("supabaseFilter", "{}") or "{}"),
            inputs,
            node_id,
        )
        filters = SupabaseService.parse_json_object(raw_filters, "supabaseFilter")
        output = service.delete_rows(table, schema=schema, filters=filters)
    else:
        raise ValueError(f"Unknown Supabase operation: {operation}")
    return output
