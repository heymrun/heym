"""Agent memory in chat build mode: turn an agent's persistent memory on and insert knowledge.

`ChatBuildSession` offers `insert_agent_memory` on build turns (Chat tab, MCP `heym_chat`,
Heym Work Chat) and hands its calls here with a workflow the user may write. The insert is
the memory dialog's AI insert (`insert_memory_text`), so a text inserted from chat lands in
the graph exactly as it would from the editor. Turning memory on is a versioned save through
`workflow_save`, committed together with the insert, so a failed insert changes nothing.

When the user asked for an insert without saying what to insert, Heym asks for the text. An
MCP client that declared form elicitation shows a free-text field (`elicitation/create`);
every other client is asked in the chat, and the model calls again with the answer.
"""

import copy
import json
import uuid
from dataclasses import dataclass
from threading import Event
from typing import Any

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.agent_memory import insert_memory_text
from app.db.models import User, Workflow
from app.services.agent_memory_service import AI_INSERT_MAX_TEXT_CHARS
from app.services.audit_log import audit
from app.services.chat_build_mode import INSERT_AGENT_MEMORY_TOOL, BuildToolOutcome, tool_error
from app.services.collab.saves import queue_collab_saved
from app.services.mcp_elicitation import MCPClientChannel, ask_form
from app.services.workflow_save import (
    WorkflowSnapshot,
    add_workflow_version,
    announce_workflow_saved,
)

INSERT_AGENT_MEMORY_TOOL_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": INSERT_AGENT_MEMORY_TOOL,
        "description": (
            "Insert knowledge into an agent node's persistent memory (its knowledge graph): "
            "the agent's own model extracts entities and relationships from the text and merges "
            "them, never deleting one. Turns persistent memory on when it is off, so it is also "
            "the way to turn memory on. Call it when the user asks. Omit text when the user has "
            "not given it, and do not ask for it yourself first: Heym asks the user, with a form "
            "where the client supports one."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "workflow_id": {
                    "type": "string",
                    "description": (
                        "The workflow with the agent. Omit it to use this turn's target or "
                        "the workflow saved earlier in this conversation."
                    ),
                },
                "agent_id": {
                    "type": "string",
                    "description": (
                        "The agent node's id or label. Omit it when the workflow has one agent."
                    ),
                },
                "text": {
                    "type": "string",
                    "description": (
                        "The knowledge to insert, exactly as the user gave it: notes, facts or a "
                        f"document, at most {AI_INSERT_MAX_TEXT_CHARS} characters. Omit it when "
                        "the user's messages do not contain it; never make it up."
                    ),
                },
            },
        },
    },
}


def text_schema(agent_label: str) -> dict[str, Any]:
    """The free-text form an MCP client shows to ask what the agent should remember."""
    return {
        "type": "object",
        "properties": {
            "text": {
                "type": "string",
                "title": "Knowledge to add",
                "description": f"Notes, facts or a document for {agent_label} to remember.",
                "minLength": 1,
                "maxLength": AI_INSERT_MAX_TEXT_CHARS,
            }
        },
        "required": ["text"],
    }


@dataclass(frozen=True)
class MemoryAgent:
    """An agent node of a workflow, as the memory tool needs it."""

    id: str
    label: str
    memory_enabled: bool
    credential_id: str
    model: str

    def brief(self) -> dict[str, Any]:
        return {"id": self.id, "label": self.label, "persistent_memory": self.memory_enabled}


@dataclass(frozen=True)
class MemoryInsertOutcome:
    """One call: what the turn reports, and whether it saved the workflow."""

    outcome: BuildToolOutcome
    saved: bool = False


def memory_agents(nodes: list[dict[str, Any]] | None) -> list[MemoryAgent]:
    """The workflow's agent nodes, in canvas order."""
    agents: list[MemoryAgent] = []
    for node in nodes or []:
        if not isinstance(node, dict) or node.get("type") != "agent" or not node.get("id"):
            continue
        data = node.get("data") if isinstance(node.get("data"), dict) else {}
        agents.append(
            MemoryAgent(
                id=str(node["id"]),
                label=str(data.get("label") or node["id"]),
                memory_enabled=bool(data.get("persistentMemoryEnabled")),
                credential_id=str(data.get("credentialId") or "").strip(),
                model=str(data.get("model") or "").strip(),
            )
        )
    return agents


