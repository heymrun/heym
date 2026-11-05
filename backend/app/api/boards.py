"""Agentic kanban board API: boards, columns, cards, moves, runs, comments, sharing."""

import uuid

from fastapi import (
    APIRouter,
    Depends,
    File,
    HTTPException,
    Request,
    UploadFile,
    status,
)
from pydantic import BaseModel
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.models import (
    ActiveWorkflowExecution,
    Board,
    BoardCard,
    BoardCardActivity,
    BoardCardRun,
    BoardColumn,
    BoardColumnWorkflow,
    BoardShare,
    BoardTeamShare,
    Credential,
    ExecutionHistory,
    GeneratedFile,
    Team,
    TeamMember,
    User,
    Workflow,
)
from app.db.session import get_db
from app.models.board_schemas import (
    BoardCardResponse,
    BoardColumnResponse,
    BoardColumnWorkflowResponse,
    BoardCreateRequest,
    BoardMemberResponse,
    BoardShareRequest,
    BoardShareResponse,
    BoardStateResponse,
    BoardSummaryResponse,
    BoardTeamShareRequest,
    BoardTeamShareResponse,
    BoardUpdateRequest,
    CardActivityResponse,
    CardAttachmentResponse,
    CardCreateRequest,
    CardDetailResponse,
    CardFieldsResponse,
    CardLinkModel,
    CardLinkResponse,
    CardMoveRequest,
    CardRunResponse,
    CardUpdateRequest,
    ColumnCreateRequest,
    ColumnUpdateRequest,
    CommentCreateRequest,
)
from app.services import board_run_service
from app.services.audit_log import audit
from app.services.board_access import (
    accessible_board_ids,
    board_member_ids,
    board_members,
    board_permission,
    board_permissions,
)
from app.services.board_card_fields import (
    ASSIGNEE_KEY,
    DUE_DATE_KEY,
    FIELD_KEYS,
    LINKS_KEY,
    MAX_LINKS,
    CardLinkValue,
    edit_version,
    links_to_metadata,
    merge_metadata,
    read_fields,
)
from app.services.credential_access import get_accessible_credential
from app.services.file_storage import (
    build_download_url,
    create_access_token,
    delete_file,
    store_file,
)
from app.services.hitl_service import build_public_base_url
from app.services.pending_review_cancel import cancel_pending_review_execution
from app.services.upload_limits import read_upload_file_limited
from app.services.workflow_access import get_accessible_workflow, workflow_access_clause

router = APIRouter()

DEFAULT_COLUMNS = (
    ("Backlog", "#8b5cf6"),
    ("Planning", "#22d3ee"),
    ("Development", "#f59e0b"),
    ("Done", "#10d9a0"),
)
ACTIVE_RUN_STATUSES = ("running", "pending")
MAX_BOARD_CARDS = 500


async def _get_owned_board(db: AsyncSession, board_id: uuid.UUID, user: User) -> Board:
    """Owner-only access: board settings, sharing and deletion."""
    result = await db.execute(select(Board).where(Board.id == board_id, Board.owner_id == user.id))
    board = result.scalar_one_or_none()
    if board is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Board not found")
    return board


async def _board_permission(db: AsyncSession, board: Board, user: User) -> str | None:
    """The caller's access to a board: "owner", "write", "read", or None when it is not shared."""
    return await board_permission(db, board, user.id)


async def _get_board_for_user(
    db: AsyncSession, board_id: uuid.UUID, user: User, *, write: bool
) -> tuple[Board, str]:
    """A board the caller owns or has been given access to (directly or through a team)."""
    board = (await db.execute(select(Board).where(Board.id == board_id))).scalar_one_or_none()
    permission = await _board_permission(db, board, user) if board is not None else None
    if board is None or permission is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Board not found")
    if write and permission == "read":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Read-only access to this board"
        )
    return board, permission


async def _get_board_column(db: AsyncSession, board: Board, column_id: uuid.UUID) -> BoardColumn:
    result = await db.execute(
        select(BoardColumn).where(BoardColumn.id == column_id, BoardColumn.board_id == board.id)
    )
    column = result.scalar_one_or_none()
    if column is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Column not found")
    return column


async def _get_board_card(db: AsyncSession, board: Board, card_id: uuid.UUID) -> BoardCard:
    result = await db.execute(
        select(BoardCard).where(BoardCard.id == card_id, BoardCard.board_id == board.id)
    )
    card = result.scalar_one_or_none()
    if card is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Card not found")
    return card


async def _reorder_columns(
    db: AsyncSession, board: Board, column: BoardColumn, target: int
) -> None:
    """Move a column to `target` and renumber the board's columns 0..n-1.

    Positions drive the planning gate and the auto-advance cascade, so they must stay a
    dense, ordered sequence — setting one column's position on its own would collide.
    """
    columns = list(
        (
            await db.execute(
                select(BoardColumn)
                .where(BoardColumn.board_id == board.id)
                .order_by(BoardColumn.position)
            )
        )
        .scalars()
        .all()
    )
    ordered = [c for c in columns if c.id != column.id]
    index = max(0, min(target, len(ordered)))
    ordered.insert(index, column)
    for position, item in enumerate(ordered):
        item.position = position


async def _reindex_cards(db: AsyncSession, column_id: uuid.UUID) -> None:
    result = await db.execute(
        select(BoardCard)
        .where(BoardCard.column_id == column_id)
        .order_by(BoardCard.position, BoardCard.updated_at)
    )
    for index, card in enumerate(result.scalars().all()):
        card.position = index


