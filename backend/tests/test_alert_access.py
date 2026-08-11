import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from sqlalchemy.dialects import postgresql

from app.services.alert_access import (
    accessible_alerts_filter,
    get_accessible_alert,
    get_owned_alert,
)


def _result(value):
    result = MagicMock()
    result.scalar_one_or_none.return_value = value
    return result


class TestAlertAccess(unittest.IsolatedAsyncioTestCase):
    async def test_owner_is_returned_on_the_first_query(self):
        alert = SimpleNamespace(id=uuid.uuid4())
        db = MagicMock()
        db.execute = AsyncMock(return_value=_result(alert))
        found = await get_accessible_alert(db, alert.id, uuid.uuid4())
        self.assertIs(found, alert)
        self.assertEqual(db.execute.await_count, 1)

    async def test_direct_share_is_found_second(self):
        alert = SimpleNamespace(id=uuid.uuid4())
        db = MagicMock()
        db.execute = AsyncMock(side_effect=[_result(None), _result(alert)])
        found = await get_accessible_alert(db, alert.id, uuid.uuid4())
        self.assertIs(found, alert)

    async def test_team_share_is_found_third(self):
        alert = SimpleNamespace(id=uuid.uuid4())
        db = MagicMock()
        db.execute = AsyncMock(side_effect=[_result(None), _result(None), _result(alert)])
        found = await get_accessible_alert(db, alert.id, uuid.uuid4())
        self.assertIs(found, alert)

    async def test_no_access_returns_none(self):
        db = MagicMock()
        db.execute = AsyncMock(side_effect=[_result(None), _result(None), _result(None)])
        found = await get_accessible_alert(db, uuid.uuid4(), uuid.uuid4())
        self.assertIsNone(found)

    async def test_get_owned_alert_only_matches_the_owner(self):
        db = MagicMock()
        db.execute = AsyncMock(return_value=_result(None))
        found = await get_owned_alert(db, uuid.uuid4(), uuid.uuid4())
        self.assertIsNone(found)
        self.assertEqual(db.execute.await_count, 1)


class TestAccessibleAlertsFilter(unittest.TestCase):
    def test_filter_covers_owned_shared_and_team_shared(self):
        sql = str(
            accessible_alerts_filter(uuid.uuid4()).compile(
                dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
            )
        )
        self.assertIn("alerts.owner_id", sql)
        self.assertIn("alert_shares", sql)
        self.assertIn("alert_team_shares", sql)
        self.assertIn("team_members", sql)
        self.assertIn("UNION", sql)
