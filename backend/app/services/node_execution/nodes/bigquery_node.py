from __future__ import annotations

from app.services.node_execution.base import NodeExecutionContext


def execute(ctx: NodeExecutionContext) -> object:
    """Execute the bigquery node."""
    self = ctx.executor
    node_id = ctx.node_id
    inputs = ctx.inputs
    node_data = ctx.node_data

    import json as _json

    from app.db.session import SessionLocal
    from app.services.bigquery_service import BigQueryService
    from app.services.encryption import decrypt_config

    credential_id = node_data.get("credentialId")
    if not credential_id:
        raise ValueError("BigQuery node requires a credential")

    bq_config: dict = {}
    with SessionLocal() as db:
        cred = self._get_accessible_credential(db, credential_id)
        if cred:
            bq_config = decrypt_config(cred.encrypted_config)

    if not bq_config:
        raise ValueError("BigQuery credential not found or invalid")

    operation = node_data.get("bqOperation", "")
    if not operation:
        raise ValueError("BigQuery node requires an operation")

    project_id = self.evaluate_message_template(
        node_data.get("bqProjectId", ""), inputs, node_id
    ).strip()

    with SessionLocal() as db:
        service = BigQueryService(credential_id, bq_config, db)

        if operation == "query":
            query = self.evaluate_message_template(node_data.get("bqQuery", ""), inputs, node_id)
            _mr_raw = str(node_data.get("bqMaxResults", "1000") or "1000")
            _mr_ev = self.evaluate_message_template(_mr_raw, inputs, node_id).strip()
            try:
                _mr_int = int(float(_mr_ev or "1000"))
                # 0 means unlimited; negative values fall back to default
                max_results = _mr_int if _mr_int >= 0 else 1000
            except (ValueError, TypeError):
                max_results = 1000
            output = service.run_query(project_id, query, max_results)

        elif operation == "insertRows":
            dataset_id = self.evaluate_message_template(
                node_data.get("bqDatasetId", ""), inputs, node_id
            ).strip()
            table_id = self.evaluate_message_template(
                node_data.get("bqTableId", ""), inputs, node_id
            ).strip()
            input_mode = node_data.get("bqRowsInputMode", "raw")

            if input_mode == "selective":
                mappings = node_data.get("bqMappings", [])
                row: dict = {}
                for mapping in mappings:
                    key = mapping.get("key", "")
                    val = self.evaluate_message_template(
                        str(mapping.get("value", "")), inputs, node_id
                    )
                    if key:
                        row[key] = val
                rows = [row]
            else:
                raw_rows = self.evaluate_message_template(
                    node_data.get("bqRows", "[]"), inputs, node_id
                )
                rows = _json.loads(raw_rows)

            output = service.insert_rows(project_id, dataset_id, table_id, rows)

        else:
            raise ValueError(f"Unknown BigQuery operation: {operation}")
    return output
