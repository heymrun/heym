"""Agent persistent memory: graph CRUD and background extraction.

Background extraction runs in a worker thread and uses sync SQLAlchemy (SessionLocal)
so it does not share the FastAPI/asyncpg event loop. Only the LLM HTTP call uses a
short-lived asyncio.run() in that thread.
"""

from __future__ import annotations

import asyncio
import json
import logging
import threading
import uuid
from dataclasses import replace
from typing import Any

from sqlalchemy import func, literal, select
from sqlalchemy.orm import Session

from app.db.models import AgentMemoryEdge, AgentMemoryNode, Credential, Workflow
from app.db.session import SessionLocal
from app.services.encryption import decrypt_config
from app.services.llm_service import execute_llm
from app.services.llm_trace import LLMTraceContext

logger = logging.getLogger(__name__)


def _is_unsupported_json_object_response_format(exc: BaseException) -> bool:
    """Some OpenAI-compatible servers only allow response_format type json_schema or text."""
    msg = str(exc).lower()
    return "response_format" in msg and (
        "json_object" in msg or "json_schema" in msg or "must be" in msg or "'text'" in msg
    )


def _trace_context_for_memory_job(base: LLMTraceContext | None) -> LLMTraceContext | None:
    """Use the same user/credential/workflow/node as the agent call; distinct trace source."""
    if base is None:
        return None
    return replace(base, source="agent_memory")


_MEMORY_SYSTEM = """You extract structured memory entities and relationships from the conversation excerpt.
Output JSON ONLY with this exact shape:
{
  "revoked_entities": [string],
  "entities": [
    {"name": string, "type": string, "properties": object, "confidence": number, "similar_to": string|null}
  ],
  "relationships": [
    {"source": string, "target": string, "type": string, "properties": object, "confidence": number}
  ]
}
Rules:
- revoked_entities: optional. Names of graph entities the user has explicitly negated, abandoned, or replaced (match names from "Existing Graph Nodes" when possible). Example: after "I don't eat ice cream anymore", revoke prior ice-cream preference entities (e.g. "Çilekli Dondurma") while emitting the new negated preference. Use [] if nothing is revoked.
- similar_to: name of an existing entity in the graph that this is the same as (for merge), or null if new.
- Use concise entity types: person, product, topic, organization, preference, other.
- confidence must be between 0.0 and 1.0.
- Only extract durable facts, preferences, or decisions worth recalling in future runs.
- Employment / employer changes: emit the new relationship only (e.g. person works for new company). Do not re-emit the old employer; the system replaces prior same-type links from that person.
- Residence / primary location changes: emit the new lives_in (or equivalent) relationship and the new place entity only; the system replaces prior same-type location links from that person. When you also set location on the person entity, include only the fields that changed (e.g. {\"location\": \"Istanbul\"}) so attributes merge with existing properties.
- If there is nothing to remember, return {"revoked_entities": [], "entities": [], "relationships": []}.
"""


def normalize_relationship_type(rel: str) -> str:
    """Lowercase, collapse whitespace, underscores to spaces (for comparing edge types)."""
    s = (rel or "").strip().lower().replace("_", " ")
    return " ".join(s.split())


_SINGLE_SLOT_OUTGOING_REL_TYPES: frozenset[str] = frozenset(
    {
        "works for",
        "works at",
        "employed at",
        "employed by",
        "manager of",
        # One primary residence / location edge per person (replaces prior city).
        "lives in",
        "resides in",
        "resident of",
        "based in",
        "located in",
    }
)


def remove_conflicting_outgoing_edges_sync(
    session: Session,
    workflow_id: uuid.UUID,
    canvas_node_id: str,
    source_node_id: uuid.UUID,
    relationship_type: str,
    keep_target_node_id: uuid.UUID,
) -> None:
    """Drop other outgoing edges from the same source with the same normalized slot type.

    Used so a new 'works for' or 'lives in' link replaces prior same-type edges without duplicates.
    """
    norm = normalize_relationship_type(relationship_type)
    if norm not in _SINGLE_SLOT_OUTGOING_REL_TYPES:
        return
    stmt = select(AgentMemoryEdge).where(
        AgentMemoryEdge.workflow_id == workflow_id,
        AgentMemoryEdge.canvas_node_id == canvas_node_id,
        AgentMemoryEdge.source_node_id == source_node_id,
    )
    rows = list(session.execute(stmt).scalars().all())
    for edge in rows:
        if normalize_relationship_type(edge.relationship_type) != norm:
            continue
        if edge.target_node_id != keep_target_node_id:
            session.delete(edge)


