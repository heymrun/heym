"""User Rules as memory: append, replace with a revision, limits, secrets and commits."""

import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from app.services import user_memory
from app.services.user_memory import (
    MAX_USER_MEMORY_LENGTH,
    STATUS_ADDED,
    STATUS_CONFLICT,
    STATUS_REFUSED,
    STATUS_REPLACED,
    STATUS_UNCHANGED,
    plan_append,
    plan_replace,
    revision_of,
)

GITHUB_TOKEN = "gh" + "p_" + "Ab1" * 12


class RevisionTests(unittest.TestCase):
    def test_none_and_empty_share_a_revision(self) -> None:
        self.assertEqual(revision_of(None), revision_of(""))

    def test_revision_changes_with_the_text(self) -> None:
        self.assertNotEqual(revision_of("a"), revision_of("b"))
        self.assertEqual(len(revision_of("a")), 16)


class PlanAppendTests(unittest.TestCase):
    def test_append_to_empty_stores_the_line(self) -> None:
        plan = plan_append(None, "  Prefers short answers  ")
        self.assertEqual(plan.text, "Prefers short answers")
        self.assertEqual(plan.result.status, STATUS_ADDED)
        self.assertEqual(plan.result.snapshot.content, "Prefers short answers")

    def test_append_adds_a_new_line(self) -> None:
        plan = plan_append("Answer in English\n", "Prefers short answers")
        self.assertEqual(plan.text, "Answer in English\nPrefers short answers")

    def test_a_line_already_there_is_unchanged(self) -> None:
        plan = plan_append("Answer in English\nPrefers short answers", "Prefers short answers")
        self.assertIsNone(plan.text)
        self.assertEqual(plan.result.status, STATUS_UNCHANGED)

    def test_empty_content_is_refused(self) -> None:
        plan = plan_append("x", "   ")
        self.assertIsNone(plan.text)
        self.assertEqual(plan.result.status, STATUS_REFUSED)
        self.assertEqual(plan.result.error, user_memory.EMPTY_APPEND)

    def test_a_secret_is_refused_with_its_reason(self) -> None:
        plan = plan_append("x", f"My GitHub token is {GITHUB_TOKEN}")
        self.assertIsNone(plan.text)
        self.assertEqual(plan.result.error, user_memory.SECRET_REFUSAL)
        self.assertEqual(plan.result.reason, "a GitHub token")

    def test_over_the_limit_is_refused(self) -> None:
        plan = plan_append("a" * (MAX_USER_MEMORY_LENGTH - 3), "too long")
        self.assertIsNone(plan.text)
        self.assertEqual(plan.result.error, user_memory.APPEND_TOO_LONG)


class PlanReplaceTests(unittest.TestCase):
    def test_matching_revision_replaces(self) -> None:
        plan = plan_replace("old line", "new line", revision_of("old line"))
        self.assertEqual(plan.text, "new line")
        self.assertEqual(plan.result.status, STATUS_REPLACED)
        self.assertEqual(plan.result.snapshot.revision, revision_of("new line"))

    def test_stale_revision_is_a_conflict_with_the_current_text(self) -> None:
        plan = plan_replace("changed elsewhere", "new line", revision_of("old line"))
        self.assertIsNone(plan.text)
        self.assertEqual(plan.result.status, STATUS_CONFLICT)
        self.assertEqual(plan.result.snapshot.content, "changed elsewhere")
        self.assertIsNotNone(plan.result.next_step)

    def test_empty_content_clears(self) -> None:
        plan = plan_replace("old line", "", revision_of("old line"))
        self.assertEqual(plan.text, "")
        self.assertEqual(plan.result.status, STATUS_REPLACED)

    def test_same_text_is_unchanged(self) -> None:
        plan = plan_replace("same", " same ", revision_of("same"))
        self.assertIsNone(plan.text)
        self.assertEqual(plan.result.status, STATUS_UNCHANGED)

    def test_over_the_limit_is_refused(self) -> None:
        plan = plan_replace("", "a" * (MAX_USER_MEMORY_LENGTH + 1), revision_of(""))
        self.assertEqual(plan.result.error, user_memory.REPLACE_TOO_LONG)

    def test_a_new_secret_line_is_refused(self) -> None:
        plan = plan_replace("keep", f"keep\ntoken: {GITHUB_TOKEN}", revision_of("keep"))
        self.assertIsNone(plan.text)
        self.assertEqual(plan.result.error, user_memory.SECRET_REFUSAL)

    def test_a_secret_line_the_user_already_stored_does_not_block(self) -> None:
        current = f"token: {GITHUB_TOKEN}\nold"
        plan = plan_replace(current, f"token: {GITHUB_TOKEN}\nnew", revision_of(current))
        self.assertEqual(plan.result.status, STATUS_REPLACED)


def _db_with(user_rules: str | None) -> tuple[AsyncMock, SimpleNamespace]:
    user = SimpleNamespace(user_rules=user_rules)
    result = MagicMock()
    result.scalar_one.return_value = user
    result.scalar_one_or_none.return_value = user_rules
    db = AsyncMock()
    db.execute.return_value = result
    return db, user


class ServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_read_returns_the_stored_text(self) -> None:
        db, _ = _db_with("Answer in English")
        snapshot = await user_memory.read_user_memory(db, uuid.uuid4())
        self.assertEqual(snapshot.content, "Answer in English")
        self.assertEqual(snapshot.max_length, MAX_USER_MEMORY_LENGTH)

    async def test_append_writes_and_commits(self) -> None:
        db, user = _db_with("Answer in English")
        result = await user_memory.append_user_memory(db, uuid.uuid4(), "Prefers short answers")
        self.assertEqual(user.user_rules, "Answer in English\nPrefers short answers")
        self.assertTrue(result.changed)
        db.commit.assert_awaited_once()

    async def test_a_refusal_writes_nothing_but_still_commits(self) -> None:
        db, user = _db_with("Answer in English")
        result = await user_memory.append_user_memory(db, uuid.uuid4(), GITHUB_TOKEN)
        self.assertEqual(user.user_rules, "Answer in English")
        self.assertFalse(result.changed)
        db.commit.assert_awaited_once()

    async def test_clearing_stores_null(self) -> None:
        db, user = _db_with("old")
        await user_memory.replace_user_memory(db, uuid.uuid4(), "", revision_of("old"))
        self.assertIsNone(user.user_rules)

    async def test_the_write_locks_the_row(self) -> None:
        db, _ = _db_with("old")
        await user_memory.replace_user_memory(db, uuid.uuid4(), "new", revision_of("old"))
        statement = db.execute.await_args.args[0]
        self.assertIsNotNone(statement._for_update_arg)


if __name__ == "__main__":
    unittest.main()
