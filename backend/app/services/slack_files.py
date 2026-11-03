"""Slack files in and out of Heym Drive, for the Slack node on a `slack_bot` credential.

`downloadFile` stores a message's files in the run's Drive and returns the message's text with
them; `sendFile` shares Drive files the run may open in a channel, a DM or a thread.

The bot token goes to Slack's API and to the download address Slack itself returns from
`files.info`, which must be on files.slack.com. An address taken from the node's input is never
fetched, so an input cannot send the token to another host.
"""

from __future__ import annotations

import json
import re
import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import httpx

from app.services import slack_service as slack
from app.services import ssrf_guard
from app.services.file_sandbox.scope import as_uuid, file_refs
from app.services.node_execution.base import NodeExecutionContext

MAX_FILES = 10
SLACK_FILE_HOST = "files.slack.com"
_FILE_ID = re.compile(r"^F[A-Z0-9]{6,}$")
_FILE_LINK = re.compile(r"/files/[UW][A-Z0-9]+/(F[A-Z0-9]{6,})")
_MESSAGE_LINK = re.compile(r"https?://[^\s/]+/archives/([CDG][A-Z0-9]{6,})/p(\d{10})(\d{6})\S*")
_UNAVAILABLE_MODES = frozenset({"hidden_by_limit", "tombstone"})
_CHUNK_BYTES = 64 * 1024
_SIGN_IN_HINT = (
    "Slack answered with a sign-in page instead of the file. Reinstall the Slack app with the "
    "files:read scope (the Slack Bot manifest in Heym has it)."
)


@dataclass
class _Source:
    """What the Message or files field names: Slack file ids, and the message when it is one."""

    file_ids: list[str] = field(default_factory=list)
    is_message: bool = False
    text: str = ""
    channel: str = ""
    ts: str = ""
    user: str = ""


@dataclass
class _Download:
    slack_file_id: str
    name: str
    mime: str
    path: Path
    size: int


def resolved_value(ctx: NodeExecutionContext, key: str) -> object:
    """A node field resolved; a field that is one `$expression` keeps its list or object."""
    raw = ctx.node_data.get(key)
    if isinstance(raw, (list, dict)):
        return raw
    text = str(raw or "").strip()
    if not text:
        return ""
    if text.startswith("$") and not any(char.isspace() for char in text):
        return ctx.executor.resolve_expression(text, ctx.inputs, ctx.node_id, preserve_type=True)
    return ctx.executor.evaluate_message_template(text, ctx.inputs, ctx.node_id)


def _parsed_json(value: str) -> object:
    stripped = value.strip()
    if not stripped.startswith(("{", "[")):
        return value
    try:
        return json.loads(stripped)
    except ValueError:
        return value


def _file_id_of(item: dict) -> str:
    """A Slack file id from a file object: Heym's own output first, then Slack's `id`."""
    for key in ("slack_file_id", "id"):
        candidate = str(item.get(key) or "").strip()
        if _FILE_ID.match(candidate):
            return candidate
    return ""


def _ids_in_text(text: str) -> list[str]:
    ids = _FILE_LINK.findall(text)
    ids.extend(part for part in re.split(r"[\s,]+", text) if _FILE_ID.match(part))
    return list(dict.fromkeys(ids))


def _fetch_message(token: str, channel: str, ts: str, thread_ts: str = "") -> dict:
    """One message by channel and ts; a reply is found in its thread."""
    if thread_ts and thread_ts != ts:
        method = "conversations.replies"
        params = {"channel": channel, "ts": thread_ts, "oldest": ts, "inclusive": "true"}
        params["limit"] = "10"
    else:
        method = "conversations.history"
        params = {"channel": channel, "latest": ts, "oldest": ts, "inclusive": "true", "limit": "1"}
    body = slack.call_slack(token, method, params, read=True)
    for message in body.get("messages") or []:
        if isinstance(message, dict) and str(message.get("ts") or "") == ts:
            return {**message, "channel": channel}
    raise slack.SlackApiError(f"Slack message {ts} was not found in {channel}")


def _from_message(token: str, message: dict) -> _Source:
    files = message.get("files")
    channel = str(message.get("channel") or "")
    ts = str(message.get("ts") or "")
    if not isinstance(files, list) and channel and ts:
        message = _fetch_message(token, channel, ts, str(message.get("thread_ts") or ""))
        files = message.get("files")
    ids = [_file_id_of(item) for item in files or [] if isinstance(item, dict)]
    return _Source(
        file_ids=list(dict.fromkeys(file_id for file_id in ids if file_id)),
        is_message=True,
        text=str(message.get("text") or ""),
        channel=channel,
        ts=ts,
        user=str(message.get("user") or ""),
    )