def delete_agent_memory_nodes_by_entity_names_sync(
    session: Session,
    workflow_id: uuid.UUID,
    canvas_node_id: str,
    names: list[str],
) -> int:
    """Delete nodes matched by entity_name (case-insensitive). Incident edges cascade. Returns count."""
    seen_lower: set[str] = set()
    deleted = 0
    for raw in names:
        nm = str(raw).strip()
        if not nm:
            continue
        key = nm.lower()
        if key in seen_lower:
            continue
        seen_lower.add(key)
        node = _find_node_by_name_sync(session, workflow_id, canvas_node_id, nm)
        if node is not None:
            session.delete(node)
            deleted += 1
    return deleted


def prune_isolated_nodes_sync(
    session: Session,
    workflow_id: uuid.UUID,
    canvas_node_id: str,
    *,
    exempt_entity_names_lower: frozenset[str] | None = None,
) -> None:
    """Remove nodes with no incident edges (floating entities).

    exempt_entity_names_lower: entity names (lowercase) from the current extraction batch that
    may legitimately have no edges yet; they are kept until a later merge.
    """
    edges = list(
        session.execute(
            select(AgentMemoryEdge).where(
                AgentMemoryEdge.workflow_id == workflow_id,
                AgentMemoryEdge.canvas_node_id == canvas_node_id,
            )
        )
        .scalars()
        .all()
    )
    touched: set[uuid.UUID] = set()
    for e in edges:
        touched.add(e.source_node_id)
        touched.add(e.target_node_id)
    nodes = list(
        session.execute(
            select(AgentMemoryNode).where(
                AgentMemoryNode.workflow_id == workflow_id,
                AgentMemoryNode.canvas_node_id == canvas_node_id,
            )
        )
        .scalars()
        .all()
    )
    skip_names = exempt_entity_names_lower or frozenset()
    for n in nodes:
        if n.id in touched:
            continue
        if n.entity_name.strip().lower() in skip_names:
            continue
        session.delete(n)


def parse_llm_json_block(text: str) -> dict[str, Any]:
    """Parse JSON from an LLM response, stripping optional markdown fences."""
    t = (text or "").strip()
    if t.startswith("```"):
        lines = t.split("\n")
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        t = "\n".join(lines).strip()
    parsed = json.loads(t)
    if not isinstance(parsed, dict):
        raise ValueError("Expected JSON object")
    return parsed


def format_conversation_for_memory(user_message: str, agent_result: dict[str, Any]) -> str:
    """Build a text transcript for memory extraction (includes sub-agent tool results)."""
    parts: list[str] = [f"User task / input:\n{user_message}\n"]
    text = agent_result.get("text")
    if isinstance(text, str) and text.strip():
        parts.append(f"Assistant final reply:\n{text.strip()}\n")
    for tc in agent_result.get("tool_calls") or []:
        if not isinstance(tc, dict):
            continue
        name = tc.get("name")
        if name in (None, "_context_compression"):
            continue
        args = tc.get("arguments")
        res = tc.get("result")
        try:
            args_s = json.dumps(args, ensure_ascii=False, default=str)[:4000]
        except TypeError:
            args_s = str(args)[:4000]
        try:
            res_s = json.dumps(res, ensure_ascii=False, default=str)[:8000]
        except TypeError:
            res_s = str(res)[:8000]
        parts.append(f"Tool {name}:\nArguments: {args_s}\nResult: {res_s}\n")
    return "\n".join(parts)


_AGENT_MEMORY_PROMPT_HEADER = (
    "### Persistent memory (from prior runs of this agent node)\n"
    "Use the facts below when relevant. The graph may be incomplete or outdated; prefer the "
    "current user message if there is a conflict.\n\n"
)


