"""A Redis credential with a blank Database Index uses database 0.

The credential form marks the field optional ("default: 0") and saves "" when it is
cleared; the credential list already shows such a credential as "(db 0)". The node read
it with int(""), so every Redis node on that credential failed with
"invalid literal for int() with base 10: ''".
"""

import unittest
from unittest.mock import MagicMock, patch

from app.services.node_execution.base import NodeExecutionContext
from app.services.node_execution.nodes import redis_node


def _run(redis_db: object) -> MagicMock:
    executor = MagicMock()
    executor.evaluate_nonempty_message_template.side_effect = lambda tpl, inputs, node_id: tpl
    credential = MagicMock()
    credential.encrypted_config = "encrypted"
    executor._get_accessible_credential.return_value = credential
    data = {
        "credentialId": "cred-1",
        "redisOperation": "get",
        "redisKey": "greeting",
    }
    ctx = NodeExecutionContext(
        executor=executor,
        node_id="redis-1",
        inputs={},
        allow_branch_skip=False,
        start_time=0,
        node={"id": "redis-1", "type": "redis", "data": data},
        node_type="redis",
        node_data=data,
        node_label="remember",
    )
    config = {"redis_host": "127.0.0.1", "redis_port": "6390", "redis_password": ""}
    if redis_db is not ...:
        config["redis_db"] = redis_db
    with (
        patch("app.services.encryption.decrypt_config", return_value=config),
        patch("app.services.redis_pool.get_redis_connection") as connect,
    ):
        connect.return_value.get.return_value = "hello"
        output = redis_node.execute(ctx)
    assert output == {"value": "hello", "exists": True, "key": "greeting"}, output
    return connect


class RedisBlankDatabaseIndexTests(unittest.TestCase):
    def test_blank_or_missing_index_is_database_0(self) -> None:
        for redis_db in ("", "  ", None, ...):
            with self.subTest(redis_db=redis_db):
                connect = _run(redis_db)
                self.assertEqual(connect.call_args.kwargs["db"], 0)

    def test_a_set_index_is_used(self) -> None:
        for redis_db, expected in (("0", 0), ("3", 3), (" 3 ", 3), (2, 2)):
            with self.subTest(redis_db=redis_db):
                self.assertEqual(_run(redis_db).call_args.kwargs["db"], expected)


if __name__ == "__main__":
    unittest.main()
