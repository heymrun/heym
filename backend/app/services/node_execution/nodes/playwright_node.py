"""Playwright node execution.

Owns everything specific to the ``playwright`` node: script assembly, the scrubbed
subprocess environment, auth-state resolution, and the sandbox/subprocess run. The
executor keeps only orchestration, so this module reaches back through
``NodeExecutionContext.executor`` for shared services such as expression resolution
and cancellation.
"""

from __future__ import annotations

import copy
import json
import os
import time
from typing import TYPE_CHECKING

from app.services.node_execution.base import NodeExecutionContext

if TYPE_CHECKING:
    from app.services.workflow_executor import WorkflowExecutor


def _build_playwright_script(
    user_code: str,
    inputs: dict,
    headless: bool = True,
    timeout_ms: int = 30000,
    capture_network: bool = False,
    heym_api_url: str = "",
    heym_execution_token: str = "",
) -> str:
    """Wrap user Playwright code with imports and inputs."""
    # ascii() keeps JSON's true/false/null out of the script: they are not Python literals.
    inputs_py = ascii(json.loads(json.dumps(inputs)))
    headless_py = repr(headless)  # True/False for Python, not json true/false
    capture_network_py = repr(capture_network)
    api_url_py = repr(heym_api_url)
    token_py = repr(heym_execution_token)
    return f"""import json
import sys

inputs = {inputs_py}
headless = {headless_py}
timeout_ms = {timeout_ms}
capture_network = {capture_network_py}
_heym_api_url = {api_url_py}
_heym_execution_token = {token_py}

try:
{_indent(user_code, 4)}
except Exception as e:
    print(json.dumps({{"status": "error", "error": str(e)}}), file=sys.stderr)
    sys.exit(1)
"""


def _indent(text: str, spaces: int) -> str:
    prefix = " " * spaces
    return "\n".join(prefix + line for line in text.splitlines())


# Environment variables the Playwright subprocess is allowed to inherit. Everything else
# (SECRET_KEY, ENCRYPTION_KEY, DATABASE_URL, provider API keys, ...) is stripped so a
# Playwright script cannot read backend secrets straight out of its own environment.
# The AI-step API URL and execution token are baked into the generated script, not passed
# via the environment, so this allowlist does not break AI steps.
_PLAYWRIGHT_ENV_ALLOWLIST = frozenset(
    {
        "PATH",
        "HOME",
        "LANG",
        "LC_ALL",
        "LC_CTYPE",
        "TZ",
        "DISPLAY",
        "TMPDIR",
        "TEMP",
        "TMP",
        "USER",
        "LOGNAME",
        "SHELL",
        # Windows essentials
        "SYSTEMROOT",
        "WINDIR",
        "PATHEXT",
        "COMSPEC",
    }
)


def _scrubbed_playwright_subprocess_env() -> dict[str, str]:
    """Build a minimal environment for the Playwright subprocess without backend secrets.

    Keeps only OS essentials plus any ``PLAYWRIGHT_*`` variables (browser cache path, etc.)
    so browser launch keeps working while secrets stay out of the child process.
    """
    env: dict[str, str] = {
        key: value for key, value in os.environ.items() if key in _PLAYWRIGHT_ENV_ALLOWLIST
    }
    for key, value in os.environ.items():
        if key.startswith("PLAYWRIGHT_"):
            env[key] = value
    return env


def _resolve_expressions_in_code(
    executor: WorkflowExecutor, code: str, inputs: dict, node_id: str
) -> str:
    """Replace Heym expressions ($node.field) in Python code with resolved values."""
    import re

    def replace_expr(match: re.Match) -> str:
        expr = match.group(1)
        try:
            resolved = executor.resolve_expression("$" + expr, inputs, node_id, preserve_type=True)
            if isinstance(resolved, str):
                return repr(resolved)
            return repr(resolved)
        except Exception:
            return match.group(0)

    return re.sub(r"\$([a-zA-Z_][a-zA-Z0-9_.]*)", replace_expr, code)


def _resolve_playwright_auth_state(
    executor: WorkflowExecutor,
    auth_state_expression: str,
    inputs: dict,
    node_id: str,
) -> dict[str, object] | None:
    """Resolve and normalize Playwright auth state from an expression or raw JSON."""
    from app.services.playwright_code_generator import normalize_playwright_auth_state

    if not auth_state_expression or not str(auth_state_expression).strip():
        return None

    expr = str(auth_state_expression).strip()
    if expr.startswith("$") and " " not in expr:
        resolved = executor.resolve_expression(expr, inputs, node_id, preserve_type=True)
    else:
        resolved = executor._resolve_template(expr, inputs, node_id)
    return normalize_playwright_auth_state(resolved)


