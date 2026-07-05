from __future__ import annotations

import copy
import re
import time
from importlib import import_module

from app.services.codex_runner_service import (
    CODEX_PUBLISH_MODES,
    CodexResumeRequest,
    CodexRunnerService,
    CodexRunRequest,
)
from app.services.node_execution.base import NodeExecutionContext


def execute(ctx: NodeExecutionContext) -> object:
    """Execute the Codex node."""
    _workflow_executor = import_module("app.services.workflow_executor")
    NodeResult = _workflow_executor.NodeResult  # noqa: N806

    self = ctx.executor
    node_id = ctx.node_id
    inputs = ctx.inputs
    node_data = ctx.node_data
    node_label = ctx.node_label

    codex_config, github_config = _load_credentials(self, node_data)
    timeout_seconds = _coerce_timeout(node_data.get("timeoutSeconds"))
    publish_mode = str(node_data.get("publishMode") or "diff_only").strip()
    if publish_mode not in CODEX_PUBLISH_MODES:
        publish_mode = "diff_only"

    resume_context = copy.deepcopy(self.hitl_resume_context.get(node_id) or {})
    runner = CodexRunnerService()
    resolved_repository_url = ""
    resolved_base_branch = "main"
    resolved_task_prompt = ""
    resolved_branch_name = _resolve_branch_name(self, node_data, inputs, node_id)
    codex_model = self.evaluate_nonempty_message_template(
        str(node_data.get("codexModel") or ""), inputs, node_id
    ).strip()
    if resume_context:
        answer_text = str(resume_context.get("answerText") or resume_context.get("answer") or "")
        resolved_repository_url = str(resume_context.get("repositoryUrl") or "").strip()
        resolved_base_branch = str(resume_context.get("baseBranch") or "main").strip() or "main"
        resolved_task_prompt = str(resume_context.get("taskPrompt") or answer_text).strip()
        resolved_branch_name = (
            str(resume_context.get("branchName") or "").strip() or resolved_branch_name
        )
        result = runner.resume_task(
            CodexResumeRequest(
                answer_text=answer_text,
                thread_id=str(resume_context.get("threadId") or "").strip() or None,
                workspace_path=str(resume_context.get("workspacePath") or "").strip(),
                branch_name=resolved_branch_name,
                publish_mode=publish_mode,
                base_branch=resolved_base_branch,
                repository_url=resolved_repository_url,
                codex_access_token=str(codex_config.get("access_token") or ""),
                github_config=github_config,
                timeout_seconds=timeout_seconds,
                codex_auth=codex_config,
                model=codex_model,
            )
        )
    else:
        # Use the nonempty variant: evaluate_message_template("") returns str(inputs), which for
        # an unset optional field (e.g. setupCommand) would run garbage as a shell command.
        repository_url = self.evaluate_nonempty_message_template(
            str(node_data.get("repositoryUrl") or ""), inputs, node_id
        ).strip()
        if not repository_url:
            raise ValueError("Codex node requires a repository URL")
        resolved_repository_url = repository_url
        base_branch = (
            self.evaluate_nonempty_message_template(
                str(node_data.get("baseBranch") or "main"), inputs, node_id
            ).strip()
            or "main"
        )
        resolved_base_branch = base_branch
        task_prompt = self.evaluate_nonempty_message_template(
            str(node_data.get("taskPrompt") or "$input.text"), inputs, node_id
        ).strip()
        if not task_prompt:
            raise ValueError("Codex node requires a task prompt")
        resolved_task_prompt = task_prompt
        setup_command = self.evaluate_nonempty_message_template(
            str(node_data.get("setupCommand") or ""), inputs, node_id
        ).strip()
        result = runner.run_task(
            CodexRunRequest(
                repository_url=repository_url,
                base_branch=base_branch,
                task_prompt=task_prompt,
                branch_name=resolved_branch_name,
                publish_mode=publish_mode,
                setup_command=setup_command,
                timeout_seconds=timeout_seconds,
                codex_access_token=str(codex_config.get("access_token") or ""),
                github_config=github_config,
                codex_auth=codex_config,
                model=codex_model,
            )
        )

    output = result.to_output()
    if result.status == "needs_input":
        question = result.question or "Codex needs more information to continue."
        pending_output = {
            "status": "needs_input",
            "summary": result.summary or "Codex needs more information.",
            "question": question,
            "answerUrl": None,
            "requestId": None,
            "expiresAt": None,
            "shareText": None,
            "shareMarkdown": None,
            "threadId": result.thread_id,
            "workspacePath": result.workspace_path,
            "branchName": result.branch_name,
        }
        return NodeResult(
            node_id=node_id,
            node_label=node_label,
            node_type=ctx.node_type,
            status="pending",
            output=pending_output,
            execution_time_ms=(time.time() - ctx.start_time) * 1000,
            metadata={
                "codex": {
                    "kind": "codex",
                    "summary": pending_output["summary"],
                    "question": question,
                    "task_prompt": resolved_task_prompt,
                    "repository_url": resolved_repository_url,
                    "base_branch": resolved_base_branch,
                    "branch_name": result.branch_name,
                    "thread_id": result.thread_id,
                    "workspace_path": result.workspace_path,
                    "original_output": output,
                }
            },
        )

    if publish_mode == "patch_artifact":
        patch_url = _store_patch_artifact(self, node_id, node_label, result.diff)
        if patch_url:
            output["patchUrl"] = patch_url

    output["status"] = "completed"
    output["_skip_source_handles"] = ["question"]
    return output


