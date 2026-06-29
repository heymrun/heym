from __future__ import annotations

from importlib import import_module
from typing import Any

from app.services.node_execution.base import NodeExecutionContext


def execute(ctx: NodeExecutionContext) -> object:
    """Execute the linear node."""
    _workflow_executor = import_module("app.services.workflow_executor")
    _coerce_boolean = _workflow_executor._coerce_boolean
    self = ctx.executor
    node_id = ctx.node_id
    inputs = ctx.inputs
    node_data = ctx.node_data

    from app.db.models import CredentialType
    from app.db.session import SessionLocal
    from app.services.encryption import decrypt_config
    from app.services.linear_service import LinearService

    credential_id = node_data.get("credentialId")
    if not credential_id:
        raise ValueError("Linear node requires a credential")

    linear_config: dict = {}
    with SessionLocal() as db:
        cred = self._get_accessible_credential(db, credential_id)
        if cred:
            if cred.type != CredentialType.linear:
                raise ValueError("Linear node requires a Linear credential")
            linear_config = decrypt_config(cred.encrypted_config)
    if not linear_config:
        raise ValueError("Linear credential not found or invalid")

    operation = str(node_data.get("linearOperation", "") or "").strip()
    if not operation:
        raise ValueError("Linear node requires an operation")

    def _linear_field(name: str, default: str = "") -> str:
        raw_value = node_data.get(name, default)
        if raw_value is None or str(raw_value).strip() == "":
            return default
        return self.evaluate_message_template(
            str(raw_value),
            inputs,
            node_id,
        ).strip()

    def _linear_limit() -> int:
        raw_limit = _linear_field("linearLimit", "50")
        try:
            return max(1, min(int(float(raw_limit or "50")), 250))
        except (TypeError, ValueError):
            return 50

    def _linear_priority() -> int | None:
        raw_priority = _linear_field("linearPriority")
        if not raw_priority:
            return None
        try:
            priority = int(float(raw_priority))
        except (TypeError, ValueError) as exc:
            raise ValueError("Linear priority must be an integer from 0 to 4") from exc
        if priority < 0 or priority > 4:
            raise ValueError("Linear priority must be an integer from 0 to 4")
        return priority

    from app.services.linear_service import _UNSET

    def _linear_update_field(name: str) -> Any:
        if name not in node_data:
            return _UNSET
        raw_value = node_data.get(name)
        if raw_value is None or str(raw_value).strip() == "":
            return _UNSET
        resolved = self.evaluate_message_template(
            str(raw_value),
            inputs,
            node_id,
        ).strip()
        if resolved.lower() == "null":
            return None
        return resolved

    def _linear_update_priority() -> Any:
        if "linearPriority" not in node_data:
            return _UNSET
        raw_priority = node_data.get("linearPriority")
        if raw_priority is None or str(raw_priority).strip() == "":
            return _UNSET
        return _linear_priority()

    def _linear_after() -> str | None:
        after = _linear_field("linearAfter")
        return after or None

    def _linear_return_all() -> bool:
        return _coerce_boolean(node_data.get("linearReturnAll"), default=False)

    def _linear_list_output(
        result: dict[str, Any],
        field_name: str,
        operation_name: str,
    ) -> dict[str, Any]:
        nodes = result["nodes"]
        return {
            "success": True,
            "operation": operation_name,
            field_name: nodes,
            "count": len(nodes),
            "pageInfo": result["pageInfo"],
        }

    service = LinearService(linear_config, credential_id=str(credential_id))
    try:
        if operation == "getViewer":
            viewer = service.get_viewer()
            output = {
                "success": True,
                "operation": operation,
                "viewer": viewer,
            }
        elif operation == "listTeams":
            output = _linear_list_output(
                service.list_teams(
                    _linear_limit(),
                    after=_linear_after(),
                    fetch_all=_linear_return_all(),
                ),
                "teams",
                operation,
            )
        elif operation == "listProjects":
            output = _linear_list_output(
                service.list_projects(
                    _linear_limit(),
                    after=_linear_after(),
                    fetch_all=_linear_return_all(),
                ),
                "projects",
                operation,
            )
        elif operation == "listIssues":
            output = _linear_list_output(
                service.list_issues(
                    _linear_limit(),
                    team_id=_linear_field("linearTeamId") or None,
                    project_id=_linear_field("linearProjectId") or None,
                    after=_linear_after(),
                    fetch_all=_linear_return_all(),
                ),
                "issues",
                operation,
            )
        elif operation == "listWorkflowStates":
            team_id = _linear_field("linearTeamId")
            if not team_id:
                raise ValueError("Linear listWorkflowStates requires a team ID")
            states = service.list_workflow_states(team_id)
            output = {
                "success": True,
                "operation": operation,
                "states": states,
                "count": len(states),
            }
        elif operation == "listTeamMembers":
            team_id = _linear_field("linearTeamId")
            if not team_id:
                raise ValueError("Linear listTeamMembers requires a team ID")
            output = _linear_list_output(
                service.list_team_members(
                    team_id,
                    _linear_limit(),
                    after=_linear_after(),
                    fetch_all=_linear_return_all(),
                ),
                "members",
                operation,
            )
        elif operation == "getIssue":
            issue_id = _linear_field("linearIssueId")
            if not issue_id:
                raise ValueError("Linear getIssue requires an issue ID or identifier")
            issue = service.get_issue(issue_id)
            output = {
                "success": True,
                "operation": operation,
                "issue": issue,
                "identifier": issue.get("identifier"),
                "url": issue.get("url"),
            }
        elif operation == "createIssue":
            team_id = _linear_field("linearTeamId")
            title = _linear_field("linearTitle")
            if not team_id or not title:
                raise ValueError("Linear createIssue requires team ID and title")
            issue = service.create_issue(
                team_id,
                title,
                description=_linear_field("linearDescription") or None,
                project_id=_linear_field("linearProjectId") or None,
                assignee_id=_linear_field("linearAssigneeId") or None,
                state_id=_linear_field("linearStateId") or None,
                priority=_linear_priority(),
            )
            output = {
                "success": True,
                "operation": operation,
                "issue": issue,
                "identifier": issue.get("identifier"),
                "url": issue.get("url"),
            }
        elif operation == "updateIssue":
            issue_id = _linear_field("linearIssueId")
            if not issue_id:
                raise ValueError("Linear updateIssue requires an issue ID or identifier")
            update_fields = {
                "title": _linear_update_field("linearTitle"),
                "description": _linear_update_field("linearDescription"),
                "team_id": _linear_update_field("linearTeamId"),
                "state_id": _linear_update_field("linearStateId"),
                "project_id": _linear_update_field("linearProjectId"),
                "assignee_id": _linear_update_field("linearAssigneeId"),
                "priority": _linear_update_priority(),
            }
            if not any(value is not _UNSET for value in update_fields.values()):
                raise ValueError("Linear updateIssue requires at least one field to update")
            issue = service.update_issue(
                issue_id,
                **{key: value for key, value in update_fields.items() if value is not _UNSET},
            )
            output = {
                "success": True,
                "operation": operation,
                "issue": issue,
                "identifier": issue.get("identifier"),
                "url": issue.get("url"),
            }
        elif operation == "deleteIssue":
            issue_id = _linear_field("linearIssueId")
            if not issue_id:
                raise ValueError("Linear deleteIssue requires an issue ID or identifier")
            deleted = service.delete_issue(issue_id)
            output = {
                "success": True,
                "operation": operation,
                "deleted": bool(deleted.get("success")),
            }
        elif operation == "addIssueLink":
            issue_id = _linear_field("linearIssueId")
            link_url = _linear_field("linearIssueLinkUrl")
            if not issue_id or not link_url:
                raise ValueError("Linear addIssueLink requires an issue ID and link URL")
            link = service.add_issue_link(issue_id, link_url)
            output = {
                "success": True,
                "operation": operation,
                "link": link,
            }
        elif operation == "createComment":
            issue_id = _linear_field("linearIssueId")
            body = _linear_field("linearCommentBody")
            if not issue_id or not body:
                raise ValueError("Linear createComment requires an issue ID and comment body")
            comment = service.create_comment(
                issue_id,
                body,
                parent_id=_linear_field("linearParentCommentId") or None,
            )
            output = {
                "success": True,
                "operation": operation,
                "comment": comment,
            }
        elif operation == "listComments":
            issue_id = _linear_field("linearIssueId")
            if not issue_id:
                raise ValueError("Linear listComments requires an issue ID or identifier")
            output = _linear_list_output(
                service.list_comments(
                    issue_id,
                    _linear_limit(),
                    after=_linear_after(),
                    fetch_all=_linear_return_all(),
                ),
                "comments",
                operation,
            )
        elif operation == "updateComment":
            comment_id = _linear_field("linearCommentId")
            body = _linear_field("linearCommentBody")
            if not comment_id or not body:
                raise ValueError("Linear updateComment requires a comment ID and comment body")
            comment = service.update_comment(comment_id, body)
            output = {
                "success": True,
                "operation": operation,
                "comment": comment,
            }
        elif operation == "deleteComment":
            comment_id = _linear_field("linearCommentId")
            if not comment_id:
                raise ValueError("Linear deleteComment requires a comment ID")
            deleted = service.delete_comment(comment_id)
            output = {
                "success": True,
                "operation": operation,
                "deleted": bool(deleted.get("success")),
                "entityId": deleted.get("entityId"),
            }
        elif operation == "resolveComment":
            comment_id = _linear_field("linearCommentId")
            if not comment_id:
                raise ValueError("Linear resolveComment requires a comment ID")
            comment = service.resolve_comment(comment_id)
            output = {
                "success": True,
                "operation": operation,
                "comment": comment,
            }
        elif operation == "unresolveComment":
            comment_id = _linear_field("linearCommentId")
            if not comment_id:
                raise ValueError("Linear unresolveComment requires a comment ID")
            comment = service.unresolve_comment(comment_id)
            output = {
                "success": True,
                "operation": operation,
                "comment": comment,
            }
        else:
            raise ValueError(f"Unknown Linear operation: {operation}")
    finally:
        service.close()
    return output
