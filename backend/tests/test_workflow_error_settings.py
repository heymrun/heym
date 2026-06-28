import unittest
import uuid

from app.models.schemas import WorkflowUpdate


class TestWorkflowUpdateSchema(unittest.TestCase):
    def test_accepts_error_workflow_id_and_minutes_saved(self) -> None:
        wid = uuid.uuid4()
        update = WorkflowUpdate(error_workflow_id=wid, minutes_saved_per_run=12.5)
        self.assertEqual(update.error_workflow_id, wid)
        self.assertEqual(update.minutes_saved_per_run, 12.5)

    def test_fields_default_to_none(self) -> None:
        update = WorkflowUpdate()
        self.assertIsNone(update.error_workflow_id)
        self.assertIsNone(update.minutes_saved_per_run)


if __name__ == "__main__":
    unittest.main()
