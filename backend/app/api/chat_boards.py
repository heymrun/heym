"""Kanban boards in chat: the board, column and card actions Chat, MCP and A2A share.

Every change goes through the board routes in ``app.api.boards``, so access, audit lines,
column chains and reviews behave exactly as in the Board tab. Reads reach the boards the
routes reach: owned ones and those shared directly or through a team. Moving a card never
approves a review; moving a card that waits for one cancels that review, and the result
says so. Results keep a card's run state under ``run_status``: a top-level ``status`` would
read as the tool call's own outcome.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable, Sequence
from datetime import date, datetime
from typing import Any, Literal
from zoneinfo import ZoneInfo

from fastapi import HTTPException, status
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api import boards as boards_api
from app.config import settings
from app.db.models import (
    Board,
    BoardCard,
    BoardCardActivity,
    BoardCardRun,
    BoardColumn,
    BoardColumnWorkflow,
    User,
)
from app.models.board_schemas import (
    BoardCreateRequest,
    BoardUpdateRequest,
    CardCreateRequest,
    CardMoveRequest,
    CardUpdateRequest,
    ColumnCreateRequest,
    ColumnUpdateRequest,
)
from app.services.board_access import (
    PERMISSION_OWNER,
    PERMISSION_READ,
    PERMISSION_WRITE,
    BoardMember,
    accessible_board_ids,
    board_members,
    board_permissions,
)
from app.services.board_card_fields import CardFilter, read_fields

Priority = Literal["low", "medium", "high", "urgent"]
RunStatus = Literal["idle", "running", "pending", "success", "failed"]
MAX_TASKS = 500
CONTENT_PREVIEW = 400
MAX_ACTIVITY = 30
REVIEW_CANCELLED_NOTE = (
    "The card was waiting for a review. Moving it cancelled that review; it was not approved."
)
OWNER_ONLY_ERROR = (
    "Only the board's owner can change its name, description or settings, or delete it"
)


class _Args(BaseModel):
    model_config = ConfigDict(extra="ignore")


class TaskFilterArgs(_Args):
    assignee: str | None = Field(
        default=None, description='"me", "unassigned", or a user_id from list_board_members.'
    )
    column_id: uuid.UUID | None = None
    column_name: str | None = Field(default=None, description="A column name, in any case.")
    priority: Priority | None = None
    due: Literal["overdue", "today", "week"] | None = Field(
        default=None, description="overdue: due before today; week: due within seven days."
    )
    label: str | None = Field(default=None, description="A label such as a client or project.")
    run_status: RunStatus | None = Field(
        default=None, description="pending means the task waits for a review."
    )
    limit: int = Field(default=100, ge=1, le=MAX_TASKS)


class ListBoardsArgs(_Args):
    pass


class BoardArgs(_Args):
    board_id: uuid.UUID


class GetBoardArgs(TaskFilterArgs):
    board_id: uuid.UUID


class GetTasksArgs(TaskFilterArgs):
    board_id: uuid.UUID | None = Field(default=None, description="Omit for every board.")


class CreateBoardArgs(_Args):
    name: str = Field(min_length=1, max_length=255)
    description: str | None = None
    auto_advance: bool = Field(
        default=True,
        description="False for a plain team task board: tasks stay where people put them.",
    )


class UpdateBoardArgs(BoardArgs):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    auto_advance: bool | None = None


class DeleteBoardArgs(BoardArgs):
    confirm_name: str = Field(description="The board's exact name, confirmed by the user.")


class CreateColumnArgs(BoardArgs):
    name: str = Field(min_length=1, max_length=255)
    color: str | None = Field(default=None, max_length=32)
    position: int | None = Field(default=None, ge=0, description="0 is the leftmost column.")


class ColumnArgs(BoardArgs):
    column_id: uuid.UUID


class UpdateColumnArgs(ColumnArgs):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    color: str | None = Field(default=None, max_length=32)
    position: int | None = Field(default=None, ge=0, description="0 is the leftmost column.")


class DeleteColumnArgs(ColumnArgs):
    move_cards_to_column_id: uuid.UUID | None = Field(
        default=None, description="Another column of the board that takes the column's tasks."
    )


class TaskFieldArgs(_Args):
    assignee_user_id: uuid.UUID | None = Field(
        default=None, description="A user_id from list_board_members; null unassigns."
    )
    priority: Priority | None = None
    due_date: date | None = Field(default=None, description="YYYY-MM-DD; null clears it.")
    labels: list[str] | None = Field(default=None, max_length=10)


class CreateTaskArgs(TaskFieldArgs):
    title: str = Field(min_length=1, max_length=500)
    description: str | None = None
    board_id: uuid.UUID | None = Field(default=None, description="Omit when no board is named.")
    column_id: uuid.UUID | None = Field(default=None, description="Omit for the first column.")
    position: int | None = Field(default=None, ge=0, description="0 is the top; omit for top.")


class CardArgs(_Args):
    card_id: uuid.UUID


class UpdateTaskArgs(TaskFieldArgs):
    card_id: uuid.UUID
    title: str | None = Field(default=None, min_length=1, max_length=500)
    description: str | None = None


class MoveTaskArgs(CardArgs):
    to_column_id: uuid.UUID
    position: int | None = Field(default=None, ge=0, description="0 is the top; omit for top.")


Handler = Callable[[AsyncSession, User, Any, str], Awaitable[dict[str, Any]]]


def board_url(public_base_url: str, board_id: object) -> str:
    """The board in Heym's Board tab."""
    return f"{public_base_url.rstrip('/')}/?tab=board&board={board_id}"


