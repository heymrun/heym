from __future__ import annotations

import base64
import secrets
import uuid

from app.services.node_execution.base import NodeExecutionContext

_VALID_OPERATIONS = (
    "listFolderFiles",
    "downloadFile",
    "syncToHeymDrive",
    "updateFile",
    "removeFile",
    "removeFolder",
)


def _decode_base64_content(raw: str) -> bytes:
    """Decode a base64 string, accepting `data:` URLs."""
    payload = str(raw).strip()
    if payload.startswith("data:"):
        comma_idx = payload.find(",")
        if comma_idx == -1:
            raise ValueError("Google Drive node: invalid base64 data URL")
        payload = payload[comma_idx + 1 :].strip()
    try:
        return base64.b64decode(payload, validate=True)
    except Exception as exc:
        raise ValueError("Google Drive node: invalid base64 content") from exc


def _sync_to_heym_drive(
    ctx: NodeExecutionContext,
    service,
    file_id: str,
    export_format: str,
    filename_override: str,
    max_bytes: int,
) -> dict:
    """Download a Google Drive file and store it in Heym Drive.

    Mirrors the persistence sequence used by the drive node's ``save`` operation so
    the resulting file behaves identically in the Drive UI and download endpoints.
    """
    from app.db.models import FileAccessToken, GeneratedFile
    from app.db.session import SessionLocal
    from app.services.file_storage import (
        _normalize_storage_filename,
        _safe_storage_path,
        build_download_url,
    )

    self = ctx.executor
    owner_id = self.trace_user_id
    if not owner_id:
        raise ValueError("Google Drive node: no owner context available")

    downloaded = service.download_file(file_id, export_format=export_format, max_bytes=max_bytes)
    content: bytes = downloaded["content"]
    filename = _normalize_storage_filename(filename_override or downloaded["filename"])

    file_uuid = uuid.uuid4()
    rel_path = f"{owner_id}/{file_uuid}/{filename}"
    abs_path = _safe_storage_path(rel_path)
    abs_path.parent.mkdir(parents=True, exist_ok=True)
    abs_path.write_bytes(content)

    token_str = secrets.token_urlsafe(32)
    with SessionLocal() as db:
        db.add(
            GeneratedFile(
                id=file_uuid,
                owner_id=owner_id,
                workflow_id=self.workflow_id,
                filename=filename,
                storage_path=rel_path,
                mime_type=downloaded["mime_type"],
                size_bytes=len(content),
                source_node_id=ctx.node_id,
                source_node_label=ctx.node_data.get("label"),
                metadata_json={"google_file_id": downloaded["id"]},
            )
        )
        db.flush()
        db.add(
            FileAccessToken(
                file_id=file_uuid,
                token=token_str,
                created_by_id=owner_id,
            )
        )
        db.commit()

    return {
        "status": "success",
        "operation": "syncToHeymDrive",
        "id": str(file_uuid),
        "google_file_id": downloaded["id"],
        "filename": filename,
        "mime_type": downloaded["mime_type"],
        "size_bytes": len(content),
        "exported": downloaded["exported"],
        "download_url": build_download_url(self._base_url, token_str),
    }


def execute(ctx: NodeExecutionContext) -> object:
    """Execute the googleDrive node."""
    self = ctx.executor
    node_id = ctx.node_id
    inputs = ctx.inputs
    node_data = ctx.node_data

    from app.config import settings
    from app.db.session import SessionLocal
    from app.services.encryption import decrypt_config
    from app.services.google_drive_service import GoogleDriveService

    credential_id = node_data.get("credentialId")
    if not credential_id:
        raise ValueError("Google Drive node requires a credential")

    operation = node_data.get("gdOperation", "")
    if not operation:
        raise ValueError("Google Drive node requires an operation")
    if operation not in _VALID_OPERATIONS:
        raise ValueError(f"Unknown Google Drive operation: {operation}")

    gd_config: dict = {}
    with SessionLocal() as db:
        cred = self._get_accessible_credential(db, credential_id)
        if cred:
            gd_config = decrypt_config(cred.encrypted_config)

    if not gd_config:
        raise ValueError("Google Drive credential not found or invalid")

    def field(name: str, default: str = "") -> str:
        """Resolve a node field, leaving blank optional fields blank.

        evaluate_message_template returns str(inputs) for an empty template, so a blank
        field routed through it comes back as the literal "{}". Optional fields must
        short-circuit before that.
        """
        raw = node_data.get(name, default)
        text = str(raw) if raw not in (None, "") else str(default)
        if not text.strip():
            return ""
        return self.evaluate_message_template(text, inputs, node_id).strip()

    max_bytes = settings.file_max_size_mb * 1024 * 1024
    permanent = bool(node_data.get("gdPermanentDelete", False))
    export_format = field("gdExportFormat")

    with SessionLocal() as db:
        service = GoogleDriveService(credential_id, gd_config, db)

        if operation == "listFolderFiles":
            raw_max = field("gdMaxResults", "100")
            try:
                max_results = int(float(raw_max or "100"))
            except (ValueError, TypeError):
                max_results = 100
            if max_results < 1:
                max_results = 100
            return service.list_folder_files(
                field("gdFolderId"),
                max_results=max_results,
                query=field("gdQuery"),
                include_trashed=bool(node_data.get("gdIncludeTrashed", False)),
            )

        if operation == "downloadFile":
            file_id = field("gdFileId")
            if not file_id:
                raise ValueError("Google Drive node: file ID is required")
            return service.download_file_base64(
                file_id, export_format=export_format, max_bytes=max_bytes
            )

        if operation == "syncToHeymDrive":
            file_id = field("gdFileId")
            if not file_id:
                raise ValueError("Google Drive node: file ID is required")
            return _sync_to_heym_drive(
                ctx,
                service,
                file_id=file_id,
                export_format=export_format,
                filename_override=field("gdFilename"),
                max_bytes=max_bytes,
            )

        if operation == "updateFile":
            file_id = field("gdFileId")
            if not file_id:
                raise ValueError("Google Drive node: file ID is required")
            raw_content = field("gdBase64Content")
            content = _decode_base64_content(raw_content) if raw_content else None
            return service.update_file(
                file_id,
                content=content,
                new_name=field("gdNewName"),
                new_parent_id=field("gdNewParentId"),
                max_bytes=max_bytes,
            )

        if operation == "removeFile":
            file_id = field("gdFileId")
            if not file_id:
                raise ValueError("Google Drive node: file ID is required")
            return service.remove_file(file_id, permanent=permanent)

        folder_id = field("gdFolderId")
        if not folder_id:
            raise ValueError("Google Drive node: folder ID is required")
        return service.remove_folder(folder_id, permanent=permanent)
