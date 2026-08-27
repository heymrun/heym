"""Where a run may execute in a multi-instance cluster.

Pure module: no database, no settings, no I/O. A node is MAIN_ONLY when it
reads or writes FILE_STORAGE_DIR, leaves state on local disk that a later run
reads back, or depends on something installed per instance. See the placement
rule in AGENTS.md before adding an entry.
"""

from __future__ import annotations

from collections.abc import Callable
from enum import Enum


class Placement(str, Enum):
    MAIN_ONLY = "main_only"
    ANYWHERE = "anywhere"


_MAIN = Placement.MAIN_ONLY
_ANY = Placement.ANYWHERE

# Every node type in node_execution/registry.py appears here. The coverage test
# in tests/test_cluster_node_placement.py fails the build if one is missing.
NODE_PLACEMENT: dict[str, Placement] = {
    "agent": _ANY,  # narrowed to MAIN_ONLY by _agent_placement when skills are attached
    "bigquery": _ANY,
    "chartOutput": _ANY,
    "clickhouse": _ANY,
    "code": _ANY,
    "codex": _MAIN,
    "condition": _ANY,
    "consoleLog": _ANY,
    "converter": _MAIN,
    "crawler": _ANY,
    "cron": _ANY,
    "dataTable": _ANY,
    "disableNode": _ANY,
    "discord": _ANY,
    "discordTrigger": _ANY,
    "drive": _MAIN,
    "errorHandler": _ANY,
    "execute": _ANY,
    "fileUploadTrigger": _MAIN,
    "github": _ANY,
    "googleDrive": _MAIN,
    "googleSheets": _ANY,
    "grist": _ANY,
    "heym": _ANY,
    "heymTrigger": _ANY,
    "htmlOutputMapper": _ANY,
    "http": _ANY,
    "imapTrigger": _ANY,
    "jira": _ANY,
    "jsonOutputMapper": _ANY,
    "linear": _ANY,
    "llm": _ANY,
    "loop": _ANY,
    "mcpCall": _ANY,
    "merge": _ANY,
    "notion": _ANY,
    "opencodeGo": _MAIN,
    "output": _ANY,
    "playwright": _ANY,
    "plugin": _MAIN,
    "pluginTrigger": _MAIN,
    "rabbitmq": _ANY,
    "rag": _ANY,
    "redis": _ANY,
    "s3": _ANY,
    "sendEmail": _MAIN,
    "sentry": _ANY,
    "set": _ANY,
    "slack": _ANY,
    "slackTrigger": _ANY,
    "sticky": _ANY,
    "supabase": _ANY,
    "switch": _ANY,
    "telegram": _ANY,
    "telegramTrigger": _ANY,
    "textInput": _ANY,
    "throwError": _ANY,
    "variable": _ANY,
    "wait": _ANY,
    "websocketSend": _ANY,
    "websocketTrigger": _ANY,
}


def _agent_placement(data: dict) -> Placement:
    """An agent pins the run only when a skill is attached.

    Skill code reads and writes Heym Drive through _load_skill_drive_files /
    _persist_skill_files in llm_service.py. Python tools, MCP tools and
    sub-workflow tools have no local file dependency.
    """
    return _MAIN if (data.get("skills") or []) else _ANY


_CONDITIONAL: dict[str, Callable[[dict], Placement]] = {"agent": _agent_placement}


def node_placement(node: dict) -> Placement:
    """Where this single node may run. An unlisted type is MAIN_ONLY.

    Unlisted means a plugin-provided type, which is loaded per instance and
    therefore main-only anyway. Registry types can never be unlisted: the
    coverage test fails the build first.
    """
    node_type = str(node.get("type") or "")
    data = node.get("data") or {}
    conditional = _CONDITIONAL.get(node_type)
    if conditional is not None:
        return conditional(data)
    return NODE_PLACEMENT.get(node_type, _MAIN)


def _sub_workflow_ids(node: dict) -> list[str]:
    """Workflow ids this node can reach."""
    node_type = str(node.get("type") or "")
    data = node.get("data") or {}
    if node_type == "execute":
        target = str(data.get("executeWorkflowId") or "")
        return [target] if target else []
    if node_type == "agent":
        return [wid for wid in (data.get("subWorkflowIds") or []) if isinstance(wid, str)]
    return []


def workflow_placement(
    nodes: list[dict],
    *,
    resolve_workflow: Callable[[str], list[dict] | None],
    _seen: frozenset[str] = frozenset(),
) -> Placement:
    """Where a whole graph may run, following sub-workflows.

    One MAIN_ONLY node anywhere in the reachable graph pins the entire run. A
    target that cannot be resolved statically - an expression, or a workflow the
    caller could not load - also pins it, because its contents are unknown.
    """
    for node in nodes:
        if node_placement(node) is _MAIN:
            return _MAIN
        for wf_id in _sub_workflow_ids(node):
            if "$" in wf_id:
                return _MAIN
            if wf_id in _seen:
                continue
            sub_nodes = resolve_workflow(wf_id)
            if sub_nodes is None:
                return _MAIN
            if (
                workflow_placement(
                    sub_nodes, resolve_workflow=resolve_workflow, _seen=_seen | {wf_id}
                )
                is _MAIN
            ):
                return _MAIN
    return _ANY
