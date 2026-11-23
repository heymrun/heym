"""Blank optional numeric credential fields read as their defaults, in every reader.

The credential dialog saves a cleared optional field ("default: 0", "default: 6333") as "".
`config_int` reads it as the default; the Redis and Qdrant pools warmed up at startup used
`int("")` and logged "Failed to initialize ... invalid literal for int()" for such credentials.
"""

import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.db.models import CredentialType
from app.services import qdrant_pool, redis_pool
from app.services.credential_config import config_int


def _session_with(credential: SimpleNamespace) -> MagicMock:
    session = MagicMock()
    session.__enter__.return_value.query.return_value.filter.return_value.all.return_value = [
        credential
    ]
    return session


class ConfigIntTests(unittest.TestCase):
    def test_blank_missing_and_null_give_the_default(self) -> None:
        for config in ({}, {"port": None}, {"port": ""}, {"port": "  "}):
            with self.subTest(config=config):
                self.assertEqual(config_int(config, "port", 6333), 6333)

    def test_values_are_read(self) -> None:
        self.assertEqual(config_int({"db": "3"}, "db", 0), 3)
        self.assertEqual(config_int({"db": " 2 "}, "db", 0), 2)
        self.assertEqual(config_int({"db": 0}, "db", 5), 0)
        self.assertEqual(config_int({"port": 7000}, "port", 6333), 7000)

    def test_text_that_is_not_a_number_still_fails(self) -> None:
        with self.assertRaises(ValueError):
            config_int({"port": "abc"}, "port", 6333)


class PoolWarmUpTests(unittest.TestCase):
    def test_redis_pool_reads_a_blank_database_index_as_0(self) -> None:
        credential = SimpleNamespace(name="cache", encrypted_config="x")
        config = {"redis_host": "127.0.0.1", "redis_port": "6390", "redis_db": ""}
        with (
            patch("app.db.session.SessionLocal", return_value=_session_with(credential)),
            patch("app.services.encryption.decrypt_config", return_value=config),
            patch.object(redis_pool, "get_redis_connection") as connect,
        ):
            self.assertEqual(redis_pool.warm_up_pools(), 1)
        connect.assert_called_once_with(host="127.0.0.1", port=6390, db=0, password=None)

    def test_qdrant_pool_reads_a_blank_port_as_6333(self) -> None:
        credential = SimpleNamespace(name="docs", encrypted_config="x", type=CredentialType.rag)
        config = {"db_type": "qdrant", "qdrant_host": "127.0.0.1", "qdrant_port": ""}
        with (
            patch("app.db.session.SessionLocal", return_value=_session_with(credential)),
            patch("app.services.encryption.decrypt_config", return_value=config),
            patch.object(qdrant_pool, "get_qdrant_client") as connect,
        ):
            self.assertEqual(qdrant_pool.warm_up_pools(), 1)
        connect.assert_called_once_with(host="127.0.0.1", port=6333, api_key=None)


if __name__ == "__main__":
    unittest.main()