def pick_agent(agents: list[MemoryAgent], ref: str | None) -> MemoryAgent | None:
    """The agent `ref` names by id or label; the only agent when `ref` is empty."""
    if not ref:
        return agents[0] if len(agents) == 1 else None
    by_id = [agent for agent in agents if agent.id == ref]
    if by_id:
        return by_id[0]
    by_label = [agent for agent in agents if agent.label.casefold() == ref.casefold()]
    return by_label[0] if len(by_label) == 1 else None


def nodes_with_memory_on(nodes: list[dict[str, Any]], agent_id: str) -> list[dict[str, Any]]:
    """A copy of `nodes` with persistent memory turned on for one agent."""
    updated = copy.deepcopy(nodes)
    for node in updated:
        if isinstance(node, dict) and str(node.get("id")) == agent_id:
            data = node.get("data") if isinstance(node.get("data"), dict) else {}
            node["data"] = {**data, "persistentMemoryEnabled": True}
    return updated


def text_question(workflow_name: str, agent: MemoryAgent) -> str:
    """What the user is asked when the request did not say what to insert."""
    question = (
        f'What should agent "{agent.label}" in "{workflow_name}" remember? Paste notes, facts or '
        f"a document, up to {AI_INSERT_MAX_TEXT_CHARS:,} characters."
    )
    if not agent.memory_enabled:
        question += " Its persistent memory is off and turns on with this insert."
    return question


def _plural(count: int, one: str, many: str) -> str:
    return f"{count} {one if count == 1 else many}"


def _pending(payload: dict[str, Any], summary: str) -> MemoryInsertOutcome:
    return MemoryInsertOutcome(
        BuildToolOutcome(result=json.dumps(payload), summary=summary, status="pending")
    )


def _not_given(note: str) -> MemoryInsertOutcome:
    return MemoryInsertOutcome(
        BuildToolOutcome(
            result=json.dumps({"status": "no_text", "note": note}),
            summary="No text to insert",
            status="success",
        )
    )


