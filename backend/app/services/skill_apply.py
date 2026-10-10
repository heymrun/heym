"""Place a skill bundle onto a workflow's agent nodes.

Match by skill name updates that skill and leaves every other skill in place. A name
that matches nothing is added. Several agents and no matching name is a choice, not a
guess. Files the edit does not mention stay, including Python the model never saw.
"""

from __future__ import annotations

import copy
import uuid
from dataclasses import dataclass
from typing import Any, Literal

from app.services.skill_archive import ArchiveFile, SkillBundle

Status = Literal["saved", "needs_choice", "error"]


@dataclass(frozen=True)
class FileEdit:
    """One file the conversation wants to change. ``SKILL.md`` is the skill body."""

    path: str
    content: str


@dataclass(frozen=True)
class SkillPlacement:
    """The nodes to store, or a choice or error the model must surface before saving."""

    status: Status
    nodes: list[dict[str, Any]] | None = None
    message: str = ""
    agents: tuple[dict[str, Any], ...] = ()


def skill_write_instructions(target_name: str | None, target_id: uuid.UUID | None) -> str:
    """What the model needs in order to call ``apply_skill`` and nothing broader."""
    lines = [
        "",
        "## Skills",
        "",
        "You can create or update an agent skill with apply_skill. A skill is a SKILL.md "
        "file and any Python files beside it. The server stores those files. Pass file_edits "
        "only for files whose text should change. Omit a file to leave it as it is.",
        "",
        "When a zip in this turn has a SKILL.md, apply_skill writes that skill. Match an "
        "existing skill by its name: the same name updates it, a new name adds it, and other "
        "skills stay. When more than one agent could take a new skill, apply_skill refuses "
        "and lists the agents. Ask which agent, then call it again with that agent_id. "
        "Do not save until it answers.",
        "",
        "With no workflow on this turn and no workflow_id, a skill zip starts a new workflow "
        "with one agent that carries the skill. To change a skill you already saved in this "
        "conversation, pass its workflow_id.",
    ]
    if target_id is not None:
        lines += [
            "",
            f'This turn updates "{target_name or "Untitled"}" ({target_id}). '
            "apply_skill writes that workflow. Do not create a second one.",
        ]
    return "\n".join(lines) + "\n"


def _is_agent(node: dict[str, Any]) -> bool:
    data = node.get("data") if isinstance(node.get("data"), dict) else {}
    return node.get("type") == "agent" or data.get("nodeType") == "agent"


def _skill_name(skill: dict[str, Any]) -> str:
    name = skill.get("name")
    return name.strip() if isinstance(name, str) else ""