async def _place_card(
    db: AsyncSession, card: BoardCard, column_id: uuid.UUID, index: int | None
) -> None:
    """Put ``card`` at ``index`` of ``column_id`` (the top when None) and renumber the column
    0..n-1, so every app shows the same order."""
    others = list(
        (
            await db.execute(
                select(BoardCard)
                .where(BoardCard.column_id == column_id, BoardCard.id != card.id)
                .order_by(BoardCard.position, BoardCard.updated_at)
            )
        )
        .scalars()
        .all()
    )
    target = 0 if index is None else max(0, min(index, len(others)))
    others.insert(target, card)
    for position, item in enumerate(others):
        if item.position != position:
            item.position = position


async def _column_workflow_responses(
    db: AsyncSession, column_ids: list[uuid.UUID]
) -> dict[uuid.UUID, list[BoardColumnWorkflowResponse]]:
    if not column_ids:
        return {}
    result = await db.execute(
        select(BoardColumnWorkflow, Workflow.name)
        .join(Workflow, Workflow.id == BoardColumnWorkflow.workflow_id)
        .where(BoardColumnWorkflow.column_id.in_(column_ids))
        .order_by(BoardColumnWorkflow.position)
    )
    grouped: dict[uuid.UUID, list[BoardColumnWorkflowResponse]] = {}
    for link, workflow_name in result.all():
        grouped.setdefault(link.column_id, []).append(
            BoardColumnWorkflowResponse(
                workflow_id=link.workflow_id,
                workflow_name=workflow_name,
                position=link.position,
            )
        )
    return grouped


CARD_CHANGED_MESSAGE = "This card was changed by someone else. Showing the latest version."


def _card_response(
    card: BoardCard,
    *,
    actively_running: bool = False,
    links: list[CardLinkResponse] | None = None,
) -> BoardCardResponse:
    metadata = card.card_metadata or {}
    values = read_fields(metadata)
    return BoardCardResponse(
        id=card.id,
        board_id=card.board_id,
        column_id=card.column_id,
        title=card.title,
        content=card.content,
        position=card.position,
        run_status="running" if actively_running else card.run_status,
        # Links are shown resolved in `fields`; their raw ids stay out of the response.
        card_metadata={k: v for k, v in metadata.items() if k != LINKS_KEY},
        fields=CardFieldsResponse(
            assignee_user_id=values.assignee_user_id,
            priority=values.priority,
            due_date=values.due_date,
            labels=list(values.labels),
            links=links or [],
        ),
        edit_version=edit_version(card.title, card.content, metadata),
        created_at=card.created_at,
        updated_at=card.updated_at,
    )


async def _resolve_links(
    db: AsyncSession, user: User, cards: list[BoardCard]
) -> dict[uuid.UUID, list[CardLinkResponse]]:
    """Each card's links as ``user`` may see them; no query when no card has links."""
    by_card = {card.id: read_fields(card.card_metadata).links for card in cards}
    workflow_ids = {link.workflow_id for links in by_card.values() for link in links}
    if not workflow_ids:
        return {}
    reachable = dict(
        (
            await db.execute(
                select(Workflow.id, Workflow.name).where(
                    Workflow.id.in_(workflow_ids), workflow_access_clause(user.id)
                )
            )
        ).all()
    )
    execution_ids = {
        link.execution_id
        for links in by_card.values()
        for link in links
        if link.execution_id is not None and link.workflow_id in reachable
    }
    executions: dict[uuid.UUID, tuple[uuid.UUID, str]] = {}
    if execution_ids:
        rows = await db.execute(
            select(
                ExecutionHistory.id, ExecutionHistory.workflow_id, ExecutionHistory.status
            ).where(ExecutionHistory.id.in_(execution_ids))
        )
        executions = {row.id: (row.workflow_id, row.status) for row in rows.all()}
    resolved: dict[uuid.UUID, list[CardLinkResponse]] = {}
    for card_id, links in by_card.items():
        items: list[CardLinkResponse] = []
        for link in links:
            if link.workflow_id not in reachable:
                items.append(CardLinkResponse(hidden=True))
                continue
            execution = executions.get(link.execution_id) if link.execution_id else None
            items.append(
                CardLinkResponse(
                    workflow_id=link.workflow_id,
                    workflow_name=reachable[link.workflow_id],
                    execution_id=link.execution_id,
                    execution_status=execution[1]
                    if execution and execution[0] == link.workflow_id
                    else None,
                )
            )
        resolved[card_id] = items
    return resolved


async def _card_out(
    db: AsyncSession, user: User, card: BoardCard, *, actively_running: bool = False
) -> BoardCardResponse:
    links = await _resolve_links(db, user, [card])
    return _card_response(card, actively_running=actively_running, links=links.get(card.id))


async def _checked_links(
    db: AsyncSession, user: User, links: list[CardLinkModel], card: BoardCard | None
) -> list[dict[str, str | None]]:
    """The links to store. Each must be reachable by the writer; links the writer cannot
    see (someone else's) are kept rather than silently dropped."""
    wanted: list[CardLinkValue] = []
    for link in links:
        workflow = (
            await db.execute(
                select(Workflow.id).where(
                    Workflow.id == link.workflow_id, workflow_access_clause(user.id)
                )
            )
        ).scalar_one_or_none()
        if workflow is None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Linked workflow not found")
        if link.execution_id is not None:
            owner = (
                await db.execute(
                    select(ExecutionHistory.workflow_id).where(
                        ExecutionHistory.id == link.execution_id
                    )
                )
            ).scalar_one_or_none()
            if owner != link.workflow_id:
                raise HTTPException(
                    status.HTTP_400_BAD_REQUEST, "Linked execution not found for that workflow"
                )
        value = CardLinkValue(link.workflow_id, link.execution_id)
        if value not in wanted:
            wanted.append(value)
    if card is not None:
        stored = read_fields(card.card_metadata).links
        unlisted = {link.workflow_id for link in stored} - {link.workflow_id for link in wanted}
        if unlisted:
            reachable = set(
                (
                    await db.execute(
                        select(Workflow.id).where(
                            Workflow.id.in_(unlisted), workflow_access_clause(user.id)
                        )
                    )
                )
                .scalars()
                .all()
            )
            wanted += [
                link
                for link in stored
                if link.workflow_id in unlisted and link.workflow_id not in reachable
            ]
    if len(wanted) > MAX_LINKS:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, f"A card can have at most {MAX_LINKS} links"
        )
    return links_to_metadata(wanted)


