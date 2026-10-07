import datetime
import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from fastapi import HTTPException

from app.api import data_tables as dt_api
from app.db.models import DataTable, DataTableRow, User
from app.models.schemas import DataTableRowCreate, DataTableRowUpdate
from app.services.node_execution.nodes.data_table_node import _check_unique_sync


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
    async def test_boolean_column_skipped_in_unique_constraints(self) -> None:
        table_id = uuid.uuid4()
        columns = [{"name": "is_active", "type": "boolean", "unique": True}]
        data = {"is_active": True}

        db = MagicMock()
        errors = await dt_api._check_unique_constraints(table_id, data, columns, db)

        self.assertEqual(errors, [])
        db.execute.assert_not_called()

    async def test_boolean_column_skipped_when_value_is_false(self) -> None:
        table_id = uuid.uuid4()
        columns = [{"name": "is_active", "type": "boolean", "unique": True}]
        data = {"is_active": False}

        db = MagicMock()
        errors = await dt_api._check_unique_constraints(table_id, data, columns, db)

        self.assertEqual(errors, [])
        db.execute.assert_not_called()

    async def test_boolean_values_normalized_for_non_boolean_unique_column(self) -> None:
        table_id = uuid.uuid4()
        columns = [{"name": "flag", "type": "string", "unique": True}]

        for truthy_val in (True, "true"):
            db = MagicMock()
            captured_params: list[dict] = []

            async def fake_execute(stmt: object, params: dict | None = None) -> SimpleNamespace:
                captured_params.append(params or {})
                return SimpleNamespace(fetchall=lambda: [({"flag": True},)])

            db.execute = AsyncMock(side_effect=fake_execute)

            errors = await dt_api._check_unique_constraints(
                table_id, {"flag": truthy_val}, columns, db
            )
            self.assertEqual(len(errors), 1)
            self.assertEqual(captured_params[0]["cv0"], "true")
            self.assertIn("Duplicate value for unique column 'flag': true", errors[0])

    async def test_boolean_false_values_normalized_for_non_boolean_unique_column(self) -> None:
        table_id = uuid.uuid4()
        columns = [{"name": "flag", "type": "string", "unique": True}]

        for falsy_val in (False, "false"):
            db = MagicMock()
            captured_params: list[dict] = []

            async def fake_execute(stmt: object, params: dict | None = None) -> SimpleNamespace:
                captured_params.append(params or {})
                return SimpleNamespace(fetchall=lambda: [({"flag": False},)])

            db.execute = AsyncMock(side_effect=fake_execute)

            errors = await dt_api._check_unique_constraints(
                table_id, {"flag": falsy_val}, columns, db
            )
            self.assertEqual(len(errors), 1)
            self.assertEqual(captured_params[0]["cv0"], "false")
            self.assertIn("Duplicate value for unique column 'flag': false", errors[0])

    async def test_string_column_duplicate_detected(self) -> None:
        table_id = uuid.uuid4()
        columns = [{"name": "email", "type": "string", "unique": True}]
        data = {"email": "test@example.com"}

        db = MagicMock()
        captured_params: list[dict] = []

        async def fake_execute(stmt: object, params: dict | None = None) -> SimpleNamespace:
            captured_params.append(params or {})
            return SimpleNamespace(fetchall=lambda: [({"email": "test@example.com"},)])

        db.execute = AsyncMock(side_effect=fake_execute)

        errors = await dt_api._check_unique_constraints(table_id, data, columns, db)
        self.assertEqual(len(errors), 1)
        self.assertIn("Duplicate value for unique column 'email': test@example.com", errors[0])


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
                return SimpleNamespace(fetchall=lambda: [({"code": 100, "name": "Row 1"},)])
            raise AssertionError(f"Unexpected query: {sql}")

        db.execute = AsyncMock(side_effect=fake_execute)

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

    async def test_update_row_boolean_column_skips_unique_constraint(self) -> None:
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
                raise AssertionError("Unique query should not be run for boolean columns")
            raise AssertionError(f"Unexpected query: {sql}")

        db.execute = AsyncMock(side_effect=fake_execute)

        resp = await dt_api.update_row(
            table_id=table.id,
            row_id=target_row.id,
            row_data=DataTableRowUpdate(data={"is_primary": True}),
            current_user=user,
            db=db,
        )

        self.assertEqual(resp.data["is_primary"], True)

    async def test_update_row_omitted_unique_column_colliding_with_another_row_triggers_409(
        self,
    ) -> None:
        user = _make_user()
        columns = [
            {"name": "email", "type": "string", "unique": True},
            {"name": "name", "type": "string"},
        ]
        table = _make_table(columns, user.id)

        target_row = DataTableRow(
            id=uuid.uuid4(),
            table_id=table.id,
            data={"email": "alice@example.com", "name": "Target Row"},
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
                return SimpleNamespace(
                    fetchall=lambda: [({"email": "alice@example.com", "name": "Existing Row"},)]
                )
            raise AssertionError(f"Unexpected query: {sql}")

        db.execute = AsyncMock(side_effect=fake_execute)

        # Update payload leaves out the unique 'email' column, only updating 'name'.
        # Merged row preserves email: "alice@example.com" and detects conflict with other row.
        with self.assertRaises(HTTPException) as ctx:
            await dt_api.update_row(
                table_id=table.id,
                row_id=target_row.id,
                row_data=DataTableRowUpdate(data={"name": "New Target Name"}),
                current_user=user,
                db=db,
            )

        self.assertEqual(ctx.exception.status_code, 409)
        self.assertIn(
            "Duplicate value for unique column 'email': alice@example.com", ctx.exception.detail
        )

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
                return SimpleNamespace(fetchall=lambda: [])
            raise AssertionError(f"Unexpected query: {sql}")

        db.execute = AsyncMock(side_effect=fake_execute)

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
    async def test_create_row_boolean_column_skips_unique_constraint(self) -> None:
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
                raise AssertionError("Unique query should not be run for boolean columns")
            raise AssertionError(f"Unexpected query: {sql}")

        db.execute = AsyncMock(side_effect=fake_execute)

        resp = await dt_api.create_row(
            table_id=table.id,
            row_data=DataTableRowCreate(data={"is_active": True}),
            current_user=user,
            db=db,
        )

        self.assertEqual(resp.data["is_active"], True)

    async def test_create_row_string_duplicate_triggers_conflict(self) -> None:
        user = _make_user()
        columns = [{"name": "code", "type": "string", "unique": True}]
        table = _make_table(columns, user.id)

        db = MagicMock()
        _wire_db(db)

        async def fake_execute(stmt: object, params: dict | None = None) -> SimpleNamespace:
            sql = str(stmt)
            if "data_tables.owner_id" in sql or "data_tables.id" in sql:
                return SimpleNamespace(scalar_one_or_none=lambda: table)
            if "SELECT data FROM data_table_rows" in sql:
                return SimpleNamespace(fetchall=lambda: [({"code": "alpha"},)])
            raise AssertionError(f"Unexpected query: {sql}")

        db.execute = AsyncMock(side_effect=fake_execute)

        with self.assertRaises(HTTPException) as ctx:
            await dt_api.create_row(
                table_id=table.id,
                row_data=DataTableRowCreate(data={"code": "alpha"}),
                current_user=user,
                db=db,
            )

        self.assertEqual(ctx.exception.status_code, 409)
        self.assertIn("Duplicate value for unique column 'code': alpha", ctx.exception.detail)


class TestDataTableNodeUniqueConstraints(unittest.TestCase):
    def test_node_skips_boolean_column_unique_constraint(self) -> None:
        table_id = str(uuid.uuid4())
        columns = [{"name": "is_active", "type": "boolean", "unique": True}]
        db = MagicMock()

        _check_unique_sync(table_id, {"is_active": True}, columns, db)
        db.execute.assert_not_called()

    def test_node_duplicate_number_or_string_raises_value_error(self) -> None:
        table_id = str(uuid.uuid4())
        columns = [{"name": "code", "type": "number", "unique": True}]
        db = MagicMock()
        db.execute.return_value.fetchall.return_value = [({"code": 100},)]

        with self.assertRaises(ValueError) as ctx:
            _check_unique_sync(table_id, {"code": 100}, columns, db)

        self.assertIn("Duplicate value for unique column 'code': 100", str(ctx.exception))

    def test_node_normalizes_boolean_on_non_boolean_unique_column(self) -> None:
        table_id = str(uuid.uuid4())
        columns = [{"name": "flag", "type": "string", "unique": True}]
        db = MagicMock()
        captured_params: list[dict] = []

        def fake_execute(stmt: object, params: dict | None = None) -> SimpleNamespace:
            captured_params.append(params or {})
            return SimpleNamespace(fetchall=lambda: [({"flag": True},)])

        db.execute.side_effect = fake_execute

        with self.assertRaises(ValueError) as ctx:
            _check_unique_sync(table_id, {"flag": True}, columns, db)

        self.assertIn("Duplicate value for unique column 'flag': true", str(ctx.exception))
        self.assertEqual(captured_params[0]["cv0"], "true")

    def test_node_update_with_omitted_unique_column_colliding_with_another_row_raises_value_error(
        self,
    ) -> None:
        table_id = str(uuid.uuid4())
        columns = [
            {"name": "email", "type": "string", "unique": True},
            {"name": "name", "type": "string"},
        ]
        target_row_id = str(uuid.uuid4())
        target_row_data = {"email": "bob@example.com", "name": "Bob"}
        update_payload = {"name": "Bob New"}
        merged = {**target_row_data, **update_payload}

        db = MagicMock()
        db.execute.return_value.fetchall.return_value = [
            ({"email": "bob@example.com", "name": "Another Row"},)
        ]

        with self.assertRaises(ValueError) as ctx:
            _check_unique_sync(table_id, merged, columns, db, exclude_row_id=target_row_id)

        self.assertIn(
            "Duplicate value for unique column 'email': bob@example.com", str(ctx.exception)
        )