def _today() -> date:
    return datetime.now(ZoneInfo(settings.effective_timezone)).date()


def _member_names(members: Sequence[BoardMember]) -> dict[uuid.UUID, str]:
    return {member.user_id: member.name or member.email for member in members}


async def _accessible_boards(db: AsyncSession, user: User) -> list[Board]:
    rows = await db.execute(
        select(Board).where(Board.id.in_(accessible_board_ids(user.id))).order_by(Board.created_at)
    )
    return list(rows.scalars().all())


async def _columns(db: AsyncSession, board_ids: Sequence[uuid.UUID]) -> list[BoardColumn]:
    rows = await db.execute(
        select(BoardColumn)
        .where(BoardColumn.board_id.in_(list(board_ids)))
        .order_by(BoardColumn.board_id, BoardColumn.position)
    )
    return list(rows.scalars().all())


async def _reachable_card(
    db: AsyncSession, user: User, card_id: uuid.UUID, *, write: bool
) -> tuple[BoardCard, Board]:
    """The card and its board when ``user`` may reach them; a missing card reads as not found."""
    card = (await db.execute(select(BoardCard).where(BoardCard.id == card_id))).scalar_one_or_none()
    if card is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Card not found")
    board, _ = await boards_api._get_board_for_user(db, card.board_id, user, write=write)
    return card, board


def _task_entry(
    card: BoardCard, *, board: Board, column_name: str | None, names: dict[uuid.UUID, str]
) -> dict[str, Any]:
    values = read_fields(card.card_metadata)
    assignee = values.assignee_user_id
    content = card.content or ""
    preview = content[:CONTENT_PREVIEW] + ("..." if len(content) > CONTENT_PREVIEW else "")
    return {
        "id": str(card.id),
        "title": card.title,
        "description": preview,
        "board_id": str(board.id),
        "board": board.name,
        "column_id": str(card.column_id),
        "column": column_name,
        "position": card.position,
        "run_status": card.run_status,
        "assignee": {"id": str(assignee), "name": names.get(assignee)} if assignee else None,
        "priority": values.priority,
        "due_date": values.due_date.isoformat() if values.due_date else None,
        "labels": list(values.labels),
        "updated_at": card.updated_at.isoformat() if card.updated_at else None,
    }


async def _task_result(db: AsyncSession, card_id: uuid.UUID) -> dict[str, Any]:
    card = await db.get(BoardCard, card_id)
    await db.refresh(card)
    board = await db.get(Board, card.board_id)
    column = await db.get(BoardColumn, card.column_id)
    names = _member_names(await board_members(db, board))
    return _task_entry(card, board=board, column_name=column.name if column else None, names=names)


def _card_filter(args: TaskFilterArgs, columns: Sequence[BoardColumn]) -> CardFilter:
    column_ids: set[uuid.UUID] | None = None
    if args.column_id is not None:
        column_ids = {args.column_id}
    if args.column_name:
        wanted = args.column_name.strip().casefold()
        named = {c.id for c in columns if c.name.casefold() == wanted}
        column_ids = named if column_ids is None else column_ids & named
    return CardFilter(
        assignee=args.assignee,
        column_ids=frozenset(column_ids) if column_ids is not None else None,
        priority=args.priority,
        due=args.due,
        label=args.label,
        run_status=args.run_status,
    )


