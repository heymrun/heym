import csv
import io
import uuid

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from fastapi.responses import StreamingResponse
from sqlalchemy import delete as sa_delete
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.models import (
    DataTable,
    DataTableRow,
    DataTableShare,
    DataTableTeamShare,
    Team,
    TeamMember,
    User,
)
from app.db.session import get_db
from app.models.schemas import (
    DataTableCreate,
    DataTableImportResponse,
    DataTableListResponse,
    DataTableResponse,
    DataTableRowCreate,
    DataTableRowResponse,
    DataTableRowUpdate,
    DataTableShareRequest,
    DataTableShareResponse,
    DataTableTeamShareRequest,
    DataTableTeamShareResponse,
    DataTableUpdate,
)

router = APIRouter()


# ── Helpers ──────────────────────────────────────────────────────────────────


async def _get_data_table_with_access(
    table_id: uuid.UUID,
    user_id: uuid.UUID,
    db: AsyncSession,
    require_write: bool = False,
) -> DataTable:
    """Return the DataTable if user has access, raising 404 otherwise."""
    # 1. Owner always has full access
    result = await db.execute(
        select(DataTable).where(DataTable.id == table_id, DataTable.owner_id == user_id)
    )
    table = result.scalar_one_or_none()
    if table is not None:
        return table

    # 2. User-level share
    share_q = (
        select(DataTable, DataTableShare.permission)
        .join(DataTableShare, DataTableShare.table_id == DataTable.id)
        .where(DataTable.id == table_id, DataTableShare.user_id == user_id)
    )
    share_result = await db.execute(share_q)
    row = share_result.one_or_none()
    if row is not None:
        table, permission = row
        if require_write and permission != "write":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="Write access required"
            )
        return table

    # 3. Team-level share
    team_q = (
        select(DataTable, DataTableTeamShare.permission)
        .join(DataTableTeamShare, DataTableTeamShare.table_id == DataTable.id)
        .join(TeamMember, TeamMember.team_id == DataTableTeamShare.team_id)
        .where(DataTable.id == table_id, TeamMember.user_id == user_id)
    )
    team_result = await db.execute(team_q)
    row = team_result.first()
    if row is not None:
        table, permission = row
        if require_write and permission != "write":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="Write access required"
            )
        return table

    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Data table not found")


async def _row_count(table_id: uuid.UUID, db: AsyncSession) -> int:
    result = await db.execute(
        select(func.count()).select_from(DataTableRow).where(DataTableRow.table_id == table_id)
    )
    return result.scalar() or 0


def _coerce_row_data(data: dict, columns: list[dict]) -> tuple[dict, list[str]]:
    """Coerce row values to their declared column types, returning (coerced_data, errors)."""
    import json as _json

    col_map = {col["name"]: col for col in columns}
    result = dict(data)
    errors: list[str] = []
    for key, value in list(result.items()):
        col = col_map.get(key)
        if not col or value is None or value == "":
            continue
        col_type = col.get("type", "string")
        try:
            if col_type == "number":
                if isinstance(value, str):
                    result[key] = float(value) if "." in value else int(value)
                elif isinstance(value, bool):
                    result[key] = int(value)
            elif col_type == "boolean":
                if isinstance(value, str):
                    result[key] = value.lower() in ("true", "1", "yes")
                elif isinstance(value, (int, float)):
                    result[key] = bool(value)
            elif col_type == "json":
                if isinstance(value, str):
                    result[key] = _json.loads(value)
            elif col_type == "string":
                if not isinstance(value, str):
                    result[key] = str(value)
        except (ValueError, TypeError, _json.JSONDecodeError) as e:
            errors.append(f"Invalid {col_type} value for '{key}': {e}")
    return result, errors


def _validate_row_data(data: dict, columns: list[dict]) -> list[str]:
    """Validate row data against column schema, returning list of error messages."""
    errors: list[str] = []
    col_map = {col["name"]: col for col in columns}
    for col in columns:
        name = col["name"]
        required = col.get("required", False)
        if required and name not in data and col.get("defaultValue") is None:
            errors.append(f"Missing required field: {name}")
    for key in data:
        if key not in col_map:
            errors.append(f"Unknown column: {key}")
    return errors


