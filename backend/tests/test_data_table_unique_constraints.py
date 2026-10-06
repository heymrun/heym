import datetime
import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from fastapi import HTTPException

from app.api import data_tables as dt_api
from app.db.models import DataTable, DataTableRow, User
from app.models.schemas import DataTableRowCreate, DataTableRowUpdate


def _make_user() -> User:
    user = User(
        id=uuid.uuid4(),
        email="tester@example.com",
        name="Tester",
        hashed_password="hashed_pw",
    )
    return user


def _make_table(columns: list[dict], owner_id: uuid.UUID) -> DataTable:
    table = DataTable(
        name="Unique Test Table",
        description="Testing unique constraint validation",
        columns=columns,
        owner_id=owner_id,
    )
    table.id = uuid.uuid4()
    now = datetime.datetime.now(datetime.timezone.utc)
    table.created_at = now
    table.updated_at = now
    return table


def _wire_db(db: MagicMock) -> None:
    async def fake_flush() -> None:
        for call in db.add.call_args_list:
            obj = call.args[0]
            if getattr(obj, "id", None) is None:
                obj.id = uuid.uuid4()

    async def fake_refresh(obj: object) -> None:
        if getattr(obj, "id", None) is None:
            obj.id = uuid.uuid4()
        now = datetime.datetime.now(datetime.timezone.utc)
        obj.created_at = now
        obj.updated_at = now

    db.add = MagicMock()
    db.flush = AsyncMock(side_effect=fake_flush)
    db.refresh = AsyncMock(side_effect=fake_refresh)


class TestCheckUniqueConstraints(unittest.IsolatedAsyncioTestCase):
    async def test_boolean_duplicate_detected_when_existing_is_true(self) -> None:
        table_id = uuid.uuid4()
        columns = [{"name": "is_active", "type": "boolean", "unique": True}]
        data = {"is_active": True}

        db = MagicMock()
        captured_sql: list[str] = []
        captured_params: list[dict] = []

        async def fake_execute(stmt: object, params: dict | None = None) -> SimpleNamespace:
            captured_sql.append(str(stmt))
            captured_params.append(params or {})
            return SimpleNamespace(fetchall=lambda: [({"is_active": True},)])

        db.execute = AsyncMock(side_effect=fake_execute)

        errors = await dt_api._check_unique_constraints(table_id, data, columns, db)

        self.assertEqual(len(errors), 1)
        self.assertIn("Duplicate value for unique column 'is_active': true", errors[0])
        self.assertEqual(captured_params[0]["cv0"], "true")
        self.assertEqual(captured_params[0]["cn0"], "is_active")

    async def test_boolean_duplicate_detected_when_existing_is_false(self) -> None:
        table_id = uuid.uuid4()
        columns = [{"name": "is_active", "type": "boolean", "unique": True}]
        data = {"is_active": False}

        db = MagicMock()
        captured_params: list[dict] = []

        async def fake_execute(stmt: object, params: dict | None = None) -> SimpleNamespace:
            captured_params.append(params or {})
            return SimpleNamespace(fetchall=lambda: [({"is_active": False},)])

        db.execute = AsyncMock(side_effect=fake_execute)

        errors = await dt_api._check_unique_constraints(table_id, data, columns, db)

        self.assertEqual(len(errors), 1)
        self.assertIn("Duplicate value for unique column 'is_active': false", errors[0])
        self.assertEqual(captured_params[0]["cv0"], "false")

    async def test_boolean_no_duplicate_when_values_differ(self) -> None:
        table_id = uuid.uuid4()
        columns = [{"name": "is_active", "type": "boolean", "unique": True}]
        data = {"is_active": False}

        db = MagicMock()

        async def fake_execute(stmt: object, params: dict | None = None) -> SimpleNamespace:
            return SimpleNamespace(fetchall=lambda: [({"is_active": True},)])

        db.execute = AsyncMock(side_effect=fake_execute)

        errors = await dt_api._check_unique_constraints(table_id, data, columns, db)

        self.assertEqual(errors, [])

    async def test_boolean_normalizes_string_and_int_truthy_values(self) -> None:
        table_id = uuid.uuid4()
        columns = [{"name": "is_active", "type": "boolean", "unique": True}]

        for truthy_val in ("true", "1", "yes", True):
            db = MagicMock()
            captured_params: list[dict] = []

            async def fake_execute(stmt: object, params: dict | None = None) -> SimpleNamespace:
                captured_params.append(params or {})
                return SimpleNamespace(fetchall=lambda: [({"is_active": True},)])

            db.execute = AsyncMock(side_effect=fake_execute)

            errors = await dt_api._check_unique_constraints(
                table_id, {"is_active": truthy_val}, columns, db
            )
            self.assertEqual(len(errors), 1)
            self.assertEqual(captured_params[0]["cv0"], "true")


