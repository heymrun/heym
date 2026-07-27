"""Google Drive API client with OAuth2 token management."""

import base64
import re
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from app.services.encryption import encrypt_config

_TOKEN_URL = "https://oauth2.googleapis.com/token"
_DRIVE_BASE = "https://www.googleapis.com/drive/v3"
_DRIVE_UPLOAD_BASE = "https://www.googleapis.com/upload/drive/v3"

FOLDER_MIME = "application/vnd.google-apps.folder"
_NATIVE_MIME_PREFIX = "application/vnd.google-apps."

# Drive caps pageSize at 1000.
_MAX_PAGE_SIZE = 1000

_ID_PATTERNS = (
    re.compile(r"/(?:file|document|spreadsheets|presentation)/d/([a-zA-Z0-9_-]+)"),
    re.compile(r"/folders/([a-zA-Z0-9_-]+)"),
    re.compile(r"[?&]id=([a-zA-Z0-9_-]+)"),
)

# Export targets for Google-native documents, which have no downloadable bytes.
EXPORT_FORMATS: dict[str, tuple[str, str]] = {
    "pdf": ("application/pdf", ".pdf"),
    "docx": (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ".docx",
    ),
    "xlsx": (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ".xlsx",
    ),
    "pptx": (
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        ".pptx",
    ),
    "csv": ("text/csv", ".csv"),
    "txt": ("text/plain", ".txt"),
}

_DEFAULT_EXPORT_BY_NATIVE_MIME: dict[str, str] = {
    "application/vnd.google-apps.document": "pdf",
    "application/vnd.google-apps.spreadsheet": "xlsx",
    "application/vnd.google-apps.presentation": "pptx",
}


def parse_drive_id(id_or_url: str) -> str:
    """Return the Drive file/folder ID from a full URL or a bare ID string."""
    value = str(id_or_url or "").strip()
    for pattern in _ID_PATTERNS:
        match = pattern.search(value)
        if match:
            return match.group(1)
    return value


def is_native_google_file(mime_type: str) -> bool:
    """Return True for Google Docs/Sheets/Slides, which must be exported, not downloaded."""
    return str(mime_type or "").startswith(_NATIVE_MIME_PREFIX)


