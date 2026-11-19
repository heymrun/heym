"""REST API for agent node persistent memory graphs."""

from __future__ import annotations

import json
import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db
from app.api.workflows import get_workflow_for_user, require_workflow_write
from app.db.models import LLM_CREDENTIAL_TYPES, AgentMemoryEdge, AgentMemoryNode, User
from app.models.agent_memory_schemas import (
    EdgeCreateRequest,
    EdgeUpdateRequest,
    MemoryAiInsertRequest,
    MemoryAiInsertResponse,
    MemoryClearResponse,
    MemoryEdgeResponse,
    MemoryGraphResponse,
    MemoryNodeResponse,
    NodeCreateRequest,
    NodeUpdateRequest,
)
from app.services.agent_memory_service import (
    MEMORY_INSERT_SYSTEM,
    MemoryMergeResult,
    apply_parsed_extraction_sync,
    build_memory_insert_payload,
    entity_name_equals_ci,
    graph_summaries_for_extraction,
    insert_only_extraction,
    memory_llm_endpoint,
    parse_llm_json_block,
    prune_isolated_nodes_sync,
    remove_conflicting_outgoing_edges_sync,
    run_memory_extraction_llm,
)
from app.services.credential_access import get_accessible_credential
from app.services.encryption import decrypt_config
from app.services.llm_trace import LLMTraceContext
from app.services.model_router import build_router_for_credential

logger = logging.getLogger(__name__)

router = APIRouter()


def _node_to_response(n: AgentMemoryNode) -> MemoryNodeResponse:
    return MemoryNodeResponse(
        id=n.id,
        entity_name=n.entity_name,
        entity_type=n.entity_type,
        properties=dict(n.properties or {}),
        confidence=float(n.confidence or 0.0),
        created_at=n.created_at,
        updated_at=n.updated_at,
    )


def _edge_to_response(e: AgentMemoryEdge) -> MemoryEdgeResponse:
    return MemoryEdgeResponse(
        id=e.id,
        source_node_id=e.source_node_id,
        target_node_id=e.target_node_id,
        relationship_type=e.relationship_type,
        properties=dict(e.properties or {}),
        confidence=float(e.confidence or 0.0),
        created_at=e.created_at,
        updated_at=e.updated_at,
    )


async def _load_graph_rows(
    db: AsyncSession,
    workflow_id: uuid.UUID,
    node_id: str,
) -> tuple[list[AgentMemoryNode], list[AgentMemoryEdge]]:
    """Every memory node and edge of one agent canvas node."""
    nres = await db.execute(
        select(AgentMemoryNode).where(
            AgentMemoryNode.workflow_id == workflow_id,
            AgentMemoryNode.canvas_node_id == node_id,
        )
    )
    nodes = list(nres.scalars().all())
    eres = await db.execute(
        select(AgentMemoryEdge).where(
            AgentMemoryEdge.workflow_id == workflow_id,
            AgentMemoryEdge.canvas_node_id == node_id,
        )
    )
    edges = list(eres.scalars().all())
    return nodes, edges


def _graph_to_response(
    nodes: list[AgentMemoryNode],
    edges: list[AgentMemoryEdge],
) -> MemoryGraphResponse:
    return MemoryGraphResponse(
        nodes=[_node_to_response(n) for n in nodes],
        edges=[_edge_to_response(e) for e in edges],
    )