class TestUpdateRowUniqueConstraints(unittest.IsolatedAsyncioTestCase):
    async def test_update_row_coerced_number_triggers_unique_constraint(self) -> None:
        user = _make_user()
        columns = [
            {"name": "code", "type": "number", "unique": True},
            {"name": "name", "type": "string"},
        ]
        table = _make_table(columns, user.id)

        target_row = DataTableRow(
            id=uuid.uuid4(),
            table_id=table.id,
            data={"code": 200, "name": "Row 2"},
            created_by=user.id,
            updated_by=user.id,
        )

        db = MagicMock()
        _wire_db(db)

        async def fake_execute(stmt: object, params: dict | None = None) -> SimpleNamespace:
            sql = str(stmt)
            if "data_tables.owner_id" in sql or "data_tables.id" in sql:
                return SimpleNamespace(scalar_one_or_none=lambda: table)
            if "data_table_rows.id" in sql and "data_table_rows.table_id" in sql:
                return SimpleNamespace(scalar_one_or_none=lambda: target_row)
            if "SELECT data FROM data_table_rows" in sql:
                # Emulate finding row 1 with code 100 in database
                return SimpleNamespace(fetchall=lambda: [({"code": 100, "name": "Row 1"},)])
            raise AssertionError(f"Unexpected query: {sql}")

        db.execute = AsyncMock(side_effect=fake_execute)

        # Update row 2 with string "100" which coerces to int 100 and collides with row 1
        with self.assertRaises(HTTPException) as ctx:
            await dt_api.update_row(
                table_id=table.id,
                row_id=target_row.id,
                row_data=DataTableRowUpdate(data={"code": "100"}),
                current_user=user,
                db=db,
            )

        self.assertEqual(ctx.exception.status_code, 409)
        self.assertIn("Duplicate value for unique column 'code': 100", ctx.exception.detail)

    async def test_update_row_coerced_boolean_triggers_unique_constraint(self) -> None:
        user = _make_user()
        columns = [
            {"name": "is_primary", "type": "boolean", "unique": True},
            {"name": "title", "type": "string"},
        ]
        table = _make_table(columns, user.id)

        target_row = DataTableRow(
            id=uuid.uuid4(),
            table_id=table.id,
            data={"is_primary": False, "title": "Secondary"},
            created_by=user.id,
            updated_by=user.id,
        )

        db = MagicMock()
        _wire_db(db)

        async def fake_execute(stmt: object, params: dict | None = None) -> SimpleNamespace:
            sql = str(stmt)
            if "data_tables.owner_id" in sql or "data_tables.id" in sql:
                return SimpleNamespace(scalar_one_or_none=lambda: table)
            if "data_table_rows.id" in sql and "data_table_rows.table_id" in sql:
                return SimpleNamespace(scalar_one_or_none=lambda: target_row)
            if "SELECT data FROM data_table_rows" in sql:
                # Existing primary row with is_primary: True in database
                return SimpleNamespace(
                    fetchall=lambda: [({"is_primary": True, "title": "Primary"},)]
                )
            raise AssertionError(f"Unexpected query: {sql}")

        db.execute = AsyncMock(side_effect=fake_execute)

        with self.assertRaises(HTTPException) as ctx:
            await dt_api.update_row(
                table_id=table.id,
                row_id=target_row.id,
                row_data=DataTableRowUpdate(data={"is_primary": "true"}),
                current_user=user,
                db=db,
            )

        self.assertEqual(ctx.exception.status_code, 409)
        self.assertIn("Duplicate value for unique column 'is_primary': true", ctx.exception.detail)

    async def test_update_row_unrelated_field_preserves_unique_value_without_conflict(self) -> None:
        user = _make_user()
        columns = [
            {"name": "email", "type": "string", "unique": True},
            {"name": "name", "type": "string"},
        ]
        table = _make_table(columns, user.id)

        target_row = DataTableRow(
            id=uuid.uuid4(),
            table_id=table.id,
            data={"email": "alice@example.com", "name": "Alice"},
            created_by=user.id,
            updated_by=user.id,
        )

        db = MagicMock()
        _wire_db(db)

        async def fake_execute(stmt: object, params: dict | None = None) -> SimpleNamespace:
            sql = str(stmt)
            if "data_tables.owner_id" in sql or "data_tables.id" in sql:
                return SimpleNamespace(scalar_one_or_none=lambda: table)
            if "data_table_rows.id" in sql and "data_table_rows.table_id" in sql:
                return SimpleNamespace(scalar_one_or_none=lambda: target_row)
            if "SELECT data FROM data_table_rows" in sql:
                # Since exclude_id is the target row itself, no OTHER rows have this email
                return SimpleNamespace(fetchall=lambda: [])
            raise AssertionError(f"Unexpected query: {sql}")

        db.execute = AsyncMock(side_effect=fake_execute)

        # Update only 'name', leaving unique 'email' unchanged
        resp = await dt_api.update_row(
            table_id=table.id,
            row_id=target_row.id,
            row_data=DataTableRowUpdate(data={"name": "Alice Smith"}),
            current_user=user,
            db=db,
        )

        self.assertEqual(resp.data["name"], "Alice Smith")
        self.assertEqual(resp.data["email"], "alice@example.com")


class TestCreateRowUniqueConstraints(unittest.IsolatedAsyncioTestCase):
    async def test_create_row_boolean_duplicate_triggers_conflict(self) -> None:
        user = _make_user()
        columns = [{"name": "is_active", "type": "boolean", "unique": True}]
        table = _make_table(columns, user.id)

        db = MagicMock()
        _wire_db(db)

        async def fake_execute(stmt: object, params: dict | None = None) -> SimpleNamespace:
            sql = str(stmt)
            if "data_tables.owner_id" in sql or "data_tables.id" in sql:
                return SimpleNamespace(scalar_one_or_none=lambda: table)
            if "SELECT data FROM data_table_rows" in sql:
                return SimpleNamespace(fetchall=lambda: [({"is_active": True},)])
            raise AssertionError(f"Unexpected query: {sql}")

        db.execute = AsyncMock(side_effect=fake_execute)

        with self.assertRaises(HTTPException) as ctx:
            await dt_api.create_row(
                table_id=table.id,
                row_data=DataTableRowCreate(data={"is_active": True}),
                current_user=user,
                db=db,
            )

        self.assertEqual(ctx.exception.status_code, 409)
        self.assertIn("Duplicate value for unique column 'is_active': true", ctx.exception.detail)
