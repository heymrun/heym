import unittest

from app.models.alert_schemas import _CONFIG_BY_TYPE
from app.services.alerts.registry import ALERT_HANDLERS, get_alert_handler


class TestAlertRegistry(unittest.TestCase):
    def test_every_config_type_has_a_handler(self):
        self.assertEqual(set(ALERT_HANDLERS), set(_CONFIG_BY_TYPE))

    def test_get_handler_returns_callable(self):
        handler = get_alert_handler("error_threshold")
        self.assertTrue(callable(handler))

    def test_unknown_type_raises(self):
        with self.assertRaises(ValueError):
            get_alert_handler("cosmic_rays")
