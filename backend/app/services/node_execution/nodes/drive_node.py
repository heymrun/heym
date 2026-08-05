from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from importlib import import_module

import httpx

from app.services.node_execution.base import NodeExecutionContext


def execute(ctx: NodeExecutionContext) -> object:
    """Execute the drive node."""
    _workflow_executor = import_module("app.services.workflow_executor")
    _fetch_drive_download_url = _workflow_executor._fetch_drive_download_url
    self = ctx.executor
    node_id = ctx.node_id
    inputs = ctx.inputs
    node_data = ctx.node_data

    import shutil as _shutil

    import bcrypt as _bcrypt

    from app.db.models import FileAccessToken, FileTeamShare, GeneratedFile, Team, TeamMember, User
    from app.db.session import SessionLocal
    from app.services.file_storage import (
        _normalize_storage_filename,
        _safe_storage_path,
        _storage_root,
        build_download_url,
    )

    operation = node_data.get("driveOperation", "")
    if not operation:
        raise ValueError("Drive Node: operation is required")

    owner_id = self.trace_user_id
    if not owner_id:
        raise ValueError("Drive Node: no owner context available")

    if operation not in ("downloadUrl", "getAll", "save"):
        file_id_str = self._resolve_template(node_data.get("driveFileId", ""), inputs, node_id)
        if not file_id_str:
            raise ValueError("Drive Node: fileId is required")
        try:
            file_uuid = uuid.UUID(str(file_id_str).strip())
        except ValueError as exc:
            raise ValueError(f"Drive Node: invalid file ID '{file_id_str}'") from exc

    def _authenticated_download_url(base_url: str, file_id: uuid.UUID) -> str:
        return f"{base_url.rstrip('/')}/api/files/{file_id}/download"

    def _shared_team_count(db: object, file_id: uuid.UUID) -> int:
        return db.query(FileTeamShare).filter(FileTeamShare.file_id == file_id).count()

    def _enable_team_sharing(db: object, file_id: uuid.UUID) -> int:
        team_ids = [
            row[0]
            for row in db.query(TeamMember.team_id).filter(TeamMember.user_id == owner_id).all()
        ]
        if not team_ids:
            return _shared_team_count(db, file_id)

        existing_team_ids = {
            row[0]
            for row in db.query(FileTeamShare.team_id)
            .filter(FileTeamShare.file_id == file_id)
            .all()
        }
        for team_id in team_ids:
            if team_id not in existing_team_ids:
                db.add(FileTeamShare(file_id=file_id, team_id=team_id))
        db.flush()
        return _shared_team_count(db, file_id)

    def _disable_team_sharing(db: object, file_id: uuid.UUID) -> int:
        db.query(FileTeamShare).filter(FileTeamShare.file_id == file_id).delete(
            synchronize_session=False
        )
        db.flush()
        return 0

    def _coerce_shared_file_match(match: object) -> tuple[object, str | None, str | None] | None:
        if match is None:
            return None
        try:
            row, owner_email, team_name = match
        except (TypeError, ValueError):
            return None
        return row, owner_email, team_name

    def _file_output_metadata(
        row: object,
        base_url: str,
        *,
        is_shared: bool = False,
        shared_by: str | None = None,
        shared_by_team: str | None = None,
    ) -> dict:
        default_token = next(
            (
                t
                for t in (getattr(row, "access_tokens", None) or [])
                if getattr(t, "basic_auth_password_hash", None) is None
            ),
            None,
        )
        created_at = getattr(row, "created_at", None)
        metadata = getattr(row, "metadata_json", None) or {}
        return {
            "id": str(row.id),
            "filename": row.filename,
            "mime_type": row.mime_type,
            "size_bytes": row.size_bytes,
            "workflow_id": str(row.workflow_id) if getattr(row, "workflow_id", None) else None,
            "source_node_label": getattr(row, "source_node_label", None),
            "download_url": build_download_url(base_url, default_token.token)
            if default_token
            else "",
            "authenticated_download_url": _authenticated_download_url(base_url, row.id),
            "is_shared": is_shared,
            "shared_by": shared_by,
            "shared_by_team": shared_by_team,
            "shared_with_my_teams": bool(getattr(row, "team_shares", None) or []),
            "metadata": metadata if isinstance(metadata, dict) else {},
            "created_at": (
                created_at.isoformat()
                if hasattr(created_at, "isoformat")
                else str(created_at)
                if created_at is not None
                else None
            ),
        }

    if operation == "save":
        import base64 as _base64
        import mimetypes as _mimetypes
        import secrets as _secrets

        from app.config import settings as _settings

        filename = self._resolve_template(node_data.get("driveFilename", ""), inputs, node_id)
        if not filename or not str(filename).strip():
            raise ValueError("Drive Node: filename is required for save")

        base64_content = self._resolve_template(
            node_data.get("driveBase64Content", ""), inputs, node_id
        )
        if not base64_content or not str(base64_content).strip():
            raise ValueError("Drive Node: base64 content is required for save")

        filename = _normalize_storage_filename(str(filename).strip())
        base64_payload = str(base64_content).strip()
        if base64_payload.startswith("data:"):
            _comma_idx = base64_payload.find(",")
            if _comma_idx == -1:
                raise ValueError("Drive Node: invalid base64 data URL")
            base64_payload = base64_payload[_comma_idx + 1 :].strip()

        try:
            file_bytes = _base64.b64decode(base64_payload, validate=True)
        except Exception as exc:
            raise ValueError("Drive Node: invalid base64 content") from exc

        mime_type = _mimetypes.guess_type(filename)[0] or "application/octet-stream"

        _max_bytes = _settings.file_max_size_mb * 1024 * 1024
        if len(file_bytes) > _max_bytes:
            raise ValueError(
                f"Drive Node: file exceeds size limit ({_settings.file_max_size_mb} MB)"
            )

        with SessionLocal() as db:
            _file_uuid = uuid.uuid4()
            _rel_path = f"{owner_id}/{_file_uuid}/{filename}"
            _abs_path = _safe_storage_path(_rel_path)
            _abs_path.parent.mkdir(parents=True, exist_ok=True)
            _abs_path.write_bytes(file_bytes)

            _row = GeneratedFile(
                id=_file_uuid,
                owner_id=owner_id,
                workflow_id=self.workflow_id,
                filename=filename,
                storage_path=_rel_path,
                mime_type=mime_type,
                size_bytes=len(file_bytes),
                source_node_id=node_id,
                source_node_label=node_data.get("label"),
                metadata_json={},
            )
            db.add(_row)
            db.flush()

            _token_str = _secrets.token_urlsafe(32)
            db.add(
                FileAccessToken(
                    file_id=_file_uuid,
                    token=_token_str,
                    created_by_id=owner_id,
                )
            )
            db.commit()

        base_url = self._base_url
        dl_url = build_download_url(base_url, _token_str)
        output = {
            "status": "success",
            "operation": "save",
            "id": str(_file_uuid),
            "filename": filename,
            "mime_type": mime_type,
            "size_bytes": len(file_bytes),
            "download_url": dl_url,
        }

    elif operation == "downloadUrl":
        import mimetypes as _mimetypes
        import secrets as _secrets
        import urllib.parse as _urllib_parse

        from app.config import settings as _settings

        source_url = self._resolve_template(node_data.get("driveSourceUrl", ""), inputs, node_id)
        if not source_url:
            raise ValueError("Drive Node: source URL is required for downloadUrl")

        try:
            _resp = _fetch_drive_download_url(source_url)
            file_bytes = _resp.content
            content_type = _resp.headers.get("content-type", "application/octet-stream")
            mime_type = content_type.split(";")[0].strip()
            cd = _resp.headers.get("content-disposition", "")
            filename = ""
            if cd:
                for _part in cd.split(";"):
                    _part = _part.strip()
                    if _part.lower().startswith("filename="):
                        filename = _part[len("filename=") :].strip().strip("\"'")
                        break
            if not filename:
                _parsed = _urllib_parse.urlparse(source_url)
                _url_path = _parsed.path.rstrip("/")
                filename = _url_path.split("/")[-1] if _url_path else ""
            if not filename:
                filename = "downloaded_file"
            filename = _normalize_storage_filename(filename)
            if not mime_type or mime_type == "application/octet-stream":
                _guessed = _mimetypes.guess_type(filename)[0]
                if _guessed:
                    mime_type = _guessed
        except httpx.HTTPStatusError as exc:
            raise ValueError(
                f"Drive Node: failed to download URL (HTTP {exc.response.status_code}): {source_url}"
            ) from exc
        except Exception as exc:
            raise ValueError(f"Drive Node: failed to download URL: {exc}") from exc

        _max_bytes = _settings.file_max_size_mb * 1024 * 1024
        if len(file_bytes) > _max_bytes:
            raise ValueError(
                f"Drive Node: downloaded file exceeds size limit ({_settings.file_max_size_mb} MB)"
            )

        with SessionLocal() as db:
            _file_uuid = uuid.uuid4()
            _rel_path = f"{owner_id}/{_file_uuid}/{filename}"
            _abs_path = _safe_storage_path(_rel_path)
            _abs_path.parent.mkdir(parents=True, exist_ok=True)
            _abs_path.write_bytes(file_bytes)

            _row = GeneratedFile(
                id=_file_uuid,
                owner_id=owner_id,
                workflow_id=self.workflow_id,
                filename=filename,
                storage_path=_rel_path,
                mime_type=mime_type,
                size_bytes=len(file_bytes),
                source_node_id=node_id,
                source_node_label=node_data.get("label"),
                metadata_json={},
            )
            db.add(_row)
            db.flush()

            _token_str = _secrets.token_urlsafe(32)
            db.add(
                FileAccessToken(
                    file_id=_file_uuid,
                    token=_token_str,
                    created_by_id=owner_id,
                )
            )
            db.commit()

        base_url = self._base_url
        dl_url = build_download_url(base_url, _token_str)
        output = {
            "status": "success",
            "operation": "downloadUrl",
            "id": str(_file_uuid),
            "filename": filename,
            "mime_type": mime_type,
            "size_bytes": len(file_bytes),
            "download_url": dl_url,
        }

    else:
        with SessionLocal() as db:
            if operation == "getAll":
                owned_query = (
                    db.query(GeneratedFile)
                    .filter(GeneratedFile.owner_id == owner_id)
                    .order_by(GeneratedFile.created_at.desc())
                )
                owned_rows = owned_query.all()
                shared_rows = (
                    db.query(GeneratedFile, User.email, Team.name)
                    .join(FileTeamShare, FileTeamShare.file_id == GeneratedFile.id)
                    .join(TeamMember, TeamMember.team_id == FileTeamShare.team_id)
                    .join(Team, Team.id == FileTeamShare.team_id)
                    .join(User, User.id == GeneratedFile.owner_id)
                    .filter(TeamMember.user_id == owner_id)
                    .order_by(GeneratedFile.created_at.desc())
                    .all()
                )

                response_rows: list[tuple[object, bool, str | None, str | None]] = []
                seen_ids: set[uuid.UUID] = set()
                for row in owned_rows:
                    response_rows.append((row, False, None, None))
                    seen_ids.add(row.id)
                for shared_match in shared_rows:
                    coerced_match = _coerce_shared_file_match(shared_match)
                    if coerced_match is None:
                        continue
                    row, owner_email, team_name = coerced_match
                    if row.id in seen_ids:
                        continue
                    response_rows.append((row, True, owner_email, team_name))
                    seen_ids.add(row.id)

                response_rows.sort(
                    key=lambda item: getattr(
                        item[0],
                        "created_at",
                        datetime.min.replace(tzinfo=timezone.utc),
                    ),
                    reverse=True,
                )
                raw_limit = node_data.get("driveLimit")
                if raw_limit is not None and str(raw_limit).strip() != "":
                    limit = int(raw_limit)
                    if limit > 0:
                        response_rows = response_rows[:limit]
                base_url = self._base_url

                files = [
                    _file_output_metadata(
                        row,
                        base_url,
                        is_shared=is_shared,
                        shared_by=shared_by,
                        shared_by_team=shared_by_team,
                    )
                    for row, is_shared, shared_by, shared_by_team in response_rows
                ]

                output = {
                    "status": "success",
                    "operation": "getAll",
                    "files": files,
                    "count": len(files),
                }

            else:
                read_shared_allowed = operation == "get"
                file_row = (
                    db.query(GeneratedFile)
                    .filter(
                        GeneratedFile.id == file_uuid,
                        GeneratedFile.owner_id == owner_id,
                    )
                    .first()
                )
                is_shared_file = False
                shared_by = None
                shared_by_team = None
                if not file_row and read_shared_allowed:
                    shared_match = (
                        db.query(GeneratedFile, User.email, Team.name)
                        .join(FileTeamShare, FileTeamShare.file_id == GeneratedFile.id)
                        .join(TeamMember, TeamMember.team_id == FileTeamShare.team_id)
                        .join(Team, Team.id == FileTeamShare.team_id)
                        .join(User, User.id == GeneratedFile.owner_id)
                        .filter(GeneratedFile.id == file_uuid, TeamMember.user_id == owner_id)
                        .order_by(Team.name.asc())
                        .first()
                    )
                    coerced_match = _coerce_shared_file_match(shared_match)
                    if coerced_match is not None:
                        file_row, shared_by, shared_by_team = coerced_match
                        is_shared_file = True
                if not file_row:
                    raise ValueError(f"Drive Node: file not found or access denied: {file_uuid}")

            if operation == "shareWithMyTeams":
                shared_team_count = _enable_team_sharing(db, file_uuid)
                db.commit()
                output = {
                    "status": "success",
                    "operation": "shareWithMyTeams",
                    "file_id": str(file_uuid),
                    "filename": file_row.filename,
                    "shared_team_count": shared_team_count,
                }

            elif operation == "unshareWithMyTeams":
                shared_team_count = _disable_team_sharing(db, file_uuid)
                db.commit()
                output = {
                    "status": "success",
                    "operation": "unshareWithMyTeams",
                    "file_id": str(file_uuid),
                    "filename": file_row.filename,
                    "shared_team_count": shared_team_count,
                }

            elif operation == "delete":
                disk_path = _storage_root() / file_row.storage_path
                if disk_path.exists():
                    disk_path.unlink()
                    parent = disk_path.parent
                    if parent.exists() and not any(parent.iterdir()):
                        _shutil.rmtree(parent, ignore_errors=True)
                db.delete(file_row)
                db.commit()
                output = {
                    "status": "success",
                    "operation": "delete",
                    "file_id": str(file_uuid),
                    "filename": file_row.filename,
                }

            elif operation in ("setPassword", "setTtl", "setMaxDownloads"):
                default_token = (
                    db.query(FileAccessToken)
                    .filter(
                        FileAccessToken.file_id == file_uuid,
                        FileAccessToken.basic_auth_password_hash.is_(None),
                    )
                    .first()
                )
                if default_token:
                    db.delete(default_token)
                    db.flush()

                import secrets as _secrets

                token_str = _secrets.token_urlsafe(32)
                pw_hash: str | None = None
                username: str | None = None
                expires_at = None
                max_downloads: int | None = None

                if operation == "setPassword":
                    raw_pw = self._resolve_template(
                        node_data.get("drivePassword", ""), inputs, node_id
                    )
                    if not raw_pw:
                        raise ValueError("Drive Node: password is required for setPassword")
                    username = "file"
                    pw_hash = _bcrypt.hashpw(raw_pw.encode(), _bcrypt.gensalt()).decode()
                elif operation == "setTtl":
                    ttl = node_data.get("driveTtlHours")
                    if ttl is None:
                        raise ValueError("Drive Node: TTL hours is required for setTtl")
                    expires_at = datetime.now(timezone.utc) + timedelta(hours=int(ttl))
                elif operation == "setMaxDownloads":
                    max_dl = node_data.get("driveMaxDownloads")
                    if max_dl is None:
                        raise ValueError(
                            "Drive Node: max downloads is required for setMaxDownloads"
                        )
                    max_downloads = int(max_dl)

                new_token = FileAccessToken(
                    file_id=file_uuid,
                    token=token_str,
                    basic_auth_username=username,
                    basic_auth_password_hash=pw_hash,
                    expires_at=expires_at,
                    max_downloads=max_downloads,
                    created_by_id=owner_id,
                )
                db.add(new_token)
                db.commit()

                base_url = self._base_url
                if pw_hash:
                    dl_url = f"{base_url.rstrip('/')}/api/files/ba/{file_uuid}"
                else:
                    dl_url = build_download_url(base_url, token_str)

                output = {
                    "status": "success",
                    "operation": operation,
                    "file_id": str(file_uuid),
                    "filename": file_row.filename,
                    "download_url": dl_url,
                }

            elif operation == "get":
                import base64 as _base64

                default_token = (
                    db.query(FileAccessToken)
                    .filter(
                        FileAccessToken.file_id == file_uuid,
                        FileAccessToken.basic_auth_password_hash.is_(None),
                    )
                    .first()
                )
                base_url = self._base_url
                dl_url = build_download_url(base_url, default_token.token) if default_token else ""

                output = {
                    "status": "success",
                    "operation": "get",
                    "id": str(file_row.id),
                    "filename": file_row.filename,
                    "mime_type": file_row.mime_type,
                    "size_bytes": file_row.size_bytes,
                    "download_url": dl_url,
                    "authenticated_download_url": _authenticated_download_url(
                        base_url, file_row.id
                    ),
                    "is_shared": is_shared_file,
                    "shared_by": shared_by,
                    "shared_by_team": shared_by_team,
                }

                if node_data.get("driveIncludeBinary"):
                    disk_path = _storage_root() / file_row.storage_path
                    if not disk_path.exists():
                        raise ValueError(f"Drive Node: file not found on disk: {file_row.filename}")
                    file_bytes = disk_path.read_bytes()
                    output["file_base64"] = _base64.b64encode(file_bytes).decode()

            elif operation != "getAll":
                raise ValueError(f"Drive Node: unknown operation '{operation}'")
    return output