async def _field_updates(
    db: AsyncSession, board: Board, user: User, request: BaseModel, card: BoardCard | None
) -> dict[str, object]:
    """The typed fields ``request`` sets, validated, in their stored form."""
    updates: dict[str, object] = {}
    for key in request.model_fields_set & set(FIELD_KEYS):
        value = getattr(request, key)
        if value is None:
            updates[key] = None
        elif key == ASSIGNEE_KEY:
            if value not in await board_member_ids(db, board):
                raise HTTPException(
                    status.HTTP_400_BAD_REQUEST, "The assignee must be a member of this board"
                )
            updates[key] = str(value)
        elif key == DUE_DATE_KEY:
            updates[key] = value.isoformat()
        elif key == LINKS_KEY:
            updates[key] = await _checked_links(db, user, value, card)
        else:
            updates[key] = value
    return updates


async def _active_board_execution_ids(
    db: AsyncSession, card_ids: list[uuid.UUID]
) -> dict[uuid.UUID, set[uuid.UUID]]:
    """Return fresh workflow executions linked to each board card run."""
    if not card_ids:
        return {}
    result = await db.execute(
        select(BoardCardRun.card_id, BoardCardRun.active_execution_id)
        .join(
            ActiveWorkflowExecution,
            ActiveWorkflowExecution.execution_id == BoardCardRun.active_execution_id,
        )
        .where(
            BoardCardRun.card_id.in_(card_ids),
            *board_run_service.live_execution_conditions(),
        )
    )
    active_by_card: dict[uuid.UUID, set[uuid.UUID]] = {}
    for card_id, execution_id in result.all():
        if execution_id is not None:
            active_by_card.setdefault(card_id, set()).add(execution_id)
    return active_by_card


async def _validate_accessible_credential(
    db: AsyncSession, credential_id: uuid.UUID, user: User
) -> None:
    credential = await get_accessible_credential(db, credential_id, user.id)
    if credential is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Credential not found")


async def _mapper_credential_name(db: AsyncSession, board: Board) -> str | None:
    if board.mapper_credential_id is None:
        return None
    result = await db.execute(
        select(Credential.name).where(Credential.id == board.mapper_credential_id)
    )
    return result.scalar_one_or_none()


def _board_summary(
    board: Board,
    *,
    column_count: int,
    card_count: int,
    cred_name: str | None,
    permission: str = "owner",
) -> BoardSummaryResponse:
    return BoardSummaryResponse(
        id=board.id,
        name=board.name,
        description=board.description,
        column_count=column_count,
        card_count=card_count,
        mapper_model=board.mapper_model,
        mapper_credential_id=board.mapper_credential_id,
        mapper_credential_name=cred_name,
        permission=permission,
        auto_advance=board.auto_advance,
        updated_at=board.updated_at,
    )