def source_of(token: str, value: object) -> _Source:
    """Read the Message or files value: a message, a link, a file, or a list of files."""
    if isinstance(value, str):
        value = _parsed_json(value)
    if isinstance(value, dict):
        if isinstance(value.get("event"), dict):
            value = value["event"]
        if "files" in value or "ts" in value:
            return _from_message(token, value)
        file_id = _file_id_of(value)
        return _Source(file_ids=[file_id] if file_id else [])
    if isinstance(value, list):
        ids: list[str] = []
        for item in value:
            if isinstance(item, (dict, list)):
                ids.extend(source_of(token, item).file_ids)
            else:
                ids.extend(_ids_in_text(str(item or "")))
        return _Source(file_ids=list(dict.fromkeys(ids)))
    text = str(value or "")
    link = _MESSAGE_LINK.search(text)
    if link:
        channel, seconds, micros = link.group(1), link.group(2), link.group(3)
        thread_ts = (parse_qs(urlparse(link.group(0)).query).get("thread_ts") or [""])[0]
        message = _fetch_message(token, channel, f"{seconds}.{micros}", thread_ts)
        return _from_message(token, message)
    return _Source(file_ids=_ids_in_text(text))


def require_slack_file_host(url: str, name: str) -> None:
    """Refuse any address that is not https://files.slack.com, before anything is sent to it."""
    parsed = urlparse(url)
    if (
        parsed.scheme != "https"
        or parsed.hostname != SLACK_FILE_HOST
        or parsed.username
        or parsed.password
        or parsed.port not in (None, 443)
    ):
        raise ValueError(
            f"Slack returned an address outside {SLACK_FILE_HOST} for {name}; it was not used"
        )


def _checked_info(token: str, file_id: str, max_bytes: int, limit_mb: int) -> tuple[str, str, str]:
    """Name, mime type and download address of a file Slack stores and Heym can keep."""
    info = slack.call_slack(token, "files.info", {"file": file_id}, read=True).get("file")
    if not isinstance(info, dict):
        raise slack.SlackApiError(f"Slack returned no details for file {file_id}")
    name = str(info.get("name") or info.get("title") or file_id)
    if info.get("is_external") or info.get("mode") == "external":
        service = str(info.get("external_type") or "another service")
        raise ValueError(f"Slack file {name} is a link to {service}, not a file Slack stores")
    if info.get("mode") in _UNAVAILABLE_MODES:
        raise ValueError(f"Slack file {name} is no longer available in the workspace")
    url = str(info.get("url_private_download") or info.get("url_private") or "")
    if not url:
        raise ValueError(f"Slack file {name} cannot be downloaded")
    if int(info.get("size") or 0) > max_bytes:
        raise ValueError(f"Slack file {name} is larger than the {limit_mb} MB file limit")
    require_slack_file_host(url, name)
    mime = str(info.get("mimetype") or "application/octet-stream")
    return name, mime, url


def _download_to(
    token: str, url: str, name: str, mime: str, target: Path, max_bytes: int, limit_mb: int
) -> int:
    """Stream one file to `target` with the bot token; returns its size in bytes."""
    ssrf_guard.guard_http_url(url, "Slack file URL")
    client = ssrf_guard.get_guarded_http_client()
    size = 0
    try:
        with client.stream("GET", url, headers={"Authorization": f"Bearer {token}"}) as response:
            if 300 <= response.status_code < 400:
                raise ValueError(_SIGN_IN_HINT)
            if response.status_code >= 400:
                raise ValueError(
                    f"Slack file {name} could not be downloaded: HTTP {response.status_code}"
                )
            content_type = response.headers.get("content-type", "").lower()
            if "text/html" in content_type and "html" not in mime.lower():
                raise ValueError(_SIGN_IN_HINT)
            with target.open("wb") as handle:
                for chunk in response.iter_bytes(_CHUNK_BYTES):
                    size += len(chunk)
                    if size > max_bytes:
                        raise ValueError(
                            f"Slack file {name} is larger than the {limit_mb} MB file limit"
                        )
                    handle.write(chunk)
    except httpx.HTTPError as exc:
        raise ValueError(f"Slack file {name} could not be downloaded: {exc}") from exc
    return size


def _remove_stored(paths: list[Path]) -> None:
    for path in paths:
        path.unlink(missing_ok=True)
        try:
            path.parent.rmdir()
        except OSError:
            pass


def _store(ctx: NodeExecutionContext, downloads: list[_Download]) -> list[dict]:
    """Every file into Drive in one transaction; on any failure none of them stays."""
    from app.db.session import SessionLocal
    from app.services.file_storage import build_download_url, get_file_path, store_file_sync

    executor = ctx.executor
    owner_id = getattr(executor, "trace_user_id", None)
    if not owner_id:
        raise ValueError("Slack node: no owner context available to store the files")
    workflow_id = as_uuid(getattr(executor, "workflow_id", None))
    stored: list[dict] = []
    written: list[Path] = []
    with SessionLocal() as db:
        try:
            for item in downloads:
                row, access_token = store_file_sync(
                    db,
                    owner_id=owner_id,
                    file_bytes=item.path.read_bytes(),
                    filename=item.name,
                    mime_type=item.mime,
                    workflow_id=workflow_id,
                    source_node_id=ctx.node_id,
                    source_node_label=ctx.node_label,
                    context="Slack node",
                )
                written.append(get_file_path(row))
                row.metadata_json = {"slack_file_id": item.slack_file_id}
                stored.append(
                    {
                        "id": str(row.id),
                        "slack_file_id": item.slack_file_id,
                        "filename": row.filename,
                        "mime_type": item.mime,
                        "size_bytes": item.size,
                        "download_url": build_download_url(executor._base_url, access_token),
                    }
                )
            db.commit()
        except Exception:
            db.rollback()
            _remove_stored(written)
            raise
    return stored


