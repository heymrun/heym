from __future__ import annotations

from importlib import import_module

from app.services.node_execution.base import NodeExecutionContext


def execute(ctx: NodeExecutionContext) -> object:
    """Execute the github node."""
    _workflow_executor = import_module("app.services.workflow_executor")
    _coerce_boolean = _workflow_executor._coerce_boolean
    self = ctx.executor
    node_id = ctx.node_id
    inputs = ctx.inputs
    node_data = ctx.node_data

    import json as _json

    from app.db.models import CredentialType
    from app.db.session import SessionLocal
    from app.services.encryption import decrypt_config
    from app.services.github_service import GitHubService

    credential_id = node_data.get("credentialId")
    if not credential_id:
        raise ValueError("GitHub node requires a credential")

    github_config: dict = {}
    with SessionLocal() as db:
        cred = self._get_accessible_credential(db, credential_id)
        if cred:
            if cred.type != CredentialType.github:
                raise ValueError("GitHub node requires a GitHub credential")
            github_config = decrypt_config(cred.encrypted_config)

    if not github_config:
        raise ValueError("GitHub credential not found or invalid")

    operation = str(node_data.get("githubOperation", "") or "").strip()
    if not operation:
        raise ValueError("GitHub node requires an operation")

    owner = self.evaluate_message_template(
        str(node_data.get("githubOwner", "") or ""), inputs, node_id
    ).strip()
    repo = self.evaluate_message_template(
        str(node_data.get("githubRepo", "") or ""), inputs, node_id
    ).strip()
    owner_optional_operations = {"getUserIssues", "inviteUser"}
    repo_optional_operations = {
        "listOrganizationRepositories",
        "listUserRepositories",
        "getUserRepositories",
        "getUserIssues",
        "inviteUser",
    }
    if operation not in owner_optional_operations and not owner:
        raise ValueError("GitHub node requires an owner or organization")
    if operation not in repo_optional_operations and not repo:
        raise ValueError("GitHub node requires owner and repository")

    def _resolve_optional_template(field_name: str) -> tuple[bool, str]:
        if field_name not in node_data:
            return False, ""
        raw_value = node_data.get(field_name)
        if raw_value is None:
            return True, ""
        if isinstance(raw_value, str) and raw_value == "":
            return True, ""
        resolved = self.evaluate_message_template(str(raw_value), inputs, node_id)
        return True, resolved

    def _parse_optional_string_list(
        field_name: str,
        label: str,
    ) -> tuple[bool, list[str] | None]:
        provided, raw = _resolve_optional_template(field_name)
        if not provided:
            return False, None
        stripped = raw.strip()
        if not stripped:
            return False, None
        try:
            parsed = _json.loads(stripped)
        except _json.JSONDecodeError as exc:
            raise ValueError(f"GitHub {label} must be a JSON array of strings") from exc
        if parsed is None:
            return True, None
        if not isinstance(parsed, list):
            raise ValueError(f"GitHub {label} must be a JSON array of strings")
        return True, [str(item) for item in parsed]

    def _parse_optional_object(
        field_name: str,
        label: str,
    ) -> tuple[bool, dict | None]:
        provided, raw = _resolve_optional_template(field_name)
        if not provided:
            return False, None
        stripped = raw.strip()
        if not stripped:
            return False, None
        try:
            parsed = _json.loads(stripped)
        except _json.JSONDecodeError as exc:
            raise ValueError(f"GitHub {label} must be a JSON object") from exc
        if parsed is None:
            return True, None
        if not isinstance(parsed, dict):
            raise ValueError(f"GitHub {label} must be a JSON object")
        return True, parsed

    labels_provided, labels = _parse_optional_string_list("githubLabels", "labels")
    assignees_provided, assignees = _parse_optional_string_list(
        "githubAssignees",
        "assignees",
    )
    service = GitHubService(github_config)
    try:
        if operation == "getRepository":
            repo_data = service.get_repository(owner, repo)
            output = {
                "success": True,
                "operation": operation,
                "repository": repo_data,
                "full_name": repo_data.get("full_name"),
                "default_branch": repo_data.get("default_branch"),
                "private": repo_data.get("private"),
                "url": repo_data.get("html_url"),
            }
        elif operation == "getRepositoryLicense":
            license_data = service.get_repository_license(owner, repo)
            output = {
                "success": True,
                "operation": operation,
                "license": license_data,
                "name": (license_data.get("license") or {}).get("name"),
                "spdx_id": (license_data.get("license") or {}).get("spdx_id"),
                "content": license_data.get("decoded_content"),
            }
        elif operation == "getRepositoryProfile":
            profile = service.get_repository_profile(owner, repo)
            output = {
                "success": True,
                "operation": operation,
                "profile": profile,
                "health_percentage": profile.get("health_percentage"),
                "description": profile.get("description"),
            }
        elif operation == "listPopularPaths":
            paths = service.list_popular_paths(owner, repo)
            output = {
                "success": True,
                "operation": operation,
                "paths": paths,
                "count": len(paths),
            }
        elif operation == "listReferrers":
            referrers = service.list_referrers(owner, repo)
            output = {
                "success": True,
                "operation": operation,
                "referrers": referrers,
                "count": len(referrers),
            }
        elif operation == "getIssue":
            issue_number_value = self.evaluate_message_template(
                str(node_data.get("githubIssueNumber", "") or ""), inputs, node_id
            ).strip()
            if not issue_number_value:
                raise ValueError("GitHub getIssue requires an issue number")
            issue_number = int(float(issue_number_value))
            issue = service.get_issue(owner, repo, issue_number)
            output = {
                "success": True,
                "operation": operation,
                "issue": issue,
                "number": issue.get("number"),
                "title": issue.get("title"),
                "state": issue.get("state"),
                "url": issue.get("html_url"),
            }
        elif operation in {"listIssues", "getRepositoryIssues"}:
            state = (
                self.evaluate_message_template(
                    str(node_data.get("githubState", "open") or "open"), inputs, node_id
                ).strip()
                or "open"
            )
            per_page_value = self.evaluate_message_template(
                str(node_data.get("githubPerPage", "30") or "30"), inputs, node_id
            ).strip()
            per_page = int(float(per_page_value or "30"))
            assignee = self.evaluate_nonempty_message_template(
                str(node_data.get("githubAssignee", "") or ""), inputs, node_id
            ).strip()
            creator = self.evaluate_nonempty_message_template(
                str(node_data.get("githubCreator", "") or ""), inputs, node_id
            ).strip()
            mentioned = self.evaluate_nonempty_message_template(
                str(node_data.get("githubMentioned", "") or ""), inputs, node_id
            ).strip()
            labels_filter = self.evaluate_nonempty_message_template(
                str(node_data.get("githubLabelsFilter", "") or ""), inputs, node_id
            ).strip()
            since = self.evaluate_nonempty_message_template(
                str(node_data.get("githubSince", "") or ""), inputs, node_id
            ).strip()
            sort = str(node_data.get("githubSort", "") or "").strip()
            direction = str(node_data.get("githubDirection", "") or "").strip()
            list_issues_method = (
                service.get_repository_issues
                if operation == "getRepositoryIssues"
                else service.list_issues
            )
            issues = list_issues_method(
                owner,
                repo,
                state=state,
                per_page=per_page,
                assignee=assignee or None,
                creator=creator or None,
                mentioned=mentioned or None,
                labels=labels_filter or None,
                since=since or None,
                sort=sort or None,
                direction=direction or None,
            )
            output = {
                "success": True,
                "operation": operation,
                "issues": issues,
                "count": len(issues),
            }
        elif operation == "createComment":
            issue_number_value = self.evaluate_message_template(
                str(node_data.get("githubIssueNumber", "") or ""), inputs, node_id
            ).strip()
            if not issue_number_value:
                raise ValueError("GitHub createComment requires an issue number")
            comment_body = self.evaluate_message_template(
                str(node_data.get("githubCommentBody", "") or ""), inputs, node_id
            )
            if not comment_body.strip():
                raise ValueError("GitHub createComment requires a comment body")
            issue_number = int(float(issue_number_value))
            comment = service.create_issue_comment(owner, repo, issue_number, comment_body)
            output = {
                "success": True,
                "operation": operation,
                "comment": comment,
                "id": comment.get("id"),
                "url": comment.get("html_url"),
            }
        elif operation == "createIssue":
            title = self.evaluate_message_template(
                str(node_data.get("githubTitle", "") or ""), inputs, node_id
            ).strip()
            if not title:
                raise ValueError("GitHub createIssue requires a title")
            body = self.evaluate_message_template(
                str(node_data.get("githubBody", "") or ""), inputs, node_id
            )
            issue = service.create_issue(
                owner,
                repo,
                title,
                body=body or None,
                labels=labels or None,
                assignees=assignees or None,
            )
            output = {
                "success": True,
                "operation": operation,
                "issue": issue,
                "number": issue.get("number"),
                "title": issue.get("title"),
                "url": issue.get("html_url"),
            }
        elif operation == "updateIssue":
            issue_number_value = self.evaluate_message_template(
                str(node_data.get("githubIssueNumber", "") or ""), inputs, node_id
            ).strip()
            if not issue_number_value:
                raise ValueError("GitHub updateIssue requires an issue number")
            issue_number = int(float(issue_number_value))
            title_provided, title_raw = _resolve_optional_template("githubTitle")
            body_provided, body = _resolve_optional_template("githubBody")
            state_provided, state_raw = _resolve_optional_template("githubState")
            state_reason_provided, state_reason_raw = _resolve_optional_template(
                "githubStateReason"
            )
            title = title_raw.strip()
            state = state_raw.strip()
            state_reason = state_reason_raw.strip()
            issue = service.update_issue(
                owner,
                repo,
                issue_number,
                title=title if title_provided else None,
                body=body if body_provided else None,
                state=state or None if state_provided else None,
                state_reason=(state_reason or None if state_reason_provided else None),
                labels=labels if labels_provided else None,
                assignees=assignees if assignees_provided else None,
            )
            output = {
                "success": True,
                "operation": operation,
                "issue": issue,
                "number": issue.get("number"),
                "title": issue.get("title"),
                "state": issue.get("state"),
                "url": issue.get("html_url"),
            }
        elif operation == "lockIssue":
            issue_number_value = self.evaluate_message_template(
                str(node_data.get("githubIssueNumber", "") or ""), inputs, node_id
            ).strip()
            if not issue_number_value:
                raise ValueError("GitHub lockIssue requires an issue number")
            lock_reason = self.evaluate_message_template(
                str(node_data.get("githubLockReason", "") or ""), inputs, node_id
            ).strip()
            allowed_lock_reasons = {"off-topic", "too heated", "resolved", "spam"}
            if lock_reason and lock_reason not in allowed_lock_reasons:
                raise ValueError(
                    "GitHub lockIssue lock reason must be one of: "
                    "off-topic, too heated, resolved, spam"
                )
            issue_number = int(float(issue_number_value))
            lock_result = service.lock_issue(
                owner,
                repo,
                issue_number,
                lock_reason=lock_reason or None,
            )
            output = {
                "success": True,
                "operation": operation,
                **lock_result,
            }
        elif operation in {"listPullRequests", "getRepositoryPullRequests"}:
            state = (
                self.evaluate_message_template(
                    str(node_data.get("githubState", "open") or "open"), inputs, node_id
                ).strip()
                or "open"
            )
            per_page_value = self.evaluate_message_template(
                str(node_data.get("githubPerPage", "30") or "30"), inputs, node_id
            ).strip()
            per_page = int(float(per_page_value or "30"))
            list_pull_requests_method = (
                service.get_repository_pull_requests
                if operation == "getRepositoryPullRequests"
                else service.list_pull_requests
            )
            pull_requests = list_pull_requests_method(
                owner,
                repo,
                state=state,
                per_page=per_page,
                sort=str(node_data.get("githubSort", "") or "").strip() or None,
                direction=(str(node_data.get("githubDirection", "") or "").strip() or None),
            )
            output = {
                "success": True,
                "operation": operation,
                "pull_requests": pull_requests,
                "count": len(pull_requests),
            }
        elif operation == "createPullRequest":
            title = self.evaluate_message_template(
                str(node_data.get("githubTitle", "") or ""), inputs, node_id
            ).strip()
            head = self.evaluate_message_template(
                str(node_data.get("githubHead", "") or ""), inputs, node_id
            ).strip()
            base = self.evaluate_message_template(
                str(node_data.get("githubBase", "") or ""), inputs, node_id
            ).strip()
            if not title or not head or not base:
                raise ValueError(
                    "GitHub createPullRequest requires title, head branch, and base branch"
                )
            body = self.evaluate_message_template(
                str(node_data.get("githubBody", "") or ""), inputs, node_id
            )
            draft = _coerce_boolean(node_data.get("githubDraft"), default=False)
            pull_request = service.create_pull_request(
                owner,
                repo,
                title,
                head,
                base,
                body=body or None,
                draft=draft,
            )
            output = {
                "success": True,
                "operation": operation,
                "pull_request": pull_request,
                "number": pull_request.get("number"),
                "title": pull_request.get("title"),
                "url": pull_request.get("html_url"),
            }
        elif operation in {"createReview", "getReview", "listReviews", "updateReview"}:
            pull_request_number_value = self.evaluate_nonempty_message_template(
                str(node_data.get("githubPullRequestNumber", "") or ""),
                inputs,
                node_id,
            ).strip()
            if not pull_request_number_value:
                raise ValueError(f"GitHub {operation} requires a pull request number")
            pull_request_number = int(float(pull_request_number_value))

            if operation == "createReview":
                raw_event = self.evaluate_nonempty_message_template(
                    str(node_data.get("githubReviewEvent", "APPROVE") or "APPROVE"),
                    inputs,
                    node_id,
                ).strip()
                event = raw_event.upper()
                allowed_review_events = {
                    "APPROVE",
                    "REQUEST_CHANGES",
                    "COMMENT",
                    "PENDING",
                }
                if event not in allowed_review_events:
                    raise ValueError(
                        "GitHub createReview event must be one of: "
                        "APPROVE, REQUEST_CHANGES, COMMENT, PENDING"
                    )
                body = self.evaluate_nonempty_message_template(
                    str(node_data.get("githubReviewBody", "") or ""),
                    inputs,
                    node_id,
                )
                if event in {"REQUEST_CHANGES", "COMMENT"} and not body.strip():
                    raise ValueError(f"GitHub createReview requires a body for event {event}")
                commit_id = self.evaluate_nonempty_message_template(
                    str(node_data.get("githubCommitId", "") or ""),
                    inputs,
                    node_id,
                ).strip()
                review = service.create_review(
                    owner,
                    repo,
                    pull_request_number,
                    event,
                    body=body or None,
                    commit_id=commit_id or None,
                )
                output = {
                    "success": True,
                    "operation": operation,
                    "review": review,
                    "id": review.get("id"),
                    "state": review.get("state"),
                    "url": review.get("html_url"),
                }
            elif operation == "listReviews":
                per_page_value = self.evaluate_message_template(
                    str(node_data.get("githubPerPage", "30") or "30"),
                    inputs,
                    node_id,
                ).strip()
                per_page = int(float(per_page_value or "30"))
                reviews = service.list_reviews(
                    owner,
                    repo,
                    pull_request_number,
                    per_page=per_page,
                )
                output = {
                    "success": True,
                    "operation": operation,
                    "reviews": reviews,
                    "count": len(reviews),
                }
            else:
                review_id_value = self.evaluate_nonempty_message_template(
                    str(node_data.get("githubReviewId", "") or ""),
                    inputs,
                    node_id,
                ).strip()
                if not review_id_value:
                    raise ValueError(f"GitHub {operation} requires a review id")
                review_id = int(float(review_id_value))
                if operation == "getReview":
                    review = service.get_review(
                        owner,
                        repo,
                        pull_request_number,
                        review_id,
                    )
                else:
                    body = self.evaluate_nonempty_message_template(
                        str(node_data.get("githubReviewBody", "") or ""),
                        inputs,
                        node_id,
                    )
                    if not body.strip():
                        raise ValueError("GitHub updateReview requires a review body")
                    review = service.update_review(
                        owner,
                        repo,
                        pull_request_number,
                        review_id,
                        body,
                    )
                output = {
                    "success": True,
                    "operation": operation,
                    "review": review,
                    "id": review.get("id"),
                    "state": review.get("state"),
                    "url": review.get("html_url"),
                }
        elif operation == "listReleases":
            per_page_value = self.evaluate_message_template(
                str(node_data.get("githubPerPage", "30") or "30"), inputs, node_id
            ).strip()
            per_page = int(float(per_page_value or "30"))
            releases = service.list_releases(owner, repo, per_page=per_page)
            output = {
                "success": True,
                "operation": operation,
                "releases": releases,
                "count": len(releases),
            }
        elif operation == "getRelease":
            release_id_value = self.evaluate_message_template(
                str(node_data.get("githubReleaseId", "") or ""), inputs, node_id
            ).strip()
            if not release_id_value:
                raise ValueError("GitHub getRelease requires a release id")
            release_id = int(float(release_id_value))
            release = service.get_release(owner, repo, release_id)
            output = {
                "success": True,
                "operation": operation,
                "release": release,
                "id": release.get("id"),
                "tag_name": release.get("tag_name"),
                "url": release.get("html_url"),
            }
        elif operation == "createRelease":
            tag_name = self.evaluate_message_template(
                str(node_data.get("githubTagName", "") or ""), inputs, node_id
            ).strip()
            if not tag_name:
                raise ValueError("GitHub createRelease requires a tag name")
            name = self.evaluate_message_template(
                str(node_data.get("githubTitle", "") or ""), inputs, node_id
            ).strip()
            body = self.evaluate_message_template(
                str(node_data.get("githubBody", "") or ""), inputs, node_id
            )
            target_commitish = self.evaluate_message_template(
                str(node_data.get("githubBranch", "") or ""), inputs, node_id
            ).strip()
            release = service.create_release(
                owner,
                repo,
                tag_name,
                name=name or None,
                body=body or None,
                target_commitish=target_commitish or None,
                draft=_coerce_boolean(node_data.get("githubDraft"), default=False),
                prerelease=_coerce_boolean(node_data.get("githubPrerelease"), default=False),
            )
            output = {
                "success": True,
                "operation": operation,
                "release": release,
                "id": release.get("id"),
                "tag_name": release.get("tag_name"),
                "url": release.get("html_url"),
            }
        elif operation == "updateRelease":
            release_id_value = self.evaluate_message_template(
                str(node_data.get("githubReleaseId", "") or ""), inputs, node_id
            ).strip()
            if not release_id_value:
                raise ValueError("GitHub updateRelease requires a release id")
            release_id = int(float(release_id_value))
            tag_name = self.evaluate_message_template(
                str(node_data.get("githubTagName", "") or ""), inputs, node_id
            ).strip()
            name_provided, name_raw = _resolve_optional_template("githubTitle")
            body_provided, body = _resolve_optional_template("githubBody")
            target_commitish_provided, target_commitish_raw = _resolve_optional_template(
                "githubBranch"
            )
            name = name_raw.strip()
            target_commitish = target_commitish_raw.strip()
            release = service.update_release(
                owner,
                repo,
                release_id,
                tag_name=tag_name or None,
                name=name if name_provided else None,
                body=body if body_provided else None,
                target_commitish=target_commitish or None if target_commitish_provided else None,
                draft=(
                    _coerce_boolean(node_data.get("githubDraft"))
                    if node_data.get("githubDraft") is not None
                    else None
                ),
                prerelease=(
                    _coerce_boolean(node_data.get("githubPrerelease"))
                    if node_data.get("githubPrerelease") is not None
                    else None
                ),
            )
            output = {
                "success": True,
                "operation": operation,
                "release": release,
                "id": release.get("id"),
                "tag_name": release.get("tag_name"),
                "url": release.get("html_url"),
            }
        elif operation == "deleteRelease":
            release_id_value = self.evaluate_message_template(
                str(node_data.get("githubReleaseId", "") or ""), inputs, node_id
            ).strip()
            if not release_id_value:
                raise ValueError("GitHub deleteRelease requires a release id")
            release_id = int(float(release_id_value))
            delete_result = service.delete_release(owner, repo, release_id)
            output = {"success": True, "operation": operation, **delete_result}
        elif operation == "listWorkflows":
            per_page_value = self.evaluate_message_template(
                str(node_data.get("githubPerPage", "30") or "30"), inputs, node_id
            ).strip()
            per_page = int(float(per_page_value or "30"))
            workflows = service.list_workflows(owner, repo, per_page=per_page)
            output = {
                "success": True,
                "operation": operation,
                "workflows": workflows,
                "count": len(workflows),
            }
        elif operation == "getWorkflow":
            workflow_id = self.evaluate_message_template(
                str(node_data.get("githubWorkflowId", "") or ""), inputs, node_id
            ).strip()
            if not workflow_id:
                raise ValueError("GitHub getWorkflow requires a workflow id or file name")
            workflow = service.get_workflow(owner, repo, workflow_id)
            output = {
                "success": True,
                "operation": operation,
                "workflow": workflow,
                "id": workflow.get("id"),
                "name": workflow.get("name"),
                "path": workflow.get("path"),
            }
        elif operation in {"enableWorkflow", "disableWorkflow", "getWorkflowUsage"}:
            workflow_id = self.evaluate_nonempty_message_template(
                str(node_data.get("githubWorkflowId", "") or ""),
                inputs,
                node_id,
            ).strip()
            if not workflow_id:
                raise ValueError(f"GitHub {operation} requires a workflow id or file name")
            if operation == "enableWorkflow":
                workflow_result = service.enable_workflow(owner, repo, workflow_id)
            elif operation == "disableWorkflow":
                workflow_result = service.disable_workflow(owner, repo, workflow_id)
            else:
                usage = service.get_workflow_usage(owner, repo, workflow_id)
                workflow_result = {
                    "workflow_id": workflow_id,
                    "usage": usage,
                    "billable": usage.get("billable"),
                }
            output = {
                "success": True,
                "operation": operation,
                **workflow_result,
            }
        elif operation == "dispatchWorkflow":
            workflow_id = self.evaluate_nonempty_message_template(
                str(node_data.get("githubWorkflowId", "") or ""), inputs, node_id
            ).strip()
            if not workflow_id:
                raise ValueError("GitHub dispatchWorkflow requires a workflow id or file name")
            ref = self.evaluate_nonempty_message_template(
                str(node_data.get("githubBranch", "") or ""), inputs, node_id
            ).strip()
            if not ref:
                raise ValueError("GitHub dispatchWorkflow requires a branch or ref")
            _, workflow_inputs = _parse_optional_object(
                "githubWorkflowInputs",
                "workflow inputs",
            )
            dispatch_result = service.dispatch_workflow(
                owner,
                repo,
                workflow_id,
                ref,
                inputs=workflow_inputs,
            )
            output = {"success": True, "operation": operation, **dispatch_result}
        elif operation == "dispatchWorkflowAndWait":
            workflow_id = self.evaluate_nonempty_message_template(
                str(node_data.get("githubWorkflowId", "") or ""), inputs, node_id
            ).strip()
            if not workflow_id:
                raise ValueError(
                    "GitHub dispatchWorkflowAndWait requires a workflow id or file name"
                )
            ref = self.evaluate_nonempty_message_template(
                str(node_data.get("githubBranch", "") or ""), inputs, node_id
            ).strip()
            if not ref:
                raise ValueError("GitHub dispatchWorkflowAndWait requires a branch or ref")
            _, workflow_inputs = _parse_optional_object(
                "githubWorkflowInputs",
                "workflow inputs",
            )
            timeout_value = self.evaluate_nonempty_message_template(
                str(node_data.get("githubWaitTimeoutSeconds", "600") or "600"),
                inputs,
                node_id,
            ).strip()
            interval_value = self.evaluate_nonempty_message_template(
                str(node_data.get("githubPollIntervalSeconds", "5") or "5"),
                inputs,
                node_id,
            ).strip()
            wait_result = service.dispatch_workflow_and_wait(
                owner,
                repo,
                workflow_id,
                ref,
                inputs=workflow_inputs,
                timeout_seconds=int(float(timeout_value or "600")),
                poll_interval_seconds=float(interval_value or "5"),
            )
            output = {"success": True, "operation": operation, **wait_result}
        elif operation == "getFile":
            path = self.evaluate_message_template(
                str(node_data.get("githubFilePath", "") or ""), inputs, node_id
            ).strip()
            if not path:
                raise ValueError("GitHub getFile requires a file path")
            ref = self.evaluate_message_template(
                str(node_data.get("githubBranch", "") or ""), inputs, node_id
            ).strip()
            file_data = service.get_file(owner, repo, path, ref=ref or None)
            output = {
                "success": True,
                "operation": operation,
                "file": file_data,
                "path": file_data.get("path"),
                "sha": file_data.get("sha"),
                "content": file_data.get("content"),
            }
        elif operation == "listFiles":
            path = self.evaluate_message_template(
                str(node_data.get("githubFilePath", "") or ""), inputs, node_id
            ).strip()
            ref = self.evaluate_message_template(
                str(node_data.get("githubBranch", "") or ""), inputs, node_id
            ).strip()
            directory = service.list_files(owner, repo, path=path, ref=ref or None)
            output = {"success": True, "operation": operation, **directory}
        elif operation == "upsertFile":
            path = self.evaluate_message_template(
                str(node_data.get("githubFilePath", "") or ""), inputs, node_id
            ).strip()
            if not path:
                raise ValueError("GitHub upsertFile requires a file path")
            message = self.evaluate_message_template(
                str(node_data.get("githubCommitMessage", "") or ""), inputs, node_id
            ).strip()
            if not message:
                raise ValueError("GitHub upsertFile requires a commit message")
            content = self.evaluate_message_template(
                str(node_data.get("githubFileContent", "") or ""), inputs, node_id
            )
            branch = self.evaluate_message_template(
                str(node_data.get("githubBranch", "") or ""), inputs, node_id
            ).strip()
            file_result = service.upsert_file(
                owner,
                repo,
                path,
                message,
                content,
                branch=branch or None,
            )
            output = {
                "success": True,
                "operation": operation,
                "file": file_result,
                "path": file_result.get("path"),
                "sha": file_result.get("sha"),
                "commit_sha": file_result.get("commit_sha"),
                "created": file_result.get("created"),
            }
        elif operation == "deleteFile":
            path = self.evaluate_message_template(
                str(node_data.get("githubFilePath", "") or ""), inputs, node_id
            ).strip()
            if not path:
                raise ValueError("GitHub deleteFile requires a file path")
            message = self.evaluate_message_template(
                str(node_data.get("githubCommitMessage", "") or ""), inputs, node_id
            ).strip()
            if not message:
                raise ValueError("GitHub deleteFile requires a commit message")
            branch = self.evaluate_message_template(
                str(node_data.get("githubBranch", "") or ""), inputs, node_id
            ).strip()
            delete_result = service.delete_file(
                owner,
                repo,
                path,
                message,
                branch=branch or None,
            )
            output = {"success": True, "operation": operation, **delete_result}
        elif operation == "listOrganizationRepositories":
            per_page_value = self.evaluate_message_template(
                str(node_data.get("githubPerPage", "30") or "30"), inputs, node_id
            ).strip()
            per_page = int(float(per_page_value or "30"))
            repositories = service.list_organization_repositories(owner, per_page=per_page)
            output = {
                "success": True,
                "operation": operation,
                "repositories": repositories,
                "count": len(repositories),
            }
        elif operation == "listUserRepositories":
            per_page_value = self.evaluate_message_template(
                str(node_data.get("githubPerPage", "30") or "30"), inputs, node_id
            ).strip()
            per_page = int(float(per_page_value or "30"))
            repositories = service.list_user_repositories(owner, per_page=per_page)
            output = {
                "success": True,
                "operation": operation,
                "repositories": repositories,
                "count": len(repositories),
            }
        elif operation == "getUserRepositories":
            per_page_value = self.evaluate_message_template(
                str(node_data.get("githubPerPage", "30") or "30"), inputs, node_id
            ).strip()
            per_page = int(float(per_page_value or "30"))
            repositories = service.get_user_repositories(owner, per_page=per_page)
            output = {
                "success": True,
                "operation": operation,
                "repositories": repositories,
                "count": len(repositories),
            }
        elif operation == "getUserIssues":
            state = str(node_data.get("githubState", "open") or "open").strip() or "open"
            per_page_value = self.evaluate_message_template(
                str(node_data.get("githubPerPage", "30") or "30"), inputs, node_id
            ).strip()
            issues = service.get_user_issues(
                state=state,
                per_page=int(float(per_page_value or "30")),
                mentioned=self.evaluate_nonempty_message_template(
                    str(node_data.get("githubMentioned", "") or ""), inputs, node_id
                ).strip()
                or None,
                labels=self.evaluate_nonempty_message_template(
                    str(node_data.get("githubLabelsFilter", "") or ""), inputs, node_id
                ).strip()
                or None,
                since=self.evaluate_nonempty_message_template(
                    str(node_data.get("githubSince", "") or ""), inputs, node_id
                ).strip()
                or None,
                sort=str(node_data.get("githubSort", "") or "").strip() or None,
                direction=(str(node_data.get("githubDirection", "") or "").strip() or None),
            )
            output = {
                "success": True,
                "operation": operation,
                "issues": issues,
                "count": len(issues),
            }
        elif operation == "inviteUser":
            organization = self.evaluate_nonempty_message_template(
                str(node_data.get("githubOrganization", "") or ""), inputs, node_id
            ).strip()
            email = self.evaluate_nonempty_message_template(
                str(node_data.get("githubInviteEmail", "") or ""), inputs, node_id
            ).strip()
            if not organization or not email:
                raise ValueError("GitHub inviteUser requires an organization and email")
            invitation = service.invite_user(organization, email)
            output = {
                "success": True,
                "operation": operation,
                "invitation": invitation,
                "id": invitation.get("id"),
                "email": invitation.get("email") or email,
            }
        else:
            raise ValueError(f"Unknown GitHub operation: {operation}")
    finally:
        service.close()
    return output