def _playwright_subprocess_inputs(executor: WorkflowExecutor, inputs: dict) -> dict:
    """Copy of node inputs plus ``vars``/``global`` so step fields resolve in the subprocess.

    Template/expression evaluation uses ``_build_context``, which already exposes ``vars``
    from ``executor.vars`` and ``global`` from the global variables merged with ``executor.vars``.
    Generated Playwright code reads a flat ``inputs`` dict only, so both namespaces must be
    injected before serializing to the runner. Without them a field like
    ``$global.secondPage`` compiles to a lookup that misses and silently falls back to the
    generator's placeholder default. Credentials stay out on purpose.
    """
    out = copy.deepcopy(inputs)
    executor._refresh_vars_context_cache()
    namespaces = {
        "vars": copy.deepcopy(executor.vars),
        "global": copy.deepcopy(executor._merged_global_context_cache or {}),
    }
    for name, values in namespaces.items():
        existing = out.get(name)
        if isinstance(existing, dict):
            out[name] = {**existing, **values}
        else:
            out[name] = values
    return out


def _execute_playwright_node(
    executor: WorkflowExecutor,
    node_data: dict,
    inputs: dict,
    node_id: str,
    node_label: str,
) -> dict:
    from app.services.playwright_code_generator import active_steps, generate_playwright_code
    from app.services.playwright_execution_tokens import create_token

    # Steps toggled off in the editor never reach validation or code generation.
    configured_steps = node_data.get("playwrightSteps") or []
    steps = active_steps(configured_steps)
    auth_enabled = node_data.get("playwrightAuthEnabled", False) is True
    playwright_code = node_data.get("playwrightCode", "").strip()
    playwright_mode = str(node_data.get("playwrightMode") or "").strip().lower()
    capture_network = node_data.get("playwrightCaptureNetwork", False)
    auth_state: dict[str, object] | None = None
    auth_check_selector = ""
    auth_check_timeout = 5000
    configured_fallback_steps = node_data.get("playwrightAuthFallbackSteps") or []

    # Mode "code" forces the custom playwrightCode path. Legacy nodes without
    # playwrightMode still use custom code when steps are empty and code is set.
    use_custom_code = playwright_mode == "code" or (
        playwright_mode != "steps" and not configured_steps and bool(playwright_code)
    )

    if auth_enabled:
        if use_custom_code:
            raise ValueError(
                "Playwright auth bootstrap requires step-based execution. Custom code is not supported."
            )
        if not steps:
            raise ValueError(
                "Playwright auth bootstrap requires step-based execution. Custom code is not supported."
            )
        if steps[0].get("action") != "navigate":
            raise ValueError(
                "Playwright auth bootstrap requires the first Playwright step to be a navigate action."
            )

        auth_check_selector = executor._resolve_template(
            str(node_data.get("playwrightAuthCheckSelector", "") or ""),
            inputs,
            node_id,
        ).strip()
        if not auth_check_selector:
            raise ValueError(
                "Playwright auth bootstrap requires an authenticated selector to verify login."
            )

        raw_auth_check_timeout = node_data.get("playwrightAuthCheckTimeout", 5000)
        try:
            auth_check_timeout = max(1, int(raw_auth_check_timeout))
        except (TypeError, ValueError):
            auth_check_timeout = 5000

        auth_state_expression = str(node_data.get("playwrightAuthStateExpression", "") or "")
        auth_state = _resolve_playwright_auth_state(
            executor,
            auth_state_expression,
            inputs,
            node_id,
        )

    is_custom_code = False
    if use_custom_code:
        # Custom code path: `playwrightCode` is attacker-controllable Python. Fail closed
        # unless an operator has explicitly opted in. Checked here at the execution sink so
        # it also covers already-stored workflows and cron / sub-workflow / anonymous
        # execution paths, not just the update endpoint. When enabled it runs in a hardened
        # isolated container (see below), not the backend process.
        is_custom_code = True
        if not playwright_code:
            raise ValueError(
                "Playwright Run Code mode requires playwrightCode. Paste Playwright Python "
                "or switch Mode back to Steps."
            )
        from app.config import settings

        if not settings.playwright_custom_code_enabled:
            raise ValueError(
                "Custom Playwright code execution is disabled. This field runs arbitrary "
                "Python and is off by default. Use step-based Playwright actions instead, "
                "or have an administrator set HEYM_PLAYWRIGHT_CUSTOM_CODE_ENABLED=true "
                "to enable it (only on trusted, isolated deployments)."
            )
    elif steps:
        # The generator drops disabled steps itself and keeps the stored index,
        # which is the key a run reports back in output["saveSteps"].
        playwright_code = generate_playwright_code(
            configured_steps,
            capture_network=capture_network,
            auth_enabled=auth_enabled,
            auth_state=auth_state,
            auth_check_selector=auth_check_selector,
            auth_check_timeout=auth_check_timeout,
            auth_fallback_steps=configured_fallback_steps,
            stealth=node_data.get("playwrightStealth", False),
        )
    elif configured_steps:
        raise ValueError(
            "Every Playwright step is disabled. Enable at least one step to run this node."
        )
    else:
        raise ValueError(
            "Playwright node requires steps. Add at least one step (navigate, click, etc.)."
        )

    headless = node_data.get("playwrightHeadless", True)
    # In Docker/headless environments (no DISPLAY), force headless to avoid "Missing X server" errors
    if not os.environ.get("DISPLAY"):
        headless = True
    timeout_ms = node_data.get("playwrightTimeout", 30000)

    has_ai_steps = any(s.get("action") == "aiStep" for s in steps)
    heym_api_url = ""
    heym_execution_token = ""
    if has_ai_steps:
        if not executor.trace_user_id:
            raise ValueError(
                "Playwright AI step requires workflow execution context (trace_user_id). "
                "AI steps cannot run in anonymous or cron-triggered workflows without user context."
            )
        heym_api_url = os.environ.get("HEYM_API_URL", "http://localhost:10105")
        heym_execution_token = create_token(str(executor.trace_user_id))

    import subprocess
    import sys
    import tempfile

    from app.services import playwright_sandbox

    playwright_inputs = _playwright_subprocess_inputs(executor, inputs)
    resolved_code = _resolve_expressions_in_code(
        executor, playwright_code, playwright_inputs, node_id
    )
    script_content = _build_playwright_script(
        resolved_code,
        playwright_inputs,
        headless=headless,
        timeout_ms=timeout_ms,
        capture_network=capture_network,
        heym_api_url=heym_api_url,
        heym_execution_token=heym_execution_token,
    )

    # playwrightTimeout = total max execution time (ms), enforced strictly.
    subprocess_timeout = max(timeout_ms / 1000, 10)

    # Untrusted custom code runs in a hardened, isolated sibling container (fail closed),
    # never in the backend process. Step-based scripts are fully generated by Heym (no
    # arbitrary code) and keep running in-process. HEYM_PLAYWRIGHT_SANDBOX=subprocess opts
    # custom code back into the in-process path for trusted / local-dev use only.
    if is_custom_code and playwright_sandbox.sandbox_mode() != "subprocess":
        try:
            returncode, sandbox_stdout, sandbox_stderr = playwright_sandbox.run_script(
                script_content, subprocess_timeout
            )
        except playwright_sandbox.PlaywrightSandboxUnavailableError as exc:
            raise ValueError(str(exc)) from exc
        except TimeoutError as exc:
            raise ValueError(str(exc)) from exc
        executor.check_cancelled()
        if returncode != 0:
            raise ValueError(
                f"Playwright script failed: {sandbox_stderr or sandbox_stdout or 'Unknown error'}"
            )
        output_str = sandbox_stdout.strip()
        if not output_str:
            return {"status": "ok", "results": {}}
        try:
            return json.loads(output_str)
        except json.JSONDecodeError:
            return {"status": "ok", "results": {"raw": output_str}}

    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
        f.write(script_content)
        script_path = f.name
    stdout_file = tempfile.NamedTemporaryFile(mode="w+", suffix=".playwright.out", delete=False)
    stderr_file = tempfile.NamedTemporaryFile(mode="w+", suffix=".playwright.err", delete=False)
    stdout_path = stdout_file.name
    stderr_path = stderr_file.name

    try:
        popen_kwargs: dict[str, object] = {
            "stdout": stdout_file,
            "stderr": stderr_file,
            "text": True,
            # Strip backend secrets from the child environment (defense in depth).
            "env": _scrubbed_playwright_subprocess_env(),
        }
        if os.name == "nt":
            popen_kwargs["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        else:
            popen_kwargs["start_new_session"] = True

        process = subprocess.Popen(
            [sys.executable, script_path],
            **popen_kwargs,
        )
        started_at = time.monotonic()
        timed_out = False

        while process.poll() is None:
            if executor.cancel_event is not None and executor.cancel_event.is_set():
                executor._terminate_subprocess(process)
                executor.check_cancelled()

            if time.monotonic() - started_at >= subprocess_timeout:
                timed_out = True
                executor._terminate_subprocess(process)
                break

            time.sleep(0.1)

        stdout_file.flush()
        stderr_file.flush()
        stdout_file.close()
        stderr_file.close()
        stdout = ""
        stderr = ""
        try:
            with open(stdout_path, encoding="utf-8") as stdout_reader:
                stdout = stdout_reader.read()
        except OSError:
            stdout = ""
        try:
            with open(stderr_path, encoding="utf-8") as stderr_reader:
                stderr = stderr_reader.read()
        except OSError:
            stderr = ""
        executor.check_cancelled()

        if timed_out:
            raise ValueError(f"Playwright script timed out after {subprocess_timeout:.1f} seconds")

        if process.returncode != 0:
            raise ValueError(f"Playwright script failed: {stderr or stdout or 'Unknown error'}")

        output_str = stdout.strip()
        if not output_str:
            return {"status": "ok", "results": {}}

        try:
            output = json.loads(output_str)
        except json.JSONDecodeError:
            return {"status": "ok", "results": {"raw": output_str}}

        return output
    finally:
        for temp_path in (stdout_path, stderr_path, script_path):
            try:
                os.unlink(temp_path)
            except OSError:
                pass
        if not stdout_file.closed:
            stdout_file.close()
        if not stderr_file.closed:
            stderr_file.close()


def execute(ctx: NodeExecutionContext) -> object:
    """Execute the playwright node."""
    return _execute_playwright_node(
        ctx.executor,
        ctx.node_data,
        ctx.inputs,
        ctx.node_id,
        ctx.node_label,
    )