def _apply_defaults(data: dict, columns: list[dict]) -> dict:
    """Fill in default values for missing columns."""
    result = dict(data)
    for col in columns:
        name = col["name"]
        if name not in result and col.get("defaultValue") is not None:
            result[name] = col["defaultValue"]
    return result


async def _check_unique_constraints(
    table_id: uuid.UUID,
    data: dict,
    columns: list[dict],
    db: AsyncSession,
    exclude_row_id: uuid.UUID | None = None,
) -> list[str]:
    """Check unique constraints for columns marked as unique. Uses a single query."""
    from sqlalchemy import text

    unique_checks = []
    for col in columns:
        if not col.get("unique"):
            continue
        name = col["name"]
        if name not in data:
            continue
        value = data[name]
        if value is None or value == "":
            continue
        unique_checks.append((name, str(value)))

    if not unique_checks:
        return []

    # Build a single query that checks all unique columns at once using OR
    conditions = []
    params: dict = {"table_id": str(table_id)}
    for i, (col_name, col_value) in enumerate(unique_checks):
        conditions.append(f"data ->> :cn{i} = :cv{i}")
        params[f"cn{i}"] = col_name
        params[f"cv{i}"] = col_value

    sql = f"SELECT data FROM data_table_rows WHERE table_id = :table_id AND ({' OR '.join(conditions)})"
    if exclude_row_id is not None:
        sql += " AND id != :exclude_id"
        params["exclude_id"] = str(exclude_row_id)

    result = await db.execute(text(sql), params)
    existing_rows = result.fetchall()

    errors: list[str] = []
    for col_name, col_value in unique_checks:
        for row in existing_rows:
            row_data = row[0] if isinstance(row[0], dict) else {}
            if str(row_data.get(col_name, "")) == col_value:
                errors.append(f"Duplicate value for unique column '{col_name}': {col_value}")
                break
    return errors


# ── DataTable CRUD ───────────────────────────────────────────────────────────


