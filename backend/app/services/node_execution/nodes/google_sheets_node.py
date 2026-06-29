from __future__ import annotations

from app.services.node_execution.base import NodeExecutionContext


def execute(ctx: NodeExecutionContext) -> object:
    """Execute the googleSheets node."""
    self = ctx.executor
    node_id = ctx.node_id
    inputs = ctx.inputs
    node_data = ctx.node_data

    import json as _json

    from app.db.session import SessionLocal
    from app.services.encryption import decrypt_config
    from app.services.google_sheets_service import GoogleSheetsService

    credential_id = node_data.get("credentialId")
    if not credential_id:
        raise ValueError("Google Sheets node requires a credential")

    gs_config: dict = {}
    with SessionLocal() as db:
        cred = self._get_accessible_credential(db, credential_id)
        if cred:
            gs_config = decrypt_config(cred.encrypted_config)

    if not gs_config:
        raise ValueError("Google Sheets credential not found or invalid")

    operation = node_data.get("gsOperation", "")
    if not operation:
        raise ValueError("Google Sheets node requires an operation")

    raw_id = self.evaluate_message_template(node_data.get("gsSpreadsheetId", ""), inputs, node_id)
    spreadsheet_id = GoogleSheetsService.parse_spreadsheet_id(raw_id)
    sheet_name = self.evaluate_message_template(
        node_data.get("gsSheetName", "Sheet1"), inputs, node_id
    )
    _sr_ev = self.evaluate_message_template(
        str(node_data.get("gsStartRow", "1") or "1"), inputs, node_id
    ).strip()
    try:
        start_row = max(1, int(float(_sr_ev or "1")))
    except (ValueError, TypeError):
        start_row = 1
    _mr_ev = self.evaluate_message_template(
        str(node_data.get("gsMaxRows", "100") or "100"), inputs, node_id
    ).strip()
    try:
        max_rows = int(float(_mr_ev or "0"))
    except (ValueError, TypeError):
        max_rows = 100
    if max_rows < 0:
        max_rows = 0
    _ur_raw = node_data.get("gsUpdateRow")
    if _ur_raw is not None and str(_ur_raw).strip() != "":
        _ur_ev = self.evaluate_message_template(str(_ur_raw), inputs, node_id).strip()
    else:
        _ur_ev = _sr_ev
    try:
        update_row = max(1, int(float(_ur_ev or "1")))
    except (ValueError, TypeError):
        update_row = 1
    if "gsHasHeader" in node_data:
        has_header = bool(node_data.get("gsHasHeader"))
    else:
        has_header = True
    with SessionLocal() as db:
        service = GoogleSheetsService(credential_id, gs_config, db)

        if operation == "readRange":
            output = service.read_range(spreadsheet_id, sheet_name, start_row, max_rows, has_header)
        elif operation == "appendRows":
            raw_values = self.evaluate_message_template(
                node_data.get("gsValues", "[]"), inputs, node_id
            )
            values = _json.loads(raw_values)
            placement = (node_data.get("gsAppendPlacement") or "append").strip().lower()
            if placement == "prepend":
                output = service.prepend_rows(spreadsheet_id, sheet_name, values)
            else:
                output = service.append_rows(spreadsheet_id, sheet_name, values)
        elif operation == "updateRange":
            raw_values = self.evaluate_message_template(
                node_data.get("gsValues", "[]"), inputs, node_id
            )
            values = _json.loads(raw_values)
            output = service.update_range(spreadsheet_id, sheet_name, update_row, values)
        elif operation == "clearRange":
            keep_header = bool(node_data.get("gsKeepHeader", False))
            output = service.clear_range(spreadsheet_id, sheet_name, keep_header=keep_header)
        elif operation == "getSheetInfo":
            output = service.get_sheet_info(spreadsheet_id)
        else:
            raise ValueError(f"Unknown Google Sheets operation: {operation}")
    return output