def format_memory_graph_for_prompt(
    nodes: list[AgentMemoryNode],
    edges: list[AgentMemoryEdge],
    *,
    max_chars: int = 16000,
) -> str | None:
    """Render stored graph nodes/edges as compact Markdown for the system prompt."""
    if not nodes:
        return None
    id_to_name = {n.id: n.entity_name for n in nodes}
    node_ids = set(id_to_name.keys())
    lines: list[str] = ["**Entities:**"]
    for n in nodes:
        props = n.properties if isinstance(getattr(n, "properties", None), dict) else {}
        prop_s = ""
        if props:
            try:
                prop_s = json.dumps(props, ensure_ascii=False)[:180]
            except TypeError:
                prop_s = str(props)[:180]
        line = f"- {n.entity_name} ({n.entity_type})"
        if prop_s and prop_s.strip() not in ("{}", "null"):
            line += f" — {prop_s}"
        lines.append(line)

    shown_edges = [
        e for e in edges if e.source_node_id in node_ids and e.target_node_id in node_ids
    ]
    if shown_edges:
        lines.append("")
        lines.append("**Relationships:**")
        for e in shown_edges:
            sn = id_to_name.get(e.source_node_id, "?")
            tn = id_to_name.get(e.target_node_id, "?")
            lines.append(f"- {sn} —[{e.relationship_type}]→ {tn}")

    text = "\n".join(lines)
    if len(text) > max_chars:
        text = text[: max_chars - 24].rstrip() + "\n… (truncated)"
    return text


def load_agent_memory_prompt_block_sync(
    workflow_id: uuid.UUID,
    canvas_node_id: str,
    *,
    max_nodes: int = 100,
    max_edges: int = 200,
    max_chars: int = 16000,
) -> str | None:
    """Load the memory graph from the DB (sync) and return Markdown, or None if empty/error."""
    from app.db.session import SessionLocal

    try:
        with SessionLocal() as db:
            nodes = (
                db.query(AgentMemoryNode)
                .filter(
                    AgentMemoryNode.workflow_id == workflow_id,
                    AgentMemoryNode.canvas_node_id == canvas_node_id,
                )
                .order_by(AgentMemoryNode.updated_at.desc())
                .limit(max_nodes)
                .all()
            )
            if not nodes:
                return None
            edges = (
                db.query(AgentMemoryEdge)
                .filter(
                    AgentMemoryEdge.workflow_id == workflow_id,
                    AgentMemoryEdge.canvas_node_id == canvas_node_id,
                )
                .limit(max_edges)
                .all()
            )
            return format_memory_graph_for_prompt(list(nodes), list(edges), max_chars=max_chars)
    except Exception:
        logger.warning(
            "Agent memory: could not load graph for system prompt (workflow=%s node=%s)",
            workflow_id,
            canvas_node_id,
            exc_info=True,
        )
        return None


def _share_targets_peer(
    share: dict[str, Any],
    owner_workflow_id: str,
    peer_workflow_id: str,
    peer_canvas_node_id: str,
) -> bool:
    """True if this share entry grants the peer (workflow + canvas node) access."""
    peer_canvas = str(share.get("peerCanvasNodeId") or "").strip()
    if peer_canvas != peer_canvas_node_id:
        return False
    pfw = share.get("peerWorkflowId")
    if pfw is None or str(pfw).strip() == "":
        return owner_workflow_id == peer_workflow_id
    return str(pfw).strip() == str(peer_workflow_id)


def _merge_owner_perm_best(
    best: dict[tuple[str, str], tuple[str, str]],
    owner_workflow_id: str,
    owner_canvas_id: str,
    label: str,
    perm: str,
) -> None:
    """Merge by (owner_workflow_id, owner_canvas_id); ``write`` wins over ``read``."""
    k = (owner_workflow_id, owner_canvas_id)
    prev = best.get(k)
    if prev is None:
        best[k] = (label, perm)
        return
    _lbl, prev_perm = prev
    merged = "write" if (perm == "write" or prev_perm == "write") else "read"
    best[k] = (label, merged)


def merge_memory_share_targets(
    workflow_nodes: dict[str, Any],
    owner_workflow_id: str,
    peer_workflow_id: str,
    peer_canvas_node_id: str,
) -> list[tuple[str, str, str]]:
    """Return ``(owner_canvas_id, owner_label, permission)`` for owners in *workflow_nodes*."""
    best: dict[tuple[str, str], tuple[str, str]] = {}
    for owner_key, node in workflow_nodes.items():
        if not isinstance(node, dict) or node.get("type") != "agent":
            continue
        data = node.get("data") or {}
        if not isinstance(data, dict):
            continue
        shares = data.get("memoryShares")
        if not isinstance(shares, list):
            continue
        owner_canvas_id = str(owner_key)[:128]
        label = str(data.get("label") or owner_key)
        for share in shares:
            if not isinstance(share, dict):
                continue
            if not _share_targets_peer(
                share,
                owner_workflow_id,
                peer_workflow_id,
                peer_canvas_node_id,
            ):
                continue
            perm_raw = str(share.get("permission") or "read").strip().lower()
            perm = "write" if perm_raw == "write" else "read"
            _merge_owner_perm_best(best, owner_workflow_id, owner_canvas_id, label, perm)
    return [(cid, lbl, p) for (wf, cid), (lbl, p) in best.items()]