@router.get("", response_model=list[DataTableListResponse])
async def list_data_tables(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[DataTableListResponse]:
    # Owned tables
    owned_result = await db.execute(
        select(DataTable)
        .where(DataTable.owner_id == current_user.id)
        .order_by(DataTable.created_at.desc())
    )
    owned = owned_result.scalars().all()

    # User-shared tables
    shared_result = await db.execute(
        select(DataTable, User.email, DataTableShare.permission)
        .join(DataTableShare, DataTableShare.table_id == DataTable.id)
        .join(User, User.id == DataTable.owner_id)
        .where(DataTableShare.user_id == current_user.id)
        .order_by(DataTable.created_at.desc())
    )
    shared = shared_result.all()

    # Team-shared tables
    team_result = await db.execute(
        select(DataTable, Team.name, DataTableTeamShare.permission)
        .join(DataTableTeamShare, DataTableTeamShare.table_id == DataTable.id)
        .join(TeamMember, TeamMember.team_id == DataTableTeamShare.team_id)
        .join(Team, Team.id == DataTableTeamShare.team_id)
        .where(TeamMember.user_id == current_user.id)
        .order_by(DataTable.created_at.desc())
    )
    team_shared = team_result.all()

    seen_ids: set[uuid.UUID] = set()
    responses: list[DataTableListResponse] = []

    for table in owned:
        count = await _row_count(table.id, db)
        responses.append(
            DataTableListResponse(
                id=table.id,
                name=table.name,
                description=table.description,
                column_count=len(table.columns or []),
                row_count=count,
                owner_id=table.owner_id,
                is_shared=False,
                created_at=table.created_at,
                updated_at=table.updated_at,
            )
        )
        seen_ids.add(table.id)

    for table, owner_email, permission in shared:
        if table.id in seen_ids:
            continue
        seen_ids.add(table.id)
        count = await _row_count(table.id, db)
        responses.append(
            DataTableListResponse(
                id=table.id,
                name=table.name,
                description=table.description,
                column_count=len(table.columns or []),
                row_count=count,
                owner_id=table.owner_id,
                is_shared=True,
                shared_by=owner_email,
                permission=permission,
                created_at=table.created_at,
                updated_at=table.updated_at,
            )
        )

    for table, team_name, permission in team_shared:
        if table.id in seen_ids:
            continue
        seen_ids.add(table.id)
        count = await _row_count(table.id, db)
        responses.append(
            DataTableListResponse(
                id=table.id,
                name=table.name,
                description=table.description,
                column_count=len(table.columns or []),
                row_count=count,
                owner_id=table.owner_id,
                is_shared=True,
                shared_by_team=team_name,
                permission=permission,
                created_at=table.created_at,
                updated_at=table.updated_at,
            )
        )

    return responses


@router.post("", response_model=DataTableResponse, status_code=status.HTTP_201_CREATED)
async def create_data_table(
    data: DataTableCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DataTableResponse:
    existing = await db.execute(
        select(DataTable).where(DataTable.owner_id == current_user.id, DataTable.name == data.name)
    )
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Data table with this name already exists",
        )

    columns_json = [col.model_dump(mode="json") for col in data.columns]
    for i, col in enumerate(columns_json):
        col["id"] = str(col.get("id", uuid.uuid4()))
        col["order"] = col.get("order", i)

    table = DataTable(
        name=data.name,
        description=data.description,
        columns=columns_json,
        owner_id=current_user.id,
    )
    db.add(table)
    await db.flush()
    await db.refresh(table)

    return DataTableResponse(
        id=table.id,
        name=table.name,
        description=table.description,
        columns=table.columns,
        owner_id=table.owner_id,
        row_count=0,
        created_at=table.created_at,
        updated_at=table.updated_at,
    )


@router.get("/{table_id}", response_model=DataTableResponse)
async def get_data_table(
    table_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DataTableResponse:
    table = await _get_data_table_with_access(table_id, current_user.id, db)
    count = await _row_count(table.id, db)

    return DataTableResponse(
        id=table.id,
        name=table.name,
        description=table.description,
        columns=table.columns,
        owner_id=table.owner_id,
        row_count=count,
        created_at=table.created_at,
        updated_at=table.updated_at,
    )


@router.put("/{table_id}", response_model=DataTableResponse)
async def update_data_table(
    table_id: uuid.UUID,
    data: DataTableUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DataTableResponse:
    result = await db.execute(
        select(DataTable).where(DataTable.id == table_id, DataTable.owner_id == current_user.id)
    )
    table = result.scalar_one_or_none()
    if table is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Data table not found")

    if data.name is not None:
        existing = await db.execute(
            select(DataTable).where(
                DataTable.owner_id == current_user.id,
                DataTable.name == data.name,
                DataTable.id != table_id,
            )
        )
        if existing.scalar_one_or_none():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Data table with this name already exists",
            )
        table.name = data.name

    if data.description is not None:
        table.description = data.description

    if data.columns is not None:
        columns_json = [col.model_dump(mode="json") for col in data.columns]
        for i, col in enumerate(columns_json):
            col["id"] = str(col.get("id", uuid.uuid4()))
            col["order"] = col.get("order", i)
        table.columns = columns_json

    await db.flush()
    await db.refresh(table)
    count = await _row_count(table.id, db)

    return DataTableResponse(
        id=table.id,
        name=table.name,
        description=table.description,
        columns=table.columns,
        owner_id=table.owner_id,
        row_count=count,
        created_at=table.created_at,
        updated_at=table.updated_at,
    )


@router.delete("/{table_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_data_table(
    table_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    result = await db.execute(
        select(DataTable).where(DataTable.id == table_id, DataTable.owner_id == current_user.id)
    )
    table = result.scalar_one_or_none()
    if table is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Data table not found")
    await db.delete(table)


# ── Row CRUD ─────────────────────────────────────────────────────────────────


@router.get("/{table_id}/rows", response_model=list[DataTableRowResponse])
async def list_rows(
    table_id: uuid.UUID,
    limit: int = 50,
    offset: int = 0,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[DataTableRowResponse]:
    table = await _get_data_table_with_access(table_id, current_user.id, db)
    columns = table.columns or []
    result = await db.execute(
        select(DataTableRow)
        .where(DataTableRow.table_id == table_id)
        .order_by(DataTableRow.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    rows = result.scalars().all()
    return [
        DataTableRowResponse(
            id=r.id,
            table_id=r.table_id,
            data=_coerce_row_data(r.data, columns)[0] if columns else r.data,
            created_by=r.created_by,
            updated_by=r.updated_by,
            created_at=r.created_at,
            updated_at=r.updated_at,
        )
        for r in rows
    ]


@router.post(
    "/{table_id}/rows", response_model=DataTableRowResponse, status_code=status.HTTP_201_CREATED
)
async def create_row(
    table_id: uuid.UUID,
    row_data: DataTableRowCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DataTableRowResponse:
    table = await _get_data_table_with_access(table_id, current_user.id, db, require_write=True)
    data = _apply_defaults(row_data.data, table.columns or [])
    data, coerce_errors = _coerce_row_data(data, table.columns or [])
    errors = coerce_errors + _validate_row_data(data, table.columns or [])
    if errors:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="; ".join(errors))

    unique_errors = await _check_unique_constraints(table_id, data, table.columns or [], db)
    if unique_errors:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="; ".join(unique_errors))

    row = DataTableRow(
        table_id=table_id, data=data, created_by=current_user.id, updated_by=current_user.id
    )
    db.add(row)
    await db.flush()
    await db.refresh(row)

    return DataTableRowResponse(
        id=row.id,
        table_id=row.table_id,
        data=row.data,
        created_by=row.created_by,
        updated_by=row.updated_by,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


@router.put("/{table_id}/rows/{row_id}", response_model=DataTableRowResponse)
async def update_row(
    table_id: uuid.UUID,
    row_id: uuid.UUID,
    row_data: DataTableRowUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DataTableRowResponse:
    table = await _get_data_table_with_access(table_id, current_user.id, db, require_write=True)
    result = await db.execute(
        select(DataTableRow).where(DataTableRow.id == row_id, DataTableRow.table_id == table_id)
    )
    row = result.scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Row not found")

    merged = {**row.data, **row_data.data}
    merged, coerce_errors = _coerce_row_data(merged, table.columns or [])
    errors = coerce_errors + _validate_row_data(merged, table.columns or [])
    if errors:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="; ".join(errors))

    unique_errors = await _check_unique_constraints(
        table_id, row_data.data, table.columns or [], db, exclude_row_id=row_id
    )
    if unique_errors:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="; ".join(unique_errors))

    row.data = merged
    row.updated_by = current_user.id
    await db.flush()
    await db.refresh(row)

    return DataTableRowResponse(
        id=row.id,
        table_id=row.table_id,
        data=row.data,
        created_by=row.created_by,
        updated_by=row.updated_by,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


@router.delete("/{table_id}/rows/{row_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_row(
    table_id: uuid.UUID,
    row_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    await _get_data_table_with_access(table_id, current_user.id, db, require_write=True)
    result = await db.execute(
        select(DataTableRow).where(DataTableRow.id == row_id, DataTableRow.table_id == table_id)
    )
    row = result.scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Row not found")
    await db.delete(row)


@router.delete("/{table_id}/rows", status_code=status.HTTP_204_NO_CONTENT)
async def clear_rows(
    table_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Delete all rows from a data table."""
    await _get_data_table_with_access(table_id, current_user.id, db, require_write=True)
    await db.execute(sa_delete(DataTableRow).where(DataTableRow.table_id == table_id))


@router.post("/{table_id}/rows/bulk", response_model=DataTableImportResponse)
async def bulk_create_rows(
    table_id: uuid.UUID,
    rows: list[DataTableRowCreate],
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DataTableImportResponse:
    table = await _get_data_table_with_access(table_id, current_user.id, db, require_write=True)
    columns = table.columns or []
    imported = 0
    errors: list[dict] = []

    for i, row_data in enumerate(rows):
        data = _apply_defaults(row_data.data, columns)
        data, coerce_errors = _coerce_row_data(data, columns)
        row_errors = coerce_errors + _validate_row_data(data, columns)
        if row_errors:
            errors.append({"row": i + 1, "errors": row_errors})
            continue
        unique_errors = await _check_unique_constraints(table_id, data, columns, db)
        if unique_errors:
            errors.append({"row": i + 1, "errors": unique_errors})
            continue
        row = DataTableRow(
            table_id=table_id, data=data, created_by=current_user.id, updated_by=current_user.id
        )
        db.add(row)
        await db.flush()
        imported += 1

    return DataTableImportResponse(imported=imported, errors=errors, total=len(rows))


# ── CSV Import / Export ──────────────────────────────────────────────────────


@router.post("/{table_id}/import-csv", response_model=DataTableImportResponse)
async def import_csv(
    table_id: uuid.UUID,
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DataTableImportResponse:
    table = await _get_data_table_with_access(table_id, current_user.id, db, require_write=True)
    columns = table.columns or []
    col_names = {col["name"] for col in columns}

    content = await file.read()
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = content.decode("latin-1")

    reader = csv.DictReader(io.StringIO(text))
    imported = 0
    errors: list[dict] = []
    total = 0

    for i, csv_row in enumerate(reader):
        total += 1
        data: dict = {}
        for key, value in csv_row.items():
            if key and key in col_names:
                data[key] = value
        data = _apply_defaults(data, columns)
        data, coerce_errors = _coerce_row_data(data, columns)
        row_errors = coerce_errors + _validate_row_data(data, columns)
        if row_errors:
            errors.append({"row": i + 1, "errors": row_errors})
            continue
        unique_errors = await _check_unique_constraints(table_id, data, columns, db)
        if unique_errors:
            errors.append({"row": i + 1, "errors": unique_errors})
            continue
        row = DataTableRow(
            table_id=table_id, data=data, created_by=current_user.id, updated_by=current_user.id
        )
        db.add(row)
        await db.flush()
        imported += 1

    return DataTableImportResponse(imported=imported, errors=errors, total=total)


@router.get("/{table_id}/export-csv")
async def export_csv(
    table_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    table = await _get_data_table_with_access(table_id, current_user.id, db)
    columns = table.columns or []
    col_names = [col["name"] for col in sorted(columns, key=lambda c: c.get("order", 0))]

    result = await db.execute(
        select(DataTableRow)
        .where(DataTableRow.table_id == table_id)
        .order_by(DataTableRow.created_at.asc())
    )
    rows = result.scalars().all()

    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=col_names, extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        writer.writerow(row.data or {})

    output.seek(0)
    filename = f"{table.name}.csv".replace(" ", "_")
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ── Sharing ──────────────────────────────────────────────────────────────────


@router.get("/{table_id}/shares", response_model=list[DataTableShareResponse])
async def list_shares(
    table_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[DataTableShareResponse]:
    result = await db.execute(
        select(DataTable).where(DataTable.id == table_id, DataTable.owner_id == current_user.id)
    )
    if result.scalar_one_or_none() is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Data table not found")

    shares_result = await db.execute(
        select(DataTableShare, User)
        .join(User, DataTableShare.user_id == User.id)
        .where(DataTableShare.table_id == table_id)
    )
    return [
        DataTableShareResponse(
            id=share.id,
            user_id=user.id,
            email=user.email,
            name=user.name,
            permission=share.permission,
            shared_at=share.created_at,
        )
        for share, user in shares_result.all()
    ]


@router.post("/{table_id}/shares", response_model=DataTableShareResponse)
async def create_share(
    table_id: uuid.UUID,
    share_data: DataTableShareRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DataTableShareResponse:
    result = await db.execute(
        select(DataTable).where(DataTable.id == table_id, DataTable.owner_id == current_user.id)
    )
    if result.scalar_one_or_none() is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Data table not found")

    user_result = await db.execute(select(User).where(User.email == share_data.email))
    target_user = user_result.scalar_one_or_none()
    if target_user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    if target_user.id == current_user.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot share with yourself"
        )

    existing_result = await db.execute(
        select(DataTableShare).where(
            DataTableShare.table_id == table_id, DataTableShare.user_id == target_user.id
        )
    )
    existing = existing_result.scalar_one_or_none()
    if existing:
        existing.permission = share_data.permission
        await db.flush()
        await db.refresh(existing)
        return DataTableShareResponse(
            id=existing.id,
            user_id=target_user.id,
            email=target_user.email,
            name=target_user.name,
            permission=existing.permission,
            shared_at=existing.created_at,
        )

    share = DataTableShare(
        table_id=table_id, user_id=target_user.id, permission=share_data.permission
    )
    db.add(share)
    await db.flush()
    await db.refresh(share)

    return DataTableShareResponse(
        id=share.id,
        user_id=target_user.id,
        email=target_user.email,
        name=target_user.name,
        permission=share.permission,
        shared_at=share.created_at,
    )


@router.delete("/{table_id}/shares/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_share(
    table_id: uuid.UUID,
    user_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    result = await db.execute(
        select(DataTable).where(DataTable.id == table_id, DataTable.owner_id == current_user.id)
    )
    if result.scalar_one_or_none() is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Data table not found")

    share_result = await db.execute(
        select(DataTableShare).where(
            DataTableShare.table_id == table_id, DataTableShare.user_id == user_id
        )
    )
    share = share_result.scalar_one_or_none()
    if share is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Share not found")
    await db.delete(share)
    await db.commit()


@router.get("/{table_id}/team-shares", response_model=list[DataTableTeamShareResponse])
async def list_team_shares(
    table_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[DataTableTeamShareResponse]:
    result = await db.execute(
        select(DataTable).where(DataTable.id == table_id, DataTable.owner_id == current_user.id)
    )
    if result.scalar_one_or_none() is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Data table not found")

    shares_result = await db.execute(
        select(DataTableTeamShare, Team)
        .join(Team, Team.id == DataTableTeamShare.team_id)
        .where(DataTableTeamShare.table_id == table_id)
        .order_by(Team.name.asc())
    )
    return [
        DataTableTeamShareResponse(
            id=share.id,
            team_id=team.id,
            team_name=team.name,
            permission=share.permission,
            shared_at=share.created_at,
        )
        for share, team in shares_result.all()
    ]


@router.post("/{table_id}/team-shares", response_model=DataTableTeamShareResponse)
async def create_team_share(
    table_id: uuid.UUID,
    payload: DataTableTeamShareRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DataTableTeamShareResponse:
    result = await db.execute(
        select(DataTable).where(DataTable.id == table_id, DataTable.owner_id == current_user.id)
    )
    if result.scalar_one_or_none() is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Data table not found")

    team_result = await db.execute(
        select(Team)
        .join(TeamMember, TeamMember.team_id == Team.id)
        .where(Team.id == payload.team_id, TeamMember.user_id == current_user.id)
    )
    team = team_result.scalar_one_or_none()
    if not team:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Team not found or you are not a member"
        )

    existing = await db.execute(
        select(DataTableTeamShare).where(
            DataTableTeamShare.table_id == table_id, DataTableTeamShare.team_id == payload.team_id
        )
    )
    share = existing.scalar_one_or_none()
    if share:
        share.permission = payload.permission
        await db.flush()
        await db.refresh(share)
        return DataTableTeamShareResponse(
            id=share.id,
            team_id=team.id,
            team_name=team.name,
            permission=share.permission,
            shared_at=share.created_at,
        )

    share = DataTableTeamShare(
        table_id=table_id, team_id=payload.team_id, permission=payload.permission
    )
    db.add(share)
    await db.flush()
    await db.refresh(share)
    await db.commit()
    return DataTableTeamShareResponse(
        id=share.id,
        team_id=team.id,
        team_name=team.name,
        permission=share.permission,
        shared_at=share.created_at,
    )


@router.delete("/{table_id}/team-shares/{team_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_team_share(
    table_id: uuid.UUID,
    team_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    result = await db.execute(
        select(DataTable).where(DataTable.id == table_id, DataTable.owner_id == current_user.id)
    )
    if result.scalar_one_or_none() is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Data table not found")

    share_result = await db.execute(
        select(DataTableTeamShare).where(
            DataTableTeamShare.table_id == table_id, DataTableTeamShare.team_id == team_id
        )
    )
    share = share_result.scalar_one_or_none()
    if share is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Team share not found")
    await db.delete(share)
    await db.commit()
