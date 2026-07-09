from __future__ import annotations

import json
from base64 import b64decode, b64encode
from importlib import import_module
from mimetypes import guess_type
from typing import Any

from app.services.jira_service import _DEFAULT_SEARCH_JQL, _UNSET
from app.services.node_execution.base import NodeExecutionContext


def execute(ctx: NodeExecutionContext) -> object:
    """Execute the Jira node."""
    _workflow_executor = import_module("app.services.workflow_executor")
    _coerce_boolean = _workflow_executor._coerce_boolean
    self = ctx.executor
    node_id = ctx.node_id
    inputs = ctx.inputs
    node_data = ctx.node_data

    from app.config import settings
    from app.db.models import CredentialType
    from app.db.session import SessionLocal
    from app.services.encryption import decrypt_config
    from app.services.jira_service import JiraService

    credential_id = node_data.get("credentialId")
    if not credential_id:
        raise ValueError("Jira node requires a credential")

    jira_config: dict[str, Any] = {}
    with SessionLocal() as db:
        cred = self._get_accessible_credential(db, credential_id)
        if cred:
            if cred.type != CredentialType.jira:
                raise ValueError("Jira node requires a Jira credential")
            jira_config = decrypt_config(cred.encrypted_config)
    if not jira_config:
        raise ValueError("Jira credential not found or invalid")

    operation = str(node_data.get("jiraOperation", "") or "").strip()
    if not operation:
        raise ValueError("Jira node requires an operation")

    def _field(name: str, default: str = "") -> str:
        raw_value = node_data.get(name, default)
        if raw_value is None or str(raw_value).strip() == "":
            return default
        return self.evaluate_message_template(str(raw_value), inputs, node_id).strip()

    def _limit() -> int:
        try:
            return max(1, min(int(float(_field("jiraLimit", "50") or "50")), 100))
        except (TypeError, ValueError):
            return 50

    def _start_at() -> int:
        try:
            return max(0, int(float(_field("jiraStartAt", "0") or "0")))
        except (TypeError, ValueError):
            return 0

    def _next_page_token() -> str | None:
        token = _field("jiraNextPageToken")
        return token or None

    def _search_fields() -> list[str] | None:
        return _string_list_field("jiraFields")

    def _labels() -> list[str] | None:
        raw_labels = _field("jiraLabels")
        if not raw_labels:
            return None
        try:
            parsed = json.loads(raw_labels)
        except json.JSONDecodeError:
            return [label.strip() for label in raw_labels.split(",") if label.strip()]
        if not isinstance(parsed, list) or not all(isinstance(label, str) for label in parsed):
            raise ValueError("Jira labels must be a JSON array of strings or comma-separated text")
        return parsed

    def _json_object_field(name: str, default: dict[str, Any] | None = None) -> dict[str, Any]:
        raw_value = _field(name)
        if not raw_value:
            return default or {}
        try:
            parsed = json.loads(raw_value)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Jira {name} must be a JSON object") from exc
        if not isinstance(parsed, dict):
            raise ValueError(f"Jira {name} must be a JSON object")
        return parsed

    def _string_list_field(name: str) -> list[str] | None:
        raw_value = _field(name)
        if not raw_value:
            return None
        try:
            parsed = json.loads(raw_value)
        except json.JSONDecodeError:
            return [item.strip() for item in raw_value.split(",") if item.strip()]
        if not isinstance(parsed, list) or not all(isinstance(item, str) for item in parsed):
            raise ValueError(f"Jira {name} must be a JSON array of strings or comma-separated text")
        return parsed

    def _attachment_content() -> bytes:
        base64_content = _field("jiraAttachmentBase64")
        if not base64_content:
            raise ValueError("Jira addAttachment requires base64 content")
        base64_payload = base64_content
        if base64_payload.startswith("data:"):
            comma_index = base64_payload.find(",")
            if comma_index == -1:
                raise ValueError("Jira attachment content must be valid base64 or a data URL")
            base64_payload = base64_payload[comma_index + 1 :].strip()
        try:
            content = b64decode(base64_payload, validate=True)
        except Exception as exc:
            raise ValueError("Jira attachment content must be valid base64") from exc
        max_bytes = settings.file_max_size_mb * 1024 * 1024
        if len(content) > max_bytes:
            raise ValueError(f"Jira attachment exceeds size limit ({settings.file_max_size_mb} MB)")
        return content

    def _with_optional_binary(attachment: dict[str, Any]) -> dict[str, Any]:
        output = dict(attachment)
        if not _coerce_boolean(node_data.get("jiraIncludeBinary"), default=False):
            return output
        content_url = str(attachment.get("content") or "").strip()
        if not content_url:
            raise ValueError("Jira attachment metadata does not include a content URL")
        content = service.download_attachment(content_url)
        output["content_base64"] = b64encode(content).decode("ascii")
        return output

    def _update_field(name: str) -> Any:
        if name not in node_data:
            return _UNSET
        raw_value = node_data.get(name)
        if raw_value is None or str(raw_value).strip() == "":
            return _UNSET
        resolved = self.evaluate_message_template(str(raw_value), inputs, node_id).strip()
        if resolved.lower() == "null":
            return None
        return resolved

    def _update_labels() -> Any:
        if "jiraLabels" not in node_data:
            return _UNSET
        raw_value = node_data.get("jiraLabels")
        if raw_value is None or str(raw_value).strip() == "":
            return _UNSET
        return _labels()

    service = JiraService(jira_config)
    try:
        if operation == "getMyself":
            output = {"success": True, "operation": operation, "user": service.get_myself()}
        elif operation == "listProjects":
            result = service.list_projects(_limit(), _start_at())
            values = result.get("values") if isinstance(result.get("values"), list) else []
            output = {
                "success": True,
                "operation": operation,
                "projects": values,
                "count": len(values),
                "pagination": _pagination(result),
            }
        elif operation == "searchIssues":
            result = service.search_issues(
                _field("jiraJql", _DEFAULT_SEARCH_JQL),
                _limit(),
                next_page_token=_next_page_token(),
                start_at=_start_at(),
                fields=_search_fields(),
            )
            issues = result.get("issues") if isinstance(result.get("issues"), list) else []
            output = {
                "success": True,
                "operation": operation,
                "issues": issues,
                "count": len(issues),
                "pagination": _search_pagination(result, _limit()),
            }
        elif operation == "getIssue":
            issue_key = _field("jiraIssueKey")
            if not issue_key:
                raise ValueError("Jira getIssue requires an issue key or ID")
            issue = service.get_issue(issue_key)
            output = {
                "success": True,
                "operation": operation,
                "issue": issue,
                "key": issue.get("key"),
            }
        elif operation == "createIssue":
            project_key = _field("jiraProjectKey")
            summary = _field("jiraSummary")
            if not project_key or not summary:
                raise ValueError("Jira createIssue requires project key and summary")
            issue = service.create_issue(
                project_key,
                _field("jiraIssueType", "Task") or "Task",
                summary,
                description=_field("jiraDescription") or None,
                assignee_account_id=_field("jiraAssigneeAccountId") or None,
                labels=_labels(),
                issue_type_id=_field("jiraIssueTypeId") or None,
            )
            output = {
                "success": True,
                "operation": operation,
                "issue": issue,
                "key": issue.get("key"),
            }
        elif operation == "updateIssue":
            issue_key = _field("jiraIssueKey")
            if not issue_key:
                raise ValueError("Jira updateIssue requires an issue key or ID")
            issue = service.update_issue(
                issue_key,
                summary=_update_field("jiraSummary"),
                description=_update_field("jiraDescription"),
                assignee_account_id=_update_field("jiraAssigneeAccountId"),
                labels=_update_labels(),
            )
            output = {
                "success": True,
                "operation": operation,
                "issue": issue,
                "key": issue.get("key"),
            }
        elif operation == "deleteIssue":
            issue_key = _field("jiraIssueKey")
            if not issue_key:
                raise ValueError("Jira deleteIssue requires an issue key or ID")
            output = {
                "success": True,
                "operation": operation,
                "deleted": service.delete_issue(issue_key),
            }
        elif operation == "getIssueChangelog":
            issue_key = _field("jiraIssueKey")
            if not issue_key:
                raise ValueError("Jira getIssueChangelog requires an issue key or ID")
            result = service.get_issue_changelog(issue_key, _limit(), _start_at())
            values = result.get("values")
            if not isinstance(values, list):
                values = result.get("histories")
            histories = values if isinstance(values, list) else []
            output = {
                "success": True,
                "operation": operation,
                "changelog": histories,
                "count": len(histories),
                "pagination": _pagination(result),
            }
        elif operation == "notifyIssue":
            issue_key = _field("jiraIssueKey")
            subject = _field("jiraNotifySubject")
            text_body = _field("jiraNotifyTextBody")
            if not issue_key or not subject or not text_body:
                raise ValueError("Jira notifyIssue requires issue key, subject, and text body")
            output = {
                "success": True,
                "operation": operation,
                "notified": service.notify_issue(
                    issue_key,
                    subject=subject,
                    text_body=text_body,
                    html_body=_field("jiraNotifyHtmlBody") or None,
                    to=_json_object_field("jiraNotifyTo", {"assignee": True}),
                ),
            }
        elif operation == "listComments":
            issue_key = _field("jiraIssueKey")
            if not issue_key:
                raise ValueError("Jira listComments requires an issue key or ID")
            result = service.list_comments(issue_key, _limit(), _start_at())
            comments = result.get("comments") if isinstance(result.get("comments"), list) else []
            output = {
                "success": True,
                "operation": operation,
                "comments": comments,
                "count": len(comments),
                "pagination": _pagination(result),
            }
        elif operation == "createComment":
            issue_key = _field("jiraIssueKey")
            body = _field("jiraCommentBody")
            if not issue_key or not body:
                raise ValueError("Jira createComment requires an issue key and comment body")
            output = {
                "success": True,
                "operation": operation,
                "comment": service.create_comment(issue_key, body),
            }
        elif operation == "getComment":
            issue_key = _field("jiraIssueKey")
            comment_id = _field("jiraCommentId")
            if not issue_key or not comment_id:
                raise ValueError("Jira getComment requires an issue key and comment ID")
            output = {
                "success": True,
                "operation": operation,
                "comment": service.get_comment(issue_key, comment_id),
            }
        elif operation == "updateComment":
            issue_key = _field("jiraIssueKey")
            comment_id = _field("jiraCommentId")
            body = _field("jiraCommentBody")
            if not issue_key or not comment_id or not body:
                raise ValueError("Jira updateComment requires an issue key, comment ID, and body")
            output = {
                "success": True,
                "operation": operation,
                "comment": service.update_comment(issue_key, comment_id, body),
            }
        elif operation == "deleteComment":
            issue_key = _field("jiraIssueKey")
            comment_id = _field("jiraCommentId")
            if not issue_key or not comment_id:
                raise ValueError("Jira deleteComment requires an issue key and comment ID")
            output = {
                "success": True,
                "operation": operation,
                "deleted": service.delete_comment(issue_key, comment_id),
            }
        elif operation == "listTransitions":
            issue_key = _field("jiraIssueKey")
            if not issue_key:
                raise ValueError("Jira listTransitions requires an issue key or ID")
            transitions = service.list_transitions(issue_key)
            output = {
                "success": True,
                "operation": operation,
                "transitions": transitions,
                "count": len(transitions),
            }
        elif operation == "transitionIssue":
            issue_key = _field("jiraIssueKey")
            transition_id = _field("jiraTransitionId")
            if not issue_key or not transition_id:
                raise ValueError("Jira transitionIssue requires an issue key and transition ID")
            transition = service.transition_issue(issue_key, transition_id)
            issue = transition.get("issue") if isinstance(transition.get("issue"), dict) else {}
            output = {
                "success": True,
                "operation": operation,
                "transition": {"transitionId": transition.get("transitionId")},
                "issue": issue,
                "key": issue.get("key"),
            }
        elif operation == "addAttachment":
            issue_key = _field("jiraIssueKey")
            filename = _field("jiraAttachmentFilename")
            if not issue_key or not filename:
                raise ValueError("Jira addAttachment requires an issue key and filename")
            mime_type = _field("jiraAttachmentMimeType") or guess_type(filename)[0]
            attachments = service.add_attachment(
                issue_key,
                filename=filename,
                content=_attachment_content(),
                mime_type=mime_type,
            )
            output = {
                "success": True,
                "operation": operation,
                "attachments": attachments,
                "count": len(attachments),
            }
        elif operation == "getAttachment":
            attachment_id = _field("jiraAttachmentId")
            if not attachment_id:
                raise ValueError("Jira getAttachment requires an attachment ID")
            output = {
                "success": True,
                "operation": operation,
                "attachment": _with_optional_binary(service.get_attachment(attachment_id)),
            }
        elif operation == "listAttachments":
            issue_key = _field("jiraIssueKey")
            if not issue_key:
                raise ValueError("Jira listAttachments requires an issue key or ID")
            result = service.list_attachments(issue_key, _limit(), _start_at())
            attachments = [
                _with_optional_binary(attachment)
                for attachment in result.get("attachments", [])
                if isinstance(attachment, dict)
            ]
            output = {
                "success": True,
                "operation": operation,
                "attachments": attachments,
                "count": len(attachments),
                "pagination": _pagination(result),
            }
        elif operation == "deleteAttachment":
            attachment_id = _field("jiraAttachmentId")
            if not attachment_id:
                raise ValueError("Jira deleteAttachment requires an attachment ID")
            output = {
                "success": True,
                "operation": operation,
                "deleted": service.delete_attachment(attachment_id),
            }
        elif operation == "getUser":
            account_id = _field("jiraAccountId")
            if not account_id:
                raise ValueError("Jira getUser requires an account ID")
            output = {"success": True, "operation": operation, "user": service.get_user(account_id)}
        elif operation == "createUser":
            email_address = _field("jiraUserEmail")
            if not email_address:
                raise ValueError("Jira createUser requires an email address")
            output = {
                "success": True,
                "operation": operation,
                "user": service.create_user(
                    email_address,
                    username=_field("jiraUsername") or None,
                    display_name=_field("jiraUserDisplayName") or None,
                    products=_string_list_field("jiraUserProducts"),
                ),
            }
        elif operation == "deleteUser":
            account_id = _field("jiraAccountId")
            if not account_id:
                raise ValueError("Jira deleteUser requires an account ID")
            output = {
                "success": True,
                "operation": operation,
                "deleted": service.delete_user(account_id),
            }
        else:
            raise ValueError(f"Unknown Jira operation: {operation}")
    finally:
        service.close()
    return output


def _pagination(result: dict[str, Any]) -> dict[str, Any]:
    return {
        "startAt": result.get("startAt"),
        "maxResults": result.get("maxResults"),
        "total": result.get("total"),
        "isLast": result.get("isLast"),
    }


def _search_pagination(result: dict[str, Any], limit: int) -> dict[str, Any]:
    if "total" in result or "startAt" in result:
        return _pagination(result)
    return {
        "maxResults": limit,
        "nextPageToken": result.get("nextPageToken"),
        "isLast": result.get("isLast"),
    }