class GoogleDriveService:
    """Sync Google Drive v3 client.

    Manages token refresh and all Drive operations used by the googleDrive node.
    Uses sync httpx + a sync DB session to match the existing executor pattern.
    """

    def __init__(self, credential_id: str, config: dict, db) -> None:
        """Initialise with decrypted credential config and an open sync DB session."""
        self._credential_id = credential_id
        self._config = dict(config)
        self._db = db

    def _is_token_expired(self) -> bool:
        """Return True if the access token expires within 60 seconds."""
        expiry_str = self._config.get("token_expiry", "")
        if not expiry_str:
            return True
        try:
            expiry = datetime.fromisoformat(expiry_str)
            if expiry.tzinfo is None:
                expiry = expiry.replace(tzinfo=timezone.utc)
            return datetime.now(timezone.utc) >= expiry - timedelta(seconds=60)
        except ValueError:
            return True

    def _refresh_token(self) -> None:
        """Exchange the refresh token for a new access token and persist to DB."""
        resp = httpx.post(
            _TOKEN_URL,
            data={
                "grant_type": "refresh_token",
                "refresh_token": self._config["refresh_token"],
                "client_id": self._config["client_id"],
                "client_secret": self._config["client_secret"],
            },
        )
        resp.raise_for_status()
        data = resp.json()
        self._config["access_token"] = data["access_token"]
        self._config["token_expiry"] = (
            datetime.now(timezone.utc) + timedelta(seconds=data["expires_in"])
        ).isoformat()

        from app.db.models import Credential

        cred = self._db.query(Credential).filter(Credential.id == self._credential_id).first()
        if cred:
            cred.encrypted_config = encrypt_config(self._config)
            self._db.commit()

    def _get_valid_token(self) -> str:
        """Return a valid access token, refreshing if necessary."""
        if self._is_token_expired():
            self._refresh_token()
        token = str(self._config.get("access_token") or "").strip()
        if not token:
            # Without this, httpx sends "Bearer " and Google answers with an opaque
            # "unregistered callers" error instead of anything actionable.
            raise ValueError(
                "Google Drive node: credential has no access token — reconnect it in "
                "Dashboard → Credentials"
            )
        return token

    def _auth_headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._get_valid_token()}"}

    def _raise_for_drive_error(self, resp: httpx.Response, file_id: str) -> None:
        """Translate Drive API failures into actionable node errors."""
        if resp.status_code < 400:
            return
        if resp.status_code == 404:
            raise ValueError(
                f"Google Drive node: file '{file_id}' not found or not accessible "
                "with this credential"
            )
        if resp.status_code == 401:
            raise ValueError("Google Drive node: credential is no longer authorized, reconnect it")
        try:
            detail = resp.json().get("error", {}).get("message", "")
        except Exception:
            detail = resp.text[:200]
        raise ValueError(f"Google Drive node: Drive API error {resp.status_code}: {detail}")

    def list_folder_files(
        self,
        folder_id: str,
        max_results: int = 100,
        query: str = "",
        include_trashed: bool = False,
    ) -> dict:
        """List files inside a folder. Empty folder_id lists the Drive root."""
        target = parse_drive_id(folder_id) or "root"
        clauses = [f"'{target}' in parents"]
        if not include_trashed:
            clauses.append("trashed = false")
        extra = str(query or "").strip()
        if extra:
            clauses.append(f"({extra})")

        files: list[dict[str, Any]] = []
        page_token = ""
        while len(files) < max_results:
            remaining = max_results - len(files)
            params: dict[str, Any] = {
                "q": " and ".join(clauses),
                "pageSize": min(remaining, _MAX_PAGE_SIZE),
                "fields": (
                    "nextPageToken, files(id, name, mimeType, size, modifiedTime, webViewLink)"
                ),
                "supportsAllDrives": True,
                "includeItemsFromAllDrives": True,
            }
            if page_token:
                params["pageToken"] = page_token

            resp = httpx.get(f"{_DRIVE_BASE}/files", headers=self._auth_headers(), params=params)
            self._raise_for_drive_error(resp, target)
            data = resp.json()

            for entry in data.get("files", []):
                raw_size = entry.get("size")
                files.append(
                    {
                        "id": entry.get("id", ""),
                        "name": entry.get("name", ""),
                        "mime_type": entry.get("mimeType", ""),
                        # Folders and Google-native files report no size.
                        "size_bytes": int(raw_size) if raw_size is not None else None,
                        "modified_time": entry.get("modifiedTime", ""),
                        "web_view_link": entry.get("webViewLink", ""),
                        "is_folder": entry.get("mimeType", "") == FOLDER_MIME,
                    }
                )

            page_token = data.get("nextPageToken", "")
            if not page_token:
                break

        files = files[:max_results]
        return {
            "status": "success",
            "operation": "listFolderFiles",
            "folder_id": target,
            "count": len(files),
            "files": files,
        }

    def get_file_metadata(self, file_id: str) -> dict:
        """Fetch id, name, mimeType, size, and parents for a file."""
        target = parse_drive_id(file_id)
        if not target:
            raise ValueError("Google Drive node: file ID is required")
        resp = httpx.get(
            f"{_DRIVE_BASE}/files/{target}",
            headers=self._auth_headers(),
            params={"fields": "id, name, mimeType, size, parents", "supportsAllDrives": True},
        )
        self._raise_for_drive_error(resp, target)
        return resp.json()

    def _resolve_export(self, mime_type: str, export_format: str) -> tuple[str, str, str]:
        """Return (format_key, export_mime, extension) for a Google-native file."""
        key = str(export_format or "").strip().lower()
        if not key:
            key = _DEFAULT_EXPORT_BY_NATIVE_MIME.get(mime_type, "pdf")
        if key not in EXPORT_FORMATS:
            supported = ", ".join(sorted(EXPORT_FORMATS))
            raise ValueError(
                f"Google Drive node: unsupported export format '{key}'. Supported: {supported}"
            )
        export_mime, extension = EXPORT_FORMATS[key]
        return key, export_mime, extension

    def download_file(
        self,
        file_id: str,
        export_format: str = "",
        max_bytes: int | None = None,
    ) -> dict:
        """Download a file's bytes, exporting Google-native documents automatically.

        Returns a dict with raw ``content`` bytes; callers decide how to encode it.
        """
        meta = self.get_file_metadata(file_id)
        target = meta.get("id", parse_drive_id(file_id))
        mime_type = meta.get("mimeType", "")
        filename = meta.get("name", target)

        if mime_type == FOLDER_MIME:
            raise ValueError(
                f"Google Drive node: '{filename}' is a folder and cannot be downloaded"
            )

        format_key: str | None
        if is_native_google_file(mime_type):
            format_key, export_mime, extension = self._resolve_export(mime_type, export_format)
            resp = httpx.get(
                f"{_DRIVE_BASE}/files/{target}/export",
                headers=self._auth_headers(),
                params={"mimeType": export_mime, "supportsAllDrives": True},
            )
            self._raise_for_drive_error(resp, target)
            content = resp.content
            if not filename.lower().endswith(extension):
                filename = f"{filename}{extension}"
            out_mime = export_mime
            exported = True
        else:
            resp = httpx.get(
                f"{_DRIVE_BASE}/files/{target}",
                headers=self._auth_headers(),
                params={"alt": "media", "supportsAllDrives": True},
            )
            self._raise_for_drive_error(resp, target)
            content = resp.content
            out_mime = mime_type
            format_key = None
            exported = False

        if max_bytes is not None and len(content) > max_bytes:
            raise ValueError(
                f"Google Drive node: file exceeds size limit ({max_bytes // (1024 * 1024)} MB)"
            )

        return {
            "id": target,
            "filename": filename,
            "mime_type": out_mime,
            "size_bytes": len(content),
            "exported": exported,
            "export_format": format_key,
            "content": content,
        }

    def download_file_base64(
        self,
        file_id: str,
        export_format: str = "",
        max_bytes: int | None = None,
    ) -> dict:
        """Node-facing download: same as download_file but base64-encoded."""
        result = self.download_file(file_id, export_format=export_format, max_bytes=max_bytes)
        content = result.pop("content")
        return {
            "status": "success",
            "operation": "downloadFile",
            **result,
            "content_base64": base64.b64encode(content).decode("ascii"),
        }

    def update_file(
        self,
        file_id: str,
        content: bytes | None = None,
        new_name: str = "",
        new_parent_id: str = "",
        max_bytes: int | None = None,
    ) -> dict:
        """Update a file's content, name, and/or parent folder.

        Blank arguments are left untouched — this is an update, not a replace.
        """
        name = str(new_name or "").strip()
        parent = parse_drive_id(new_parent_id) if str(new_parent_id or "").strip() else ""
        if content is None and not name and not parent:
            raise ValueError(
                "Google Drive node: updateFile requires content, a new name, or a new parent"
            )
        if content is not None and max_bytes is not None and len(content) > max_bytes:
            raise ValueError(
                f"Google Drive node: content exceeds size limit ({max_bytes // (1024 * 1024)} MB)"
            )

        meta = self.get_file_metadata(file_id)
        target = meta.get("id", parse_drive_id(file_id))
        updated: list[str] = []
        latest = meta

        if content is not None:
            resp = httpx.patch(
                f"{_DRIVE_UPLOAD_BASE}/files/{target}",
                headers={
                    **self._auth_headers(),
                    "Content-Type": meta.get("mimeType", "application/octet-stream"),
                },
                params={"uploadType": "media", "supportsAllDrives": True},
                content=content,
            )
            self._raise_for_drive_error(resp, target)
            latest = resp.json()
            updated.append("content")

        if name or parent:
            body: dict[str, Any] = {}
            params: dict[str, Any] = {
                "fields": "id, name, mimeType, size, modifiedTime",
                "supportsAllDrives": True,
            }
            if name:
                body["name"] = name
                updated.append("name")
            if parent:
                params["addParents"] = parent
                params["removeParents"] = ",".join(meta.get("parents", []) or [])
                updated.append("parent")

            resp = httpx.patch(
                f"{_DRIVE_BASE}/files/{target}",
                headers=self._auth_headers(),
                params=params,
                json=body,
            )
            self._raise_for_drive_error(resp, target)
            latest = resp.json()

        raw_size = latest.get("size")
        return {
            "status": "success",
            "operation": "updateFile",
            "id": target,
            "name": latest.get("name", meta.get("name", "")),
            "mime_type": latest.get("mimeType", meta.get("mimeType", "")),
            "size_bytes": int(raw_size) if raw_size is not None else None,
            "modified_time": latest.get("modifiedTime", ""),
            "updated": updated,
        }

    def _remove(self, file_id: str, permanent: bool, operation: str) -> dict:
        """Trash or permanently delete a Drive item."""
        meta = self.get_file_metadata(file_id)
        target = meta.get("id", parse_drive_id(file_id))
        name = meta.get("name", "")

        if permanent:
            resp = httpx.delete(
                f"{_DRIVE_BASE}/files/{target}",
                headers=self._auth_headers(),
                params={"supportsAllDrives": True},
            )
            self._raise_for_drive_error(resp, target)
            mode = "permanent"
        else:
            resp = httpx.patch(
                f"{_DRIVE_BASE}/files/{target}",
                headers=self._auth_headers(),
                params={"fields": "id, name", "supportsAllDrives": True},
                json={"trashed": True},
            )
            self._raise_for_drive_error(resp, target)
            mode = "trashed"

        return {
            "status": "success",
            "operation": operation,
            "id": target,
            "name": name,
            "deleted": mode,
        }

    def remove_file(self, file_id: str, permanent: bool = False) -> dict:
        """Trash (default) or permanently delete a file. Refuses folders."""
        meta = self.get_file_metadata(file_id)
        if meta.get("mimeType") == FOLDER_MIME:
            raise ValueError(
                f"Google Drive node: '{meta.get('name', file_id)}' is a folder — "
                "use removeFolder instead"
            )
        return self._remove(file_id, permanent, "removeFile")

    def remove_folder(self, folder_id: str, permanent: bool = False) -> dict:
        """Trash (default) or permanently delete a folder and its contents. Refuses files."""
        meta = self.get_file_metadata(folder_id)
        if meta.get("mimeType") != FOLDER_MIME:
            raise ValueError(
                f"Google Drive node: '{meta.get('name', folder_id)}' is not a folder — "
                "use removeFile instead"
            )
        return self._remove(folder_id, permanent, "removeFolder")
