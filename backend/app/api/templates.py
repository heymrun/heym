"""Templates API – share and reuse workflow / node templates."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.models import NodeTemplate, User, WorkflowTemplate
from app.db.session import get_db
from app.models.schemas import (
    CreateTemplateRequest,
    NodeTemplateResponse,
    TemplateListResponse,
    UpdateNodeTemplateRequest,
    UpdateWorkflowTemplateRequest,
    WorkflowTemplateResponse,
)
from app.services import template_service

router = APIRouter()


def _wf_response(t: WorkflowTemplate) -> WorkflowTemplateResponse:
    return WorkflowTemplateResponse(
        id=t.id,
        author_id=t.author_id,
        author_name=t.author.name if t.author else None,
        name=t.name,
        description=t.description,
        tags=t.tags,
        nodes=t.nodes,
        edges=t.edges,
        canvas_snapshot=t.canvas_snapshot,
        visibility=t.visibility,
        shared_with=t.shared_with,
        shared_with_teams=t.shared_with_teams or [],
        use_count=t.use_count,
        created_at=t.created_at,
    )


def _nd_response(t: NodeTemplate) -> NodeTemplateResponse:
    return NodeTemplateResponse(
        id=t.id,
        author_id=t.author_id,
        author_name=t.author.name if t.author else None,
        name=t.name,
        description=t.description,
        tags=t.tags,
        node_type=t.node_type,
        node_data=t.node_data,
        visibility=t.visibility,
        shared_with=t.shared_with,
        shared_with_teams=t.shared_with_teams or [],
        use_count=t.use_count,
        created_at=t.created_at,
    )


@router.get("", response_model=TemplateListResponse)
async def list_templates(
    type: str | None = Query(None, description="'workflow' or 'node'; omit for both"),
    search: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> TemplateListResponse:
    """List workflow and/or node templates visible to the current user."""
    wf_templates: list = []
    nd_templates: list = []

    if type is None or type == "workflow":
        wf_templates = await template_service.list_workflow_templates(db, current_user, search)
    if type is None or type == "node":
        nd_templates = await template_service.list_node_templates(db, current_user, search)

    return TemplateListResponse(
        workflow_templates=[_wf_response(t) for t in wf_templates],
        node_templates=[_nd_response(t) for t in nd_templates],
    )


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_template(
    payload: CreateTemplateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> WorkflowTemplateResponse | NodeTemplateResponse:
    """Share a workflow or node as a reusable template."""
    if payload.kind == "workflow":
        if payload.workflow is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="'workflow' field is required for kind='workflow'",
            )
        wf = payload.workflow
        template = await template_service.create_workflow_template(
            db=db,
            author_id=current_user.id,
            name=wf.name,
            description=wf.description,
            tags=wf.tags,
            nodes=wf.nodes,
            edges=wf.edges,
            canvas_snapshot=wf.canvas_snapshot,
            visibility=wf.visibility.value,
            shared_with=wf.shared_with,
            shared_with_teams=getattr(wf, "shared_with_teams", None) or [],
        )
        return WorkflowTemplateResponse(
            id=template.id,
            author_id=template.author_id,
            author_name=current_user.name,
            name=template.name,
            description=template.description,
            tags=template.tags,
            nodes=template.nodes,
            edges=template.edges,
            canvas_snapshot=template.canvas_snapshot,
            visibility=template.visibility,
            shared_with=template.shared_with,
            shared_with_teams=template.shared_with_teams or [],
            use_count=template.use_count,
            created_at=template.created_at,
        )

    elif payload.kind == "node":
        if payload.node is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="'node' field is required for kind='node'",
            )
        nd = payload.node
        template = await template_service.create_node_template(
            db=db,
            author_id=current_user.id,
            name=nd.name,
            description=nd.description,
            tags=nd.tags,
            node_type=nd.node_type,
            node_data=nd.node_data,
            visibility=nd.visibility.value,
            shared_with=nd.shared_with,
            shared_with_teams=getattr(nd, "shared_with_teams", None) or [],
        )
        return NodeTemplateResponse(
            id=template.id,
            author_id=template.author_id,
            author_name=current_user.name,
            name=template.name,
            description=template.description,
            tags=template.tags,
            node_type=template.node_type,
            node_data=template.node_data,
            visibility=template.visibility,
            shared_with=template.shared_with,
            shared_with_teams=template.shared_with_teams or [],
            use_count=template.use_count,
            created_at=template.created_at,
        )

    raise HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail="kind must be 'workflow' or 'node'",
    )


@router.get("/workflow/{template_id}", response_model=WorkflowTemplateResponse)
async def get_workflow_template(
    template_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> WorkflowTemplateResponse:
    template = await template_service.get_workflow_template(db, template_id)
    if not template:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Template not found")
    return _wf_response(template)


@router.get("/node/{template_id}", response_model=NodeTemplateResponse)
async def get_node_template(
    template_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> NodeTemplateResponse:
    template = await template_service.get_node_template(db, template_id)
    if not template:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Template not found")
    return _nd_response(template)


@router.post("/workflow/{template_id}/use", response_model=WorkflowTemplateResponse)
async def use_workflow_template(
    template_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> WorkflowTemplateResponse:
    template = await template_service.get_workflow_template(db, template_id)
    if not template:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Template not found")
    template = await template_service.increment_workflow_template_use(db, template)
    return _wf_response(template)


@router.post("/node/{template_id}/use", response_model=NodeTemplateResponse)
async def use_node_template(
    template_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> NodeTemplateResponse:
    template = await template_service.get_node_template(db, template_id)
    if not template:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Template not found")
    template = await template_service.increment_node_template_use(db, template)
    return _nd_response(template)


@router.patch("/workflow/{template_id}", response_model=WorkflowTemplateResponse)
async def update_workflow_template(
    template_id: uuid.UUID,
    payload: UpdateWorkflowTemplateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> WorkflowTemplateResponse:
    """Update editable fields of a workflow template. Only the author can edit."""
    template = await template_service.get_workflow_template(db, template_id)
    if not template:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Template not found")
    if template.author_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized")
    template = await template_service.update_workflow_template(
        db,
        template,
        name=payload.name,
        description=payload.description,
        tags=payload.tags,
        visibility=payload.visibility.value if payload.visibility else None,
        shared_with=payload.shared_with,
        shared_with_teams=payload.shared_with_teams,
    )
    template = await template_service.get_workflow_template(db, template.id)
    return _wf_response(template)


@router.patch("/node/{template_id}", response_model=NodeTemplateResponse)
async def update_node_template(
    template_id: uuid.UUID,
    payload: UpdateNodeTemplateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> NodeTemplateResponse:
    """Update editable fields of a node template. Only the author can edit."""
    template = await template_service.get_node_template(db, template_id)
    if not template:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Template not found")
    if template.author_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized")
    template = await template_service.update_node_template(
        db,
        template,
        name=payload.name,
        description=payload.description,
        tags=payload.tags,
        visibility=payload.visibility.value if payload.visibility else None,
        shared_with=payload.shared_with,
        shared_with_teams=payload.shared_with_teams,
    )
    template = await template_service.get_node_template(db, template.id)
    return _nd_response(template)


@router.delete("/workflow/{template_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_workflow_template(
    template_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    template = await template_service.get_workflow_template(db, template_id)
    if not template:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Template not found")
    if template.author_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized")
    await template_service.delete_workflow_template(db, template)


@router.delete("/node/{template_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_node_template(
    template_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    template = await template_service.get_node_template(db, template_id)
    if not template:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Template not found")
    if template.author_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized")
    await template_service.delete_node_template(db, template)
