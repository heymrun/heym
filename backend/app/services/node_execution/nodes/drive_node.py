from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from importlib import import_module

import httpx

from app.services.node_execution.base import NodeExecutionContext


def execute(ctx: NodeExecutionContext) -> object:
    """Execute the drive node."""
    _workflow_executor = import_module("app.services.workflow_executor")
    _convert_image = _workflow_executor._convert_image
    _detect_pandoc_format = _workflow_executor._detect_pandoc_format
    _extract_pdf_text = _workflow_executor._extract_pdf_text
    _fetch_drive_download_url = _workflow_executor._fetch_drive_download_url
    self = ctx.executor
    node_id = ctx.node_id
    inputs = ctx.inputs
    node_data = ctx.node_data

    import shutil as _shutil

    import bcrypt as _bcrypt

    from app.db.models import FileAccessToken, GeneratedFile
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
                query = (
                    db.query(GeneratedFile)
                    .filter(GeneratedFile.owner_id == owner_id)
                    .order_by(GeneratedFile.created_at.desc())
                )
                raw_limit = node_data.get("driveLimit")
                if raw_limit is not None and str(raw_limit).strip() != "":
                    limit = int(raw_limit)
                    if limit > 0:
                        query = query.limit(limit)
                file_rows = query.all()
                base_url = self._base_url

                files = []
                for row in file_rows:
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
                    files.append(
                        {
                            "id": str(row.id),
                            "filename": row.filename,
                            "mime_type": row.mime_type,
                            "size_bytes": row.size_bytes,
                            "workflow_id": (
                                str(row.workflow_id) if getattr(row, "workflow_id", None) else None
                            ),
                            "source_node_label": getattr(row, "source_node_label", None),
                            "download_url": (
                                build_download_url(base_url, default_token.token)
                                if default_token
                                else ""
                            ),
                            "metadata": metadata if isinstance(metadata, dict) else {},
                            "created_at": (
                                created_at.isoformat()
                                if hasattr(created_at, "isoformat")
                                else str(created_at)
                                if created_at is not None
                                else None
                            ),
                        }
                    )

                output = {
                    "status": "success",
                    "operation": "getAll",
                    "files": files,
                    "count": len(files),
                }

            else:
                file_row = (
                    db.query(GeneratedFile)
                    .filter(
                        GeneratedFile.id == file_uuid,
                        GeneratedFile.owner_id == owner_id,
                    )
                    .first()
                )
                if not file_row:
                    raise ValueError(f"Drive Node: file not found or access denied: {file_uuid}")

            if operation == "delete":
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
                }

                if node_data.get("driveIncludeBinary"):
                    disk_path = _storage_root() / file_row.storage_path
                    if not disk_path.exists():
                        raise ValueError(f"Drive Node: file not found on disk: {file_row.filename}")
                    file_bytes = disk_path.read_bytes()
                    output["file_base64"] = _base64.b64encode(file_bytes).decode()

            elif operation == "convertFile":
                import tempfile as _tempfile

                import pypandoc as _pypandoc

                from app.config import settings as _settings

                target_format = node_data.get("driveConvertTargetFormat", "")
                if not target_format:
                    raise ValueError("Drive Node: targetFormat is required for convertFile")

                _image_formats = {"jpg", "jpeg", "png", "bmp", "webp"}
                _doc_formats = {"pdf", "docx", "html", "md", "txt", "csv", "epub"}

                src_mime = file_row.mime_type or ""
                src_filename = file_row.filename or ""
                _image_mimes = {
                    "image/jpeg",
                    "image/jpg",
                    "image/png",
                    "image/bmp",
                    "image/webp",
                }
                is_image_input = src_mime in _image_mimes

                if is_image_input and target_format in _doc_formats:
                    raise ValueError(
                        f"Drive Node: cannot convert image to '{target_format}' — "
                        f"choose an image output format (jpg, png, bmp, webp)"
                    )
                if not is_image_input and target_format in _image_formats:
                    raise ValueError(
                        f"Drive Node: cannot convert document to '{target_format}' — "
                        f"choose a document output format (pdf, docx, html, md, txt)"
                    )

                disk_path = _storage_root() / file_row.storage_path
                if not disk_path.exists():
                    raise ValueError(f"Drive Node: source file not found on disk: {src_filename}")
                src_bytes = disk_path.read_bytes()

                if is_image_input:
                    try:
                        out_bytes, out_mime = _convert_image(src_bytes, target_format)
                    except Exception as exc:
                        raise ValueError(f"Drive Node: conversion failed: {exc}") from exc
                    norm_ext = "jpg" if target_format in ("jpg", "jpeg") else target_format
                    base_name = (
                        src_filename.rsplit(".", 1)[0] if "." in src_filename else src_filename
                    )
                    out_filename = f"{base_name}.{norm_ext}"
                else:
                    _special_inputs = {"application/pdf", "application/json"}
                    pandoc_fmt = _detect_pandoc_format(src_mime, src_filename)
                    if pandoc_fmt is None and src_mime not in _special_inputs:
                        raise ValueError(
                            f"Drive Node: convertFile does not support input format '{src_mime}'"
                        )
                    _all_doc_formats = {
                        "pdf",
                        "docx",
                        "html",
                        "md",
                        "txt",
                        "csv",
                        "epub",
                    }
                    if target_format not in _all_doc_formats:
                        raise ValueError(
                            f"Drive Node: convertFile does not support output format '{target_format}'"
                        )
                    base_name = (
                        src_filename.rsplit(".", 1)[0] if "." in src_filename else src_filename
                    )

                    # CSV output: Python-native (pandoc has no csv output format)
                    if target_format == "csv":
                        import csv as _csv_mod
                        import io as _io_mod
                        import json as _json

                        if src_mime != "application/json":
                            raise ValueError(
                                "Drive Node: CSV output is only supported for JSON array input"
                            )
                        try:
                            _raw = src_bytes.decode("utf-8", errors="replace")
                            _data = _json.loads(_raw)
                            if (
                                not isinstance(_data, list)
                                or not _data
                                or not isinstance(_data[0], dict)
                            ):
                                raise ValueError(
                                    "JSON must be an array of objects for CSV conversion"
                                )
                            _buf = _io_mod.StringIO()
                            _writer = _csv_mod.DictWriter(
                                _buf,
                                fieldnames=list(_data[0].keys()),
                                extrasaction="ignore",
                            )
                            _writer.writeheader()
                            _writer.writerows(_data)
                            out_bytes = _buf.getvalue().encode("utf-8")
                        except Exception as exc:
                            raise ValueError(f"Drive Node: conversion failed: {exc}") from exc
                        out_filename = f"{base_name}.csv"
                        out_mime = "text/csv"
                    else:
                        # Pandoc path for all other document output formats
                        _format_to_ext = {
                            "pdf": "pdf",
                            "docx": "docx",
                            "html": "html",
                            "md": "md",
                            "txt": "txt",
                            "epub": "epub",
                        }
                        _format_to_mime = {
                            "pdf": "application/pdf",
                            "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                            "html": "text/html",
                            "md": "text/markdown",
                            "txt": "text/plain",
                            "epub": "application/epub+zip",
                        }
                        _pandoc_target = {
                            "pdf": "pdf",
                            "docx": "docx",
                            "html": "html",
                            "md": "markdown",
                            "txt": "plain",
                            "epub": "epub",
                        }
                        out_ext = _format_to_ext[target_format]
                        out_filename = f"{base_name}.{out_ext}"
                        out_mime = _format_to_mime[target_format]
                        try:
                            with _tempfile.TemporaryDirectory() as tmpdir:
                                if src_mime == "application/pdf":
                                    extracted = _extract_pdf_text(src_bytes)
                                    src_tmp = f"{tmpdir}/input.txt"
                                    with open(src_tmp, "w", encoding="utf-8") as fh:
                                        fh.write(extracted)
                                    pandoc_fmt = "markdown"
                                elif src_mime == "application/json":
                                    import json as _json

                                    _raw = src_bytes.decode("utf-8", errors="replace")
                                    try:
                                        _data = _json.loads(_raw)
                                        _pretty = _json.dumps(_data, indent=2, ensure_ascii=False)
                                    except _json.JSONDecodeError:
                                        _pretty = _raw
                                    src_tmp = f"{tmpdir}/input.md"
                                    with open(src_tmp, "w", encoding="utf-8") as fh:
                                        fh.write(f"```json\n{_pretty}\n```\n")
                                    pandoc_fmt = "markdown"
                                else:
                                    src_ext = (
                                        src_filename.rsplit(".", 1)[-1]
                                        if "." in src_filename
                                        else "txt"
                                    )
                                    src_tmp = f"{tmpdir}/input.{src_ext}"
                                    with open(src_tmp, "wb") as fh:
                                        fh.write(src_bytes)
                                out_tmp = f"{tmpdir}/output.{out_ext}"
                                extra_args = (
                                    ["--pdf-engine=weasyprint"] if target_format == "pdf" else []
                                )
                                _pypandoc.convert_file(
                                    src_tmp,
                                    _pandoc_target[target_format],
                                    outputfile=out_tmp,
                                    format=pandoc_fmt,
                                    extra_args=extra_args,
                                )
                                with open(out_tmp, "rb") as fh:
                                    out_bytes = fh.read()
                        except Exception as exc:
                            raise ValueError(f"Drive Node: conversion failed: {exc}") from exc

                _max_bytes = _settings.file_max_size_mb * 1024 * 1024
                if len(out_bytes) > _max_bytes:
                    raise ValueError(
                        f"Drive Node: converted file exceeds size limit ({_settings.file_max_size_mb} MB)"
                    )

                import secrets as _secrets

                out_filename = _normalize_storage_filename(out_filename)
                new_uuid = uuid.uuid4()
                rel_path = f"{owner_id}/{new_uuid}/{out_filename}"
                abs_path = _safe_storage_path(rel_path)
                abs_path.parent.mkdir(parents=True, exist_ok=True)
                abs_path.write_bytes(out_bytes)

                new_row = GeneratedFile(
                    id=new_uuid,
                    owner_id=owner_id,
                    workflow_id=self.workflow_id,
                    filename=out_filename,
                    storage_path=rel_path,
                    mime_type=out_mime,
                    size_bytes=len(out_bytes),
                    source_node_id=node_id,
                    source_node_label=node_data.get("label"),
                    metadata_json={},
                )
                db.add(new_row)
                db.flush()

                token_str = _secrets.token_urlsafe(32)
                db.add(
                    FileAccessToken(
                        file_id=new_uuid,
                        token=token_str,
                        created_by_id=owner_id,
                    )
                )
                db.commit()

                base_url = self._base_url
                dl_url = build_download_url(base_url, token_str)
                output = {
                    "status": "success",
                    "operation": "convertFile",
                    "id": str(new_uuid),
                    "filename": out_filename,
                    "mime_type": out_mime,
                    "size_bytes": len(out_bytes),
                    "download_url": dl_url,
                }

            elif operation != "getAll":
                raise ValueError(f"Drive Node: unknown operation '{operation}'")
    return output
