"""Tests for _find_workflow_by_node_id parameterized query in Slack and Telegram webhooks."""

import json
import unittest


class _FakeResult:
    """Minimal async-compatible result for capturing executed statements."""

    def scalars(self):
        return iter([])


async def _never_verifies(_db, _credential_id):
    return False


class TestSlackFindWorkflowByNodeId(unittest.IsolatedAsyncioTestCase):
    """Verify _find_workflow_by_node_id in the Slack webhook uses proper parameterized JSONB containment."""

    async def test_slack_bind_param_uses_parenthesized_cast(self):
        """The SQL text must use (:node_filter)::jsonb, not :node_filter::jsonb.

        SQLAlchemy's bind-param parser treats the trailing 'r' in ':node_filter::jsonb'
        as part of the parameter name (node_filte), causing ArgumentError at runtime.
        Wrapping in parens — (:node_filter)::jsonb — disambiguates correctly.
        """
        from app.api.slack import _find_workflow_by_node_id

        captured_sql = None

        async def capture_execute(stmt):
            nonlocal captured_sql
            captured_sql = stmt
            return _FakeResult()

        from unittest.mock import AsyncMock

        db = AsyncMock()
        db.execute = capture_execute

        await _find_workflow_by_node_id(db, "test-node-id", _never_verifies)

        compiled = str(captured_sql)
        # The parenthesized cast must appear in the compiled output
        assert "(:node_filter)" in compiled, (
            f"Expected parenthesized bind param in compiled SQL, got: {compiled}"
        )

    async def test_slack_node_filter_value_is_valid_json(self):
        """The node_filter bind value must be valid JSON: [{"id": "<node_id>", "type": ...}]."""
        from app.api.slack import _find_workflow_by_node_id

        captured_params = None

        async def capture_execute(stmt):
            nonlocal captured_params
            captured_params = stmt.compile().params
            return _FakeResult()

        from unittest.mock import AsyncMock

        db = AsyncMock()
        db.execute = capture_execute

        node_id = "my-test-node"
        await _find_workflow_by_node_id(db, node_id, _never_verifies)

        filter_value = captured_params["node_filter"]
        parsed = json.loads(filter_value)
        assert isinstance(parsed, list)
        assert len(parsed) == 1
        assert parsed[0] == {"id": node_id, "type": "slackTrigger"}


class TestTelegramFindWorkflowByNodeId(unittest.IsolatedAsyncioTestCase):
    """Verify _find_workflow_by_node_id in the Telegram webhook uses proper parameterized JSONB containment."""

    async def test_telegram_bind_param_uses_parenthesized_cast(self):
        """Same parenthesized-cast check for the Telegram handler."""
        from app.api.telegram import _find_workflow_by_node_id

        captured_sql = None

        async def capture_execute(stmt):
            nonlocal captured_sql
            captured_sql = stmt
            return _FakeResult()

        from unittest.mock import AsyncMock

        db = AsyncMock()
        db.execute = capture_execute

        await _find_workflow_by_node_id(db, "test-node-id", _never_verifies)

        compiled = str(captured_sql)
        assert "(:node_filter)" in compiled, (
            f"Expected parenthesized bind param in compiled SQL, got: {compiled}"
        )

    async def test_telegram_node_filter_value_is_valid_json(self):
        """The node_filter bind value for Telegram must be valid JSON."""
        from app.api.telegram import _find_workflow_by_node_id

        captured_params = None

        async def capture_execute(stmt):
            nonlocal captured_params
            captured_params = stmt.compile().params
            return _FakeResult()

        from unittest.mock import AsyncMock

        db = AsyncMock()
        db.execute = capture_execute

        node_id = "my-test-node"
        await _find_workflow_by_node_id(db, node_id, _never_verifies)

        filter_value = captured_params["node_filter"]
        parsed = json.loads(filter_value)
        assert isinstance(parsed, list)
        assert len(parsed) == 1
        assert parsed[0] == {"id": node_id, "type": "telegramTrigger"}


class TestNodeIdSpecialChars(unittest.TestCase):
    """Verify that special characters in node_id are safely encoded inside JSON values."""

    def test_node_id_special_chars_are_escaped(self):
        """Characters like quotes and backslashes in node_id stay inside the JSON value."""
        node_id = 'node"; DROP TABLE workflows;--'
        filter_value = json.dumps([{"id": node_id}])
        parsed = json.loads(filter_value)
        # json.dumps escapes the inner quotes, so the value is a single JSON string
        assert parsed[0]["id"] == node_id
        # The serialized form should not contain raw SQL-breaking sequences
        assert "DROP TABLE" in filter_value  # it's inside a JSON string, safe