def list_memory_share_owners_sync(
    peer_workflow_id: uuid.UUID,
    peer_canvas_node_id: str,
    user_id: uuid.UUID,
) -> list[tuple[uuid.UUID, str, str, str]]:
    """Scan all workflows owned by *user* for agent ``memoryShares`` pointing at *peer*.

    Returns ``(owner_workflow_id, owner_canvas_id, owner_label, permission)``.
    """
    out: list[tuple[uuid.UUID, str, str, str]] = []
    peer_wf = str(peer_workflow_id)
    try:
        with SessionLocal() as session:
            rows = session.execute(
                select(Workflow.id, Workflow.nodes).where(
                    Workflow.owner_id == user_id,
                    Workflow.scheduled_for_deletion.is_(None),
                )
            ).all()
    except Exception:
        logger.warning(
            "Agent memory: could not scan workflows for memory shares (peer=%s)",
            peer_canvas_node_id,
            exc_info=True,
        )
        return []
    for wf_id, nodes_json in rows:
        owner_wf_str = str(wf_id)
        if not isinstance(nodes_json, list):
            continue
        for node in nodes_json:
            if not isinstance(node, dict) or node.get("type") != "agent":
                continue
            data = node.get("data") or {}
            if not isinstance(data, dict):
                continue
            shares = data.get("memoryShares")
            if not isinstance(shares, list):
                continue
            owner_canvas_id = str(node.get("id") or "").strip()[:128]
            if not owner_canvas_id:
                continue
            label = str(data.get("label") or owner_canvas_id)
            for share in shares:
                if not isinstance(share, dict):
                    continue
                if not _share_targets_peer(share, owner_wf_str, peer_wf, peer_canvas_node_id):
                    continue
                perm_raw = str(share.get("permission") or "read").strip().lower()
                perm = "write" if perm_raw == "write" else "read"
                out.append((wf_id, owner_canvas_id, label, perm))
    return out


def resolve_memory_share_owners_for_peer(
    peer_workflow_id: uuid.UUID,
    peer_canvas_node_id: str,
    workflow_nodes: dict[str, Any] | None,
    trace_user_id: uuid.UUID | None,
) -> list[tuple[str, str, str, str]]:
    """Return ``(owner_workflow_id_str, owner_canvas_id, owner_label, permission)`` (write wins)."""
    best: dict[tuple[str, str], tuple[str, str]] = {}
    peer_wf = str(peer_workflow_id)

    if trace_user_id is not None:
        for owf, ocid, olbl, perm in list_memory_share_owners_sync(
            peer_workflow_id, peer_canvas_node_id, trace_user_id
        ):
            _merge_owner_perm_best(best, str(owf), ocid, olbl, perm)
    elif workflow_nodes:
        for ocid, olbl, perm in merge_memory_share_targets(
            workflow_nodes,
            peer_wf,
            peer_wf,
            peer_canvas_node_id,
        ):
            _merge_owner_perm_best(best, peer_wf, ocid, olbl, perm)

    return [(wf, cid, lbl, p) for (wf, cid), (lbl, p) in best.items()]


def memory_extraction_targets_for_agent_node(
    workflow_nodes: dict[str, Any] | None,
    current_workflow_id: uuid.UUID,
    current_canvas_node_id: str,
    persistent_memory_enabled: bool,
    trace_user_id: uuid.UUID | None,
) -> list[tuple[uuid.UUID, str]]:
    """Distinct ``(workflow_id, canvas_node_id)`` for post-run memory extraction."""
    targets: list[tuple[uuid.UUID, str]] = []
    if persistent_memory_enabled:
        targets.append((current_workflow_id, current_canvas_node_id))
    for owner_wf, owner_cid, _label, perm in resolve_memory_share_owners_for_peer(
        current_workflow_id,
        current_canvas_node_id,
        workflow_nodes,
        trace_user_id,
    ):
        if perm != "write":
            continue
        try:
            owf_uuid = uuid.UUID(str(owner_wf))
        except ValueError:
            continue
        if owf_uuid == current_workflow_id and owner_cid == current_canvas_node_id:
            continue
        targets.append((owf_uuid, owner_cid))
    seen: set[tuple[str, str]] = set()
    deduped: list[tuple[uuid.UUID, str]] = []
    for wf, cid in targets:
        k = (str(wf), cid)
        if k in seen:
            continue
        seen.add(k)
        deduped.append((wf, cid))
    return deduped


