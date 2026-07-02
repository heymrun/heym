from __future__ import annotations

import json
from typing import Any

from app.db.models import CredentialType
from app.db.session import SessionLocal
from app.services.encryption import decrypt_config
from app.services.node_execution.base import NodeExecutionContext
from app.services.sentry_service import SentryService


def execute(ctx: NodeExecutionContext) -> object:
    """Execute the sentry node."""
    self = ctx.executor
    node_id = ctx.node_id
    inputs = ctx.inputs
    node_data = ctx.node_data

    credential_id = node_data.get("credentialId")
    if not credential_id:
        raise ValueError("Sentry node requires a credential")

    sentry_config: dict = {}
    with SessionLocal() as db:
        cred = self._get_accessible_credential(db, credential_id)
        if cred:
            if cred.type != CredentialType.sentry:
                raise ValueError("Sentry node requires a Sentry credential")
            sentry_config = decrypt_config(cred.encrypted_config)
    if not sentry_config:
        raise ValueError("Sentry credential not found or invalid")

    operation = str(node_data.get("sentryOperation", "") or "").strip()
    if not operation:
        raise ValueError("Sentry node requires an operation")

    def _sentry_text(field_name: str, default: str = "") -> str:
        return self.evaluate_nonempty_message_template(
            str(node_data.get(field_name, default) or default),
            inputs,
            node_id,
        ).strip()

    def _required_sentry_text(field_name: str, label: str) -> str:
        value = _sentry_text(field_name)
        if not value:
            raise ValueError(f"Sentry {operation} requires {label}")
        return value

    def _sentry_array(field_name: str, default: str = "[]") -> list[Any]:
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
        try:
            parsed = json.loads(evaluated or "[]")
        except json.JSONDecodeError as exc:
            raise ValueError(f"{field_name} must be valid JSON") from exc
        if not isinstance(parsed, list):
            raise ValueError(f"{field_name} must be a JSON array")
        return parsed

    def _sentry_object(field_name: str, default: str = "{}") -> dict[str, Any]:
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
        try:
            parsed = json.loads(evaluated or "{}")
        except json.JSONDecodeError as exc:
            raise ValueError(f"{field_name} must be valid JSON") from exc
        if not isinstance(parsed, dict):
            raise ValueError(f"{field_name} must be a JSON object")
        return parsed

    def _required_sentry_object(field_name: str) -> dict[str, Any]:
        value = _sentry_object(field_name)
        if not value:
            raise ValueError(f"Sentry {operation} requires a non-empty JSON payload")
        return value

    organization = _sentry_text("sentryOrganizationSlug")
    project = _sentry_text("sentryProjectSlug")
    service = SentryService(sentry_config)
    try:
        if operation == "listOrganizations":
            organizations = service.list_organizations(_sentry_text("sentryLimit", "25"))
            output = {
                "success": True,
                "operation": operation,
                "organizations": organizations,
                "count": len(organizations),
            }
        elif operation == "updateOrganization":
            organization_result = service.update_organization(
                _required_sentry_text("sentryOrganizationSlug", "an organization slug"),
                _required_sentry_object("sentryPayload"),
            )
            output = {
                "success": True,
                "operation": operation,
                "organization": organization_result,
            }
        elif operation == "listProjects":
            organization = organization or _required_sentry_text(
                "sentryOrganizationSlug", "an organization slug"
            )
            projects = service.list_projects(organization, _sentry_text("sentryLimit", "25"))
            output = {
                "success": True,
                "operation": operation,
                "projects": projects,
                "count": len(projects),
            }
        elif operation == "createProject":
            project_result = service.create_project(
                _required_sentry_text("sentryOrganizationSlug", "an organization slug"),
                _required_sentry_text("sentryTeamSlug", "a team slug"),
                _required_sentry_text("sentryName", "a project name"),
                slug=_sentry_text("sentrySlug") or None,
                platform=_sentry_text("sentryPlatform") or None,
            )
            output = {"success": True, "operation": operation, "project": project_result}
        elif operation == "getProject":
            project_result = service.get_project(
                _required_sentry_text("sentryOrganizationSlug", "an organization slug"),
                _required_sentry_text("sentryProjectSlug", "a project slug"),
            )
            output = {"success": True, "operation": operation, "project": project_result}
        elif operation == "updateProject":
            project_result = service.update_project(
                _required_sentry_text("sentryOrganizationSlug", "an organization slug"),
                _required_sentry_text("sentryProjectSlug", "a project slug"),
                _required_sentry_object("sentryPayload"),
            )
            output = {"success": True, "operation": operation, "project": project_result}
        elif operation == "deleteProject":
            project_result = service.delete_project(
                _required_sentry_text("sentryOrganizationSlug", "an organization slug"),
                _required_sentry_text("sentryProjectSlug", "a project slug"),
            )
            output = {"success": True, "operation": operation, "project": project_result}
        elif operation == "listTeams":
            teams = service.list_teams(
                _required_sentry_text("sentryOrganizationSlug", "an organization slug"),
                _sentry_text("sentryLimit", "25"),
            )
            output = {
                "success": True,
                "operation": operation,
                "teams": teams,
                "count": len(teams),
            }
        elif operation == "createTeam":
            team = service.create_team(
                _required_sentry_text("sentryOrganizationSlug", "an organization slug"),
                _required_sentry_text("sentryName", "a team name"),
                slug=_sentry_text("sentrySlug") or None,
            )
            output = {"success": True, "operation": operation, "team": team}
        elif operation == "updateTeam":
            team = service.update_team(
                _required_sentry_text("sentryOrganizationSlug", "an organization slug"),
                _required_sentry_text("sentryTeamSlug", "a team slug"),
                _required_sentry_object("sentryPayload"),
            )
            output = {"success": True, "operation": operation, "team": team}
        elif operation == "deleteTeam":
            team = service.delete_team(
                _required_sentry_text("sentryOrganizationSlug", "an organization slug"),
                _required_sentry_text("sentryTeamSlug", "a team slug"),
            )
            output = {"success": True, "operation": operation, "team": team}
        elif operation == "listIssues":
            issues = service.list_issues(
                _required_sentry_text("sentryOrganizationSlug", "an organization slug"),
                project_slug=project or None,
                query=_sentry_text("sentryQuery") if "sentryQuery" in node_data else None,
                stats_period=_sentry_text("sentryStatsPeriod") or None,
                limit=_sentry_text("sentryLimit", "25"),
            )
            output = {
                "success": True,
                "operation": operation,
                "issues": issues,
                "count": len(issues),
            }
        elif operation == "getIssue":
            issue = service.get_issue(
                _required_sentry_text("sentryOrganizationSlug", "an organization slug"),
                _required_sentry_text("sentryIssueId", "an issue ID"),
            )
            output = {"success": True, "operation": operation, "issue": issue}
        elif operation == "updateIssue":
            issue = service.update_issue(
                _required_sentry_text("sentryOrganizationSlug", "an organization slug"),
                _required_sentry_text("sentryIssueId", "an issue ID"),
                status=_sentry_text("sentryStatus") or None,
                assigned_to=_sentry_text("sentryAssignedTo") or None,
            )
            output = {"success": True, "operation": operation, "issue": issue}
        elif operation == "deleteIssue":
            issue = service.delete_issue(
                _required_sentry_text("sentryOrganizationSlug", "an organization slug"),
                _required_sentry_text("sentryIssueId", "an issue ID"),
            )
            output = {"success": True, "operation": operation, "issue": issue}
        elif operation == "listEvents":
            events = service.list_events(
                _required_sentry_text("sentryOrganizationSlug", "an organization slug"),
                project_slug=_required_sentry_text("sentryProjectSlug", "a project slug"),
                query=_sentry_text("sentryQuery") or None,
                limit=_sentry_text("sentryLimit", "25"),
            )
            output = {
                "success": True,
                "operation": operation,
                "events": events,
                "count": len(events),
            }
        elif operation == "getEvent":
            event = service.get_event(
                _required_sentry_text("sentryOrganizationSlug", "an organization slug"),
                _required_sentry_text("sentryProjectSlug", "a project slug"),
                _required_sentry_text("sentryEventId", "an event ID"),
            )
            output = {"success": True, "operation": operation, "event": event}
        elif operation == "listReleases":
            releases = service.list_releases(
                _required_sentry_text("sentryOrganizationSlug", "an organization slug"),
                _sentry_text("sentryLimit", "25"),
            )
            output = {
                "success": True,
                "operation": operation,
                "releases": releases,
                "count": len(releases),
            }
        elif operation == "getRelease":
            release = service.get_release(
                _required_sentry_text("sentryOrganizationSlug", "an organization slug"),
                _required_sentry_text("sentryReleaseVersion", "a release version"),
            )
            output = {"success": True, "operation": operation, "release": release}
        elif operation == "createRelease":
            refs = _sentry_array("sentryReleaseRefs")
            if any(not isinstance(item, dict) for item in refs):
                raise ValueError("sentryReleaseRefs must contain JSON objects")
            release = service.create_release(
                _required_sentry_text("sentryOrganizationSlug", "an organization slug"),
                _required_sentry_text("sentryReleaseVersion", "a release version"),
                projects=[
                    str(item)
                    for item in _sentry_array("sentryReleaseProjects")
                    if str(item).strip()
                ],
                refs=refs,
            )
            output = {"success": True, "operation": operation, "release": release}
        elif operation == "updateRelease":
            release = service.update_release(
                _required_sentry_text("sentryOrganizationSlug", "an organization slug"),
                _required_sentry_text("sentryReleaseVersion", "a release version"),
                _required_sentry_object("sentryPayload"),
            )
            output = {"success": True, "operation": operation, "release": release}
        elif operation == "deleteRelease":
            release = service.delete_release(
                _required_sentry_text("sentryOrganizationSlug", "an organization slug"),
                _required_sentry_text("sentryReleaseVersion", "a release version"),
            )
            output = {"success": True, "operation": operation, "release": release}
        else:
            raise ValueError(f"Unknown Sentry operation: {operation}")
    finally:
        service.close()

    return output
