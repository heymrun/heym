"""The SQL task store against PostgreSQL: scoping and conditional state changes."""

import uuid

from app.services.a2a.models import TaskState
from app.services.a2a.task_store import SqlTaskStore, TaskQuery, TaskScope
from tests.a2a_fixtures import A2APostgresCase


class SqlTaskStoreTests(A2APostgresCase):
    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        self.store = SqlTaskStore()
        self.global_scope = TaskScope(self.user_id, None)
        self.server_scope = TaskScope(self.user_id, self.server_id)

    async def test_a_task_is_visible_only_on_its_own_surface(self) -> None:
        task = await self.store.create(self.global_scope, self.conversation_id)

        self.assertIsNotNone(await self.store.get(self.global_scope, task.id))
        self.assertIsNone(await self.store.get(self.server_scope, task.id))
        self.assertIsNone(await self.store.get(TaskScope(self.other_user_id, None), task.id))

    async def test_start_and_finish_are_conditional(self) -> None:
        task = await self.store.create(self.server_scope, self.conversation_id)

        self.assertTrue(await self.store.start(self.server_scope, task.id))
        self.assertFalse(await self.store.start(self.server_scope, task.id))
        self.assertTrue(
            await self.store.finish(task.id, TaskState.COMPLETED, None, {"text": "Done."})
        )
        self.assertFalse(await self.store.finish(task.id, TaskState.FAILED, "late", None))

        stored = await self.store.get(self.server_scope, task.id)
        self.assertIs(stored.state, TaskState.COMPLETED)
        self.assertEqual(stored.artifacts, {"text": "Done."})

    async def test_cancel_only_moves_unfinished_tasks(self) -> None:
        task = await self.store.create(self.global_scope, self.conversation_id)

        canceled = await self.store.cancel(self.global_scope, task.id)
        self.assertIs(canceled.state, TaskState.CANCELED)
        self.assertIsNone(await self.store.cancel(self.global_scope, task.id))
        self.assertIsNone(await self.store.cancel(TaskScope(self.other_user_id, None), task.id))

    async def test_list_pages_within_the_surface(self) -> None:
        for _ in range(3):
            await self.store.create(self.global_scope, self.conversation_id)
        await self.store.create(self.server_scope, self.conversation_id)

        page = await self.store.list(
            self.global_scope,
            TaskQuery(context_id=None, state=None, updated_after=None, offset=0, limit=2),
        )

        self.assertEqual(page.total, 3)
        self.assertEqual(len(page.tasks), 2)

    async def test_conversation_ownership(self) -> None:
        self.assertTrue(await self.store.owns_conversation(self.user_id, self.conversation_id))
        self.assertFalse(
            await self.store.owns_conversation(self.user_id, self.other_conversation_id)
        )
        self.assertFalse(await self.store.owns_conversation(self.user_id, uuid.uuid4()))