async def _tasks(
    db: AsyncSession, user: User, boards: Sequence[Board], args: TaskFilterArgs
) -> dict[str, Any]:
    if not boards:
        return {"count": 0, "tasks": [], "truncated": False}
    by_id = {board.id: board for board in boards}
    columns = await _columns(db, list(by_id))
    column_names = {c.id: c.name for c in columns}
    column_rank = {c.id: (str(c.board_id), c.position) for c in columns}
    card_filter = _card_filter(args, columns)
    cards = (
        (await db.execute(select(BoardCard).where(BoardCard.board_id.in_(list(by_id)))))
        .scalars()
        .all()
    )
    names: dict[uuid.UUID, str] = {}
    for board in boards:
        names.update(_member_names(await board_members(db, board)))
    today = _today()
    matching = [
        card
        for card in cards
        if card_filter.matches(
            read_fields(card.card_metadata),
            column_id=card.column_id,
            run_status=card.run_status,
            user_id=user.id,
            today=today,
        )
    ]
    matching.sort(key=lambda c: (*column_rank.get(c.column_id, ("", 0)), c.position))
    selected = matching[: args.limit]
    return {
        "count": len(selected),
        "tasks": [
            _task_entry(
                card,
                board=by_id[card.board_id],
                column_name=column_names.get(card.column_id),
                names=names,
            )
            for card in selected
        ],
        "truncated": len(matching) > len(selected),
    }


def _board_entry(board: Board, permission: str, base: str) -> dict[str, Any]:
    return {
        "id": str(board.id),
        "name": board.name,
        "description": board.description,
        "permission": permission,
        "auto_advance": board.auto_advance,
        "url": board_url(base, board.id),
    }


async def _list_boards(
    db: AsyncSession, user: User, args: ListBoardsArgs, base: str
) -> dict[str, Any]:
    boards = await _accessible_boards(db, user)
    if not boards:
        return {"count": 0, "boards": []}
    permissions = await board_permissions(db, boards, user.id)
    ids = [board.id for board in boards]
    column_counts = dict(
        (
            await db.execute(
                select(BoardColumn.board_id, func.count(BoardColumn.id))
                .where(BoardColumn.board_id.in_(ids))
                .group_by(BoardColumn.board_id)
            )
        ).all()
    )
    statuses: dict[uuid.UUID, dict[str, int]] = {}
    for board_id, run_status, count in (
        await db.execute(
            select(BoardCard.board_id, BoardCard.run_status, func.count(BoardCard.id))
            .where(BoardCard.board_id.in_(ids))
            .group_by(BoardCard.board_id, BoardCard.run_status)
        )
    ).all():
        statuses.setdefault(board_id, {})[run_status] = count
    out = []
    for board in boards:
        entry = _board_entry(board, permissions.get(board.id, PERMISSION_READ), base)
        entry["column_count"] = column_counts.get(board.id, 0)
        entry["card_count"] = sum(statuses.get(board.id, {}).values())
        entry["run_status_counts"] = statuses.get(board.id, {})
        out.append(entry)
    return {"count": len(out), "boards": out}


async def _get_board(db: AsyncSession, user: User, args: GetBoardArgs, base: str) -> dict[str, Any]:
    board, permission = await boards_api._get_board_for_user(db, args.board_id, user, write=False)
    columns = await _columns(db, [board.id])
    column_ids = [c.id for c in columns]
    chain_counts = (
        dict(
            (
                await db.execute(
                    select(BoardColumnWorkflow.column_id, func.count(BoardColumnWorkflow.id))
                    .where(BoardColumnWorkflow.column_id.in_(column_ids))
                    .group_by(BoardColumnWorkflow.column_id)
                )
            ).all()
        )
        if column_ids
        else {}
    )
    card_counts = dict(
        (
            await db.execute(
                select(BoardCard.column_id, func.count(BoardCard.id))
                .where(BoardCard.board_id == board.id)
                .group_by(BoardCard.column_id)
            )
        ).all()
    )
    return {
        "board": _board_entry(board, permission, base),
        "columns": [
            {
                "id": str(c.id),
                "name": c.name,
                "position": c.position,
                "color": c.color,
                "workflow_count": chain_counts.get(c.id, 0),
                "card_count": card_counts.get(c.id, 0),
            }
            for c in columns
        ],
        **(await _tasks(db, user, [board], args)),
    }