class ChatAgentMemoryTool:
    """`insert_agent_memory` for one build turn."""

    def __init__(
        self,
        *,
        db: AsyncSession,
        user: User,
        llm_session_id: str,
        client: MCPClientChannel | None = None,
        cancel_event: Event | None = None,
    ) -> None:
        self.db = db
        self.user = user
        self.llm_session_id = llm_session_id
        self.client = client
        self.cancel_event = cancel_event

    @staticmethod
    def display_args(args: dict[str, Any]) -> dict[str, Any]:
        """The step row's arguments: the text's length, never the text."""
        text = args.get("text") if isinstance(args.get("text"), str) else ""
        return {
            "workflow_id": args.get("workflow_id"),
            "agent_id": args.get("agent_id"),
            "characters": len(text),
        }

    async def call(self, workflow: Workflow, args: dict[str, Any]) -> MemoryInsertOutcome:
        """Insert the text, asking for it when the call has none; `workflow` is writable."""
        agents = memory_agents(workflow.nodes)
        if not agents:
            return MemoryInsertOutcome(tool_error(f'"{workflow.name}" has no agent node.'))
        ref = str(args.get("agent_id") or "").strip() or None
        agent = pick_agent(agents, ref)
        if agent is None:
            return _pending(
                {
                    "status": "needs_choice",
                    "message": "Pass agent_id: the id of the agent whose memory to fill.",
                    "agents": [a.brief() for a in agents],
                },
                "Needs a choice of agent",
            )
        try:
            credential_id = uuid.UUID(agent.credential_id)
        except ValueError:
            credential_id = None
        if credential_id is None or not agent.model:
            return MemoryInsertOutcome(
                tool_error(
                    f'The agent "{agent.label}" needs a credential and a model before its '
                    "memory can be filled."
                )
            )

        text = str(args.get("text") or "").strip()
        if not text:
            asked = await self._ask_for_text(workflow.name, agent)
            if isinstance(asked, MemoryInsertOutcome):
                return asked
            text = asked
        if len(text) > AI_INSERT_MAX_TEXT_CHARS:
            return MemoryInsertOutcome(
                tool_error(
                    f"The text has {len(text)} characters; one insert takes at most "
                    f"{AI_INSERT_MAX_TEXT_CHARS}. Split it at paragraph boundaries and insert "
                    "each part with its own call."
                )
            )
        return await self._insert(workflow, agent, credential_id, text)

    async def _ask_for_text(
        self, workflow_name: str, agent: MemoryAgent
    ) -> str | MemoryInsertOutcome:
        """The text the user typed into the client's form, or what the model gets instead."""
        question = text_question(workflow_name, agent)
        if self.client is not None and self.client.supports_form_elicitation:
            reply = await ask_form(
                self.client,
                user_id=self.user.id,
                message=question,
                requested_schema=text_schema(agent.label),
                cancel_event=self.cancel_event,
            )
            if reply is not None and reply.action == "accept":
                text = str(reply.content.get("text") or "").strip()
                if text:
                    return text
            if reply is not None and reply.action in ("accept", "decline", "cancel"):
                return _not_given(
                    "The user gave no text. Nothing was inserted and memory was not changed. "
                    "Do not ask again unless the user does."
                )
        return _pending(
            {
                "status": "needs_text",
                "question": question,
                "note": (
                    "Nothing was written. Ask the user this question with a heym-clarify block "
                    "holding one question of type text, and stop. Then call "
                    f"{INSERT_AGENT_MEMORY_TOOL} again with their answer as text."
                ),
            },
            "Waiting for the text to insert",
        )

    async def _insert(
        self, workflow: Workflow, agent: MemoryAgent, credential_id: uuid.UUID, text: str
    ) -> MemoryInsertOutcome:
        try:
            inserted = await insert_memory_text(
                self.db,
                user_id=self.user.id,
                workflow_id=workflow.id,
                node_id=agent.id,
                text=text,
                credential_id=credential_id,
                model=agent.model,
                session_id=self.llm_session_id,
            )
        except HTTPException as exc:
            await self.db.rollback()
            return MemoryInsertOutcome(tool_error(str(exc.detail)))

        turn_on = not agent.memory_enabled
        version_number: int | None = None
        if turn_on:
            before = WorkflowSnapshot.capture(workflow)
            workflow.nodes = nodes_with_memory_on(list(workflow.nodes or []), agent.id)
            version_number = await add_workflow_version(self.db, workflow, before, self.user.id)
            await queue_collab_saved(
                self.db, workflow.id, self.user.id, session=None, state_hash=None
            )
        await self.db.commit()
        events: list[dict[str, Any]] = []
        if turn_on:
            await self.db.refresh(workflow)
            await announce_workflow_saved(workflow, self.user.id, created=False)
            audit(
                action="workflow.update",
                actor=self.user,
                target_type="workflow",
                target_id=workflow.id,
                target_name=workflow.name,
                source="chat_agent_memory",
                versioned=True,
                nodes=len(workflow.nodes or []),
            )
            events.append(
                {
                    "type": "workflow_created",
                    "workflow_id": str(workflow.id),
                    "workflow_name": workflow.name,
                    "workflow_description": workflow.description,
                    "workflow_url": f"/workflows/{workflow.id}",
                    "nodes": workflow.nodes or [],
                    "edges": workflow.edges or [],
                }
            )
        audit(
            action="agent_memory.insert",
            actor=self.user,
            target_type="workflow",
            target_id=workflow.id,
            target_name=workflow.name,
            source="chat",
            agent_node_id=agent.id,
            characters=len(text),
            entities_applied=inserted.entities_applied,
            relationships_applied=inserted.relationships_applied,
        )

        found = inserted.entities_applied or inserted.relationships_applied
        payload: dict[str, Any] = {
            "status": "inserted",
            "workflow_id": str(workflow.id),
            "workflow_name": workflow.name,
            "agent": {"id": agent.id, "label": agent.label},
            "memory_turned_on": turn_on,
            "entities_applied": inserted.entities_applied,
            "relationships_applied": inserted.relationships_applied,
            "memory": {
                "entities": len(inserted.graph.nodes),
                "relationships": len(inserted.graph.edges),
            },
        }
        if version_number is not None:
            payload["version"] = version_number + 1
        if not found:
            payload["note"] = (
                "The model found no entities or relationships in this text. Tell the user and "
                "suggest stating the facts more directly."
            )
        summary = (
            f"Inserted {_plural(inserted.entities_applied, 'entity', 'entities')} and "
            f"{_plural(inserted.relationships_applied, 'relationship', 'relationships')}"
            if found
            else "Nothing to insert"
        )
        if turn_on:
            summary += " · memory turned on"
        return MemoryInsertOutcome(
            BuildToolOutcome(
                result=json.dumps(payload), summary=summary, status="success", events=events
            ),
            saved=turn_on,
        )