@router.get(
    "/{workflow_id}/nodes/{node_id}/agent-memory/graph",
    response_model=MemoryGraphResponse,
)
async def get_memory_graph(
    workflow_id: uuid.UUID,
    node_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> MemoryGraphResponse:
    wf = await get_workflow_for_user(db, workflow_id, current_user.id)
    if wf is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow not found")

    nodes, edges = await _load_graph_rows(db, workflow_id, node_id)
    return _graph_to_response(nodes, edges)


@router.post(
    "/{workflow_id}/nodes/{node_id}/agent-memory/nodes",
    response_model=MemoryNodeResponse,
    status_code=status.HTTP_201_CREATED,
)
async def add_memory_node(
    workflow_id: uuid.UUID,
    node_id: str,
    body: NodeCreateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> MemoryNodeResponse:
    wf = await get_workflow_for_user(db, workflow_id, current_user.id)
    if wf is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow not found")
    await require_workflow_write(db, wf, current_user.id)

    row = AgentMemoryNode(
        id=uuid.uuid4(),
        workflow_id=workflow_id,
        canvas_node_id=node_id[:128],
        entity_name=body.entity_name.strip()[:255],
        entity_type=body.entity_type.strip()[:50],
        properties=dict(body.properties),
        confidence=float(body.confidence),
    )
    db.add(row)
    await db.flush()
    await db.refresh(row)
    return _node_to_response(row)


@router.put(
    "/{workflow_id}/agent-memory/nodes/{memory_node_id}",
    response_model=MemoryNodeResponse,
)
async def update_memory_node(
    workflow_id: uuid.UUID,
    memory_node_id: uuid.UUID,
    body: NodeUpdateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> MemoryNodeResponse:
    wf = await get_workflow_for_user(db, workflow_id, current_user.id)
    if wf is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow not found")
    await require_workflow_write(db, wf, current_user.id)

    res = await db.execute(
        select(AgentMemoryNode).where(
            AgentMemoryNode.id == memory_node_id,
            AgentMemoryNode.workflow_id == workflow_id,
        )
    )
    row = res.scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Memory node not found")

    if body.entity_name is not None:
        row.entity_name = body.entity_name.strip()[:255]
    if body.entity_type is not None:
        row.entity_type = body.entity_type.strip()[:50]
    if body.properties is not None:
        row.properties = dict(body.properties)
    if body.confidence is not None:
        row.confidence = float(body.confidence)
    await db.flush()
    await db.refresh(row)
    return _node_to_response(row)


@router.delete("/{workflow_id}/agent-memory/nodes/{memory_node_id}")
async def delete_memory_node(
    workflow_id: uuid.UUID,
    memory_node_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, str]:
    wf = await get_workflow_for_user(db, workflow_id, current_user.id)
    if wf is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow not found")
    await require_workflow_write(db, wf, current_user.id)

    res = await db.execute(
        select(AgentMemoryNode).where(
            AgentMemoryNode.id == memory_node_id,
            AgentMemoryNode.workflow_id == workflow_id,
        )
    )
    row = res.scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Memory node not found")

    await db.execute(delete(AgentMemoryNode).where(AgentMemoryNode.id == memory_node_id))
    return {"status": "deleted"}


@router.post(
    "/{workflow_id}/nodes/{node_id}/agent-memory/edges",
    response_model=MemoryEdgeResponse,
    status_code=status.HTTP_201_CREATED,
)
async def add_memory_edge(
    workflow_id: uuid.UUID,
    node_id: str,
    body: EdgeCreateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> MemoryEdgeResponse:
    wf = await get_workflow_for_user(db, workflow_id, current_user.id)
    if wf is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow not found")
    await require_workflow_write(db, wf, current_user.id)

    src_nm = body.source_entity_name.strip()
    tgt_nm = body.target_entity_name.strip()
    src_res = await db.execute(
        select(AgentMemoryNode).where(
            AgentMemoryNode.workflow_id == workflow_id,
            AgentMemoryNode.canvas_node_id == node_id,
            entity_name_equals_ci(AgentMemoryNode.entity_name, src_nm),
        )
    )
    tgt_res = await db.execute(
        select(AgentMemoryNode).where(
            AgentMemoryNode.workflow_id == workflow_id,
            AgentMemoryNode.canvas_node_id == node_id,
            entity_name_equals_ci(AgentMemoryNode.entity_name, tgt_nm),
        )
    )
    src = src_res.scalars().first()
    tgt = tgt_res.scalars().first()
    if src is None or tgt is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Source or target entity not found (names must match exactly)",
        )

    row = AgentMemoryEdge(
        id=uuid.uuid4(),
        workflow_id=workflow_id,
        canvas_node_id=node_id[:128],
        source_node_id=src.id,
        target_node_id=tgt.id,
        relationship_type=body.relationship_type.strip()[:100],
        properties=dict(body.properties),
        confidence=float(body.confidence),
    )
    db.add(row)
    await db.flush()
    canvas_key = node_id[:128]

    def _after_edge_write(sync_sess: Session) -> None:
        replaced_edge_nodes = remove_conflicting_outgoing_edges_sync(
            sync_sess,
            workflow_id,
            canvas_key,
            src.id,
            row.relationship_type,
            tgt.id,
        )
        prune_isolated_nodes_sync(
            sync_sess,
            workflow_id,
            canvas_key,
            candidate_node_ids=frozenset({src.id, tgt.id}) | replaced_edge_nodes,
        )

    await db.run_sync(_after_edge_write)
    await db.refresh(row)
    return _edge_to_response(row)


@router.put(
    "/{workflow_id}/agent-memory/edges/{memory_edge_id}",
    response_model=MemoryEdgeResponse,
)
async def update_memory_edge(
    workflow_id: uuid.UUID,
    memory_edge_id: uuid.UUID,
    body: EdgeUpdateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> MemoryEdgeResponse:
    wf = await get_workflow_for_user(db, workflow_id, current_user.id)
    if wf is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow not found")
    await require_workflow_write(db, wf, current_user.id)

    res = await db.execute(
        select(AgentMemoryEdge).where(
            AgentMemoryEdge.id == memory_edge_id,
            AgentMemoryEdge.workflow_id == workflow_id,
        )
    )
    row = res.scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Memory edge not found")

    if body.relationship_type is not None:
        row.relationship_type = body.relationship_type.strip()[:100]
    if body.properties is not None:
        row.properties = dict(body.properties)
    if body.confidence is not None:
        row.confidence = float(body.confidence)
    await db.flush()

    def _after_edge_update(sync_sess: Session) -> None:
        replaced_edge_nodes = remove_conflicting_outgoing_edges_sync(
            sync_sess,
            workflow_id,
            row.canvas_node_id,
            row.source_node_id,
            row.relationship_type,
            row.target_node_id,
        )
        prune_isolated_nodes_sync(
            sync_sess,
            workflow_id,
            row.canvas_node_id,
            candidate_node_ids=frozenset({row.source_node_id, row.target_node_id})
            | replaced_edge_nodes,
        )

    await db.run_sync(_after_edge_update)
    await db.refresh(row)
    return _edge_to_response(row)


@router.delete("/{workflow_id}/agent-memory/edges/{memory_edge_id}")
async def delete_memory_edge(
    workflow_id: uuid.UUID,
    memory_edge_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, str]:
    wf = await get_workflow_for_user(db, workflow_id, current_user.id)
    if wf is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow not found")
    await require_workflow_write(db, wf, current_user.id)

    res = await db.execute(
        select(AgentMemoryEdge).where(
            AgentMemoryEdge.id == memory_edge_id,
            AgentMemoryEdge.workflow_id == workflow_id,
        )
    )
    row = res.scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Memory edge not found")

    # No pruning here: Undo re-creates the edge by looking up its endpoints by
    # entity name, so a manual delete must never also remove a now-isolated
    # endpoint, or Undo gets a 400 ("Source or target entity not found").
    await db.execute(delete(AgentMemoryEdge).where(AgentMemoryEdge.id == memory_edge_id))
    await db.flush()
    return {"status": "deleted"}


@router.post(
    "/{workflow_id}/nodes/{node_id}/agent-memory/ai-insert",
    response_model=MemoryAiInsertResponse,
)
async def ai_insert_memory(
    workflow_id: uuid.UUID,
    node_id: str,
    body: MemoryAiInsertRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> MemoryAiInsertResponse:
    """Extract entities and relationships from a text with the agent's model and merge them.

    Insert only: `revoked_entities` is dropped, so the text can add to and update the graph but
    never delete an entity. Returns the graph read in this same transaction, because the
    request's commit lands after the response and a follow-up GET could still see the old graph.
    """
    wf = await get_workflow_for_user(db, workflow_id, current_user.id)
    if wf is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow not found")
    await require_workflow_write(db, wf, current_user.id)

    credential = await get_accessible_credential(db, body.credential_id, current_user.id)
    if credential is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="The agent's credential was not found or is not shared with you",
        )
    if credential.type not in LLM_CREDENTIAL_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="The agent's credential cannot run a model",
        )

    config = decrypt_config(credential.encrypted_config)
    model_router = build_router_for_credential(
        credential_id=str(credential.id),
        credential_name=credential.name,
        credential_type=credential.type.value,
        config=config,
    )
    api_key, base_url = memory_llm_endpoint(credential.type.value, config)
    if not api_key and model_router is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="The agent's credential has no API key",
        )

    canvas_key = node_id[:128]
    nodes, edges = await _load_graph_rows(db, workflow_id, canvas_key)
    nodes_summary, edges_summary = graph_summaries_for_extraction(nodes, edges)
    trace_context = LLMTraceContext(
        user_id=current_user.id,
        credential_id=credential.id,
        workflow_id=workflow_id,
        node_id=canvas_key,
        node_label="Agent memory insert",
        source="agent_memory",
        # One insert is one conversation: a fresh, nonempty OpenCode session per request.
        session_id=str(uuid.uuid4()),
    )
    try:
        llm_out = await run_memory_extraction_llm(
            credential_type=credential.type.value,
            api_key=api_key,
            base_url=base_url,
            model=body.model.strip(),
            user_payload=build_memory_insert_payload(body.text, nodes_summary, edges_summary),
            trace_context=trace_context,
            router=model_router,
            system_instruction=MEMORY_INSERT_SYSTEM,
        )
    except Exception as exc:
        logger.warning("Agent memory AI insert: model request failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="The model request failed. Check the agent's credential and model.",
        ) from exc

    try:
        parsed = parse_llm_json_block(str(llm_out.get("text") or ""))
    except (json.JSONDecodeError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="The model did not return valid JSON. Try again or pick another model.",
        ) from exc

    extraction = insert_only_extraction(parsed)

    def _merge(sync_sess: Session) -> MemoryMergeResult:
        # The old employer or location loses its link but stays: an insert never deletes.
        return apply_parsed_extraction_sync(
            sync_sess, workflow_id, canvas_key, extraction, prune_replaced=False
        )

    merged = await db.run_sync(_merge)
    await db.flush()
    nodes, edges = await _load_graph_rows(db, workflow_id, canvas_key)
    return MemoryAiInsertResponse(
        graph=_graph_to_response(nodes, edges),
        entities_applied=merged.entities_applied,
        relationships_applied=merged.relationships_applied,
    )


@router.delete(
    "/{workflow_id}/nodes/{node_id}/agent-memory/graph",
    response_model=MemoryClearResponse,
)
async def clear_memory_graph(
    workflow_id: uuid.UUID,
    node_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> MemoryClearResponse:
    """Delete every memory node and edge of one agent canvas node; peers' graphs are untouched."""
    wf = await get_workflow_for_user(db, workflow_id, current_user.id)
    if wf is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow not found")
    await require_workflow_write(db, wf, current_user.id)

    canvas_key = node_id[:128]
    edge_result = await db.execute(
        delete(AgentMemoryEdge).where(
            AgentMemoryEdge.workflow_id == workflow_id,
            AgentMemoryEdge.canvas_node_id == canvas_key,
        )
    )
    node_result = await db.execute(
        delete(AgentMemoryNode).where(
            AgentMemoryNode.workflow_id == workflow_id,
            AgentMemoryNode.canvas_node_id == canvas_key,
        )
    )
    await db.flush()
    return MemoryClearResponse(
        deleted_nodes=int(node_result.rowcount or 0),
        deleted_edges=int(edge_result.rowcount or 0),
    )