async def _get_board_tasks(
    db: AsyncSession, user: User, args: GetTasksArgs, base: str
) -> dict[str, Any]:
    if args.board_id is not None:
        board, _ = await boards_api._get_board_for_user(db, args.board_id, user, write=False)
        boards = [board]
    else:
        boards = await _accessible_boards(db, user)
    return await _tasks(db, user, boards, args)


async def _get_card_detail(
    db: AsyncSession, user: User, args: CardArgs, base: str
) -> dict[str, Any]:
    card, board = await _reachable_card(db, user, args.card_id, write=False)
    column = await db.get(BoardColumn, card.column_id)
    names = _member_names(await board_members(db, board))
    activities = (
        (
            await db.execute(
                select(BoardCardActivity)
                .where(BoardCardActivity.card_id == card.id)
                .order_by(BoardCardActivity.created_at)
            )
        )
        .scalars()
        .all()
    )
    runs = (
        (
            await db.execute(
                select(BoardCardRun)
                .where(BoardCardRun.card_id == card.id)
                .order_by(BoardCardRun.started_at.desc())
                .limit(20)
            )
        )
        .scalars()
        .all()
    )
    entry = _task_entry(card, board=board, column_name=column.name if column else None, names=names)
    entry["description"] = card.content
    entry["url"] = board_url(base, board.id)
    entry["comments"] = [
        {
            "author": names.get(a.author_user_id) if a.author_user_id else a.author_type,
            "content": a.content,
            "created_at": a.created_at.isoformat() if a.created_at else None,
        }
        for a in activities
        if a.kind == "comment"
    ]
    entry["activity"] = [
        {
            "kind": a.kind,
            "content": a.content,
            "created_at": a.created_at.isoformat() if a.created_at else None,
        }
        for a in activities
        if a.kind != "comment"
    ][-MAX_ACTIVITY:]
    entry["runs"] = [
        {
            "workflow": r.workflow_name,
            "run_status": r.status,
            "execution_id": str(r.execution_history_id) if r.execution_history_id else None,
            "output": r.output or {},
            "error": r.error,
            "started_at": r.started_at.isoformat() if r.started_at else None,
            "finished_at": r.finished_at.isoformat() if r.finished_at else None,
        }
        for r in runs
    ]
    return entry


async def _list_members(db: AsyncSession, user: User, args: BoardArgs, base: str) -> dict[str, Any]:
    board, _ = await boards_api._get_board_for_user(db, args.board_id, user, write=False)
    members = await board_members(db, board)
    return {
        "count": len(members),
        "members": [
            {
                "user_id": str(m.user_id),
                "name": m.name,
                "email": m.email,
                "permission": m.permission,
            }
            for m in members
        ],
    }


async def _owned_board(db: AsyncSession, user: User, board_id: uuid.UUID) -> Board:
    board, permission = await boards_api._get_board_for_user(db, board_id, user, write=False)
    if permission != PERMISSION_OWNER:
        raise HTTPException(status.HTTP_403_FORBIDDEN, OWNER_ONLY_ERROR)
    return board


async def _create_board(
    db: AsyncSession, user: User, args: CreateBoardArgs, base: str
) -> dict[str, Any]:
    summary = await boards_api.create_board(
        request=BoardCreateRequest(
            name=args.name.strip(), description=args.description, auto_advance=args.auto_advance
        ),
        db=db,
        current_user=user,
    )
    board = await db.get(Board, summary.id)
    return {"created": True, "board": _board_entry(board, PERMISSION_OWNER, base)}


async def _update_board(
    db: AsyncSession, user: User, args: UpdateBoardArgs, base: str
) -> dict[str, Any]:
    await _owned_board(db, user, args.board_id)
    fields = args.model_fields_set & {"name", "description", "auto_advance"}
    if not fields:
        return {"error": "Nothing to change: pass name, description or auto_advance"}
    await boards_api.update_board(
        board_id=args.board_id,
        request=BoardUpdateRequest(**args.model_dump(include=fields)),
        db=db,
        current_user=user,
    )
    board = await db.get(Board, args.board_id)
    await db.refresh(board)
    return {"updated": True, "board": _board_entry(board, PERMISSION_OWNER, base)}


