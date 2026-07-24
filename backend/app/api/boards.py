"""Agentic kanban board API: boards, columns, cards, moves, runs, comments, sharing."""

import uuid
from datetime import datetime, timedelta, timezone

from fastapi import (
    APIRouter,
    Depends,
    File,
    HTTPException,
    Request,
    UploadFile,
    status,
)
from sqlalchemy import delete, func, or_, select
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
    CardMoveRequest,
    CardRunResponse,
    CardUpdateRequest,
    ColumnCreateRequest,
    ColumnUpdateRequest,
    CommentCreateRequest,
)
from app.services import board_run_service
from app.services.credential_access import get_accessible_credential
from app.services.execution_cancellation import ACTIVE_EXECUTION_STALE_AFTER_SECONDS
from app.services.file_storage import (
    build_download_url,
    create_access_token,
    delete_file,
    store_file,
)
from app.services.hitl_service import build_public_base_url
from app.services.upload_limits import read_upload_file_limited
from app.services.workflow_access import get_accessible_workflow

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
    if board.owner_id == user.id:
        return "owner"
    permissions = list(
        (
            await db.execute(
                select(BoardShare.permission).where(
                    BoardShare.board_id == board.id, BoardShare.user_id == user.id
                )
            )
        )
        .scalars()
        .all()
    )
    permissions += list(
        (
            await db.execute(
                select(BoardTeamShare.permission)
                .join(TeamMember, TeamMember.team_id == BoardTeamShare.team_id)
                .where(BoardTeamShare.board_id == board.id, TeamMember.user_id == user.id)
            )
        )
        .scalars()
        .all()
    )
    if not permissions:
        return None
    # The most permissive share wins.
    return "write" if "write" in permissions else "read"


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


def _card_response(card: BoardCard, *, actively_running: bool = False) -> BoardCardResponse:
    return BoardCardResponse(
        id=card.id,
        board_id=card.board_id,
        column_id=card.column_id,
        title=card.title,
        content=card.content,
        position=card.position,
        run_status="running" if actively_running else card.run_status,
        card_metadata=card.card_metadata or {},
        created_at=card.created_at,
        updated_at=card.updated_at,
    )


async def _active_board_execution_ids(
    db: AsyncSession, card_ids: list[uuid.UUID]
) -> dict[uuid.UUID, set[uuid.UUID]]:
    """Return fresh workflow executions linked to each board card run."""
    if not card_ids:
        return {}
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=ACTIVE_EXECUTION_STALE_AFTER_SECONDS)
    result = await db.execute(
        select(BoardCardRun.card_id, BoardCardRun.active_execution_id)
        .join(
            ActiveWorkflowExecution,
            ActiveWorkflowExecution.execution_id == BoardCardRun.active_execution_id,
        )
        .where(
            BoardCardRun.card_id.in_(card_ids),
            ActiveWorkflowExecution.heartbeat_at >= cutoff,
            ActiveWorkflowExecution.cancel_requested_at.is_(None),
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
        updated_at=board.updated_at,
    )


@router.get("", response_model=list[BoardSummaryResponse])
async def list_boards(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[BoardSummaryResponse]:
    shared_board_ids = set(
        (await db.execute(select(BoardShare.board_id).where(BoardShare.user_id == current_user.id)))
        .scalars()
        .all()
    ) | set(
        (
            await db.execute(
                select(BoardTeamShare.board_id)
                .join(TeamMember, TeamMember.team_id == BoardTeamShare.team_id)
                .where(TeamMember.user_id == current_user.id)
            )
        )
        .scalars()
        .all()
    )
    result = await db.execute(
        select(Board)
        .where(
            or_(Board.owner_id == current_user.id, Board.id.in_(shared_board_ids))
            if shared_board_ids
            else Board.owner_id == current_user.id
        )
        .order_by(Board.created_at)
    )
    boards = result.scalars().all()
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
        permission = await _board_permission(db, board, current_user) or "read"
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
            _card_response(card, actively_running=card.id in active_executions) for card in cards
        ],
        has_active_runs=bool(active_executions)
        or any(card.run_status in ACTIVE_RUN_STATUSES for card in cards),
    )


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
    if "mapper_model" in fields_set:
        board.mapper_model = request.mapper_model
    if "mapper_credential_id" in fields_set:
        if request.mapper_credential_id is not None:
            await _validate_accessible_credential(db, request.mapper_credential_id, current_user)
        board.mapper_credential_id = request.mapper_credential_id
    await db.commit()
    await db.refresh(board)
    cred_name = await _mapper_credential_name(db, board)
    return _board_summary(board, column_count=0, card_count=0, cred_name=cred_name)


@router.delete("/{board_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_board(
    board_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    board = await _get_owned_board(db, board_id, current_user)
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
    position = request.position if request.position is not None else count
    column = BoardColumn(
        board_id=board.id, name=request.name, position=position, color=request.color
    )
    db.add(column)
    await db.commit()
    await db.refresh(column)
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
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    board, _ = await _get_board_for_user(db, board_id, current_user, write=True)
    column = await _get_board_column(db, board, column_id)
    card_count = (
        await db.execute(select(func.count(BoardCard.id)).where(BoardCard.column_id == column.id))
    ).scalar() or 0
    if card_count:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Move or delete the cards in this column first",
        )
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
    if request.position is not None:
        position = request.position
    else:
        count = (
            await db.execute(
                select(func.count(BoardCard.id)).where(BoardCard.column_id == column.id)
            )
        ).scalar() or 0
        position = count
    card = BoardCard(
        board_id=board.id,
        column_id=column.id,
        title=request.title,
        content=request.content,
        position=position,
    )
    db.add(card)
    await db.flush()
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
    return _card_response(card)


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
        card=_card_response(card, actively_running=bool(active_execution_ids)),
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
    if request.title is not None:
        card.title = request.title
    if request.content is not None:
        card.content = request.content
    if request.card_metadata is not None:
        card.card_metadata = request.card_metadata
    if request.position is not None:
        card.position = request.position
        await _reindex_cards(db, card.column_id)
    await db.commit()
    await db.refresh(card)
    return _card_response(card)


@router.delete("/{board_id}/cards/{card_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_card(
    board_id: uuid.UUID,
    card_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    board, _ = await _get_board_for_user(db, board_id, current_user, write=True)
    card = await _get_board_card(db, board, card_id)
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
    card.column_id = target.id
    if request.position is not None:
        card.position = request.position
    await _reindex_cards(db, target.id)
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
        # Only a forward move (into a later column) may cascade; moving a card back
        # (e.g. to Backlog) runs the column's chain but must not auto-advance.
        forward = target.position > source.position
        await board_run_service.enqueue_card_chain(
            db,
            card=card,
            column=target,
            board=board,
            move={"from_column": source.name, "to_column": target.name},
            rerun=False,
            allow_advance=forward,
        )
    await db.refresh(card)
    return _card_response(card)


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
    enqueued = await board_run_service.enqueue_card_chain(
        db,
        card=card,
        column=column,
        board=board,
        move=None,
        rerun=True,
        allow_advance=allow_advance,
    )
    if not enqueued:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A run is already active or the column has no workflows",
        )
    await db.refresh(card)
    return _card_response(card)


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
    await db.delete(share)
    await db.commit()