def augment_system_instruction_with_memory(
    system_instruction: str | None,
    workflow_id: uuid.UUID | None,
    canvas_node_id: str | None,
    *,
    enabled: bool,
    workflow_nodes: dict[str, Any] | None = None,
    trace_user_id: uuid.UUID | None = None,
) -> str | None:
    """Append persistent-memory blocks (own + shared) when present; returns updated or original."""
    if not workflow_id or not canvas_node_id:
        return system_instruction

    blocks: list[str] = []
    if enabled:
        own = load_agent_memory_prompt_block_sync(workflow_id, canvas_node_id)
        if own:
            blocks.append(_AGENT_MEMORY_PROMPT_HEADER + own)

    for owner_wf, owner_cid, owner_label, perm in resolve_memory_share_owners_for_peer(
        workflow_id,
        canvas_node_id,
        workflow_nodes,
        trace_user_id,
    ):
        if str(owner_wf) == str(workflow_id) and owner_cid == canvas_node_id:
            continue
        try:
            owf_uuid = uuid.UUID(str(owner_wf))
        except ValueError:
            continue
        shared = load_agent_memory_prompt_block_sync(owf_uuid, owner_cid)
        if not shared:
            continue
        mode = "read/write" if perm == "write" else "read-only"
        intro = (
            f"### Shared agent memory (from `{owner_label}` — {mode})\n"
            f"The following knowledge graph is shared from agent node `{owner_label}`. "
            f"Use it when relevant; prefer the current user message on conflicts.\n"
        )
        if perm == "write":
            intro += (
                "New durable facts from this run may be merged into this shared graph "
                "after a successful completion.\n\n"
            )
        else:
            intro += "This graph is provided as read-only context for this run.\n\n"
        blocks.append(intro + shared)

    if not blocks:
        return system_instruction

    merged = "\n\n".join(blocks)
    if system_instruction:
        return f"{system_instruction}\n\n{merged}"
    return merged


def entity_name_equals_ci(entity_name_column: Any, name: str) -> Any:
    """Case-insensitive match using SQL lower() on both operands.

    Comparing ``func.lower(column)`` to a Python-lowercased bind value breaks for
    some Unicode letters (e.g. Turkish dotted capital I) under PostgreSQL.
    """
    nm = name.strip()
    return func.lower(entity_name_column) == func.lower(literal(nm))


def _find_node_by_name_sync(
    session: Session,
    workflow_id: uuid.UUID,
    canvas_node_id: str,
    name: str,
) -> AgentMemoryNode | None:
    stmt = (
        select(AgentMemoryNode)
        .where(
            AgentMemoryNode.workflow_id == workflow_id,
            AgentMemoryNode.canvas_node_id == canvas_node_id,
            entity_name_equals_ci(AgentMemoryNode.entity_name, name),
        )
        .limit(1)
    )
    return session.execute(stmt).scalars().first()


