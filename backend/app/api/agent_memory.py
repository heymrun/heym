"""REST API for agent node persistent memory graphs."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db
from app.api.workflows import get_workflow_for_user
from app.db.models import AgentMemoryEdge, AgentMemoryNode, User
from app.models.agent_memory_schemas import (
    EdgeCreateRequest,
    EdgeUpdateRequest,
    MemoryEdgeResponse,
    MemoryGraphResponse,
    MemoryNodeResponse,
    NodeCreateRequest,
    NodeUpdateRequest,
)
from app.services.agent_memory_service import (
    entity_name_equals_ci,
    prune_isolated_nodes_sync,
    remove_conflicting_outgoing_edges_sync,
)

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
    return MemoryGraphResponse(
        nodes=[_node_to_response(n) for n in nodes],
        edges=[_edge_to_response(e) for e in edges],
    )


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
        remove_conflicting_outgoing_edges_sync(
            sync_sess,
            workflow_id,
            canvas_key,
            src.id,
            row.relationship_type,
            tgt.id,
        )
        prune_isolated_nodes_sync(sync_sess, workflow_id, canvas_key)

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
        remove_conflicting_outgoing_edges_sync(
            sync_sess,
            workflow_id,
            row.canvas_node_id,
            row.source_node_id,
            row.relationship_type,
            row.target_node_id,
        )
        prune_isolated_nodes_sync(sync_sess, workflow_id, row.canvas_node_id)

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

    res = await db.execute(
        select(AgentMemoryEdge).where(
            AgentMemoryEdge.id == memory_edge_id,
            AgentMemoryEdge.workflow_id == workflow_id,
        )
    )
    row = res.scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Memory edge not found")

    canvas_key = row.canvas_node_id
    wf_id = row.workflow_id
    await db.execute(delete(AgentMemoryEdge).where(AgentMemoryEdge.id == memory_edge_id))
    await db.flush()

    def _after_edge_delete(sync_sess: Session) -> None:
        prune_isolated_nodes_sync(sync_sess, wf_id, canvas_key)

    await db.run_sync(_after_edge_delete)
    return {"status": "deleted"}
