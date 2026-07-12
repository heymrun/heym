"""Agentic kanban board API: boards, columns, cards, moves, runs, comments."""

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.models import (
    Board,
    BoardCard,
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
)

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