async def _delete_board(
    db: AsyncSession, user: User, args: DeleteBoardArgs, base: str
) -> dict[str, Any]:
    board = await _owned_board(db, user, args.board_id)
    if args.confirm_name.strip() != board.name:
        return {
            "error": (
                "confirm_name must be the board's exact name. Ask the user to confirm deleting "
                f"the board {board.name!r} with all its tasks."
            )
        }
    name = board.name
    await boards_api.delete_board(board_id=board.id, db=db, current_user=user)
    return {"deleted": True, "board": {"id": str(args.board_id), "name": name}}


def _column_entry(column: Any) -> dict[str, Any]:
    return {
        "id": str(column.id),
        "name": column.name,
        "position": column.position,
        "color": column.color,
    }


async def _create_column(
    db: AsyncSession, user: User, args: CreateColumnArgs, base: str
) -> dict[str, Any]:
    column = await boards_api.create_column(
        board_id=args.board_id,
        request=ColumnCreateRequest(
            name=args.name.strip(), position=args.position, color=args.color
        ),
        db=db,
        current_user=user,
    )
    return {"created": True, "column": _column_entry(column)}


async def _update_column(
    db: AsyncSession, user: User, args: UpdateColumnArgs, base: str
) -> dict[str, Any]:
    fields = args.model_fields_set & {"name", "color", "position"}
    if not fields:
        return {"error": "Nothing to change: pass name, color or position"}
    column = await boards_api.update_column(
        board_id=args.board_id,
        column_id=args.column_id,
        request=ColumnUpdateRequest(**args.model_dump(include=fields)),
        db=db,
        current_user=user,
    )
    return {"updated": True, "column": _column_entry(column)}


async def _delete_column(
    db: AsyncSession, user: User, args: DeleteColumnArgs, base: str
) -> dict[str, Any]:
    column = await db.get(BoardColumn, args.column_id)
    name = column.name if column is not None and column.board_id == args.board_id else None
    await boards_api.delete_column(
        board_id=args.board_id,
        column_id=args.column_id,
        move_cards_to_column_id=args.move_cards_to_column_id,
        db=db,
        current_user=user,
    )
    return {"deleted": True, "column": {"id": str(args.column_id), "name": name}}


def _field_payload(args: TaskFieldArgs) -> dict[str, Any]:
    keys = args.model_fields_set & {"assignee_user_id", "priority", "due_date", "labels"}
    return {key: getattr(args, key) for key in keys}


async def _create_task(
    db: AsyncSession, user: User, args: CreateTaskArgs, base: str
) -> dict[str, Any]:
    board_id = args.board_id
    if board_id is None:
        boards = await _accessible_boards(db, user)
        permissions = await board_permissions(db, boards, user.id)
        writable = [
            b for b in boards if permissions.get(b.id) in (PERMISSION_OWNER, PERMISSION_WRITE)
        ]
        if not writable:
            return {"error": "No boards you can add tasks to"}
        if len(writable) > 1:
            return {
                "requires_board_selection": True,
                "count": len(writable),
                "boards": [
                    {"id": str(b.id), "name": b.name, "description": b.description}
                    for b in writable
                ],
            }
        board_id = writable[0].id
    card = await boards_api.create_card(
        board_id=board_id,
        request=CardCreateRequest(
            title=args.title.strip(),
            content=(args.description or "").strip(),
            column_id=args.column_id,
            position=args.position,
            **_field_payload(args),
        ),
        db=db,
        current_user=user,
    )
    task = await _task_result(db, card.id)
    return {
        "created": True,
        "task": task,
        "board": {"id": str(board_id), "name": task["board"]},
        "url": board_url(base, board_id),
    }


async def _update_task(
    db: AsyncSession, user: User, args: UpdateTaskArgs, base: str
) -> dict[str, Any]:
    card, board = await _reachable_card(db, user, args.card_id, write=True)
    payload = _field_payload(args)
    if args.title is not None:
        payload["title"] = args.title.strip()
    if "description" in args.model_fields_set:
        payload["content"] = (args.description or "").strip()
    if not payload:
        return {"error": "Nothing to change"}
    await boards_api.update_card(
        board_id=board.id,
        card_id=card.id,
        request=CardUpdateRequest(**payload),
        db=db,
        current_user=user,
    )
    return {"updated": True, "task": await _task_result(db, card.id)}