def apply_parsed_extraction_sync(
    session: Session,
    workflow_id: uuid.UUID,
    canvas_node_id: str,
    data: dict[str, Any],
) -> None:
    """Merge extraction JSON into stored graph (new overrides old on same entity name)."""
    canvas_key = canvas_node_id[:128]
    entities = data.get("entities") or []
    relationships = data.get("relationships") or []
    revoked = data.get("revoked_entities")
    if not isinstance(entities, list):
        entities = []
    if not isinstance(relationships, list):
        relationships = []
    if isinstance(revoked, list):
        revoke_names = [str(x).strip() for x in revoked if str(x).strip()]
        delete_agent_memory_nodes_by_entity_names_sync(
            session, workflow_id, canvas_key, revoke_names
        )
    session.flush()

    entity_names_lower: set[str] = set()
    for raw in entities:
        if not isinstance(raw, dict):
            continue
        name = str(raw.get("name") or "").strip()
        if not name:
            continue
        entity_names_lower.add(name.lower())
        ent_type = str(raw.get("type") or "other").strip()[:50] or "other"
        props = raw.get("properties") if isinstance(raw.get("properties"), dict) else {}
        try:
            conf = float(raw.get("confidence") or 0.0)
        except (TypeError, ValueError):
            conf = 0.0
        similar_to = raw.get("similar_to")
        target_existing: AgentMemoryNode | None = None
        if isinstance(similar_to, str) and similar_to.strip():
            target_existing = _find_node_by_name_sync(
                session, workflow_id, canvas_key, similar_to.strip()
            )
        if target_existing is None:
            target_existing = _find_node_by_name_sync(session, workflow_id, canvas_key, name)

        if target_existing:
            target_existing.entity_name = name[:255]
            target_existing.entity_type = ent_type
            prior = (
                target_existing.properties if isinstance(target_existing.properties, dict) else {}
            )
            target_existing.properties = {**prior, **props}
            target_existing.confidence = conf
        else:
            session.add(
                AgentMemoryNode(
                    id=uuid.uuid4(),
                    workflow_id=workflow_id,
                    canvas_node_id=canvas_key,
                    entity_name=name[:255],
                    entity_type=ent_type,
                    properties=props,
                    confidence=conf,
                )
            )

    session.flush()

    for raw in relationships:
        if not isinstance(raw, dict):
            continue
        src_name = str(raw.get("source") or "").strip()
        tgt_name = str(raw.get("target") or "").strip()
        rel_type = str(raw.get("type") or "related").strip()[:100] or "related"
        if not src_name or not tgt_name:
            continue
        props = raw.get("properties") if isinstance(raw.get("properties"), dict) else {}
        try:
            conf = float(raw.get("confidence") or 0.0)
        except (TypeError, ValueError):
            conf = 0.0
        src = _find_node_by_name_sync(session, workflow_id, canvas_key, src_name)
        tgt = _find_node_by_name_sync(session, workflow_id, canvas_key, tgt_name)
        if src is None or tgt is None:
            continue
        stmt = select(AgentMemoryEdge).where(
            AgentMemoryEdge.workflow_id == workflow_id,
            AgentMemoryEdge.canvas_node_id == canvas_key,
            AgentMemoryEdge.source_node_id == src.id,
            AgentMemoryEdge.target_node_id == tgt.id,
            AgentMemoryEdge.relationship_type == rel_type,
        )
        existing = session.execute(stmt.limit(1)).scalars().first()
        if existing:
            existing.properties = props
            existing.confidence = conf
        else:
            session.add(
                AgentMemoryEdge(
                    id=uuid.uuid4(),
                    workflow_id=workflow_id,
                    canvas_node_id=canvas_key,
                    source_node_id=src.id,
                    target_node_id=tgt.id,
                    relationship_type=rel_type,
                    properties=props,
                    confidence=conf,
                )
            )
        remove_conflicting_outgoing_edges_sync(
            session,
            workflow_id,
            canvas_key,
            src.id,
            rel_type,
            tgt.id,
        )

    session.flush()
    prune_isolated_nodes_sync(
        session,
        workflow_id,
        canvas_key,
        exempt_entity_names_lower=frozenset(entity_names_lower),
    )


async def _run_memory_extraction_llm(
    *,
    credential_type: str,
    api_key: str,
    base_url: str | None,
    model: str,
    user_payload: str,
    trace_context: LLMTraceContext | None,
) -> dict[str, Any]:
    """LLM-only coroutine (no DB); safe to run under asyncio.run in a worker thread."""
    common: dict[str, Any] = {
        "credential_type": credential_type,
        "api_key": api_key,
        "base_url": base_url,
        "model": model,
        "system_instruction": _MEMORY_SYSTEM,
        "user_message": user_payload,
        "temperature": 0.2,
        "trace_context": trace_context,
    }
    try:
        return await execute_llm(
            **common,
            response_format={"type": "json_object"},
        )
    except Exception as exc:
        if not _is_unsupported_json_object_response_format(exc):
            raise
        logger.info(
            "Agent memory: provider rejected json_object response_format; retrying without it"
        )
        return await execute_llm(
            **common,
            response_format=None,
        )


