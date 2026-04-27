import io
import json
import uuid
import zipfile

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import get_current_user, get_db
from app.db.models import Folder, User, Workflow, WorkflowShare
from app.models.schemas import (
    FolderCreate,
    FolderResponse,
    FolderTreeResponse,
    FolderUpdate,
    FolderWithContentsResponse,
    WorkflowListResponse,
)

router = APIRouter(prefix="/folders", tags=["folders"])


def _build_zip_bytes(
    folder_name: str,
    workflows: list[dict],
    children: list[dict],
    prefix: str = "",
) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        _write_folder_to_zip(zf, folder_name, workflows, children, prefix)
    return buf.getvalue()


def _write_folder_to_zip(
    zf: zipfile.ZipFile,
    folder_name: str,
    workflows: list[dict],
    children: list[dict],
    prefix: str,
) -> None:
    safe_name = folder_name.replace("/", "_").replace("\\", "_")
    folder_path = f"{prefix}{safe_name}/"

    for wf in workflows:
        safe_wf_name = wf["name"].replace("/", "_").replace("\\", "_")
        content = json.dumps(
            {"name": wf["name"], "nodes": wf["nodes"], "edges": wf["edges"]},
            ensure_ascii=False,
        ).encode("utf-8")
        zf.writestr(f"{folder_path}{safe_wf_name}.json", content)

    for child in children:
        _write_folder_to_zip(
            zf,
            child["name"],
            child["workflows"],
            child["children"],
            folder_path,
        )


def _get_first_node_type(workflow: Workflow) -> str | None:
    nodes = workflow.nodes or []
    edges = workflow.edges or []

    if not nodes:
        return None

    target_node_ids = {edge.get("target") for edge in edges if edge.get("target")}
    start_nodes = [
        node
        for node in nodes
        if node.get("id") not in target_node_ids
        and node.get("data", {}).get("active") is not False
        and node.get("type") not in ("sticky", "errorHandler")
    ]

    if start_nodes:
        return start_nodes[0].get("type")

    active_nodes = [
        node
        for node in nodes
        if node.get("data", {}).get("active") is not False
        and node.get("type") not in ("sticky", "errorHandler")
    ]
    if active_nodes:
        return active_nodes[0].get("type")

    return None


