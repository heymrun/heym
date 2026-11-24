"""A widget title or cache TTL its column cannot hold is refused, not a 500.

`dashboard_widgets.title` is VARCHAR(255) and `cache_ttl_seconds` an INTEGER. The create and
update requests accepted any length and any int, so PostgreSQL refused the value and the
route answered 500 Internal Server Error.
"""

import unittest

from pydantic import ValidationError

from app.api import chat_dashboards
from app.db.models import DashboardWidget
from app.models.dashboard_schemas import (
    CACHE_TTL_MAX_SECONDS,
    WIDGET_TITLE_MAX_LENGTH,
    WidgetCreateRequest,
    WidgetUpdateRequest,
)


class DashboardWidgetLimitTests(unittest.TestCase):
    def test_the_limits_are_the_column_sizes(self) -> None:
        self.assertEqual(DashboardWidget.__table__.c.title.type.length, WIDGET_TITLE_MAX_LENGTH)
        self.assertEqual(CACHE_TTL_MAX_SECONDS, 2**31 - 1)
        self.assertEqual(chat_dashboards.MAX_WIDGET_TITLE_LENGTH, WIDGET_TITLE_MAX_LENGTH)

    def test_a_value_the_column_holds_is_accepted_and_a_larger_one_refused(self) -> None:
        for model in (WidgetCreateRequest, WidgetUpdateRequest):
            for field, fits, too_big in (
                ("title", "x" * WIDGET_TITLE_MAX_LENGTH, "x" * (WIDGET_TITLE_MAX_LENGTH + 1)),
                ("cache_ttl_seconds", CACHE_TTL_MAX_SECONDS, CACHE_TTL_MAX_SECONDS + 1),
            ):
                with self.subTest(model=model.__name__, field=field):
                    self.assertEqual(getattr(model(**{field: fits}), field), fits)
                    with self.assertRaises(ValidationError):
                        model(**{field: too_big})

    def test_defaults_and_a_zero_ttl_still_work(self) -> None:
        created = WidgetCreateRequest()
        self.assertEqual((created.title, created.cache_ttl_seconds), ("Untitled", 300))
        self.assertEqual(WidgetUpdateRequest(cache_ttl_seconds=0).cache_ttl_seconds, 0)


if __name__ == "__main__":
    unittest.main()