def _agent_rows(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for node in nodes:
        if not _is_agent(node):
            continue
        data = node.get("data") if isinstance(node.get("data"), dict) else {}
        skills = data.get("skills") if isinstance(data.get("skills"), list) else []
        label = data.get("label") if isinstance(data.get("label"), str) else ""
        rows.append(
            {
                "id": str(node.get("id") or ""),
                "label": label or str(node.get("id") or "agent"),
                "skills": [_skill_name(skill) for skill in skills if isinstance(skill, dict)],
            }
        )
    return rows


def _same(left: str, right: str) -> bool:
    return left.strip().casefold() == right.strip().casefold()


def _is_skill_markdown(path: str) -> bool:
    leaf = path.replace("\\", "/").rsplit("/", 1)[-1]
    return leaf.casefold() == "skill.md"


def _editable(path: str) -> bool:
    return path.lower().endswith((".md", ".py")) and not _is_skill_markdown(path)


def overlay(bundle: SkillBundle | None, edits: list[FileEdit], *, name: str) -> SkillBundle:
    """The skill to write: the bundle, then any file edits on top."""
    content = bundle.content if bundle is not None else ""
    files = {item.path: item.content for item in bundle.files} if bundle is not None else {}
    for edit in edits:
        path = edit.path.replace("\\", "/").strip().lstrip("/")
        if not path or ".." in path.split("/"):
            continue
        if _is_skill_markdown(path):
            content = edit.content
        elif _editable(path):
            files[path] = edit.content
    return SkillBundle(
        name=name,
        content=content,
        files=tuple(ArchiveFile(path, text) for path, text in files.items()),
        directory="",
    )


def _record(existing: dict[str, Any] | None, bundle: SkillBundle) -> dict[str, Any]:
    """A skill object. Files already stored and absent from the bundle stay."""
    current = existing if isinstance(existing, dict) else {}
    kept: list[dict[str, Any]] = []
    incoming = {item.path: item.content for item in bundle.files}
    for item in current.get("files") or []:
        if not isinstance(item, dict):
            continue
        path = item.get("path")
        if not isinstance(path, str) or path in incoming or path.lower().endswith((".md", ".py")):
            continue
        kept.append(item)
    files = kept + [
        {"path": item.path, "content": item.content, "encoding": "text"} for item in bundle.files
    ]
    record = {
        "id": str(current.get("id") or uuid.uuid4()),
        "name": bundle.name,
        "content": bundle.content,
        "files": files,
    }
    for key in ("timeoutSeconds", "driveFilesEnabled"):
        if key in current:
            record[key] = current[key]
    return record


def _matches(
    nodes: list[dict[str, Any]], name: str, agent_id: str | None
) -> list[tuple[dict[str, Any], int]]:
    found: list[tuple[dict[str, Any], int]] = []
    for node in nodes:
        if not _is_agent(node):
            continue
        if agent_id is not None and str(node.get("id") or "") != agent_id:
            continue
        skills = (node.get("data") or {}).get("skills")
        if not isinstance(skills, list):
            continue
        for index, skill in enumerate(skills):
            if isinstance(skill, dict) and _same(_skill_name(skill), name):
                found.append((node, index))
    return found


def place_skill(
    nodes: list[dict[str, Any]],
    bundle: SkillBundle | None,
    *,
    agent_id: str | None = None,
    skill_name: str | None = None,
    edits: list[FileEdit] | None = None,
) -> SkillPlacement:
    """Update or add one skill. The returned nodes are copies."""
    edits = edits or []
    name = (skill_name or (bundle.name if bundle is not None else "")).strip()
    if bundle is None and not edits:
        return SkillPlacement(
            status="error", message="Nothing to write. Attach a skill zip or pass file_edits."
        )
    if not name:
        return SkillPlacement(status="error", message="Name the skill to update.")

    agents = [node for node in nodes if _is_agent(node)]
    if agent_id is not None and not any(str(node.get("id") or "") == agent_id for node in agents):
        return SkillPlacement(status="error", message="That agent is not on this workflow.")

    matches = _matches(nodes, name, agent_id)
    if len(matches) > 1:
        return SkillPlacement(
            status="needs_choice",
            message="More than one skill has this name. Pass agent_id.",
            agents=tuple(_agent_rows(nodes)),
        )
    if len(matches) == 1:
        node, index = matches[0]
        return _write(
            nodes, node, index, overlay(bundle or _bundle_from_skill(node, index), edits, name=name)
        )

    if bundle is None:
        return SkillPlacement(status="error", message=f'No skill named "{name}" on this workflow.')
    targets = [node for node in agents if agent_id is None or str(node.get("id") or "") == agent_id]
    if agent_id is not None:
        target = targets[0]
    elif len(agents) == 1:
        target = agents[0]
    elif len(agents) == 0:
        return SkillPlacement(
            status="error", message="This workflow has no agent to attach the skill to."
        )
    else:
        return SkillPlacement(
            status="needs_choice",
            message="Several agents could take this skill. Pass agent_id.",
            agents=tuple(_agent_rows(nodes)),
        )
    return _write(nodes, target, None, overlay(bundle, edits, name=bundle.name))


def _bundle_from_skill(node: dict[str, Any], index: int) -> SkillBundle:
    skill = (node.get("data") or {})["skills"][index]
    files = tuple(
        ArchiveFile(item["path"], item.get("content") or "")
        for item in skill.get("files") or []
        if isinstance(item, dict)
        and isinstance(item.get("path"), str)
        and (item.get("encoding") or "text") == "text"
        and str(item["path"]).lower().endswith((".md", ".py"))
    )
    return SkillBundle(
        name=_skill_name(skill),
        content=skill.get("content") if isinstance(skill.get("content"), str) else "",
        files=files,
        directory="",
    )


def _write(
    nodes: list[dict[str, Any]], node: dict[str, Any], index: int | None, bundle: SkillBundle
) -> SkillPlacement:
    copied = copy.deepcopy(nodes)
    target = next(item for item in copied if item.get("id") == node.get("id"))
    data = target.setdefault("data", {})
    skills = list(data.get("skills") or [])
    existing = skills[index] if index is not None else None
    record = _record(existing, bundle)
    if index is None:
        skills.append(record)
    else:
        skills[index] = record
    data["skills"] = skills
    return SkillPlacement(status="saved", nodes=copied, message=bundle.name)


def new_skill_workflow(
    bundle: SkillBundle, credential_id: str, model: str
) -> tuple[str, list[dict[str, Any]], list[dict[str, Any]]]:
    """A runnable workflow: a text input, one agent carrying the skill, and an output."""
    skill = _record(None, bundle)
    nodes: list[dict[str, Any]] = [
        {
            "id": "request",
            "type": "textInput",
            "position": {"x": 80, "y": 160},
            "data": {
                "label": "Request",
                "inputFields": [{"key": "text", "label": "Request", "type": "text"}],
            },
        },
        {
            "id": "agent",
            "type": "agent",
            "position": {"x": 380, "y": 140},
            "data": {
                "label": "Agent",
                "credentialId": credential_id,
                "model": model,
                "systemInstruction": f"Follow the {bundle.name} skill.",
                "userMessage": "$Request.text",
                "tools": [],
                "mcpConnections": [],
                "skills": [skill],
                "toolTimeoutSeconds": 60,
                "maxToolIterations": 8,
            },
        },
        {
            "id": "result",
            "type": "output",
            "position": {"x": 700, "y": 160},
            "data": {"label": "Result", "message": "$Agent.text"},
        },
    ]
    edges = [
        {"id": "request-agent", "source": "request", "target": "agent"},
        {"id": "agent-result", "source": "agent", "target": "result"},
    ]
    title = bundle.name.strip()[:255] or "Skill"
    return title, nodes, edges
