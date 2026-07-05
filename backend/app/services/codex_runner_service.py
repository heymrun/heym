from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote, urlparse, urlunparse

from app.config import settings
from app.services.github_service import GitHubService

CODEX_FINAL_OUTPUT_SCHEMA: dict = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "status": {"type": "string", "enum": ["completed", "needs_input"]},
        "summary": {"type": "string"},
        "question": {"type": "string"},
        "validation": {"type": "string"},
        "pull_request_title": {"type": "string"},
        "pull_request_body": {"type": "string"},
    },
    "required": ["status", "summary"],
}


@dataclass(frozen=True)
class CodexRunRequest:
    """Input for a Codex CLI run inside a cloned repository workspace."""

    repository_url: str
    base_branch: str
    task_prompt: str
    branch_name: str
    publish_mode: str
    setup_command: str
    timeout_seconds: float
    codex_access_token: str
    github_config: dict
    codex_auth: dict = field(default_factory=dict)


@dataclass(frozen=True)
class CodexResumeRequest:
    """Input for resuming a paused Codex CLI thread."""

    answer_text: str
    thread_id: str | None
    workspace_path: str
    branch_name: str
    publish_mode: str
    base_branch: str
    repository_url: str
    codex_access_token: str
    github_config: dict
    timeout_seconds: float
    codex_auth: dict = field(default_factory=dict)


@dataclass
class CodexRunResult:
    """Normalized Codex node output."""

    status: str
    summary: str = ""
    question: str = ""
    validation: str = ""
    diff: str = ""
    changed_files: list[str] = field(default_factory=list)
    thread_id: str | None = None
    workspace_path: str | None = None
    branch_name: str = ""
    pull_request_url: str | None = None
    usage: dict | None = None
    raw_events: list[dict] = field(default_factory=list)

    def to_output(self) -> dict:
        output = {
            "status": self.status,
            "summary": self.summary,
            "question": self.question,
            "validation": self.validation,
            "diff": self.diff,
            "changedFiles": self.changed_files,
            "threadId": self.thread_id,
            "workspacePath": self.workspace_path,
            "branchName": self.branch_name,
            "pullRequestUrl": self.pull_request_url,
            "usage": self.usage or {},
        }
        return {key: value for key, value in output.items() if value not in (None, "", [])}


class CodexJsonlParser:
    """Parse Codex CLI JSONL output into a stable node result."""

    def parse(self, stdout: str) -> CodexRunResult:
        events: list[dict] = []
        final_payload: dict | None = None
        thread_id: str | None = None
        usage: dict | None = None

        for raw_line in stdout.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(event, dict):
                continue
            events.append(event)
            thread_id = thread_id or self._find_string_key(
                event,
                {"thread_id", "threadId", "conversation_id", "conversationId", "session_id"},
            )
            usage_candidate = self._find_dict_key(event, {"usage", "token_usage", "tokenUsage"})
            if usage_candidate is not None:
                usage = usage_candidate
            payload = self._extract_final_payload(event)
            if payload is not None:
                final_payload = payload

        if final_payload is None:
            final_payload = self._last_status_payload(events)
        if final_payload is None:
            return CodexRunResult(
                status="completed",
                summary="Codex completed without a structured final payload.",
                thread_id=thread_id,
                usage=usage,
                raw_events=events,
            )

        status = str(final_payload.get("status") or "completed").strip() or "completed"
        if status not in {"completed", "needs_input"}:
            status = "completed"
        return CodexRunResult(
            status=status,
            summary=str(final_payload.get("summary") or "").strip(),
            question=str(final_payload.get("question") or "").strip(),
            validation=str(final_payload.get("validation") or "").strip(),
            thread_id=thread_id
            or self._find_string_key(
                final_payload,
                {"thread_id", "threadId", "conversation_id", "conversationId", "session_id"},
            ),
            usage=usage,
            raw_events=events,
        )

    def _extract_final_payload(self, event: dict) -> dict | None:
        if str(event.get("status") or "") in {"completed", "needs_input"}:
            return event
        for key in ("result", "final", "final_output", "output", "data"):
            value = event.get(key)
            if isinstance(value, dict) and str(value.get("status") or "") in {
                "completed",
                "needs_input",
            }:
                return value
            if isinstance(value, str):
                parsed = self._parse_embedded_json(value)
                if parsed is not None:
                    return parsed
        return None

    def _last_status_payload(self, events: list[dict]) -> dict | None:
        for event in reversed(events):
            payload = self._extract_final_payload(event)
            if payload is not None:
                return payload
        return None

    @staticmethod
    def _parse_embedded_json(value: str) -> dict | None:
        cleaned = value.strip()
        if not cleaned.startswith("{"):
            return None
        try:
            parsed = json.loads(cleaned)
        except json.JSONDecodeError:
            return None
        return parsed if isinstance(parsed, dict) else None

    def _find_string_key(self, value: object, keys: set[str]) -> str | None:
        if isinstance(value, dict):
            for key, item in value.items():
                if key in keys and isinstance(item, str) and item.strip():
                    return item.strip()
                found = self._find_string_key(item, keys)
                if found:
                    return found
        if isinstance(value, list):
            for item in value:
                found = self._find_string_key(item, keys)
                if found:
                    return found
        return None

    def _find_dict_key(self, value: object, keys: set[str]) -> dict | None:
        if isinstance(value, dict):
            for key, item in value.items():
                if key in keys and isinstance(item, dict):
                    return item
                found = self._find_dict_key(item, keys)
                if found is not None:
                    return found
        if isinstance(value, list):
            for item in value:
                found = self._find_dict_key(item, keys)
                if found is not None:
                    return found
        return None


