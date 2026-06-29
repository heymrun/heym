from __future__ import annotations

import json

from app.services.node_execution.base import NodeExecutionContext


def execute(ctx: NodeExecutionContext) -> object:
    """Execute the grist node."""
    self = ctx.executor
    node_id = ctx.node_id
    inputs = ctx.inputs
    node_data = ctx.node_data

    from app.services.grist_pool import check_grist_response, get_grist_client

    credential_id = node_data.get("credentialId")
    if not credential_id:
        raise ValueError("Grist node requires a credential")

    operation = node_data.get("gristOperation", "")
    if not operation:
        raise ValueError("Grist node requires an operation")

    from app.db.session import SessionLocal
    from app.services.encryption import decrypt_config

    grist_config: dict = {}
    with SessionLocal() as db:
        cred = self._get_accessible_credential(db, credential_id)
        if cred:
            grist_config = decrypt_config(cred.encrypted_config)

    if not grist_config:
        raise ValueError("Grist credential not found")

    api_key = grist_config.get("api_key", "")
    server_url = grist_config.get("server_url", "").rstrip("/")

    if not api_key or not server_url:
        raise ValueError("Grist credential requires api_key and server_url")

    client = get_grist_client(server_url, api_key)

    doc_id_template = node_data.get("gristDocId", "")
    doc_id = self.evaluate_message_template(doc_id_template, inputs, node_id)

    table_id_template = node_data.get("gristTableId", "")
    table_id = self.evaluate_message_template(table_id_template, inputs, node_id)

    if operation == "listTables":
        if not doc_id:
            raise ValueError("Grist listTables requires a document ID")
        response = client.get(f"/api/docs/{doc_id}/tables")
        check_grist_response(response)
        data = response.json()
        output = {
            "success": True,
            "operation": "listTables",
            "tables": data.get("tables", []),
        }

    elif operation == "listColumns":
        if not doc_id or not table_id:
            raise ValueError("Grist listColumns requires document ID and table ID")
        response = client.get(f"/api/docs/{doc_id}/tables/{table_id}/columns")
        check_grist_response(response)
        data = response.json()
        output = {
            "success": True,
            "operation": "listColumns",
            "columns": data.get("columns", []),
        }

    elif operation == "getRecord":
        if not doc_id or not table_id:
            raise ValueError("Grist getRecord requires document ID and table ID")
        record_id_template = node_data.get("gristRecordId", "")
        record_id = self.evaluate_message_template(record_id_template, inputs, node_id)
        if not record_id:
            raise ValueError("Grist getRecord requires a record ID")
        filter_param = json.dumps({"id": [int(record_id)]})
        response = client.get(
            f"/api/docs/{doc_id}/tables/{table_id}/records",
            params={"filter": filter_param},
        )
        check_grist_response(response)
        data = response.json()
        records = data.get("records", [])
        output = {
            "success": True,
            "operation": "getRecord",
            "record": records[0] if records else None,
            "found": len(records) > 0,
        }

    elif operation == "getRecords":
        if not doc_id or not table_id:
            raise ValueError("Grist getRecords requires document ID and table ID")

        params: dict = {}
        filter_template = node_data.get("gristFilter", "")
        if filter_template and filter_template.strip() not in ("", "{}"):
            filter_str = self.evaluate_message_template(filter_template, inputs, node_id)
            if filter_str and filter_str.strip() not in ("", "{}"):
                try:
                    filter_obj = json.loads(filter_str)
                    normalized_filter: dict = {}
                    for key, value in filter_obj.items():
                        if isinstance(value, list):
                            normalized_filter[key] = value
                        else:
                            normalized_filter[key] = [value]
                    params["filter"] = json.dumps(normalized_filter, ensure_ascii=False)
                except json.JSONDecodeError:
                    params["filter"] = filter_str

        sort_template = node_data.get("gristSort", "")
        if sort_template:
            sort_str = self.evaluate_message_template(sort_template, inputs, node_id)
            if sort_str:
                params["sort"] = sort_str

        limit = node_data.get("gristLimit")
        if limit:
            params["limit"] = int(limit)

        response = client.get(
            f"/api/docs/{doc_id}/tables/{table_id}/records",
            params=params,
        )
        check_grist_response(response)
        data = response.json()
        records = data.get("records", [])
        output = {
            "success": True,
            "operation": "getRecords",
            "records": records,
            "count": len(records),
        }

    elif operation == "createRecord":
        if not doc_id or not table_id:
            raise ValueError("Grist createRecord requires document ID and table ID")
        record_data_template = node_data.get("gristRecordData", "{}")
        record_data_str = self.evaluate_message_template(record_data_template, inputs, node_id)
        try:
            record_data = (
                json.loads(record_data_str) if isinstance(record_data_str, str) else record_data_str
            )
        except Exception:
            record_data = {}

        payload = {"records": [{"fields": record_data}]}
        response = client.post(
            f"/api/docs/{doc_id}/tables/{table_id}/records",
            json=payload,
        )
        check_grist_response(response)
        data = response.json()
        created_records = data.get("records", [])
        output = {
            "success": True,
            "operation": "createRecord",
            "record": created_records[0] if created_records else None,
            "id": created_records[0].get("id") if created_records else None,
        }

    elif operation == "createRecords":
        if not doc_id or not table_id:
            raise ValueError("Grist createRecords requires document ID and table ID")
        records_data_template = node_data.get("gristRecordsData", "[]")
        records_data_str = self.evaluate_message_template(records_data_template, inputs, node_id)
        try:
            records_data = (
                json.loads(records_data_str)
                if isinstance(records_data_str, str)
                else records_data_str
            )
        except Exception:
            records_data = []

        if not isinstance(records_data, list):
            records_data = [records_data]

        payload = {"records": [{"fields": r} for r in records_data]}
        response = client.post(
            f"/api/docs/{doc_id}/tables/{table_id}/records",
            json=payload,
        )
        check_grist_response(response)
        data = response.json()
        created_records = data.get("records", [])
        output = {
            "success": True,
            "operation": "createRecords",
            "records": created_records,
            "count": len(created_records),
            "ids": [r.get("id") for r in created_records],
        }

    elif operation == "updateRecord":
        if not doc_id or not table_id:
            raise ValueError("Grist updateRecord requires document ID and table ID")
        record_id_template = node_data.get("gristRecordId", "")
        record_id = self.evaluate_message_template(record_id_template, inputs, node_id)
        if not record_id:
            raise ValueError("Grist updateRecord requires a record ID")
        record_data_template = node_data.get("gristRecordData", "{}")
        record_data_str = self.evaluate_message_template(record_data_template, inputs, node_id)
        try:
            record_data = (
                json.loads(record_data_str) if isinstance(record_data_str, str) else record_data_str
            )
        except Exception:
            record_data = {}

        payload = {"records": [{"id": int(record_id), "fields": record_data}]}
        response = client.patch(
            f"/api/docs/{doc_id}/tables/{table_id}/records",
            json=payload,
        )
        check_grist_response(response)
        output = {
            "success": True,
            "operation": "updateRecord",
            "id": int(record_id),
        }

    elif operation == "updateRecords":
        if not doc_id or not table_id:
            raise ValueError("Grist updateRecords requires document ID and table ID")
        records_data_template = node_data.get("gristRecordsData", "[]")
        records_data_str = self.evaluate_message_template(records_data_template, inputs, node_id)
        try:
            records_data = (
                json.loads(records_data_str)
                if isinstance(records_data_str, str)
                else records_data_str
            )
        except Exception:
            records_data = []

        if not isinstance(records_data, list):
            records_data = [records_data]

        payload = {
            "records": [
                {"id": int(r.get("id", 0)), "fields": r.get("fields", r)} for r in records_data
            ]
        }
        response = client.patch(
            f"/api/docs/{doc_id}/tables/{table_id}/records",
            json=payload,
        )
        check_grist_response(response)
        output = {
            "success": True,
            "operation": "updateRecords",
            "count": len(records_data),
        }

    elif operation == "deleteRecord":
        if not doc_id or not table_id:
            raise ValueError("Grist deleteRecord requires document ID and table ID")
        record_ids_template = node_data.get("gristRecordIds", "")
        if not record_ids_template:
            record_id_template = node_data.get("gristRecordId", "")
            record_id = self.evaluate_message_template(record_id_template, inputs, node_id)
            if not record_id:
                raise ValueError("Grist deleteRecord requires record ID(s)")
            record_ids = [int(record_id)]
        else:
            record_ids_str = self.evaluate_message_template(record_ids_template, inputs, node_id)
            try:
                record_ids = (
                    json.loads(record_ids_str)
                    if isinstance(record_ids_str, str)
                    else record_ids_str
                )
                if not isinstance(record_ids, list):
                    record_ids = [int(record_ids)]
                else:
                    record_ids = [int(rid) for rid in record_ids]
            except Exception:
                raise ValueError("Invalid record IDs for deleteRecord")

        response = client.post(
            f"/api/docs/{doc_id}/tables/{table_id}/data/delete",
            json=record_ids,
        )
        check_grist_response(response)
        output = {
            "success": True,
            "operation": "deleteRecord",
            "deleted": record_ids,
            "count": len(record_ids),
        }

    else:
        raise ValueError(f"Unknown Grist operation: {operation}")
    return output
