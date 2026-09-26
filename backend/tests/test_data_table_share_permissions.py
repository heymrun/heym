"""The highest permission across direct and team shares wins for data tables."""

import datetime
import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

from fastapi import HTTPException

from app.api import data_tables as dt_api
from app.db.models import DataTable


def _table(owner_id: uuid.UUID) -> DataTable:
    table = DataTable(name="Customers", description=None, columns=[], owner_id=owner_id)
    table.id = uuid.uuid4()
    now = datetime.datetime.now()
    table.created_at = now
    table.updated_at = now
    return table


class _Result:
    """Stands in for a SQLAlchemy Result across the accessors the helpers call."""

    def __init__(self, rows: list) -> None:
        self._rows = rows

    def scalar_one_or_none(self):
        if len(self._rows) > 1:
            raise AssertionError("scalar_one_or_none() on more than one row")
        return self._rows[0] if self._rows else None

    def scalars(self):
        return SimpleNamespace(all=lambda: list(self._rows))

    def all(self):
        return list(self._rows)

    def one_or_none(self):
        return self._rows[0] if self._rows else None

    def first(self):
        return self._rows[0] if self._rows else None

    def scalar(self):
        return 0


def _access_db(table: DataTable, user_shares: list[str], team_shares: list[str]) -> AsyncMock:
    """Answer each query by its compiled shape so any lookup strategy is modelled faithfully.

    The user holds no ownership, the given direct-share permissions, and one team share per
    entry of ``team_shares`` (in that row order, as the database may return them).
    """

    async def execute(stmt):
        sql = str(stmt)
        if "data_tables.owner_id = " in sql:
            return _Result([])
        if "data_table_team_shares" in sql:
            if sql.startswith("SELECT data_tables"):
                return _Result([(table, p) for p in team_shares])
            return _Result(list(team_shares))
        if "data_table_shares" in sql:
            if sql.startswith("SELECT data_tables"):
                return _Result([(table, p) for p in user_shares])
            return _Result(list(user_shares))
        if sql.startswith("SELECT data_tables"):
            return _Result([table])
        raise AssertionError(f"unexpected query shape: {sql!r}")

    db = AsyncMock()
    db.execute = AsyncMock(side_effect=execute)
    return db


class GetDataTableWithAccessTests(unittest.IsolatedAsyncioTestCase):
    async def _write(self, user_shares: list[str], team_shares: list[str]) -> DataTable:
        table = _table(uuid.uuid4())
        db = _access_db(table, user_shares, team_shares)
        result = await dt_api._get_data_table_with_access(
            table.id, uuid.uuid4(), db, require_write=True
        )
        self.assertIs(result, table)
        return result

    async def test_direct_read_and_team_write_allows_write(self) -> None:
        await self._write(["read"], ["write"])

    async def test_two_teams_read_then_write_allows_write(self) -> None:
        await self._write([], ["read", "write"])

    async def test_two_teams_write_then_read_allows_write(self) -> None:
        await self._write([], ["write", "read"])

    async def test_direct_write_and_team_read_allows_write(self) -> None:
        await self._write(["write"], ["read"])

    async def test_read_only_shares_still_reject_write(self) -> None:
        table = _table(uuid.uuid4())
        db = _access_db(table, ["read"], ["read", "read"])

        with self.assertRaises(HTTPException) as ctx:
            await dt_api._get_data_table_with_access(table.id, uuid.uuid4(), db, require_write=True)

        self.assertEqual(ctx.exception.status_code, 403)

    async def test_read_only_shares_allow_read(self) -> None:
        table = _table(uuid.uuid4())
        db = _access_db(table, ["read"], ["read", "read"])

        result = await dt_api._get_data_table_with_access(table.id, uuid.uuid4(), db)

        self.assertIs(result, table)

    async def test_unshared_table_is_not_found(self) -> None:
        table = _table(uuid.uuid4())
        db = _access_db(table, [], [])

        with self.assertRaises(HTTPException) as ctx:
            await dt_api._get_data_table_with_access(table.id, uuid.uuid4(), db)

        self.assertEqual(ctx.exception.status_code, 404)


def _list_db(
    shared: list[tuple[DataTable, str, str]],
    team_shared: list[tuple[DataTable, str, str]],
) -> AsyncMock:
    """Answer the four list queries by shape: owned, user shares, team shares, row count."""

    async def execute(stmt):
        sql = str(stmt)
        if sql.startswith("SELECT count"):
            return _Result([])
        if "data_table_team_shares" in sql:
            return _Result(team_shared)
        if "data_table_shares" in sql:
            return _Result(shared)
        if sql.startswith("SELECT data_tables"):
            return _Result([])
        raise AssertionError(f"unexpected query shape: {sql!r}")

    db = AsyncMock()
    db.execute = AsyncMock(side_effect=execute)
    return db


class ListDataTablesTests(unittest.IsolatedAsyncioTestCase):
    async def _list(self, shared, team_shared):
        user = SimpleNamespace(id=uuid.uuid4())
        db = _list_db(shared, team_shared)
        return await dt_api.list_data_tables(current_user=user, db=db)

    async def test_team_write_beats_direct_read(self) -> None:
        table = _table(uuid.uuid4())

        rows = await self._list([(table, "owner@x.com", "read")], [(table, "Team A", "write")])

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].permission, "write")
        self.assertEqual(rows[0].shared_by_team, "Team A")
        self.assertIsNone(rows[0].shared_by)

    async def test_direct_write_beats_team_read(self) -> None:
        table = _table(uuid.uuid4())

        rows = await self._list([(table, "owner@x.com", "write")], [(table, "Team A", "read")])

        self.assertEqual(rows[0].permission, "write")
        self.assertEqual(rows[0].shared_by, "owner@x.com")
        self.assertIsNone(rows[0].shared_by_team)

    async def test_two_teams_report_write_in_either_order(self) -> None:
        table = _table(uuid.uuid4())

        for team_rows in (
            [(table, "Team A", "read"), (table, "Team B", "write")],
            [(table, "Team B", "write"), (table, "Team A", "read")],
        ):
            rows = await self._list([], team_rows)

            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0].permission, "write")
            self.assertEqual(rows[0].shared_by_team, "Team B")

    async def test_equal_permissions_keep_the_direct_share(self) -> None:
        table = _table(uuid.uuid4())

        rows = await self._list([(table, "owner@x.com", "read")], [(table, "Team A", "read")])

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].shared_by, "owner@x.com")


if __name__ == "__main__":
    unittest.main()