class CodexRunnerService:
    """Run Codex CLI in an isolated workspace using a ChatGPT/Codex access token."""

    def __init__(self, cli_command: str | None = None, workspace_root: str | None = None) -> None:
        self.cli_command = cli_command or settings.codex_cli_command
        self.workspace_root = Path(workspace_root or settings.codex_workspace_dir)
        self.parser = CodexJsonlParser()

    def run_task(self, request: CodexRunRequest) -> CodexRunResult:
        workspace = self._prepare_workspace(request)
        self._authenticate(
            workspace, request.codex_auth, request.codex_access_token, request.timeout_seconds
        )
        if request.setup_command.strip():
            self._run_setup_command(workspace, request.setup_command, request.timeout_seconds)
        prompt = self._build_prompt(request.task_prompt, request.publish_mode)
        result = self._run_codex_exec(
            workspace=workspace,
            prompt=prompt,
            timeout_seconds=request.timeout_seconds,
            resume_thread_id=None,
            codex_access_token=self._exec_token(request.codex_auth, request.codex_access_token),
        )
        return self._finalize_result(result, workspace, request)

    def resume_task(self, request: CodexResumeRequest) -> CodexRunResult:
        workspace = Path(request.workspace_path).resolve()
        if not workspace.exists() or not workspace.is_dir():
            raise ValueError("Codex workspace is no longer available")
        self._authenticate(
            workspace, request.codex_auth, request.codex_access_token, request.timeout_seconds
        )
        prompt = self._build_resume_prompt(request.answer_text, request.publish_mode)
        result = self._run_codex_exec(
            workspace=workspace,
            prompt=prompt,
            timeout_seconds=request.timeout_seconds,
            resume_thread_id=request.thread_id,
            codex_access_token=self._exec_token(request.codex_auth, request.codex_access_token),
        )
        run_request = CodexRunRequest(
            repository_url=request.repository_url,
            base_branch=request.base_branch,
            task_prompt=request.answer_text,
            branch_name=request.branch_name,
            publish_mode=request.publish_mode,
            setup_command="",
            timeout_seconds=request.timeout_seconds,
            codex_access_token=request.codex_access_token,
            github_config=request.github_config,
            codex_auth=request.codex_auth,
        )
        return self._finalize_result(result, workspace, run_request)

    def _prepare_workspace(self, request: CodexRunRequest) -> Path:
        self.workspace_root.mkdir(parents=True, exist_ok=True)
        workspace = (self.workspace_root / str(uuid.uuid4())).resolve()
        clone_url = self._clone_url_with_token(request.repository_url, request.github_config)
        self._run_command(
            [
                "git",
                "clone",
                "--branch",
                request.base_branch,
                "--single-branch",
                clone_url,
                str(workspace),
            ],
            cwd=self.workspace_root,
            timeout_seconds=request.timeout_seconds,
            sensitive_values=[request.github_config.get("api_key", "")],
        )
        return workspace

    def _authenticate(
        self,
        workspace: Path,
        codex_auth: dict,
        access_token: str,
        timeout_seconds: float,
    ) -> None:
        """Authenticate the Codex CLI for this run.

        ChatGPT-subscription credentials write ``auth.json`` directly (no per-token API cost);
        access-token credentials use ``codex login --with-access-token``.
        """
        if str((codex_auth or {}).get("auth_mode") or "").strip() == "chatgpt":
            self._write_chatgpt_auth(workspace, codex_auth)
            return
        self._codex_login(workspace, access_token, timeout_seconds)

    def _write_chatgpt_auth(self, workspace: Path, codex_auth: dict) -> None:
        codex_home = workspace / ".codex-home"
        codex_home.mkdir(parents=True, exist_ok=True)
        access_token = str(codex_auth.get("access_token") or "").strip()
        id_token = str(codex_auth.get("id_token") or "").strip()
        if not access_token and not id_token:
            raise ValueError("Codex ChatGPT credential is missing tokens; re-run the sign-in")
        auth_payload = {
            "OPENAI_API_KEY": None,
            "tokens": {
                "id_token": id_token,
                "access_token": access_token,
                "refresh_token": str(codex_auth.get("refresh_token") or ""),
                "account_id": str(codex_auth.get("account_id") or ""),
            },
            "last_refresh": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        }
        auth_path = codex_home / "auth.json"
        auth_path.write_text(json.dumps(auth_payload), encoding="utf-8")
        auth_path.chmod(0o600)

    def _codex_login(self, workspace: Path, access_token: str, timeout_seconds: float) -> None:
        codex_home = workspace / ".codex-home"
        codex_home.mkdir(parents=True, exist_ok=True)
        env = self._codex_env(workspace, access_token)
        try:
            subprocess.run(
                [self.cli_command, "login", "--with-access-token"],
                input=access_token,
                text=True,
                cwd=workspace,
                env=env,
                capture_output=True,
                timeout=min(timeout_seconds, 120),
                check=True,
            )
        except FileNotFoundError as exc:
            raise ValueError("Codex CLI is not installed or not on PATH") from exc
        except subprocess.CalledProcessError as exc:
            raise ValueError(
                self._mask_sensitive(exc.stderr or exc.stdout, [access_token])
            ) from exc

    def _run_setup_command(
        self,
        workspace: Path,
        setup_command: str,
        timeout_seconds: float,
    ) -> None:
        env = self._safe_env()
        self._run_command(
            ["/bin/sh", "-lc", setup_command],
            cwd=workspace,
            timeout_seconds=min(timeout_seconds, 600),
            env=env,
        )

    def _run_codex_exec(
        self,
        *,
        workspace: Path,
        prompt: str,
        timeout_seconds: float,
        resume_thread_id: str | None,
        codex_access_token: str,
    ) -> CodexRunResult:
        schema_path = workspace / ".codex-output-schema.json"
        schema_path.write_text(json.dumps(CODEX_FINAL_OUTPUT_SCHEMA), encoding="utf-8")
        cmd = [self.cli_command, "exec"]
        if resume_thread_id:
            cmd.extend(["resume", resume_thread_id])
        cmd.extend(
            [
                "--json",
                "--output-schema",
                str(schema_path),
                "--sandbox",
                "workspace-write",
                "--ask-for-approval",
                "never",
                prompt,
            ]
        )
        completed = self._run_command(
            cmd,
            cwd=workspace,
            timeout_seconds=timeout_seconds,
            env=self._codex_env(workspace, codex_access_token),
        )
        return self.parser.parse(completed.stdout)

    def _finalize_result(
        self,
        result: CodexRunResult,
        workspace: Path,
        request: CodexRunRequest,
    ) -> CodexRunResult:
        result.workspace_path = str(workspace)
        result.branch_name = request.branch_name
        result.diff = self._git_output(["git", "diff", "--binary"], workspace)
        result.changed_files = self._changed_files(workspace)
        if result.status == "completed" and request.publish_mode == "draft_pr":
            result.pull_request_url = self._publish_draft_pr(workspace, request, result)
        return result

    def _publish_draft_pr(
        self,
        workspace: Path,
        request: CodexRunRequest,
        result: CodexRunResult,
    ) -> str | None:
        if not result.changed_files:
            return None
        self._run_command(["git", "checkout", "-B", request.branch_name], cwd=workspace)
        self._run_command(["git", "add", "-A"], cwd=workspace)
        self._run_command(
            [
                "git",
                "-c",
                "user.name=Heym Codex",
                "-c",
                "user.email=codex@heym.run",
                "commit",
                "-m",
                self._commit_title(result),
            ],
            cwd=workspace,
        )
        remote_url = self._clone_url_with_token(request.repository_url, request.github_config)
        self._run_command(["git", "remote", "set-url", "origin", remote_url], cwd=workspace)
        self._run_command(
            ["git", "push", "-u", "origin", request.branch_name],
            cwd=workspace,
            sensitive_values=[request.github_config.get("api_key", "")],
        )
        owner, repo = self._parse_github_owner_repo(request.repository_url)
        pr = GitHubService(request.github_config).create_pull_request(
            owner,
            repo,
            self._commit_title(result),
            request.branch_name,
            request.base_branch,
            body=result.summary or None,
            draft=True,
        )
        return str(pr.get("html_url") or "").strip() or None

    def _run_command(
        self,
        cmd: list[str],
        *,
        cwd: Path,
        timeout_seconds: float = 600,
        env: dict[str, str] | None = None,
        sensitive_values: list[object] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        try:
            return subprocess.run(
                cmd,
                cwd=cwd,
                env=env if env is not None else self._safe_env(),
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
                check=True,
            )
        except subprocess.TimeoutExpired as exc:
            raise ValueError(f"Command timed out after {timeout_seconds:.0f} seconds") from exc
        except subprocess.CalledProcessError as exc:
            values = [str(v) for v in (sensitive_values or []) if str(v)]
            detail = self._mask_sensitive(exc.stderr or exc.stdout or str(exc), values)
            raise ValueError(detail or "Command failed") from exc

    def _safe_env(self) -> dict[str, str]:
        env = dict(os.environ)
        env.pop("CODEX_ACCESS_TOKEN", None)
        env.pop("OPENAI_API_KEY", None)
        return env

    @staticmethod
    def _exec_token(codex_auth: dict, access_token: str) -> str:
        """Access token to expose to ``codex exec``; empty for ChatGPT mode (uses auth.json)."""
        if str((codex_auth or {}).get("auth_mode") or "").strip() == "chatgpt":
            return ""
        return access_token

    def _codex_env(self, workspace: Path, access_token: str) -> dict[str, str]:
        env = self._safe_env()
        env["CODEX_HOME"] = str(workspace / ".codex-home")
        if access_token:
            env["CODEX_ACCESS_TOKEN"] = access_token
        return env

    def _git_output(self, cmd: list[str], workspace: Path) -> str:
        try:
            completed = subprocess.run(
                cmd,
                cwd=workspace,
                env=self._safe_env(),
                capture_output=True,
                text=True,
                timeout=60,
                check=True,
            )
        except (OSError, subprocess.SubprocessError):
            return ""
        return completed.stdout

    def _changed_files(self, workspace: Path) -> list[str]:
        output = self._git_output(["git", "status", "--short"], workspace)
        return [line[3:].strip() for line in output.splitlines() if line.strip()]

    def cleanup_workspace(self, workspace_path: str | None) -> None:
        if not workspace_path:
            return
        path = Path(workspace_path).resolve()
        root = self.workspace_root.resolve()
        if path == root or root not in path.parents:
            return
        shutil.rmtree(path, ignore_errors=True)

    @staticmethod
    def _build_prompt(task_prompt: str, publish_mode: str) -> str:
        mode_instruction = (
            "Prepare changes only; Heym will create the draft pull request."
            if publish_mode == "draft_pr"
            else "Do not create a pull request or push branches."
        )
        return (
            "You are running as the Heym Codex node inside a local cloned repository.\n"
            f"{mode_instruction}\n"
            "If you need missing requirements, secrets, or a product decision, return "
            "`status: needs_input` with one concise question. Otherwise implement the task "
            "and return `status: completed` with a summary and validation notes.\n\n"
            f"Task:\n{task_prompt}"
        )

    @staticmethod
    def _build_resume_prompt(answer_text: str, publish_mode: str) -> str:
        return (
            "The user answered your previous follow-up question. Continue the same task. "
            "Return `needs_input` only if one more user decision is essential. "
            f"Publish mode: {publish_mode}.\n\nAnswer:\n{answer_text}"
        )

    @staticmethod
    def _commit_title(result: CodexRunResult) -> str:
        summary = re.sub(r"\s+", " ", result.summary).strip()
        if not summary:
            return "Apply Codex changes"
        return summary[:72]

    @staticmethod
    def _clone_url_with_token(repository_url: str, github_config: dict) -> str:
        token = str(github_config.get("api_key") or "").strip()
        if not token:
            return repository_url
        parsed = urlparse(repository_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            return repository_url
        if "@" in parsed.netloc:
            return repository_url
        netloc = f"x-access-token:{quote(token, safe='')}@{parsed.netloc}"
        return urlunparse(parsed._replace(netloc=netloc))

    @staticmethod
    def _parse_github_owner_repo(repository_url: str) -> tuple[str, str]:
        parsed = urlparse(repository_url)
        path = parsed.path.removesuffix(".git").strip("/")
        parts = [part for part in path.split("/") if part]
        if len(parts) < 2:
            raise ValueError("Repository URL must include owner and repository")
        return parts[-2], parts[-1]

    @staticmethod
    def _mask_sensitive(text: str, values: list[object]) -> str:
        masked = text
        for value in values:
            secret = str(value or "")
            if secret:
                masked = masked.replace(secret, "[masked]")
        return masked
