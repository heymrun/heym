"""One alert whose metric query fails must not take the rest of its batch down (real Postgres)."""

import unittest
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any
from unittest.mock import patch

from sqlalchemy import delete, select, text

from app.db.models import Alert, User
from app.db.session import async_session_maker, engine
from app.services.alerts import evaluator
from app.services.alerts.registry import get_alert_handler


async def _failing_handler(ctx: Any) -> None:
    # Fails inside Postgres, which leaves the session's transaction aborted.
    await ctx.db.execute(text("SELECT 1 / 0"))


def _handler_for(alert_type: str) -> Any:
    return _failing_handler if alert_type == "error_threshold" else get_alert_handler(alert_type)


class RealPostgresAlertBatchIsolationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        await engine.dispose()
        self.owner_id = uuid.uuid4()
        due = datetime.now(timezone.utc) - timedelta(minutes=5)
        try:
            async with async_session_maker() as session:
                session.add(
                    User(
                        id=self.owner_id,
                        email=f"alert_batch_{self.owner_id.hex[:8]}@example.com",
                        hashed_password="hashed_pw",
                        name="Alert Batch Test User",
                    )
                )
                await session.flush()
                self.broken = Alert(
                    owner_id=self.owner_id,
                    name="broken",
                    alert_type="error_threshold",
                    scope="system",
                    config={
                        "alert_type": "error_threshold",
                        "window_minutes": 60,
                        "threshold_count": 5,
                    },
                    next_check_at=due,
                )
                self.healthy = Alert(
                    owner_id=self.owner_id,
                    name="healthy",
                    alert_type="execution_count",
                    scope="system",
                    config={
                        "alert_type": "execution_count",
                        "window_minutes": 60,
                        "threshold_count": 5,
                    },
                    next_check_at=due,
                )
                session.add_all([self.broken, self.healthy])
                await session.commit()
        except Exception as exc:
            raise unittest.SkipTest(f"PostgreSQL setup failed: {exc}") from exc

    async def asyncTearDown(self) -> None:
        async with async_session_maker() as session:
            await session.execute(delete(User).where(User.id == self.owner_id))
            await session.commit()
        await engine.dispose()

    async def test_a_failing_metric_query_does_not_abort_the_other_alerts(self) -> None:
        with patch.object(evaluator, "get_alert_handler", _handler_for):
            await evaluator.evaluate_due_alerts()

        async with async_session_maker() as session:
            rows = {
                row.name: row
                for row in (
                    await session.execute(select(Alert).where(Alert.owner_id == self.owner_id))
                ).scalars()
            }
        self.assertEqual(rows["healthy"].last_observed_value, 0.0)
        self.assertIsNone(rows["broken"].last_observed_value)
        # Both were claimed, so the broken one waits for its next interval.
        self.assertIsNotNone(rows["broken"].last_evaluated_at)


if __name__ == "__main__":
    unittest.main()