async def _move_task(db: AsyncSession, user: User, args: MoveTaskArgs, base: str) -> dict[str, Any]:
    card, board = await _reachable_card(db, user, args.card_id, write=True)
    from_column_id = card.column_id
    changes_column = from_column_id != args.to_column_id
    if changes_column and card.run_status == "running":
        return {
            "error": (
                "This card is still running; wait for it to finish before moving it to "
                "another column."
            )
        }
    was_pending = card.run_status == "pending"
    moved = await boards_api.move_card(
        board_id=board.id,
        card_id=card.id,
        request=CardMoveRequest(to_column_id=args.to_column_id, position=args.position),
        db=db,
        current_user=user,
    )
    names = {c.id: c.name for c in await _columns(db, [board.id])}
    result: dict[str, Any] = {
        "moved": True,
        "task": await _task_result(db, card.id),
        "from_column": names.get(from_column_id),
        "to_column": names.get(args.to_column_id),
    }
    if changes_column and was_pending:
        result["review_cancelled"] = True
        result["note"] = REVIEW_CANCELLED_NOTE
    if moved.run_status == "running":
        result["chain_started"] = True
    if moved.column_id != args.to_column_id:
        result["auto_advanced_to"] = names.get(moved.column_id)
    return result


async def _delete_task(db: AsyncSession, user: User, args: CardArgs, base: str) -> dict[str, Any]:
    card, board = await _reachable_card(db, user, args.card_id, write=True)
    title = card.title
    await boards_api.delete_card(board_id=board.id, card_id=card.id, db=db, current_user=user)
    return {"deleted": True, "task": {"id": str(args.card_id), "title": title}}


_TOOLS: dict[str, tuple[type[_Args], str, str, Handler]] = {
    "list_boards": (
        ListBoardsArgs,
        "List the kanban boards the user owns or that are shared with them, with permission "
        "(owner, write, read), auto_advance, column and task counts and run status counts.",
        "Listing boards...",
        _list_boards,
    ),
    "get_board": (
        GetBoardArgs,
        "Read one board: its columns (id, name, position, workflow_count, card_count) and its "
        "tasks, with optional filters. Use it to resolve a column or task by name before "
        "changing anything.",
        "Reading board...",
        _get_board,
    ),
    "get_board_tasks": (
        GetTasksArgs,
        "List tasks across every board the user can open, or one board, with optional "
        "filters: assignee (me, unassigned or a user_id), column, priority, due (overdue, "
        "today, week), label and run_status (pending means waiting for a review).",
        "Listing board tasks...",
        _get_board_tasks,
    ),
    "get_card_detail": (
        CardArgs,
        "Read one task: its description, fields, comments, activity and workflow runs with "
        "their execution ids, outputs and errors.",
        "Reading card detail...",
        _get_card_detail,
    ),
    "list_board_members": (
        BoardArgs,
        "List everyone who can open a board, with user_id, name, email and permission. Use it "
        "to turn a person's name into assignee_user_id.",
        "Listing board members...",
        _list_members,
    ),
    "create_board": (
        CreateBoardArgs,
        "Create a board owned by the user, with the columns Backlog, Planning, Development and "
        "Done. Set auto_advance false for a plain team task board.",
        "Creating board...",
        _create_board,
    ),
    "update_board": (
        UpdateBoardArgs,
        "Change a board's name, description or auto_advance. Owner only.",
        "Updating board...",
        _update_board,
    ),
    "delete_board": (
        DeleteBoardArgs,
        "Delete a board with all its columns and tasks. Owner only. Call it only when the user "
        "asked to delete that board and confirmed its name; confirm_name must equal the name.",
        "Deleting board...",
        _delete_board,
    ),
    "create_board_column": (
        CreateColumnArgs,
        "Add a column to a board, at position (0 is the leftmost) or at the end.",
        "Adding column...",
        _create_column,
    ),
    "update_board_column": (
        UpdateColumnArgs,
        "Rename, recolor or reorder a column. Workflow chains are set in the Board tab.",
        "Updating column...",
        _update_column,
    ),
    "delete_board_column": (
        DeleteColumnArgs,
        "Delete a column. A column with tasks needs move_cards_to_column_id; its tasks move "
        "there without running workflows. Refused while one of its tasks is running or "
        "waiting for a review.",
        "Deleting column...",
        _delete_column,
    ),
    "create_board_task": (
        CreateTaskArgs,
        "Create a task with an optional description, column, position and fields "
        "(assignee_user_id, priority, due_date, labels). Without board_id it uses the "
        "only board the user can write to, or returns requires_board_selection.",
        "Adding task to board...",
        _create_task,
    ),
    "update_board_task": (
        UpdateTaskArgs,
        "Change a task's title, description or fields. Only the fields passed change; null "
        "clears one. Use it to assign and reassign.",
        "Updating task...",
        _update_task,
    ),
    "move_board_task": (
        MoveTaskArgs,
        "Move a task to a column, or reorder it inside its column (position 0 is the top). "
        "Moving into a column with workflows starts them. Moving a task that waits for a "
        "review cancels that review; it never approves it.",
        "Moving task...",
        _move_task,
    ),
    "delete_board_task": (
        CardArgs,
        "Delete a task, only when the user asked to delete it.",
        "Deleting task...",
        _delete_task,
    ),
}

