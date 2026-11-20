"""A chat that carries a skill: run that skill in Heym, or convert it and run it.

When the user attaches a skill and asks to use it, the job is the skill's own result, not
a new workflow. ``apply_skill`` puts the skill on Request -> Agent -> Result; the turn may
tune those nodes, change the skill's own files (``apply_skill`` with ``file_edits``) and
run it, but ``save_workflow`` refuses a new workflow, an added or removed node, and an agent
that loses the skill. The rules hold for every later message of that chat, not only the one
that carried the zip: the chat build session reads the skill names from the stored
attachment blocks and calls ``skill_save_problem`` before a save.

The one new workflow such a chat may build is a page loader the user asked for: only input,
fetch and data shaping nodes, nothing that runs a model or code. A loader cannot write a
document, so it cannot stand in for the skill.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from app.services.chat_message_edit import attachment_blocks
from app.services.skill_archive import ZIP_BLOCK_HEADER, skill_names_in_zip_block

CREATE_REFUSED = (
    "This chat uses the attached skill. Do not build a workflow for it: call apply_skill to "
    "put the skill on an agent, then run it with run_workflow_test. The only new workflow "
    "allowed here is a page loader the user asked for (see the page loader rule). To build "
    "something else, the user can start a new chat."
)
LOADER_REFUSED = (
    "This workflow is a page loader in a chat that uses a skill, and it must stay one "
    "(see the page loader rule)."
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

# A page loader reads pages and shapes their text; nothing in it runs a model or code.
LOADER_NODE_TYPES = frozenset(
    {
        "textInput",
        "http",
        "playwright",
        "crawler",
        "set",
        "variable",
        "loop",
        "merge",
        "condition",
        "sticky",
        "output",
    }
)
FETCH_NODE_TYPES = frozenset({"http", "playwright", "crawler"})
LOADER_RULE = (
    "Page loader rule: a new workflow in this chat may only load web pages. Its nodes are "
    "Text Input, HTTP, Playwright (steps only: no custom code, no AI step), Crawler, Set, "
    "Variable, Loop, Merge, Condition, Sticky note and Output, with at least one HTTP, "
    "Playwright or Crawler node. No agent, LLM, code or other node."
)


def _data(node: dict[str, Any]) -> dict[str, Any]:
    data = node.get("data")
    return data if isinstance(data, dict) else {}


def _label(node: dict[str, Any]) -> str:
    return str(_data(node).get("label") or node.get("id") or "a node")


def _playwright_problem(node: dict[str, Any]) -> str | None:
    data = _data(node)
    mode = str(data.get("playwrightMode") or "").strip().lower()
    if mode == "code" or str(data.get("playwrightCode") or "").strip():
        return f"Playwright node '{_label(node)}' runs custom code; use steps instead."
    for key in ("playwrightSteps", "playwrightAuthFallbackSteps"):
        steps = data.get(key)
        for step in steps if isinstance(steps, list) else []:
            if isinstance(step, dict) and step.get("action") == "aiStep":
                return f"Playwright node '{_label(node)}' has an AI step; use plain steps."
    return None


def page_loader_problem(nodes: list[dict[str, Any]]) -> str | None:
    """Why ``nodes`` are not a page loader, or None when they are one."""
    fetches = False
    for node in nodes:
        node_type = str(node.get("type") or "")
        if node_type not in LOADER_NODE_TYPES:
            return f"'{_label(node)}' is a {node_type or 'untyped'} node. {LOADER_RULE}"
        if _data(node).get("skills"):
            return f"'{_label(node)}' carries a skill. {LOADER_RULE}"
        if node_type == "playwright":
            problem = _playwright_problem(node)
            if problem is not None:
                return f"{problem} {LOADER_RULE}"
        fetches = fetches or node_type in FETCH_NODE_TYPES
    if not fetches:
        return f"It loads no page. {LOADER_RULE}"
    return None


def conversation_skill_names(user_messages: Iterable[str]) -> list[str]:
    """The skills earlier messages of a chat attached, read from their stored zip blocks."""
    names: list[str] = []
    for content in user_messages:
        for block in attachment_blocks(content):
            if not block.lstrip("\n").startswith(ZIP_BLOCK_HEADER):
                continue
            for name in skill_names_in_zip_block(block):
                if name not in names:
                    names.append(name)
    return names


def _shape(nodes: list[dict[str, Any]]) -> set[tuple[str, str]]:
    return {(str(node.get("id") or ""), str(node.get("type") or "")) for node in nodes}


def _skill_names(nodes: list[dict[str, Any]]) -> set[str]:
    names: set[str] = set()
    for node in nodes:
        for skill in _data(node).get("skills") or []:
            if isinstance(skill, dict) and isinstance(skill.get("name"), str):
                names.add(skill["name"].strip().casefold())
    return names


def skill_save_problem(
    previous_nodes: list[dict[str, Any]] | None, nodes: list[dict[str, Any]]
) -> str | None:
    """Why ``save_workflow`` is refused in a skill chat, or None when the save may go on."""
    if previous_nodes is None:
        problem = page_loader_problem(nodes)
        return None if problem is None else f"{CREATE_REFUSED} {problem}"
    if page_loader_problem(previous_nodes) is None:
        problem = page_loader_problem(nodes)
        return None if problem is None else f"{LOADER_REFUSED} {problem}"
    if _shape(previous_nodes) != _shape(nodes):
        return SHAPE_REFUSED
    if not _skill_names(previous_nodes) <= _skill_names(nodes):
        return DROP_REFUSED
    return None


def skill_use_instructions(skill_names: list[str]) -> str:
    """The rules for a chat whose messages carry a skill the user wants used."""
    names = ", ".join(skill_names) or "the attached skill"
    lines = [
        "",
        "## Using the attached skill",
        "",
        f"This chat carries a skill ({names}). The user wants that skill used for their "
        "request, inside Heym. Do this:",
        "1. Call apply_skill. It puts the skill on a Request -> Agent -> Result workflow.",
        "2. When the user names something to read first (a website or page, a file), get it "
        "before the skill runs. An attached file: use it. A web page: run a page loader from "
        "the workflow list with that URL, once, and put the page text it returns into the "
        "Request text. A page loader is a workflow whose name or description says it loads, "
        "fetches, scrapes or crawls a web page and returns the page's content. A workflow "
        "made for another job is not one, even when it reads pages on the way: never run "
        "Skill Discover, or any workflow that searches, discovers, reviews or answers in its "
        "own format, to get a page. When the list has no page loader, or the loader you ran "
        "did not return the page text, stop before running the skill: say in one sentence "
        "that no workflow here can load that page, and ask the user to paste its text, "
        "attach it as a file, or let you build a page loader. Never stand in for the "
        "page with search_documentation, Heym's documentation or your own knowledge.",
        "3. Call run_workflow_test with the user's request (and what you gathered) as the "
        "Request text. The agent runs the skill's Python scripts through its skill tool "
        "(script and args); there is no shell, Node.js, npm or LibreOffice. Calls in one run "
        "share a folder, so a later call can check or convert a file an earlier call made.",
        "4. Answer from the run: what the skill produced, with the file links from its output.",
        "",
        "Never build another workflow for the request and never add, remove or replace nodes: "
        "no HTTP, Code, LLM, loop or other steps around or instead of the skill. save_workflow "
        "refuses that in this chat; it may only change the settings of the skill workflow's "
        "nodes. run_python is off in this chat: the skill makes the files, not your own code.",
        "",
        f"{LOADER_RULE} Build a page loader only when the user asks for one. Test it with "
        "run_workflow_test, then run it with execute_workflow and the URL, and go on with "
        "step 3 in the same reply; do not call finish before the skill has run.",
        "",
        "These rules hold for every later message in this chat. The skill workflow from "
        "apply_skill already exists then (its id is in the conversation): run it with "
        "execute_workflow, or change the skill's files with apply_skill (workflow_id and "
        "file_edits) and run it with run_workflow_test.",
        "",
        "When the skill cannot run in Heym as it is written (it needs a shell, Node.js, npm or "
        "LibreOffice, it has no Python entry point for the request, a library it imports is "
        "missing, or its run fails for that reason), convert the skill itself with apply_skill "
        "file_edits, then run again:",
        "- main.py reads the request from standard input, does the job with Python libraries "
        "in the sandbox, writes the files the user should receive into the folder named by the "
        "_OUTPUT_DIR environment variable and prints a short JSON result. When the input is "
        "empty or --help is passed, it prints a one-line usage and exits with code 2 without "
        "writing any file; it never writes a placeholder or empty document.",
        "- Rewrite SKILL.md for Heym: say what main.py takes and returns, keep the skill's "
        "guidance that still applies (structure, style, rules), and remove every step that "
        "needs a shell, Node.js, npm, LibreOffice or another tool the sandbox lacks, so the "
        "agent does not try them. If apply_skill answers with unchanged_files, that edit "
        "changed nothing: send the new text.",
        "",
        "When the test runs are spent, tell the user what still fails. Do not fall back to "
        "another approach.",
    ]
    return "\n".join(lines) + "\n"
