"""Agentic kanban board API: boards, columns, cards, moves, runs, comments."""

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.models import (
    Board,
    BoardCard,
    BoardCardActivity,
    BoardCardRun,
    BoardColumn,
    BoardColumnWorkflow,
    User,
    Workflow,
)
from app.db.session import get_db
from app.models.board_schemas import (
    BoardCardResponse,
    BoardColumnResponse,
    BoardColumnWorkflowResponse,
    BoardCreateRequest,
    BoardStateResponse,
    BoardSummaryResponse,
    BoardUpdateRequest,
    CardActivityResponse,
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

router = APIRouter()

DEFAULT_COLUMNS = ["Backlog", "Planning", "To Do", "Waiting", "Development", "Done"]
ACTIVE_RUN_STATUSES = ("running", "pending")
MAX_BOARD_CARDS = 500


async def _get_owned_board(db: AsyncSession, board_id: uuid.UUID, user: User) -> Board:
    result = await db.execute(select(Board).where(Board.id == board_id, Board.owner_id == user.id))
    board = result.scalar_one_or_none()
    if board is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Board not found")
    return board


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


def _card_response(card: BoardCard) -> BoardCardResponse:
    return BoardCardResponse(
        id=card.id,
        board_id=card.board_id,
        column_id=card.column_id,
        title=card.title,
        content=card.content,
        position=card.position,
        run_status=card.run_status,
        card_metadata=card.card_metadata or {},
        created_at=card.created_at,
        updated_at=card.updated_at,
    )


@router.get("", response_model=list[BoardSummaryResponse])
async def list_boards(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[BoardSummaryResponse]:
    result = await db.execute(
        select(Board).where(Board.owner_id == current_user.id).order_by(Board.created_at)
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
        summaries.append(
            BoardSummaryResponse(
                id=board.id,
                name=board.name,
                description=board.description,
                column_count=column_count,
                card_count=card_count,
                updated_at=board.updated_at,
            )
        )
    return summaries


@router.post("", response_model=BoardSummaryResponse, status_code=status.HTTP_201_CREATED)
async def create_board(
    request: BoardCreateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> BoardSummaryResponse:
    board = Board(owner_id=current_user.id, name=request.name, description=request.description)
    db.add(board)
    await db.flush()
    for index, column_name in enumerate(DEFAULT_COLUMNS):
        db.add(BoardColumn(board_id=board.id, name=column_name, position=index))
    await db.commit()
    await db.refresh(board)
    return BoardSummaryResponse(
        id=board.id,
        name=board.name,
        description=board.description,
        column_count=len(DEFAULT_COLUMNS),
        card_count=0,
        updated_at=board.updated_at,
    )


@router.get("/{board_id}", response_model=BoardStateResponse)
async def get_board_state(
    board_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> BoardStateResponse:
    board = await _get_owned_board(db, board_id, current_user)
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
    workflows_by_column = await _column_workflow_responses(db, [c.id for c in columns])
    return BoardStateResponse(
        id=board.id,
        name=board.name,
        description=board.description,
        columns=[
            BoardColumnResponse(
                id=column.id,
                board_id=column.board_id,
                name=column.name,
                position=column.position,
                color=column.color,
                workflows=workflows_by_column.get(column.id, []),
            )
            for column in columns
        ],
        cards=[_card_response(card) for card in cards],
        has_active_runs=any(card.run_status in ACTIVE_RUN_STATUSES for card in cards),
    )


@router.patch("/{board_id}", response_model=BoardSummaryResponse)
async def update_board(
    board_id: uuid.UUID,
    request: BoardUpdateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> BoardSummaryResponse:
    board = await _get_owned_board(db, board_id, current_user)
    if request.name is not None:
        board.name = request.name
    if request.description is not None:
        board.description = request.description
    await db.commit()
    await db.refresh(board)
    return BoardSummaryResponse(
        id=board.id,
        name=board.name,
        description=board.description,
        column_count=0,
        card_count=0,
        updated_at=board.updated_at,
    )


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
    board = await _get_owned_board(db, board_id, current_user)
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
    board = await _get_owned_board(db, board_id, current_user)
    column = await _get_board_column(db, board, column_id)
    if request.name is not None:
        column.name = request.name
    if request.color is not None:
        column.color = request.color
    if request.position is not None:
        column.position = request.position
    if request.workflow_ids is not None:
        owned = (
            (
                await db.execute(
                    select(Workflow).where(
                        Workflow.id.in_(request.workflow_ids),
                        Workflow.owner_id == current_user.id,
                    )
                )
            )
            .scalars()
            .all()
        )
        if len(owned) != len(set(request.workflow_ids)):
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
        workflows=workflows_by_column.get(column.id, []),
    )


@router.delete("/{board_id}/columns/{column_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_column(
    board_id: uuid.UUID,
    column_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    board = await _get_owned_board(db, board_id, current_user)
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
    board = await _get_owned_board(db, board_id, current_user)
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
    board = await _get_owned_board(db, board_id, current_user)
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
    return CardDetailResponse(
        card=_card_response(card),
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
                status=r.status,
                execution_history_id=r.execution_history_id,
                output=r.output or {},
                error=r.error,
                started_at=r.started_at,
                finished_at=r.finished_at,
            )
            for r in runs_result.scalars().all()
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
    board = await _get_owned_board(db, board_id, current_user)
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
    board = await _get_owned_board(db, board_id, current_user)
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
    board = await _get_owned_board(db, board_id, current_user)
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


@router.post("/{board_id}/cards/{card_id}/move", response_model=BoardCardResponse)
async def move_card(
    board_id: uuid.UUID,
    card_id: uuid.UUID,
    request: CardMoveRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> BoardCardResponse:
    board = await _get_owned_board(db, board_id, current_user)
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
        await board_run_service.enqueue_card_chain(
            db,
            card=card,
            column=target,
            board=board,
            move={"from_column": source.name, "to_column": target.name},
            rerun=False,
        )
    await db.refresh(card)
    return _card_response(card)


@router.post("/{board_id}/cards/{card_id}/run", response_model=BoardCardResponse)
async def run_card_chain(
    board_id: uuid.UUID,
    card_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> BoardCardResponse:
    board = await _get_owned_board(db, board_id, current_user)
    card = await _get_board_card(db, board, card_id)
    column = await _get_board_column(db, board, card.column_id)
    enqueued = await board_run_service.enqueue_card_chain(
        db, card=card, column=column, board=board, move=None, rerun=True
    )
    if not enqueued:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A run is already active or the column has no workflows",
        )
    await db.refresh(card)
    return _card_response(card)
