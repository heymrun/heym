from __future__ import annotations

from typing import Any

from app.services.node_execution.base import NodeExecutionContext


def execute(ctx: NodeExecutionContext) -> object:
    """Execute the notion node."""
    self = ctx.executor
    node_id = ctx.node_id
    inputs = ctx.inputs
    node_data = ctx.node_data

    from app.db.session import SessionLocal
    from app.services.encryption import decrypt_config
    from app.services.notion_service import NotionService

    credential_id = node_data.get("credentialId")
    if not credential_id:
        raise ValueError("Notion node requires a credential")

    notion_config: dict = {}
    with SessionLocal() as db:
        cred = self._get_accessible_credential(db, credential_id)
        if cred:
            from app.db.models import CredentialType

            if cred.type != CredentialType.notion:
                raise ValueError("Credential type must be notion")
            notion_config = decrypt_config(cred.encrypted_config)
    if not notion_config:
        raise ValueError("Notion credential not found or invalid")

    operation = str(node_data.get("notionOperation", "") or "").strip()
    if not operation:
        raise ValueError("Notion node requires an operation")

    service = NotionService(notion_config)

    def _notion_text(field_name: str, default: str = "") -> str:
        return self.evaluate_nonempty_message_template(
            str(node_data.get(field_name, default) or default),
            inputs,
            node_id,
        ).strip()

    def _notion_object(field_name: str, default: str = "{}") -> dict[str, Any]:
        raw_value = str(node_data.get(field_name, default) or default).strip()
        if self._is_single_dollar_expression(raw_value):
            resolved = self.resolve_expression(
                raw_value,
                inputs,
                node_id,
                preserve_type=True,
            )
            if not isinstance(resolved, dict):
                raise ValueError(f"{field_name} must resolve to a JSON object")
            return resolved
        evaluated = self.evaluate_message_template(raw_value, inputs, node_id)
        return NotionService.parse_json_object(evaluated, field_name)

    def _notion_array(field_name: str, default: str = "[]") -> list[Any]:
        raw_value = str(node_data.get(field_name, default) or default).strip()
        if self._is_single_dollar_expression(raw_value):
            resolved = self.resolve_expression(
                raw_value,
                inputs,
                node_id,
                preserve_type=True,
            )
            if not isinstance(resolved, list):
                raise ValueError(f"{field_name} must resolve to a JSON array")
            return resolved
        evaluated = self.evaluate_message_template(raw_value, inputs, node_id)
        return NotionService.parse_json_array(evaluated, field_name)

    def _required_notion_text(field_name: str, label: str) -> str:
        value = _notion_text(field_name)
        if not value:
            raise ValueError(f"Notion {operation} requires {label}")
        return value

    def _notion_page_size() -> tuple[int, bool]:
        raw_value = _notion_text("notionPageSize", "100")
        try:
            value = int(float(raw_value or "100"))
        except (TypeError, ValueError):
            value = 100
        return (100 if value == 0 else value, value == 0)

    if operation == "search":
        page_size, fetch_all = _notion_page_size()
        filter_object = _notion_object("notionFilter")
        sort = _notion_object("notionSort")
        output = service.search(
            query=_notion_text("notionQuery"),
            filter_object=filter_object or None,
            sort=sort or None,
            page_size=page_size,
            start_cursor=_notion_text("notionStartCursor") or None,
            fetch_all=fetch_all,
        )
    elif operation == "getPage":
        output = service.retrieve_page(_required_notion_text("notionPageId", "a page ID"))
    elif operation == "createPage":
        properties = _notion_object("notionProperties")
        if not properties:
            raise ValueError("Notion createPage requires properties")
        data_source_id = _notion_text("notionDataSourceId")
        parent_page_id = _notion_text("notionParentPageId")
        if not data_source_id and not parent_page_id:
            raise ValueError("Notion createPage requires a data source ID or parent page ID")
        icon = _notion_object("notionIcon")
        cover = _notion_object("notionCover")
        output = service.create_page(
            properties=properties,
            data_source_id=data_source_id,
            parent_page_id=parent_page_id,
            children=_notion_array("notionChildren"),
            icon=icon or None,
            cover=cover or None,
        )
    elif operation == "updatePage":
        page_id = _required_notion_text("notionPageId", "a page ID")
        properties = _notion_object("notionProperties")
        icon = _notion_object("notionIcon")
        cover = _notion_object("notionCover")
        if not properties and not icon and not cover:
            raise ValueError("Notion updatePage requires properties, icon, or cover")
        output = service.update_page(
            page_id,
            properties=properties or None,
            icon=icon or None,
            cover=cover or None,
        )
    elif operation == "trashPage":
        output = service.update_page(
            _required_notion_text("notionPageId", "a page ID"),
            in_trash=True,
        )
    elif operation == "restorePage":
        output = service.update_page(
            _required_notion_text("notionPageId", "a page ID"),
            in_trash=False,
        )
    elif operation == "createDatabase":
        output = service.create_database(_notion_object("notionDatabase"))
    elif operation == "retrieveDatabase":
        output = service.retrieve_database(
            _required_notion_text("notionDatabaseId", "a database ID")
        )
    elif operation == "updateDatabase":
        database = _notion_object("notionDatabase")
        if not database:
            raise ValueError("Notion updateDatabase requires at least one field")
        output = service.update_database(
            _required_notion_text("notionDatabaseId", "a database ID"),
            database,
        )
    elif operation == "retrieveDataSource":
        output = service.retrieve_data_source(
            _required_notion_text("notionDataSourceId", "a data source ID")
        )
    elif operation == "createDataSource":
        output = service.create_data_source(_notion_object("notionDataSource"))
    elif operation == "updateDataSource":
        data_source = _notion_object("notionDataSource")
        if not data_source:
            raise ValueError("Notion updateDataSource requires at least one field")
        output = service.update_data_source(
            _required_notion_text("notionDataSourceId", "a data source ID"),
            data_source,
        )
    elif operation == "queryDataSource":
        page_size, fetch_all = _notion_page_size()
        output = service.query_data_source(
            _required_notion_text("notionDataSourceId", "a data source ID"),
            filter_object=_notion_object("notionFilter") or None,
            sorts=_notion_array("notionSorts") or None,
            page_size=page_size,
            start_cursor=_notion_text("notionStartCursor") or None,
            fetch_all=fetch_all,
        )
    elif operation == "getBlockChildren":
        page_size, fetch_all = _notion_page_size()
        output = service.retrieve_block_children(
            _required_notion_text("notionBlockId", "a block or page ID"),
            page_size=page_size,
            start_cursor=_notion_text("notionStartCursor") or None,
            fetch_all=fetch_all,
        )
    elif operation == "updateBlock":
        output = service.update_block(
            _required_notion_text("notionBlockId", "a block ID"),
            _notion_object("notionBlock"),
        )
    elif operation == "deleteBlock":
        output = service.delete_block(_required_notion_text("notionBlockId", "a block ID"))
    elif operation == "appendBlocks":
        children = _notion_array("notionChildren")
        if not children:
            raise ValueError("Notion appendBlocks requires child blocks")
        after_block_id = _notion_text("notionAfterBlockId") or None
        output = service.append_block_children(
            _required_notion_text("notionBlockId", "a block or page ID"),
            children,
            position=_notion_text("notionAppendPosition", "end") or "end",
            after=after_block_id,
        )
    else:
        raise ValueError(f"Unknown Notion operation: {operation}")
    service.close()
    output["operation"] = operation
    return output
