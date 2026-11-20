"""A chat turn that carries a skill: run that skill in Heym, or convert it and run it.

When the user attaches a skill and asks to use it, the job is the skill's own result, not
a new workflow. ``apply_skill`` puts the skill on Request -> Agent -> Result; the turn may
tune those nodes, change the skill's own files (``apply_skill`` with ``file_edits``) and
run it, but ``save_workflow`` refuses a new workflow, an added or removed node, and an agent
that loses the skill. The chat build session calls ``skill_save_problem`` before a save.
"""

from __future__ import annotations

from typing import Any

CREATE_REFUSED = (
    "This turn uses the attached skill. Do not build a workflow for it: call apply_skill to "
    "put the skill on an agent, then run it with run_workflow_test."
)
SHAPE_REFUSED = (
    "This workflow runs the attached skill: keep its nodes as they are (you may change their "
    "settings). To make the skill work in Heym, change the skill's own files with "
    "apply_skill file_edits, then run it again."
)
DROP_REFUSED = (
    "This workflow runs the attached skill: keep the skill on its agent. To change what it "
    "does, edit the skill's own files with apply_skill file_edits."
)


def _shape(nodes: list[dict[str, Any]]) -> set[tuple[str, str]]:
    return {(str(node.get("id") or ""), str(node.get("type") or "")) for node in nodes}


def _skill_names(nodes: list[dict[str, Any]]) -> set[str]:
    names: set[str] = set()
    for node in nodes:
        data = node.get("data") if isinstance(node.get("data"), dict) else {}
        for skill in data.get("skills") or []:
            if isinstance(skill, dict) and isinstance(skill.get("name"), str):
                names.add(skill["name"].strip().casefold())
    return names


def skill_save_problem(
    previous_nodes: list[dict[str, Any]] | None, nodes: list[dict[str, Any]]
) -> str | None:
    """Why ``save_workflow`` is refused in a skill turn, or None when the save may go on."""
    if previous_nodes is None:
        return CREATE_REFUSED
    if _shape(previous_nodes) != _shape(nodes):
        return SHAPE_REFUSED
    if not _skill_names(previous_nodes) <= _skill_names(nodes):
        return DROP_REFUSED
    return None


def skill_use_instructions(skill_names: list[str]) -> str:
    """The rules for a turn whose message carries a skill the user wants used."""
    names = ", ".join(skill_names) or "the attached skill"
    lines = [
        "",
        "## Using the attached skill",
        "",
        f"This message carries a skill ({names}). The user wants that skill used for their "
        "request, inside Heym. Do this:",
        "1. Call apply_skill. It puts the skill on a Request -> Agent -> Result workflow.",
        "2. Call run_workflow_test with the user's request as the Request text. The agent runs "
        "the skill's Python scripts through its skill tool (script and args); there is no "
        "shell, Node.js, npm or LibreOffice. Put what the request needs (page text, facts, "
        "data from an existing workflow or tool) into that text.",
        "3. Answer from the run: what the skill produced, with the file links from its output.",
        "",
        "Never build another workflow for the request and never add, remove or replace nodes: "
        "no HTTP, Code, LLM, loop or other steps around or instead of the skill. save_workflow "
        "refuses that in this turn; it may only change the settings of the skill workflow's "
        "nodes.",
        "",
        "When the skill cannot run in Heym as it is written (it needs a shell, Node.js, npm or "
        "LibreOffice, it has no Python entry point for the request, or its run fails for that "
        "reason), convert the skill itself with apply_skill file_edits: add a main.py that "
        "reads the request from standard input, does the job with Python libraries in the "
        "sandbox, writes the files the user should receive into the folder named by the "
        "_OUTPUT_DIR environment variable and prints a short JSON result; then say in "
        "SKILL.md that main.py does it, and run again. When the test runs are spent, tell the "
        "user what still fails. Do not fall back to another approach.",
    ]
    return "\n".join(lines) + "\n"