def extract_and_merge_memory_sync(
    workflow_id: uuid.UUID,
    canvas_node_id: str,
    credential_id: str,
    model: str,
    user_message: str,
    agent_result: dict[str, Any],
    *,
    trace_context: LLMTraceContext | None = None,
) -> None:
    """Load graph via sync DB, call LLM, merge into DB (for background thread)."""
    conversation = format_conversation_for_memory(user_message, agent_result)
    if len(conversation.strip()) < 8:
        return

    try:
        cred_uuid = uuid.UUID(credential_id)
    except ValueError:
        logger.warning("Agent memory: invalid credential id")
        return

    with SessionLocal() as session:
        try:
            cred = (
                session.execute(select(Credential).where(Credential.id == cred_uuid))
                .scalars()
                .first()
            )
            if cred is None:
                logger.warning("Agent memory: credential not found")
                return

            config = decrypt_config(cred.encrypted_config)
            api_key = config.get("api_key")
            base_url = config.get("base_url")
            if not base_url and cred.type.value == "google":
                from app.services.llm_service import GOOGLE_OPENAI_BASE_URL

                base_url = GOOGLE_OPENAI_BASE_URL
            elif base_url and cred.type.value == "custom":
                base_url = str(base_url).rstrip("/")
                if not base_url.endswith("/v1"):
                    base_url = base_url + "/v1"
            if not api_key:
                logger.warning("Agent memory: no API key on credential")
                return

            nodes_list = list(
                session.execute(
                    select(AgentMemoryNode).where(
                        AgentMemoryNode.workflow_id == workflow_id,
                        AgentMemoryNode.canvas_node_id == canvas_node_id,
                    )
                )
                .scalars()
                .all()
            )
            existing_nodes_summary = [
                {"name": n.entity_name, "type": n.entity_type, "properties": n.properties}
                for n in nodes_list
            ]
            edges_list = list(
                session.execute(
                    select(AgentMemoryEdge).where(
                        AgentMemoryEdge.workflow_id == workflow_id,
                        AgentMemoryEdge.canvas_node_id == canvas_node_id,
                    )
                )
                .scalars()
                .all()
            )
            id_to_name = {n.id: n.entity_name for n in nodes_list}
            existing_edges_summary = [
                {
                    "source": id_to_name.get(e.source_node_id, "?"),
                    "target": id_to_name.get(e.target_node_id, "?"),
                    "type": e.relationship_type,
                }
                for e in edges_list
            ]

            conv_trim = conversation if len(conversation) <= 24000 else conversation[:24000] + "\n…"
            user_payload = (
                f"Conversation:\n{conv_trim}\n\n"
                f"Existing Graph Nodes:\n{json.dumps(existing_nodes_summary, ensure_ascii=False)}\n\n"
                f"Existing Graph Edges:\n{json.dumps(existing_edges_summary, ensure_ascii=False)}\n"
            )

            try:
                llm_out = asyncio.run(
                    _run_memory_extraction_llm(
                        credential_type=cred.type.value,
                        api_key=api_key,
                        base_url=base_url,
                        model=model,
                        user_payload=user_payload,
                        trace_context=trace_context,
                    )
                )
            except Exception:
                logger.exception("Agent memory: LLM extraction failed")
                session.rollback()
                return

            raw_text = llm_out.get("text") or ""
            try:
                parsed = parse_llm_json_block(raw_text)
            except (json.JSONDecodeError, ValueError) as e:
                logger.warning("Agent memory: bad JSON from LLM: %s", e)
                session.rollback()
                return

            apply_parsed_extraction_sync(session, workflow_id, canvas_node_id, parsed)
            session.commit()
        except Exception:
            logger.exception("Agent memory: merge failed")
            session.rollback()
            raise


def schedule_agent_memory_extraction(
    workflow_id: uuid.UUID,
    canvas_node_id: str,
    credential_id: str,
    model: str,
    user_message: str,
    agent_result: dict[str, Any],
    *,
    trace_context: LLMTraceContext | None = None,
) -> None:
    """Queue a single background memory extraction after one full agent node run.

    Not tied to individual tool iterations: the executor calls this once when the agent
    returns a successful result (same thread hands off to a daemon thread immediately).
    """
    mem_trace = _trace_context_for_memory_job(trace_context)

    def _runner() -> None:
        try:
            extract_and_merge_memory_sync(
                workflow_id=workflow_id,
                canvas_node_id=canvas_node_id,
                credential_id=credential_id,
                model=model,
                user_message=user_message,
                agent_result=agent_result,
                trace_context=mem_trace,
            )
        except Exception:
            logger.exception("Agent memory: background job crashed")

    threading.Thread(target=_runner, daemon=True, name="agent-memory").start()