def download_files(ctx: NodeExecutionContext, token: str) -> dict:
    """Store the files of a Slack message (or the files named) in the run's Drive."""
    from app.config import settings

    source = source_of(token, resolved_value(ctx, "slackFile"))
    if not source.is_message and not source.file_ids:
        raise ValueError(
            "Slack node found no message or file in Message or files. Use a Slack message such "
            "as $slackEvent.event, a message or file link, or a file id (F…)."
        )
    if len(source.file_ids) > MAX_FILES:
        raise ValueError(f"Slack node downloads at most {MAX_FILES} files at a time")
    limit_mb = settings.file_max_size_mb
    max_bytes = limit_mb * 1024 * 1024

    stored: list[dict] = []
    if source.file_ids:
        folder = Path(tempfile.mkdtemp(prefix="heym-slack-"))
        try:
            downloads: list[_Download] = []
            for index, file_id in enumerate(source.file_ids):
                name, mime, url = _checked_info(token, file_id, max_bytes, limit_mb)
                target = folder / str(index)
                size = _download_to(token, url, name, mime, target, max_bytes, limit_mb)
                downloads.append(_Download(file_id, name, mime, target, size))
            stored = _store(ctx, downloads)
        finally:
            shutil.rmtree(folder, ignore_errors=True)

    output: dict = {
        "files": stored,
        "file_ids": [item["id"] for item in stored],
        "count": len(stored),
        "text": source.text,
        "channel": source.channel,
        "ts": source.ts,
        "user": source.user,
    }
    if stored:
        output.update(stored[0])
    return output


def _upload(url: str, name: str, mime: str, content: bytes) -> None:
    """Send one file's bytes to the upload address Slack gave; the address is the credential."""
    ssrf_guard.guard_http_url(url, "Slack upload URL")
    client = ssrf_guard.get_guarded_http_client()
    try:
        response = client.post(url, files={"file": (name, content, mime)})
    except httpx.HTTPError as exc:
        raise ValueError(f"Slack did not accept the upload of {name}: {exc}") from exc
    if response.status_code != 200:
        raise ValueError(f"Slack did not accept the upload of {name}: HTTP {response.status_code}")


def send_files(
    ctx: NodeExecutionContext, token: str, *, channel: str, thread_ts: str, comment: str
) -> dict:
    """Share Drive files the run may open in one Slack message."""
    from app.db.session import SessionLocal
    from app.services.file_sandbox.manifest import FileAccessError, resolve_files

    refs = file_refs(resolved_value(ctx, "slackUploadFile"))
    if not refs:
        raise ValueError("Slack files is required for this operation")
    if len(refs) > MAX_FILES:
        raise ValueError(f"Slack node sends at most {MAX_FILES} files at a time")
    actor_id = ctx.executor._require_actor_user_id("Slack node files")
    try:
        with SessionLocal() as db:
            files = resolve_files(db, actor_id, refs, scope=ctx.executor.file_scope)
    except FileAccessError as exc:
        raise ValueError(f"Slack node: {exc}") from exc

    uploaded: list[dict] = []
    for ref in files:
        if ref.storage_path is None:
            raise ValueError(f"Slack node: file content is missing from storage: {ref.name}")
        content = ref.storage_path.read_bytes()
        ticket = slack.call_slack(
            token,
            "files.getUploadURLExternal",
            {"filename": ref.name, "length": str(len(content))},
            form=True,
        )
        upload_url = str(ticket.get("upload_url") or "")
        slack_file_id = str(ticket.get("file_id") or "")
        require_slack_file_host(upload_url, ref.name)
        _upload(upload_url, ref.name, ref.mime or "application/octet-stream", content)
        uploaded.append({"slack_file_id": slack_file_id, "title": ref.name, "id": str(ref.id)})

    payload: dict = {
        "files": [{"id": item["slack_file_id"], "title": item["title"]} for item in uploaded],
        "channel_id": channel,
    }
    if thread_ts:
        payload["thread_ts"] = thread_ts
    if comment.strip():
        payload["initial_comment"] = comment
    slack.call_slack(token, "files.completeUploadExternal", payload)
    return {"channel": channel, "threadTs": thread_ts, "files": uploaded, "count": len(uploaded)}
