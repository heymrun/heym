from __future__ import annotations

import re

from app.services.node_execution.base import NodeExecutionContext
from app.services.opencode_runner_service import (
    OpenCodeRunnerService,
    OpenCodeRunRequest,
)

# Publish modes mirror the Codex node. ``diff_only`` / ``patch_artifact`` never touch the remote.
OPENCODE_PUBLISH_MODES: frozenset[str] = frozenset(
    {
        "diff_only",
        "draft_pr",
        "open_pr",
        "commit_push",
        "direct_commit",
        "update_existing_pr",
        "open_or_update_pr",
        "patch_artifact",
    }
)


def execute(ctx: NodeExecutionContext) -> object:
    """Execute the OpenCode Go node."""
    self = ctx.executor
    node_data = ctx.node_data
    inputs = ctx.inputs
    node_id = ctx.node_id

    opencode_config, github_config = _load_credentials(self, node_data)

    repository_url = self.evaluate_nonempty_message_template(
        str(node_data.get("repositoryUrl") or ""), inputs, node_id
    ).strip()
    if not repository_url:
        raise ValueError("OpenCode Go node requires a repository URL")
    base_branch = (
        self.evaluate_nonempty_message_template(
            str(node_data.get("baseBranch") or "main"), inputs, node_id
        ).strip()
        or "main"
    )
    task_prompt = self.evaluate_nonempty_message_template(
        str(node_data.get("taskPrompt") or "$input.text"), inputs, node_id
    ).strip()
    if not task_prompt:
        raise ValueError("OpenCode Go node requires a task prompt")
    publish_mode = str(node_data.get("publishMode") or "diff_only").strip()
    if publish_mode not in OPENCODE_PUBLISH_MODES:
        publish_mode = "diff_only"
    branch_name = _resolve_branch_name(self, node_data, inputs, node_id)
    model = self.evaluate_nonempty_message_template(
        str(node_data.get("opencodeModel") or ""), inputs, node_id
    ).strip()
    variant = str(node_data.get("opencodeVariant") or "").strip()
    timeout_seconds = _coerce_timeout(node_data.get("timeoutSeconds"))

    runner = OpenCodeRunnerService()
    result = runner.run_task(
        OpenCodeRunRequest(
            repository_url=repository_url,
            base_branch=base_branch,
            task_prompt=task_prompt,
            branch_name=branch_name,
            publish_mode=publish_mode,
            timeout_seconds=timeout_seconds,
            api_key=str(opencode_config.get("api_key") or ""),
            base_url=str(opencode_config.get("base_url") or ""),
            github_config=github_config,
            model=model,
            variant=variant,
        )
    )

    output = result.to_output()
    if publish_mode == "patch_artifact":
        patch_url = _store_patch_artifact(self, node_id, ctx.node_label, result.diff)
        if patch_url:
            output["patchUrl"] = patch_url
    output["status"] = "completed"
    # No resume path (lean HITL): reclaim the workspace + sibling opencode home now that the
    # diff/patch have been captured into the result.
    runner.cleanup_workspace(result.workspace_path)
    return output


def _load_credentials(executor: object, node_data: dict) -> tuple[dict, dict]:
    from app.db.models import CredentialType
    from app.db.session import SessionLocal
    from app.services.encryption import decrypt_config

    opencode_credential_id = node_data.get("credentialId")
    github_credential_id = node_data.get("githubCredentialId")
    if not opencode_credential_id:
        raise ValueError("OpenCode Go node requires an OpenCode credential")
    if not github_credential_id:
        raise ValueError("OpenCode Go node requires a GitHub credential")

    opencode_config: dict = {}
    github_config: dict = {}
    with SessionLocal() as db:
        opencode_credential = executor._get_accessible_credential(db, opencode_credential_id)
        if opencode_credential is None or opencode_credential.type != CredentialType.opencode:
            raise ValueError("OpenCode Go node requires an OpenCode credential")
        opencode_config = decrypt_config(opencode_credential.encrypted_config)

        github_credential = executor._get_accessible_credential(db, github_credential_id)
        if github_credential is None or github_credential.type != CredentialType.github:
            raise ValueError("OpenCode Go node requires a GitHub credential")
        github_config = decrypt_config(github_credential.encrypted_config)

    if not str(opencode_config.get("api_key") or "").strip():
        raise ValueError("OpenCode credential is missing api_key")
    if not str(github_config.get("api_key") or "").strip():
        raise ValueError("GitHub credential is missing api_key")
    return opencode_config, github_config


def _store_patch_artifact(executor: object, node_id: str, node_label: str, diff_text: str) -> str:
    """Store the OpenCode diff as a downloadable Drive file and return its download URL."""
    if not str(diff_text or "").strip():
        return ""
    import secrets
    import uuid

    from app.db.models import FileAccessToken, GeneratedFile
    from app.db.session import SessionLocal
    from app.services.file_storage import _safe_storage_path, build_download_url

    owner_id = getattr(executor, "trace_user_id", None)
    if not owner_id:
        raise ValueError("OpenCode patch_artifact mode requires an owner context")

    diff_bytes = diff_text.encode("utf-8")
    filename = "opencode-changes.patch"
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
                metadata_json={"kind": "opencode_patch"},
            )
        )
        token_str = secrets.token_urlsafe(32)
        db.add(FileAccessToken(file_id=file_uuid, token=token_str, created_by_id=owner_id))
        db.commit()

    return build_download_url(getattr(executor, "_base_url", ""), token_str)


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
        resolved = f"opencode/{execution_id[:8] or 'run'}"
    cleaned = re.sub(r"[^A-Za-z0-9._/-]+", "-", resolved).strip("-/")
    return cleaned or "opencode/run"
