import unittest
import unittest.mock
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from app.api.workflows import create_workflow
from app.models.schemas import WorkflowCreate


class CreateWorkflowCommitTests(unittest.IsolatedAsyncioTestCase):
    """Regression guard for the import flow's create-then-update race.

    ``create_workflow`` must durably ``commit`` before returning, not merely
    ``flush``. Otherwise a fast follow-up request (the JSON-import flow issues
    create then immediately update) can start its transaction before the
    ``get_db()`` teardown commit lands and 404 on the just-created workflow.
    """

    async def test_create_workflow_commits_before_returning(self) -> None:
        db = AsyncMock()
        db.add = MagicMock()
        db.flush = AsyncMock()
        db.commit = AsyncMock()
        db.refresh = AsyncMock(side_effect=lambda row: None)

        current_user = SimpleNamespace(id=uuid.uuid4())

        with unittest.mock.patch(
            "app.api.workflows._build_workflow_response",
            return_value="response-sentinel",
        ):
            result = await create_workflow(
                workflow_data=WorkflowCreate(name="Imported Workflow"),
                current_user=current_user,
                db=db,
            )

        self.assertEqual(result, "response-sentinel")
        db.add.assert_called_once()
        # The durable commit is the fix for the race; a bare flush would not
        # make the row visible to a concurrent follow-up request.
        db.commit.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