def _store_patch_artifact(executor: object, node_id: str, node_label: str, diff_text: str) -> str:
    """Store the Codex diff as a downloadable Drive file and return its download URL."""
    if not str(diff_text or "").strip():
        return ""
    import secrets
    import uuid

    from app.db.models import FileAccessToken, GeneratedFile
    from app.db.session import SessionLocal
    from app.services.file_storage import _safe_storage_path, build_download_url

    owner_id = getattr(executor, "trace_user_id", None)
    if not owner_id:
        raise ValueError("Codex patch_artifact mode requires an owner context")

    diff_bytes = diff_text.encode("utf-8")
    filename = "codex-changes.patch"
    file_uuid = uuid.uuid4()
    rel_path = f"{owner_id}/{file_uuid}/{filename}"
    abs_path = _safe_storage_path(rel_path)
    abs_path.parent.mkdir(parents=True, exist_ok=True)
    abs_path.write_bytes(diff_bytes)

    with SessionLocal() as db:
        db.add(
            GeneratedFile(
                id=file_uuid,
                owner_id=owner_id,
                workflow_id=getattr(executor, "workflow_id", None),
                filename=filename,
                storage_path=rel_path,
                mime_type="text/x-patch",
                size_bytes=len(diff_bytes),
                source_node_id=node_id,
                source_node_label=node_label,
                metadata_json={"kind": "codex_patch"},
            )
        )
        token_str = secrets.token_urlsafe(32)
        db.add(FileAccessToken(file_id=file_uuid, token=token_str, created_by_id=owner_id))
        db.commit()

    return build_download_url(getattr(executor, "_base_url", ""), token_str)


def _load_credentials(executor: object, node_data: dict) -> tuple[dict, dict]:
    from app.db.models import CredentialType
    from app.db.session import SessionLocal
    from app.services.encryption import decrypt_config

    codex_credential_id = node_data.get("credentialId")
    github_credential_id = node_data.get("githubCredentialId")
    if not codex_credential_id:
        raise ValueError("Codex node requires a Codex access token credential")
    if not github_credential_id:
        raise ValueError("Codex node requires a GitHub credential")

    codex_config: dict = {}
    github_config: dict = {}
    with SessionLocal() as db:
        codex_credential = executor._get_accessible_credential(db, codex_credential_id)
        if codex_credential is None or codex_credential.type != CredentialType.codex:
            raise ValueError("Codex node requires a Codex credential")
        codex_config = decrypt_config(codex_credential.encrypted_config)
        codex_config = _refresh_chatgpt_tokens_if_needed(db, codex_credential, codex_config)

        github_credential = executor._get_accessible_credential(db, github_credential_id)
        if github_credential is None or github_credential.type != CredentialType.github:
            raise ValueError("Codex node requires a GitHub credential")
        github_config = decrypt_config(github_credential.encrypted_config)

    if not str(codex_config.get("access_token") or "").strip():
        raise ValueError("Codex credential is missing access_token")
    if not str(github_config.get("api_key") or "").strip():
        raise ValueError("GitHub credential is missing api_key")
    return codex_config, github_config


def _refresh_chatgpt_tokens_if_needed(db: object, credential: object, codex_config: dict) -> dict:
    """Refresh an expired ChatGPT token bundle and persist the rotated tokens.

    Access-token credentials are returned unchanged. Refresh failures are non-fatal: the existing
    (possibly stale) bundle is returned so the runner can still attempt the run.
    """
    if str(codex_config.get("auth_mode") or "").strip() != "chatgpt":
        return codex_config
    from app.services.codex_oauth_service import (
        CodexOAuthError,
        CodexOAuthService,
        bundle_is_expired,
    )

    if not bundle_is_expired(codex_config.get("expires_at")):
        return codex_config
    refresh_token = str(codex_config.get("refresh_token") or "").strip()
    if not refresh_token:
        return codex_config
    try:
        bundle = CodexOAuthService().refresh_tokens(refresh_token)
    except CodexOAuthError:
        return codex_config

    from app.services.encryption import encrypt_config

    updated = {**codex_config, **bundle.to_config()}
    credential.encrypted_config = encrypt_config(updated)
    db.commit()
    return updated


def _coerce_timeout(value: object) -> float:
    try:
        timeout = float(value or 3600)
    except (TypeError, ValueError):
        timeout = 3600.0
    return max(60.0, min(timeout, 21600.0))


def _resolve_branch_name(executor: object, node_data: dict, inputs: dict, node_id: str) -> str:
    raw_branch = str(node_data.get("branchName") or "").strip()
    if raw_branch:
        resolved = executor.evaluate_message_template(raw_branch, inputs, node_id).strip()
    else:
        execution_id = str(getattr(executor, "execution_id", "") or "")
        resolved = f"codex/{execution_id[:8] or 'run'}"
    cleaned = re.sub(r"[^A-Za-z0-9._/-]+", "-", resolved).strip("-/")
    return cleaned or "codex/run"
