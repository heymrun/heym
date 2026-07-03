import unittest
import uuid

from app.services.workflow_executor import WorkflowExecutor


class WorkflowMetadataVariablesTest(unittest.TestCase):
    def _executor(self, **kwargs) -> WorkflowExecutor:
        return WorkflowExecutor(nodes=[], edges=[], **kwargs)

    def test_workflow_path_and_url_derived_from_id_and_base(self) -> None:
        wid = uuid.uuid4()
        executor = self._executor(
            workflow_id=wid,
            workflow_name="Daily Report",
            workflow_description="Sends a report",
            public_base_url="https://app.test/",
        )
        ctx = executor._build_context({})
        self.assertEqual(str(ctx["workflowName"]), "Daily Report")
        self.assertEqual(str(ctx["workflowDescription"]), "Sends a report")
        self.assertEqual(str(ctx["workflowPath"]), f"/workflows/{wid}")
        self.assertEqual(str(ctx["workflowUrl"]), f"https://app.test/workflows/{wid}")

    def test_empty_when_no_workflow_id(self) -> None:
        executor = self._executor(workflow_id=None)
        ctx = executor._build_context({})
        self.assertEqual(str(ctx["workflowPath"]), "")
        self.assertEqual(str(ctx["workflowUrl"]), "")

    def test_execution_id_empty_until_run_then_stable(self) -> None:
        executor = self._executor(workflow_id=uuid.uuid4())
        ctx_before = executor._build_context({})
        self.assertEqual(str(ctx_before["executionId"]), "")
        executor.execution_id = "abc123"
        ctx_after = executor._build_context({})
        self.assertEqual(str(ctx_after["executionId"]), "abc123")


if __name__ == "__main__":
    unittest.main()