@router.get("", response_model=list[BoardSummaryResponse])
async def list_boards(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[BoardSummaryResponse]:
    result = await db.execute(
        select(Board)
        .where(Board.id.in_(accessible_board_ids(current_user.id)))
        .order_by(Board.created_at)
    )
    boards = result.scalars().all()
    permissions = await board_permissions(db, boards, current_user.id)
    summaries: list[BoardSummaryResponse] = []
    for board in boards:
        column_count = (
            await db.execute(
                select(func.count(BoardColumn.id)).where(BoardColumn.board_id == board.id)
            )
        ).scalar() or 0
        card_count = (
            await db.execute(select(func.count(BoardCard.id)).where(BoardCard.board_id == board.id))
        ).scalar() or 0
        cred_name = await _mapper_credential_name(db, board)
        permission = permissions.get(board.id, "read")
        summaries.append(
            _board_summary(
                board,
                column_count=column_count,
                card_count=card_count,
                cred_name=cred_name,
                permission=permission,
            )
        )
    return summaries


@router.post("", response_model=BoardSummaryResponse, status_code=status.HTTP_201_CREATED)
async def create_board(
    request: BoardCreateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> BoardSummaryResponse:
    if request.mapper_credential_id is not None:
        await _validate_accessible_credential(db, request.mapper_credential_id, current_user)
    board = Board(
        owner_id=current_user.id,
        name=request.name,
        description=request.description,
        mapper_model=request.mapper_model,
        mapper_credential_id=request.mapper_credential_id,
        auto_advance=request.auto_advance,
    )
    db.add(board)
    await db.flush()
    for index, (column_name, color) in enumerate(DEFAULT_COLUMNS):
        db.add(
            BoardColumn(
                board_id=board.id,
                name=column_name,
                position=index,
                color=color,
            )
        )
    await db.commit()
    await db.refresh(board)
    audit(
        action="board.create",
        actor=current_user,
        target_type="board",
        target_id=board.id,
        target_name=board.name,
    )
    cred_name = await _mapper_credential_name(db, board)
    return _board_summary(
        board, column_count=len(DEFAULT_COLUMNS), card_count=0, cred_name=cred_name
    )


@router.get("/{board_id}", response_model=BoardStateResponse)
async def get_board_state(
    board_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> BoardStateResponse:
    board, permission = await _get_board_for_user(db, board_id, current_user, write=False)
    columns_result = await db.execute(
        select(BoardColumn).where(BoardColumn.board_id == board.id).order_by(BoardColumn.position)
    )
    columns = columns_result.scalars().all()
    cards_result = await db.execute(
        select(BoardCard)
        .where(BoardCard.board_id == board.id)
        .order_by(BoardCard.position)
        .limit(MAX_BOARD_CARDS)
    )
    cards = cards_result.scalars().all()
    active_executions = await _active_board_execution_ids(db, [card.id for card in cards])
    links = await _resolve_links(db, current_user, list(cards))
    workflows_by_column = await _column_workflow_responses(db, [c.id for c in columns])
    cred_name = await _mapper_credential_name(db, board)
    return BoardStateResponse(
        id=board.id,
        name=board.name,
        description=board.description,
        mapper_model=board.mapper_model,
        mapper_credential_id=board.mapper_credential_id,
        mapper_credential_name=cred_name,
        permission=permission,
        auto_advance=board.auto_advance,
        columns=[
            BoardColumnResponse(
                id=column.id,
                board_id=column.board_id,
                name=column.name,
                position=column.position,
                color=column.color,
                ai_instructions=column.ai_instructions,
                workflows=workflows_by_column.get(column.id, []),
            )
            for column in columns
        ],
        cards=[
            _card_response(
                card,
                actively_running=card.id in active_executions,
                links=links.get(card.id),
            )
            for card in cards
        ],
        has_active_runs=bool(active_executions)
        or any(card.run_status in ACTIVE_RUN_STATUSES for card in cards),
    )


@router.get("/{board_id}/members", response_model=list[BoardMemberResponse])
async def list_board_members(
    board_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[BoardMemberResponse]:
    """Everyone who can open the board, for assigning cards."""
    board, _ = await _get_board_for_user(db, board_id, current_user, write=False)
    return [
        BoardMemberResponse(
            user_id=member.user_id,
            name=member.name,
            email=member.email,
            permission=member.permission,
        )
        for member in await board_members(db, board)
    ]


@router.patch("/{board_id}", response_model=BoardSummaryResponse)
async def update_board(
    board_id: uuid.UUID,
    request: BoardUpdateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> BoardSummaryResponse:
    board = await _get_owned_board(db, board_id, current_user)
    fields_set = request.model_fields_set
    if request.name is not None:
        board.name = request.name
    if request.description is not None:
        board.description = request.description
    if request.auto_advance is not None:
        board.auto_advance = request.auto_advance
    if "mapper_model" in fields_set:
        board.mapper_model = request.mapper_model
    if "mapper_credential_id" in fields_set:
        if request.mapper_credential_id is not None:
            await _validate_accessible_credential(db, request.mapper_credential_id, current_user)
        board.mapper_credential_id = request.mapper_credential_id
    await db.commit()
    await db.refresh(board)
    audit(
        action="board.update",
        actor=current_user,
        target_type="board",
        target_id=board.id,
        target_name=board.name,
        fields=",".join(sorted(fields_set)) or None,
    )
    cred_name = await _mapper_credential_name(db, board)
    return _board_summary(board, column_count=0, card_count=0, cred_name=cred_name)


@router.delete("/{board_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_board(
    board_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    board = await _get_owned_board(db, board_id, current_user)
    audit(
        action="board.delete",
        actor=current_user,
        target_type="board",
        target_id=board.id,
        target_name=board.name,
    )
    await db.delete(board)
    await db.commit()


@router.post(
    "/{board_id}/columns",
    response_model=BoardColumnResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_column(
    board_id: uuid.UUID,
    request: ColumnCreateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> BoardColumnResponse:
    board, _ = await _get_board_for_user(db, board_id, current_user, write=True)
    count = (
        await db.execute(select(func.count(BoardColumn.id)).where(BoardColumn.board_id == board.id))
    ).scalar() or 0
    column = BoardColumn(board_id=board.id, name=request.name, position=count, color=request.color)
    db.add(column)
    if request.position is not None:
        # Insert at the requested slot and keep positions a dense 0..n-1 sequence.
        await db.flush()
        await _reorder_columns(db, board, column, request.position)
    await db.commit()
    await db.refresh(column)
    audit(
        action="board.column_create",
        actor=current_user,
        target_type="board",
        target_id=board.id,
        target_name=board.name,
        column_id=column.id,
        column_name=column.name,
    )
    return BoardColumnResponse(
        id=column.id,
        board_id=column.board_id,
        name=column.name,
        position=column.position,
        color=column.color,
        workflows=[],
    )


@router.patch("/{board_id}/columns/{column_id}", response_model=BoardColumnResponse)
async def update_column(
    board_id: uuid.UUID,
    column_id: uuid.UUID,
    request: ColumnUpdateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> BoardColumnResponse:
    board, _ = await _get_board_for_user(db, board_id, current_user, write=True)
    column = await _get_board_column(db, board, column_id)
    fields_set = request.model_fields_set
    if request.name is not None:
        column.name = request.name
    if request.color is not None:
        column.color = request.color
    if request.position is not None:
        await _reorder_columns(db, board, column, request.position)
    if "ai_instructions" in fields_set:
        column.ai_instructions = request.ai_instructions
    if request.workflow_ids is not None:
        # Check that all workflows are accessible to the user (owned or shared)
        for workflow_id in set(request.workflow_ids):
            workflow = await get_accessible_workflow(db, workflow_id, current_user.id)
            if workflow is None:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="One or more workflows were not found",
                )
        existing = (
            (
                await db.execute(
                    select(BoardColumnWorkflow).where(BoardColumnWorkflow.column_id == column.id)
                )
            )
            .scalars()
            .all()
        )
        for link in existing:
            await db.delete(link)
        await db.flush()
        for index, workflow_id in enumerate(request.workflow_ids):
            db.add(
                BoardColumnWorkflow(column_id=column.id, workflow_id=workflow_id, position=index)
            )
    await db.commit()
    await db.refresh(column)
    audit(
        action="board.column_update",
        actor=current_user,
        target_type="board",
        target_id=board.id,
        target_name=board.name,
        column_id=column.id,
        column_name=column.name,
        fields=",".join(sorted(fields_set)) or None,
    )
    workflows_by_column = await _column_workflow_responses(db, [column.id])
    return BoardColumnResponse(
        id=column.id,
        board_id=column.board_id,
        name=column.name,
        position=column.position,
        color=column.color,
        ai_instructions=column.ai_instructions,
        workflows=workflows_by_column.get(column.id, []),
    )


@router.delete("/{board_id}/columns/{column_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_column(
    board_id: uuid.UUID,
    column_id: uuid.UUID,
    move_cards_to_column_id: uuid.UUID | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    """Delete a column. Its cards block the delete unless ``move_cards_to_column_id`` names
    another column of the board: they then move to its top, without running its chain."""
    board, _ = await _get_board_for_user(db, board_id, current_user, write=True)
    column = await _get_board_column(db, board, column_id)
    cards = list(
        (
            await db.execute(
                select(BoardCard)
                .where(BoardCard.column_id == column.id)
                .order_by(BoardCard.position, BoardCard.updated_at)
            )
        )
        .scalars()
        .all()
    )
    if cards:
        if move_cards_to_column_id is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Move or delete the cards in this column first",
            )
        if move_cards_to_column_id == column.id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Choose another column for the cards",
            )
        target = await _get_board_column(db, board, move_cards_to_column_id)
        if any(card.run_status in ACTIVE_RUN_STATUSES for card in cards):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="A card in this column is running or waiting for a review",
            )
        others = list(
            (
                await db.execute(
                    select(BoardCard)
                    .where(BoardCard.column_id == target.id)
                    .order_by(BoardCard.position, BoardCard.updated_at)
                )
            )
            .scalars()
            .all()
        )
        for card in cards:
            card.column_id = target.id
            db.add(
                BoardCardActivity(
                    card_id=card.id,
                    kind="event",
                    author_type="system",
                    content=(
                        f"Moved from {column.name} to {target.name} when {column.name} was deleted"
                    ),
                    data={"from_column_id": str(column.id), "to_column_id": str(target.id)},
                )
            )
        for position, card in enumerate([*cards, *others]):
            card.position = position
        # The cards must point at the target before the column row goes, or the foreign
        # key's ON DELETE CASCADE removes them with it.
        await db.flush()
    await db.delete(column)
    # Keep positions a dense 0..n-1 sequence — the planning gate is positional.
    remaining = list(
        (
            await db.execute(
                select(BoardColumn)
                .where(BoardColumn.board_id == board.id)
                .order_by(BoardColumn.position)
            )
        )
        .scalars()
        .all()
    )
    for position, item in enumerate(remaining):
        item.position = position
    audit(
        action="board.column_delete",
        actor=current_user,
        target_type="board",
        target_id=board.id,
        target_name=board.name,
        column_id=column_id,
        column_name=column.name,
        moved_cards=len(cards),
    )
    await db.commit()


@router.delete("/{board_id}/columns/{column_id}/cards", status_code=status.HTTP_204_NO_CONTENT)
async def empty_column(
    board_id: uuid.UUID,
    column_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    """Delete every card in a board column."""
    board, _ = await _get_board_for_user(db, board_id, current_user, write=True)
    column = await _get_board_column(db, board, column_id)
    audit(
        action="board.column_empty",
        actor=current_user,
        target_type="board",
        target_id=board.id,
        target_name=board.name,
        column_id=column.id,
        column_name=column.name,
    )
    await db.execute(delete(BoardCard).where(BoardCard.column_id == column.id))
    await db.commit()


@router.post(
    "/{board_id}/cards", response_model=BoardCardResponse, status_code=status.HTTP_201_CREATED
)
async def create_card(
    board_id: uuid.UUID,
    request: CardCreateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> BoardCardResponse:
    board, _ = await _get_board_for_user(db, board_id, current_user, write=True)
    if request.column_id is not None:
        column = await _get_board_column(db, board, request.column_id)
    else:
        result = await db.execute(
            select(BoardColumn)
            .where(BoardColumn.board_id == board.id)
            .order_by(BoardColumn.position)
            .limit(1)
        )
        column = result.scalar_one_or_none()
        if column is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="Board has no columns"
            )
    card = BoardCard(
        id=uuid.uuid4(),
        board_id=board.id,
        column_id=column.id,
        title=request.title,
        content=request.content,
        position=0,
    )
    updates = await _field_updates(db, board, current_user, request, None)
    if updates:
        card.card_metadata = merge_metadata({}, updates=updates)
    db.add(card)
    await db.flush()
    await _place_card(db, card, column.id, request.position)
    db.add(
        BoardCardActivity(
            card_id=card.id,
            kind="event",
            author_type="system",
            content=f"Card created in {column.name}",
            data={"column_id": str(column.id)},
        )
    )
    await db.commit()
    await db.refresh(card)
    audit(
        action="board.card_create",
        actor=current_user,
        target_type="board",
        target_id=board.id,
        target_name=board.name,
        card_id=card.id,
        card_title=card.title,
        column_id=column.id,
    )
    return await _card_out(db, current_user, card)


@router.get("/{board_id}/cards/{card_id}", response_model=CardDetailResponse)
async def get_card_detail(
    board_id: uuid.UUID,
    card_id: uuid.UUID,
    limit: int = 100,
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> CardDetailResponse:
    board, _ = await _get_board_for_user(db, board_id, current_user, write=False)
    card = await _get_board_card(db, board, card_id)
    activities_result = await db.execute(
        select(BoardCardActivity)
        .where(BoardCardActivity.card_id == card.id)
        .order_by(BoardCardActivity.created_at)
        .offset(offset)
        .limit(limit)
    )
    runs_result = await db.execute(
        select(BoardCardRun)
        .where(BoardCardRun.card_id == card.id)
        .order_by(BoardCardRun.started_at.desc())
        .limit(50)
    )
    runs = runs_result.scalars().all()
    active_executions = await _active_board_execution_ids(db, [card.id])
    active_execution_ids = active_executions.get(card.id, set())
    return CardDetailResponse(
        card=await _card_out(db, current_user, card, actively_running=bool(active_execution_ids)),
        activities=[
            CardActivityResponse(
                id=a.id,
                kind=a.kind,
                author_type=a.author_type,
                author_user_id=a.author_user_id,
                content=a.content,
                data=a.data or {},
                run_id=a.run_id,
                created_at=a.created_at,
            )
            for a in activities_result.scalars().all()
        ],
        runs=[
            CardRunResponse(
                id=r.id,
                card_id=r.card_id,
                column_id=r.column_id,
                workflow_id=r.workflow_id,
                workflow_name=r.workflow_name,
                chain_position=r.chain_position,
                chain_length=r.chain_length,
                status=("running" if r.active_execution_id in active_execution_ids else r.status),
                execution_history_id=r.execution_history_id,
                active_execution_id=r.active_execution_id,
                output=r.output or {},
                error=r.error,
                started_at=r.started_at,
                finished_at=r.finished_at,
            )
            for r in runs
        ],
    )


@router.patch("/{board_id}/cards/{card_id}", response_model=BoardCardResponse)
async def update_card(
    board_id: uuid.UUID,
    card_id: uuid.UUID,
    request: CardUpdateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> BoardCardResponse:
    board, _ = await _get_board_for_user(db, board_id, current_user, write=True)
    card = await _get_board_card(db, board, card_id)
    expected = request.expected_edit_version
    if expected is not None and expected != edit_version(
        card.title, card.content, card.card_metadata
    ):
        current = await _card_out(db, current_user, card)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"message": CARD_CHANGED_MESSAGE, "card": current.model_dump(mode="json")},
        )
    updates = await _field_updates(db, board, current_user, request, card)
    if request.title is not None:
        card.title = request.title
    if request.content is not None:
        card.content = request.content
    if request.card_metadata is not None or updates:
        card.card_metadata = merge_metadata(
            card.card_metadata, raw=request.card_metadata, updates=updates
        )
    if request.position is not None:
        await _place_card(db, card, card.column_id, request.position)
    await db.commit()
    await db.refresh(card)
    audit(
        action="board.card_update",
        actor=current_user,
        target_type="board",
        target_id=board.id,
        target_name=board.name,
        card_id=card.id,
        card_title=card.title,
        fields=",".join(sorted(request.model_fields_set)) or None,
    )
    return await _card_out(db, current_user, card)


@router.delete("/{board_id}/cards/{card_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_card(
    board_id: uuid.UUID,
    card_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    board, _ = await _get_board_for_user(db, board_id, current_user, write=True)
    card = await _get_board_card(db, board, card_id)
    audit(
        action="board.card_delete",
        actor=current_user,
        target_type="board",
        target_id=board.id,
        target_name=board.name,
        card_id=card.id,
        card_title=card.title,
    )
    await db.delete(card)
    await db.commit()


@router.post(
    "/{board_id}/cards/{card_id}/comments",
    response_model=CardActivityResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_card_comment(
    board_id: uuid.UUID,
    card_id: uuid.UUID,
    request: CommentCreateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> CardActivityResponse:
    board, _ = await _get_board_for_user(db, board_id, current_user, write=True)
    card = await _get_board_card(db, board, card_id)
    activity = BoardCardActivity(
        card_id=card.id,
        kind="comment",
        author_type="user",
        author_user_id=current_user.id,
        content=request.content,
    )
    db.add(activity)
    await db.commit()
    await db.refresh(activity)

    # Answering a card that is waiting at the planning gate re-runs its column chain with
    # the answer, which releases the gate and lets the card flow on.
    column = await _get_board_column(db, board, card.column_id)
    await board_run_service.answer_card_comment(db, card=card, column=column, board=board)

    return CardActivityResponse(
        id=activity.id,
        kind=activity.kind,
        author_type=activity.author_type,
        author_user_id=activity.author_user_id,
        content=activity.content,
        data=activity.data or {},
        run_id=activity.run_id,
        created_at=activity.created_at,
    )


@router.delete(
    "/{board_id}/cards/{card_id}/activities/{activity_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_card_activity(
    board_id: uuid.UUID,
    card_id: uuid.UUID,
    activity_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    """Remove one entry from a card's timeline (it also leaves the next run's context)."""
    board, _ = await _get_board_for_user(db, board_id, current_user, write=True)
    card = await _get_board_card(db, board, card_id)
    activity = (
        await db.execute(
            select(BoardCardActivity).where(
                BoardCardActivity.id == activity_id, BoardCardActivity.card_id == card.id
            )
        )
    ).scalar_one_or_none()
    if activity is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Activity not found")
    await db.delete(activity)
    await db.commit()


@router.post("/{board_id}/cards/{card_id}/move", response_model=BoardCardResponse)
async def move_card(
    board_id: uuid.UUID,
    card_id: uuid.UUID,
    request: CardMoveRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> BoardCardResponse:
    board, _ = await _get_board_for_user(db, board_id, current_user, write=True)
    card = await _get_board_card(db, board, card_id)
    target = await _get_board_column(db, board, request.to_column_id)
    column_changed = card.column_id != target.id
    source = await _get_board_column(db, board, card.column_id) if column_changed else target

    old_column_id = card.column_id
    current_index = card.position
    card.column_id = target.id
    index = request.position
    if index is None and not column_changed:
        index = current_index
    await _place_card(db, card, target.id, index)
    if column_changed:
        await _reindex_cards(db, old_column_id)
        db.add(
            BoardCardActivity(
                card_id=card.id,
                kind="event",
                author_type="system",
                content=f"Moved from {source.name} to {target.name}",
                data={
                    "from_column_id": str(old_column_id),
                    "to_column_id": str(target.id),
                },
            )
        )
    await db.commit()

    if column_changed:
        if card.run_status == "pending":
            # A card parked on a human answer has no active run row to block on, but
            # the review itself is still open. Moving it must close that review first,
            # or the old column's chain would resume into a card no longer sitting
            # there once someone eventually answers it.
            pending_run = (
                (
                    await db.execute(
                        select(BoardCardRun).where(
                            BoardCardRun.card_id == card.id, BoardCardRun.status == "pending"
                        )
                    )
                )
                .scalars()
                .first()
            )
            if (
                pending_run is not None
                and pending_run.workflow_id is not None
                and pending_run.execution_history_id is not None
            ):
                await cancel_pending_review_execution(
                    db,
                    workflow_id=pending_run.workflow_id,
                    execution_id=pending_run.execution_history_id,
                )

        # Only a forward move (into a later column) may cascade; moving a card back
        # (e.g. to Backlog) runs the column's chain but must not auto-advance.
        forward = target.position > source.position
        result = await board_run_service.enqueue_card_chain(
            db,
            card=card,
            column=target,
            board=board,
            move={"from_column": source.name, "to_column": target.name},
            rerun=False,
            allow_advance=forward,
        )
        if result == board_run_service.ENQUEUE_BLOCKED:
            # The move already committed and cannot be undone here; surface the skip
            # on the card's timeline instead of failing a request that already succeeded.
            db.add(
                BoardCardActivity(
                    card_id=card.id,
                    kind="event",
                    author_type="system",
                    content=f"{target.name}'s chain did not start: a run was still active",
                    data={"column_id": str(target.id)},
                )
            )
            await db.commit()
    audit(
        action="board.card_move",
        actor=current_user,
        target_type="board",
        target_id=board.id,
        target_name=board.name,
        card_id=card.id,
        card_title=card.title,
        from_column=source.name,
        to_column=target.name,
    )
    await db.refresh(card)
    return await _card_out(db, current_user, card)


@router.post("/{board_id}/cards/{card_id}/run", response_model=BoardCardResponse)
async def run_card_chain(
    board_id: uuid.UUID,
    card_id: uuid.UUID,
    skip_auto_advance: bool = False,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> BoardCardResponse:
    board, _ = await _get_board_for_user(db, board_id, current_user, write=True)
    card = await _get_board_card(db, board, card_id)
    column = await _get_board_column(db, board, card.column_id)
    # Enforce the positional planning gate server-side: the leftmost column and the
    # one to its right never auto-advance on Run — a comment releases them.
    ordered = list(
        (
            await db.execute(
                select(BoardColumn.id)
                .where(BoardColumn.board_id == board.id)
                .order_by(BoardColumn.position)
            )
        )
        .scalars()
        .all()
    )
    column_index = ordered.index(column.id) if column.id in ordered else -1
    allow_advance = column_index >= board_run_service.GATE_COLUMN_INDEX and not skip_auto_advance
    result = await board_run_service.enqueue_card_chain(
        db,
        card=card,
        column=column,
        board=board,
        move=None,
        rerun=True,
        allow_advance=allow_advance,
    )
    if result != board_run_service.ENQUEUE_STARTED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A run is already active or the column has no workflows",
        )
    audit(
        action="board.card_run",
        actor=current_user,
        target_type="board",
        target_id=board.id,
        target_name=board.name,
        card_id=card.id,
        card_title=card.title,
        column_name=column.name,
        auto_advance=allow_advance,
    )
    await db.refresh(card)
    return await _card_out(db, current_user, card)


# ─── Card attachments ────────────────────────────────────────────────────────────────


def _card_attachments(card: BoardCard) -> list[dict]:
    metadata = card.card_metadata or {}
    attachments = metadata.get("attachments")
    return list(attachments) if isinstance(attachments, list) else []


def _set_card_attachments(card: BoardCard, attachments: list[dict]) -> None:
    # The JSON column is only persisted when it is reassigned, not mutated in place.
    card.card_metadata = {**(card.card_metadata or {}), "attachments": attachments}


@router.post(
    "/{board_id}/cards/{card_id}/attachments",
    response_model=CardAttachmentResponse,
    status_code=status.HTTP_201_CREATED,
)
async def add_card_attachment(
    board_id: uuid.UUID,
    card_id: uuid.UUID,
    request: Request,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> CardAttachmentResponse:
    """Attach a file to a card. Workflows read it from `$input.card.metadata.attachments`."""
    board, _ = await _get_board_for_user(db, board_id, current_user, write=True)
    card = await _get_board_card(db, board, card_id)
    file_bytes = await read_upload_file_limited(file)
    try:
        stored = await store_file(
            db,
            owner_id=board.owner_id,
            file_bytes=file_bytes,
            filename=file.filename or "attachment",
            mime_type=file.content_type,
            source_node_label="board attachment",
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    token = await create_access_token(db, file_id=stored.id, created_by_id=current_user.id)
    attachment = {
        "file_id": str(stored.id),
        "name": stored.filename,
        "url": build_download_url(build_public_base_url(request), token.token),
        "mime_type": stored.mime_type,
        "size": stored.size_bytes,
    }
    _set_card_attachments(card, [*_card_attachments(card), attachment])
    db.add(
        BoardCardActivity(
            card_id=card.id,
            kind="event",
            author_type="user",
            content=f"Attached {stored.filename}",
            data={"attachment": attachment},
        )
    )
    await db.commit()
    return CardAttachmentResponse(**attachment)


@router.delete(
    "/{board_id}/cards/{card_id}/attachments/{file_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_card_attachment(
    board_id: uuid.UUID,
    card_id: uuid.UUID,
    file_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    board, _ = await _get_board_for_user(db, board_id, current_user, write=True)
    card = await _get_board_card(db, board, card_id)
    attachments = _card_attachments(card)
    remaining = [a for a in attachments if str(a.get("file_id")) != str(file_id)]
    if len(remaining) == len(attachments):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Attachment not found")
    _set_card_attachments(card, remaining)
    stored = await db.get(GeneratedFile, file_id)
    if stored is not None and stored.owner_id == board.owner_id:
        await delete_file(db, stored)
    await db.commit()


# ─── Sharing ────────────────────────────────────────────────────────────────────────


def _validate_permission(permission: str) -> str:
    if permission not in ("read", "write"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Permission must be read or write"
        )
    return permission


@router.get("/{board_id}/shares", response_model=list[BoardShareResponse])
async def list_board_shares(
    board_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[BoardShareResponse]:
    board = await _get_owned_board(db, board_id, current_user)
    result = await db.execute(
        select(BoardShare, User)
        .join(User, BoardShare.user_id == User.id)
        .where(BoardShare.board_id == board.id)
    )
    return [
        BoardShareResponse(
            id=share.id,
            user_id=user.id,
            email=user.email,
            name=user.name,
            permission=share.permission,
            shared_at=share.created_at,
        )
        for share, user in result.all()
    ]


@router.post("/{board_id}/shares", response_model=BoardShareResponse)
async def create_board_share(
    board_id: uuid.UUID,
    request: BoardShareRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> BoardShareResponse:
    board = await _get_owned_board(db, board_id, current_user)
    permission = _validate_permission(request.permission)
    target = (
        await db.execute(select(User).where(User.email == request.email))
    ).scalar_one_or_none()
    if target is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    if target.id == current_user.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot share with yourself"
        )
    share = (
        await db.execute(
            select(BoardShare).where(
                BoardShare.board_id == board.id, BoardShare.user_id == target.id
            )
        )
    ).scalar_one_or_none()
    if share is None:
        share = BoardShare(board_id=board.id, user_id=target.id, permission=permission)
        db.add(share)
    else:
        share.permission = permission
    await db.commit()
    await db.refresh(share)
    audit(
        action="board.share_add",
        actor=current_user,
        target_type="board",
        target_id=board.id,
        target_name=board.name,
        grantee_id=target.id,
        grantee_email=target.email,
        permission=permission,
    )
    return BoardShareResponse(
        id=share.id,
        user_id=target.id,
        email=target.email,
        name=target.name,
        permission=share.permission,
        shared_at=share.created_at,
    )


@router.delete("/{board_id}/shares/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_board_share(
    board_id: uuid.UUID,
    user_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    board = await _get_owned_board(db, board_id, current_user)
    share = (
        await db.execute(
            select(BoardShare).where(BoardShare.board_id == board.id, BoardShare.user_id == user_id)
        )
    ).scalar_one_or_none()
    if share is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Share not found")
    audit(
        action="board.share_remove",
        actor=current_user,
        target_type="board",
        target_id=board.id,
        target_name=board.name,
        grantee_id=user_id,
    )
    await db.delete(share)
    await db.commit()


@router.get("/{board_id}/team-shares", response_model=list[BoardTeamShareResponse])
async def list_board_team_shares(
    board_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[BoardTeamShareResponse]:
    board = await _get_owned_board(db, board_id, current_user)
    result = await db.execute(
        select(BoardTeamShare, Team)
        .join(Team, BoardTeamShare.team_id == Team.id)
        .where(BoardTeamShare.board_id == board.id)
    )
    return [
        BoardTeamShareResponse(
            id=share.id,
            team_id=team.id,
            team_name=team.name,
            permission=share.permission,
            shared_at=share.created_at,
        )
        for share, team in result.all()
    ]


@router.post("/{board_id}/team-shares", response_model=BoardTeamShareResponse)
async def create_board_team_share(
    board_id: uuid.UUID,
    request: BoardTeamShareRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> BoardTeamShareResponse:
    board = await _get_owned_board(db, board_id, current_user)
    permission = _validate_permission(request.permission)
    team = (
        await db.execute(
            select(Team)
            .join(TeamMember, TeamMember.team_id == Team.id)
            .where(Team.id == request.team_id, TeamMember.user_id == current_user.id)
        )
    ).scalar_one_or_none()
    if team is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Team not found")
    share = (
        await db.execute(
            select(BoardTeamShare).where(
                BoardTeamShare.board_id == board.id, BoardTeamShare.team_id == team.id
            )
        )
    ).scalar_one_or_none()
    if share is None:
        share = BoardTeamShare(board_id=board.id, team_id=team.id, permission=permission)
        db.add(share)
    else:
        share.permission = permission
    await db.commit()
    await db.refresh(share)
    audit(
        action="board.team_share_add",
        actor=current_user,
        target_type="board",
        target_id=board.id,
        target_name=board.name,
        team_id=team.id,
        team_name=team.name,
        permission=permission,
    )
    return BoardTeamShareResponse(
        id=share.id,
        team_id=team.id,
        team_name=team.name,
        permission=share.permission,
        shared_at=share.created_at,
    )


@router.delete("/{board_id}/team-shares/{team_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_board_team_share(
    board_id: uuid.UUID,
    team_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    board = await _get_owned_board(db, board_id, current_user)
    share = (
        await db.execute(
            select(BoardTeamShare).where(
                BoardTeamShare.board_id == board.id, BoardTeamShare.team_id == team_id
            )
        )
    ).scalar_one_or_none()
    if share is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Share not found")
    audit(
        action="board.team_share_remove",
        actor=current_user,
        target_type="board",
        target_id=board.id,
        target_name=board.name,
        team_id=team_id,
    )
    await db.delete(share)
    await db.commit()