@router.get("", response_model=list[FolderResponse])
async def list_root_folders(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[Folder]:
    result = await db.execute(
        select(Folder)
        .where(Folder.owner_id == current_user.id)
        .where(Folder.parent_id.is_(None))
        .order_by(Folder.name)
    )
    return list(result.scalars().all())


@router.get("/tree", response_model=list[FolderTreeResponse])
async def get_folder_tree(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[FolderTreeResponse]:
    result = await db.execute(
        select(Folder)
        .where(Folder.owner_id == current_user.id)
        .options(selectinload(Folder.children), selectinload(Folder.workflows))
        .order_by(Folder.name)
    )
    folders = list(result.scalars().unique().all())

    shares_result = await db.execute(
        select(WorkflowShare)
        .options(selectinload(WorkflowShare.workflow))
        .where(
            WorkflowShare.user_id == current_user.id,
            WorkflowShare.folder_id.isnot(None),
        )
    )
    shares_with_folders = list(shares_result.scalars().all())

    folder_map: dict[uuid.UUID, FolderTreeResponse] = {}
    for folder in folders:
        folder_map[folder.id] = FolderTreeResponse(
            id=folder.id,
            name=folder.name,
            parent_id=folder.parent_id,
            children=[],
            workflows=[
                WorkflowListResponse(
                    id=w.id,
                    name=w.name,
                    description=w.description,
                    folder_id=w.folder_id,
                    first_node_type=_get_first_node_type(w),
                    scheduled_for_deletion=w.scheduled_for_deletion,
                    created_at=w.created_at,
                    updated_at=w.updated_at,
                )
                for w in folder.workflows
            ],
        )

    for share in shares_with_folders:
        if share.folder_id and share.folder_id in folder_map:
            w = share.workflow
            folder_map[share.folder_id].workflows.append(
                WorkflowListResponse(
                    id=w.id,
                    name=w.name,
                    description=w.description,
                    folder_id=share.folder_id,
                    first_node_type=_get_first_node_type(w),
                    scheduled_for_deletion=None,
                    created_at=w.created_at,
                    updated_at=w.updated_at,
                )
            )

    root_folders: list[FolderTreeResponse] = []
    for folder in folders:
        folder_response = folder_map[folder.id]
        if folder.parent_id is None:
            root_folders.append(folder_response)
        elif folder.parent_id in folder_map:
            folder_map[folder.parent_id].children.append(folder_response)

    return root_folders


@router.get("/{folder_id}/export")
async def export_folder_as_zip(
    folder_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> StreamingResponse:
    result = await db.execute(
        select(Folder).where(Folder.id == folder_id).where(Folder.owner_id == current_user.id)
    )
    folder = result.scalar_one_or_none()
    if not folder:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Folder not found")

    async def _load_folder_dict(f: Folder) -> dict:
        wf_result = await db.execute(select(Workflow).where(Workflow.folder_id == f.id))
        folder_workflows = list(wf_result.scalars().all())

        children_result = await db.execute(
            select(Folder)
            .where(Folder.parent_id == f.id)
            .where(Folder.owner_id == current_user.id)
            .order_by(Folder.name)
        )
        folder_children = list(children_result.scalars().all())

        return {
            "name": f.name,
            "workflows": [
                {"name": w.name, "nodes": w.nodes or [], "edges": w.edges or []}
                for w in folder_workflows
            ],
            "children": [await _load_folder_dict(c) for c in folder_children],
        }

    folder_dict = await _load_folder_dict(folder)
    zip_bytes = _build_zip_bytes(
        folder_name=folder_dict["name"],
        workflows=folder_dict["workflows"],
        children=folder_dict["children"],
    )

    safe_filename = folder.name.replace('"', "").replace("/", "_")
    return StreamingResponse(
        iter([zip_bytes]),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{safe_filename}.zip"'},
    )


@router.get("/{folder_id}", response_model=FolderWithContentsResponse)
async def get_folder(
    folder_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> FolderWithContentsResponse:
    result = await db.execute(
        select(Folder)
        .where(Folder.id == folder_id)
        .where(Folder.owner_id == current_user.id)
        .options(selectinload(Folder.children), selectinload(Folder.workflows))
    )
    folder = result.scalar_one_or_none()
    if not folder:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Folder not found")

    return FolderWithContentsResponse(
        id=folder.id,
        name=folder.name,
        parent_id=folder.parent_id,
        owner_id=folder.owner_id,
        created_at=folder.created_at,
        updated_at=folder.updated_at,
        children=[
            FolderResponse(
                id=c.id,
                name=c.name,
                parent_id=c.parent_id,
                owner_id=c.owner_id,
                created_at=c.created_at,
                updated_at=c.updated_at,
            )
            for c in folder.children
        ],
        workflows=[
            WorkflowListResponse(
                id=w.id,
                name=w.name,
                description=w.description,
                folder_id=w.folder_id,
                first_node_type=_get_first_node_type(w),
                scheduled_for_deletion=w.scheduled_for_deletion,
                created_at=w.created_at,
                updated_at=w.updated_at,
            )
            for w in folder.workflows
        ],
    )


@router.post("", response_model=FolderResponse, status_code=status.HTTP_201_CREATED)
async def create_folder(
    data: FolderCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Folder:
    if data.parent_id:
        parent_result = await db.execute(
            select(Folder)
            .where(Folder.id == data.parent_id)
            .where(Folder.owner_id == current_user.id)
        )
        parent = parent_result.scalar_one_or_none()
        if not parent:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Parent folder not found"
            )

    folder = Folder(
        name=data.name,
        parent_id=data.parent_id,
        owner_id=current_user.id,
    )
    db.add(folder)
    await db.commit()
    await db.refresh(folder)
    return folder


@router.put("/{folder_id}", response_model=FolderResponse)
async def update_folder(
    folder_id: uuid.UUID,
    data: FolderUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Folder:
    result = await db.execute(
        select(Folder).where(Folder.id == folder_id).where(Folder.owner_id == current_user.id)
    )
    folder = result.scalar_one_or_none()
    if not folder:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Folder not found")

    if data.name is not None:
        folder.name = data.name

    if data.parent_id is not None:
        if data.parent_id == folder_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot set folder as its own parent",
            )

        descendants = await _get_all_descendant_ids(db, folder_id, current_user.id)
        if data.parent_id in descendants:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot move folder into its own descendant",
            )

        if data.parent_id != uuid.UUID(int=0):
            parent_result = await db.execute(
                select(Folder)
                .where(Folder.id == data.parent_id)
                .where(Folder.owner_id == current_user.id)
            )
            parent = parent_result.scalar_one_or_none()
            if not parent:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND, detail="Parent folder not found"
                )
            folder.parent_id = data.parent_id
        else:
            folder.parent_id = None

    await db.commit()
    await db.refresh(folder)
    return folder


async def _get_all_descendant_ids(
    db: AsyncSession, folder_id: uuid.UUID, owner_id: uuid.UUID
) -> set[uuid.UUID]:
    descendants: set[uuid.UUID] = set()
    to_check = [folder_id]

    while to_check:
        current_id = to_check.pop()
        result = await db.execute(
            select(Folder.id)
            .where(Folder.parent_id == current_id)
            .where(Folder.owner_id == owner_id)
        )
        children_ids = list(result.scalars().all())
        for child_id in children_ids:
            if child_id not in descendants:
                descendants.add(child_id)
                to_check.append(child_id)

    return descendants


@router.delete("/{folder_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_folder(
    folder_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    result = await db.execute(
        select(Folder).where(Folder.id == folder_id).where(Folder.owner_id == current_user.id)
    )
    folder = result.scalar_one_or_none()
    if not folder:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Folder not found")

    await db.delete(folder)
    await db.commit()


@router.put("/{folder_id}/workflows/{workflow_id}", response_model=WorkflowListResponse)
async def move_workflow_to_folder(
    folder_id: uuid.UUID,
    workflow_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> WorkflowListResponse:
    folder_result = await db.execute(
        select(Folder).where(Folder.id == folder_id).where(Folder.owner_id == current_user.id)
    )
    folder = folder_result.scalar_one_or_none()
    if not folder:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Folder not found")

    workflow_result = await db.execute(
        select(Workflow).where(
            Workflow.id == workflow_id,
            or_(
                Workflow.owner_id == current_user.id,
                Workflow.id.in_(
                    select(WorkflowShare.workflow_id).where(
                        WorkflowShare.user_id == current_user.id
                    )
                ),
            ),
        )
    )
    workflow = workflow_result.scalar_one_or_none()
    if not workflow:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow not found")

    if workflow.owner_id == current_user.id:
        workflow.folder_id = folder_id
        await db.commit()
        await db.refresh(workflow)
        return WorkflowListResponse(
            id=workflow.id,
            name=workflow.name,
            description=workflow.description,
            folder_id=workflow.folder_id,
            first_node_type=_get_first_node_type(workflow),
            scheduled_for_deletion=workflow.scheduled_for_deletion,
            created_at=workflow.created_at,
            updated_at=workflow.updated_at,
        )
    else:
        share_result = await db.execute(
            select(WorkflowShare).where(
                WorkflowShare.workflow_id == workflow_id,
                WorkflowShare.user_id == current_user.id,
            )
        )
        share = share_result.scalar_one_or_none()
        if share:
            share.folder_id = folder_id
            await db.commit()
            await db.refresh(share)
        return WorkflowListResponse(
            id=workflow.id,
            name=workflow.name,
            description=workflow.description,
            folder_id=folder_id,
            first_node_type=_get_first_node_type(workflow),
            scheduled_for_deletion=None,
            created_at=workflow.created_at,
            updated_at=workflow.updated_at,
        )


@router.delete("/workflows/{workflow_id}/folder", response_model=WorkflowListResponse)
async def remove_workflow_from_folder(
    workflow_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> WorkflowListResponse:
    result = await db.execute(
        select(Workflow).where(
            Workflow.id == workflow_id,
            or_(
                Workflow.owner_id == current_user.id,
                Workflow.id.in_(
                    select(WorkflowShare.workflow_id).where(
                        WorkflowShare.user_id == current_user.id
                    )
                ),
            ),
        )
    )
    workflow = result.scalar_one_or_none()
    if not workflow:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow not found")

    if workflow.owner_id == current_user.id:
        workflow.folder_id = None
        await db.commit()
        await db.refresh(workflow)
        return WorkflowListResponse(
            id=workflow.id,
            name=workflow.name,
            description=workflow.description,
            folder_id=workflow.folder_id,
            first_node_type=_get_first_node_type(workflow),
            scheduled_for_deletion=workflow.scheduled_for_deletion,
            created_at=workflow.created_at,
            updated_at=workflow.updated_at,
        )
    else:
        share_result = await db.execute(
            select(WorkflowShare).where(
                WorkflowShare.workflow_id == workflow_id,
                WorkflowShare.user_id == current_user.id,
            )
        )
        share = share_result.scalar_one_or_none()
        if share:
            share.folder_id = None
            await db.commit()
            await db.refresh(share)
        return WorkflowListResponse(
            id=workflow.id,
            name=workflow.name,
            description=workflow.description,
            folder_id=None,
            first_node_type=_get_first_node_type(workflow),
            scheduled_for_deletion=None,
            created_at=workflow.created_at,
            updated_at=workflow.updated_at,
        )