BOARD_TOOL_NAMES = frozenset(_TOOLS)


def _strip_formats(node: Any) -> Any:
    if isinstance(node, dict):
        return {key: _strip_formats(value) for key, value in node.items() if key != "format"}
    if isinstance(node, list):
        return [_strip_formats(value) for value in node]
    return node


BOARD_TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            # Function tools take ids and dates as plain strings.
            "parameters": _strip_formats(model.model_json_schema()),
        },
    }
    for name, (model, description, _label, _handler) in _TOOLS.items()
]


def board_tool_label(name: str) -> str:
    """The progress label the chat shows while a board tool runs."""
    return _TOOLS[name][2]


def _detail(detail: object) -> str:
    if isinstance(detail, dict):
        return str(detail.get("message") or detail)
    return str(detail)


async def call_board_tool(
    db: AsyncSession,
    user: User,
    name: str,
    arguments: dict[str, Any] | None,
    public_base_url: str,
) -> dict[str, Any]:
    """Validate a board action and run it through the board routes."""
    model, _description, _label, handler = _TOOLS[name]
    try:
        args = model.model_validate(arguments or {})
    except ValidationError as exc:
        return {
            "error": "; ".join(
                f"{'.'.join(str(part) for part in error['loc'])}: {error['msg']}"
                for error in exc.errors()
            )
        }
    try:
        return await handler(db, user, args, public_base_url)
    except HTTPException as exc:
        return {"error": _detail(exc.detail)}


def summarize_board_tool(name: str, result: dict[str, Any]) -> str:
    """A short progress line, naming a task by its title only."""
    if result.get("error"):
        return f"Error: {str(result['error'])[:150]}"
    if result.get("requires_board_selection"):
        return f"Board selection required ({int(result.get('count') or 0)} available)"
    if name == "list_boards":
        return f"{int(result.get('count') or 0)} board(s) listed"
    if name in {"get_board", "get_board_tasks"}:
        return f"{int(result.get('count') or 0)} task(s) listed"
    if name == "list_board_members":
        return f"{int(result.get('count') or 0)} member(s)"
    if name == "get_card_detail":
        return f"Card {result.get('title')!r}: {result.get('run_status')}"
    task = result.get("task") or {}
    if name == "move_board_task":
        return f"Moved task {task.get('title')!r} to {result.get('to_column')}"
    if name == "create_board_task":
        board = (result.get("board") or {}).get("name")
        return f"Created task {task.get('title')!r} on board {board!r}"
    if name == "update_board_task":
        return f"Updated task {task.get('title')!r}"
    if name == "delete_board_task":
        return f"Deleted task {task.get('title')!r}"
    verb = "Created" if result.get("created") else "Deleted" if result.get("deleted") else "Updated"
    if "board" in result:
        return f"{verb} board {(result.get('board') or {}).get('name')!r}"
    if "column" in result:
        verb = "Added" if result.get("created") else verb
        return f"{verb} column {(result.get('column') or {}).get('name')!r}"
    return "Board updated"
