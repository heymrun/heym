"""Tests for the heym node handler."""

import unittest
import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from sqlalchemy import true
from sqlalchemy.dialects import postgresql

from app.services.node_execution.base import NodeExecutionContext
from app.services.node_execution.nodes import heym_node


def _ctx(
    node_data: dict,
    workflow_id: uuid.UUID | None = None,
    actor_user_id: uuid.UUID | None = None,
) -> NodeExecutionContext:
    """A node context; without an actor the handler looks up the owning workflow first."""
    executor = MagicMock()
    executor.workflow_id = str(workflow_id or uuid.uuid4())
    executor.actor_user_id = actor_user_id
    executor.evaluate_message_template.side_effect = lambda v, *_a, **_kw: str(v) if v else ""
    node = {"id": "n1", "type": "heym", "data": node_data}
    return NodeExecutionContext(
        executor=executor,
        node_id="n1",
        inputs={},
        allow_branch_skip=False,
        start_time=0.0,
        node=node,
        node_type="heym",
        node_data=node_data,
        node_label=node_data.get("label", "heym"),
    )


def _workflow(name: str, owner_id: uuid.UUID, nodes: list | None = None) -> MagicMock:
    workflow = MagicMock()
    workflow.id = uuid.uuid4()
    workflow.name = name
    workflow.description = "desc"
    workflow.owner_id = owner_id
    workflow.active = True
    workflow.folder_id = None
    workflow.updated_at = datetime(2026, 8, 11, tzinfo=timezone.utc)
    workflow.nodes = nodes if nodes is not None else [{"id": "a", "type": "llm", "data": {}}]
    workflow.edges = []
    return workflow


class HeymNodeTestBase(unittest.TestCase):
    def setUp(self) -> None:
        self.owner_id = uuid.uuid4()
        self.db = MagicMock()
        session_cm = MagicMock()
        session_cm.__enter__.return_value = self.db
        session_cm.__exit__.return_value = False
        self.session_patcher = patch(
            "app.db.session.SessionLocal", MagicMock(return_value=session_cm)
        )
        self.session_patcher.start()
        self.addCleanup(self.session_patcher.stop)

    def _scalars(self, rows: list) -> MagicMock:
        result = MagicMock()
        result.scalars.return_value.all.return_value = rows
        return result

    def _scalar_one(self, row: object) -> MagicMock:
        result = MagicMock()
        result.scalar_one_or_none.return_value = row
        return result


class ListWorkflowsTest(HeymNodeTestBase):
    def test_lists_accessible_workflows_with_node_counts(self) -> None:
        owning = _workflow("Owning", self.owner_id)
        other = _workflow("Other", self.owner_id, nodes=[{"id": "a"}, {"id": "b"}])
        self.db.execute.side_effect = [
            self._scalar_one(owning),
            self._scalars([owning, other]),
        ]

        result = heym_node.execute(_ctx({"heymOperation": "listWorkflows"}))

        self.assertEqual(result["total"], 2)
        self.assertEqual(result["workflows"][1]["node_count"], 2)
        self.assertEqual(result["workflows"][0]["name"], "Owning")

    def test_limit_caps_the_returned_rows_but_not_the_total(self) -> None:
        owning = _workflow("Owning", self.owner_id)
        rows = [_workflow(f"W{i}", self.owner_id) for i in range(5)]
        self.db.execute.side_effect = [self._scalar_one(owning), self._scalars(rows)]

        result = heym_node.execute(_ctx({"heymOperation": "listWorkflows", "heymLimit": "2"}))

        self.assertEqual(len(result["workflows"]), 2)
        self.assertEqual(result["total"], 5)

    def test_empty_limit_returns_every_workflow(self) -> None:
        owning = _workflow("Owning", self.owner_id)
        rows = [_workflow(f"W{i}", self.owner_id) for i in range(5)]
        self.db.execute.side_effect = [self._scalar_one(owning), self._scalars(rows)]

        result = heym_node.execute(_ctx({"heymOperation": "listWorkflows", "heymLimit": ""}))

        self.assertEqual(len(result["workflows"]), 5)

    def test_a_limit_resolved_from_a_float_still_limits(self) -> None:
        # "$cfg.limit" with a number column holding 2.0 renders as "2.0".
        for limit, expected in (("2.0", 2), ("2.9", 2), ("abc", 5), ("inf", 5), ("nan", 5)):
            with self.subTest(limit=limit):
                owning = _workflow("Owning", self.owner_id)
                rows = [_workflow(f"W{i}", self.owner_id) for i in range(5)]
                self.db.execute.side_effect = [self._scalar_one(owning), self._scalars(rows)]

                result = heym_node.execute(
                    _ctx({"heymOperation": "listWorkflows", "heymLimit": limit})
                )

                self.assertEqual(len(result["workflows"]), expected)

    def test_zero_limit_returns_every_workflow(self) -> None:
        owning = _workflow("Owning", self.owner_id)
        rows = [_workflow(f"W{i}", self.owner_id) for i in range(5)]
        self.db.execute.side_effect = [self._scalar_one(owning), self._scalars(rows)]

        result = heym_node.execute(_ctx({"heymOperation": "listWorkflows", "heymLimit": "0"}))

        self.assertEqual(len(result["workflows"]), 5)
        self.assertEqual(result["total"], 5)


class GetWorkflowTest(HeymNodeTestBase):
    def test_returns_full_node_configuration(self) -> None:
        owning = _workflow("Owning", self.owner_id)
        target = _workflow(
            "Target",
            self.owner_id,
            nodes=[
                {
                    "id": "a",
                    "type": "llm",
                    "position": {"x": 10, "y": 20},
                    "data": {"label": "ask", "credentialId": "cred-1", "userMessage": "hi"},
                }
            ],
        )
        self.db.execute.side_effect = [self._scalar_one(owning), self._scalar_one(target)]

        node = heym_node.execute(
            _ctx({"heymOperation": "getWorkflow", "heymWorkflowId": str(target.id)})
        )["nodes"][0]

        self.assertEqual(node["id"], "a")
        self.assertEqual(node["type"], "llm")
        self.assertEqual(node["label"], "ask")
        self.assertEqual(node["position"], {"x": 10, "y": 20})
        self.assertEqual(node["data"]["credentialId"], "cred-1")
        self.assertEqual(node["data"]["userMessage"], "hi")

    def test_node_data_exposes_hardcoded_secrets_for_scanning(self) -> None:
        """The DLP case: a token pasted into a field has to be visible to be found."""
        owning = _workflow("Owning", self.owner_id)
        target = _workflow(
            "Target",
            self.owner_id,
            nodes=[{"id": "a", "type": "http", "data": {"curl": "curl -H 'key: sk-live-123'"}}],
        )
        self.db.execute.side_effect = [self._scalar_one(owning), self._scalar_one(target)]

        result = heym_node.execute(
            _ctx({"heymOperation": "getWorkflow", "heymWorkflowId": str(target.id)})
        )

        self.assertIn("sk-live-123", result["nodes"][0]["data"]["curl"])

    def test_edges_carry_their_handles(self) -> None:
        owning = _workflow("Owning", self.owner_id)
        target = _workflow("Target", self.owner_id)
        target.edges = [
            {"id": "e1", "source": "a", "target": "b", "sourceHandle": "true", "targetHandle": None}
        ]
        self.db.execute.side_effect = [self._scalar_one(owning), self._scalar_one(target)]

        edge = heym_node.execute(
            _ctx({"heymOperation": "getWorkflow", "heymWorkflowId": str(target.id)})
        )["edges"][0]

        self.assertEqual(edge["sourceHandle"], "true")
        self.assertIsNone(edge["targetHandle"])

    def test_inaccessible_workflow_raises(self) -> None:
        owning = _workflow("Owning", self.owner_id)
        self.db.execute.side_effect = [self._scalar_one(owning), self._scalar_one(None)]

        with self.assertRaises(ValueError) as caught:
            heym_node.execute(
                _ctx({"heymOperation": "getWorkflow", "heymWorkflowId": str(uuid.uuid4())})
            )

        self.assertIn("not found", str(caught.exception).lower())

    def test_missing_workflow_id_raises(self) -> None:
        owning = _workflow("Owning", self.owner_id)
        self.db.execute.side_effect = [self._scalar_one(owning)]

        with self.assertRaises(ValueError):
            heym_node.execute(_ctx({"heymOperation": "getWorkflow"}))


class GetExecutionHistoryTest(HeymNodeTestBase):
    def _entries(self, rows: list) -> MagicMock:
        result = MagicMock()
        result.scalars.return_value.all.return_value = rows
        return result

    def _counts(self, counts: dict[str, int]) -> MagicMock:
        result = MagicMock()
        result.all.return_value = list(counts.items())
        return result

    def _encrypted(self, count: int = 0) -> MagicMock:
        result = MagicMock()
        result.scalar_one.return_value = count
        return result

    def _queue(
        self, owning: MagicMock, target: MagicMock, rows: list, counts: dict, encrypted: int = 0
    ) -> None:
        """Queue the five statements the handler issues, in order."""
        self.db.execute.side_effect = [
            self._scalar_one(owning),
            self._scalar_one(target),
            self._counts(counts),
            self._encrypted(encrypted),
            self._entries(rows),
        ]

    def _history_sql(self) -> str:
        """Compile the last two statements (breakdown, slice) for inspection."""
        return " ".join(
            str(call.args[0].compile(dialect=postgresql.dialect()))
            for call in self.db.execute.call_args_list[2:]
        )

    def _entry(self, status: str, minute: int = 0) -> MagicMock:
        entry = MagicMock()
        entry.id = uuid.uuid4()
        entry.status = status
        entry.started_at = datetime(2026, 8, 11, 12, minute, tzinfo=timezone.utc)
        entry.execution_time_ms = 1234.0
        entry.trigger_source = "manual"
        entry.recovered = False
        entry.inputs = {"text": "go"}
        entry.outputs = {"text": "done"}
        entry.node_results = [{"huge": "trace"}]
        return entry

    def test_returns_history_entries_with_a_status_breakdown(self) -> None:
        owning = _workflow("Owning", self.owner_id)
        target = _workflow("Target", self.owner_id)
        entries = [self._entry("success", 3), self._entry("error", 2), self._entry("success", 1)]
        self._queue(owning, target, entries, {"success": 2, "error": 1})

        result = heym_node.execute(
            _ctx({"heymOperation": "getExecutionHistory", "heymWorkflowId": str(target.id)})
        )

        self.assertEqual(result["total"], 3)
        self.assertEqual(len(result["executions"]), 3)
        self.assertEqual(result["by_status"], {"success": 2, "error": 1})
        self.assertEqual(result["workflow_name"], "Target")
        self.assertIsNone(result["since"])

    def test_encrypted_runs_are_counted_but_never_listed(self) -> None:
        owning = _workflow("Owning", self.owner_id)
        target = _workflow("Target", self.owner_id)
        self._queue(owning, target, [self._entry("success")], {"success": 3}, encrypted=2)

        result = heym_node.execute(
            _ctx({"heymOperation": "getExecutionHistory", "heymWorkflowId": str(target.id)})
        )

        self.assertEqual(result["encrypted_skipped"], 2)
        self.assertEqual(result["total"], 3)
        listing = str(
            self.db.execute.call_args_list[-1].args[0].compile(dialect=postgresql.dialect())
        )
        self.assertIn("execution_history.encrypted IS false", listing)

    def test_entry_carries_outputs_but_never_node_results(self) -> None:
        owning = _workflow("Owning", self.owner_id)
        target = _workflow("Target", self.owner_id)
        self._queue(owning, target, [self._entry("success")], {"success": 1})

        entry = heym_node.execute(
            _ctx({"heymOperation": "getExecutionHistory", "heymWorkflowId": str(target.id)})
        )["executions"][0]

        self.assertEqual(
            set(entry.keys()),
            {
                "id",
                "status",
                "started_at",
                "execution_time_ms",
                "trigger_source",
                "recovered",
                "inputs",
                "outputs",
            },
        )
        self.assertEqual(entry["inputs"], {"text": "go"})
        self.assertEqual(entry["outputs"], {"text": "done"})
        self.assertNotIn("node_results", entry)

    def test_limit_caps_entries_but_the_breakdown_covers_everything(self) -> None:
        owning = _workflow("Owning", self.owner_id)
        target = _workflow("Target", self.owner_id)
        # The database applies the LIMIT, so it hands back only the requested slice
        # while the breakdown query still counts all five.
        entries = [self._entry("success", i) for i in range(2)]
        self._queue(owning, target, entries, {"success": 5})

        result = heym_node.execute(
            _ctx(
                {
                    "heymOperation": "getExecutionHistory",
                    "heymWorkflowId": str(target.id),
                    "heymLimit": "2",
                }
            )
        )

        self.assertEqual(len(result["executions"]), 2)
        self.assertEqual(result["total"], 5)
        self.assertEqual(result["by_status"], {"success": 5})

    def test_history_is_bounded_in_sql_and_skips_node_results(self) -> None:
        """Regression: the whole history used to be loaded into memory and tallied in Python."""
        owning = _workflow("Owning", self.owner_id)
        target = _workflow("Target", self.owner_id)
        self._queue(owning, target, [self._entry("success")], {"success": 40000})

        heym_node.execute(
            _ctx(
                {
                    "heymOperation": "getExecutionHistory",
                    "heymWorkflowId": str(target.id),
                    "heymLimit": "1",
                    "heymStatus": "success",
                }
            )
        )

        counts_sql, _encrypted_sql, slice_sql = [
            str(call.args[0].compile(dialect=postgresql.dialect()))
            for call in self.db.execute.call_args_list[2:]
        ]
        self.assertIn("count(", counts_sql.lower())
        self.assertIn("GROUP BY", counts_sql)
        self.assertIn("LIMIT", slice_sql)
        self.assertNotIn("node_results", slice_sql)
        self.assertNotIn("node_results", counts_sql)

    def test_empty_limit_applies_no_sql_limit(self) -> None:
        owning = _workflow("Owning", self.owner_id)
        target = _workflow("Target", self.owner_id)
        self._queue(owning, target, [self._entry("success")], {"success": 1})

        heym_node.execute(
            _ctx({"heymOperation": "getExecutionHistory", "heymWorkflowId": str(target.id)})
        )

        self.assertNotIn("LIMIT", self._history_sql())

    def test_empty_limit_returns_every_entry(self) -> None:
        owning = _workflow("Owning", self.owner_id)
        target = _workflow("Target", self.owner_id)
        entries = [self._entry("success", i) for i in range(5)]
        self._queue(owning, target, entries, {"success": 5})

        result = heym_node.execute(
            _ctx({"heymOperation": "getExecutionHistory", "heymWorkflowId": str(target.id)})
        )

        self.assertEqual(len(result["executions"]), 5)

    def test_since_days_sets_the_window(self) -> None:
        owning = _workflow("Owning", self.owner_id)
        target = _workflow("Target", self.owner_id)
        self._queue(owning, target, [self._entry("success")], {"success": 1})

        result = heym_node.execute(
            _ctx(
                {
                    "heymOperation": "getExecutionHistory",
                    "heymWorkflowId": str(target.id),
                    "heymSinceDays": "7",
                }
            )
        )

        self.assertIsNotNone(result["since"])

    def test_since_days_resolved_from_a_float_still_sets_the_window(self) -> None:
        owning = _workflow("Owning", self.owner_id)
        target = _workflow("Target", self.owner_id)
        self._queue(owning, target, [self._entry("success")], {"success": 1})

        result = heym_node.execute(
            _ctx(
                {
                    "heymOperation": "getExecutionHistory",
                    "heymWorkflowId": str(target.id),
                    "heymSinceDays": "1.0",
                }
            )
        )

        self.assertIsNotNone(result["since"])

    # `heymWorkflowId` of `all` reads the history of every workflow the run's user can reach.

    def _queue_all(self, rows: list[tuple[MagicMock, str]], counts: dict[str, int]) -> None:
        """Queue the four statements the handler issues: owner, breakdown, encrypted, slice."""
        sliced = MagicMock()
        sliced.all.return_value = rows
        self.db.execute.side_effect = [
            self._scalar_one(_workflow("Owning", self.owner_id)),
            self._counts(counts),
            self._encrypted(),
            sliced,
        ]

    def _run_all(self, **extra: str) -> dict:
        data = {"heymOperation": "getExecutionHistory", "heymWorkflowId": "all", **extra}
        return heym_node.execute(_ctx(data))

    def test_all_workflows_returns_entries_labelled_with_their_workflow(self) -> None:
        first, second = self._entry("success", 2), self._entry("error", 1)
        self._queue_all([(first, "Alpha"), (second, "Beta")], {"success": 4, "error": 3})

        result = self._run_all()

        self.assertEqual(result["total"], 7)
        self.assertEqual(result["by_status"], {"success": 4, "error": 3})
        self.assertEqual([e["workflow_name"] for e in result["executions"]], ["Alpha", "Beta"])
        self.assertTrue(all("workflow_id" in e for e in result["executions"]))
        self.assertIsNone(result["workflow_id"])
        self.assertIsNone(result["workflow_name"])

    def test_all_workflows_does_not_look_up_a_single_workflow(self) -> None:
        self._queue_all([], {})

        self._run_all()

        self.assertEqual(self.db.execute.call_count, 4)

    def test_all_workflows_value_is_case_insensitive(self) -> None:
        self._queue_all([(self._entry("success"), "Alpha")], {"success": 1})

        self.assertEqual(len(self._run_all(heymWorkflowId="ALL")["executions"]), 1)

    def test_all_workflows_is_scoped_to_the_owners_workflows_and_skips_node_results(self) -> None:
        self._queue_all([(self._entry("success"), "Alpha")], {"success": 1})

        self._run_all(heymLimit="1", heymStatus="success", heymSinceDays="3")

        counts_sql, _encrypted_sql, slice_sql = [
            str(call.args[0].compile(dialect=postgresql.dialect()))
            for call in self.db.execute.call_args_list[1:]
        ]
        for sql in (counts_sql, slice_sql):
            self.assertIn("workflows.owner_id", sql)
            self.assertIn("workflows.kind", sql)
            self.assertNotIn("node_results", sql)
        self.assertIn("GROUP BY", counts_sql)
        self.assertIn("LIMIT", slice_sql)

    def test_all_workflows_empty_limit_applies_no_sql_limit(self) -> None:
        self._queue_all([(self._entry("success"), "Alpha")], {"success": 1})

        self._run_all()

        self.assertNotIn("LIMIT", self._history_sql_from(1))

    def test_get_workflow_does_not_accept_all(self) -> None:
        self.db.execute.side_effect = [self._scalar_one(_workflow("Owning", self.owner_id))]

        with self.assertRaises(ValueError) as caught:
            heym_node.execute(_ctx({"heymOperation": "getWorkflow", "heymWorkflowId": "all"}))

        self.assertIn("not found", str(caught.exception).lower())

    def _history_sql_from(self, start: int) -> str:
        return " ".join(
            str(call.args[0].compile(dialect=postgresql.dialect()))
            for call in self.db.execute.call_args_list[start:]
        )


class OperationValidationTest(HeymNodeTestBase):
    def test_missing_operation_raises(self) -> None:
        with self.assertRaises(ValueError) as caught:
            heym_node.execute(_ctx({"label": "heym"}))

        self.assertIn("operation", str(caught.exception).lower())

    def test_unknown_operation_raises(self) -> None:
        owning = _workflow("Owning", self.owner_id)
        self.db.execute.side_effect = [self._scalar_one(owning)]

        with self.assertRaises(ValueError):
            heym_node.execute(_ctx({"heymOperation": "deleteEverything"}))


class OwnerResolutionTest(HeymNodeTestBase):
    def test_unsaved_workflow_id_falls_back_to_the_actor(self) -> None:
        rows = [_workflow("Mine", self.owner_id)]
        self.db.execute.side_effect = [self._scalars(rows)]
        ctx = _ctx({"heymOperation": "listWorkflows"}, actor_user_id=uuid.uuid4())
        ctx.executor.workflow_id = None

        result = heym_node.execute(ctx)

        self.assertEqual(result["total"], 1)

    def test_no_resolvable_owner_raises_a_clear_error(self) -> None:
        ctx = _ctx({"heymOperation": "listWorkflows"})
        ctx.executor.workflow_id = None
        ctx.executor.actor_user_id = None

        with self.assertRaises(ValueError) as caught:
            heym_node.execute(ctx)

        self.assertIn("save the workflow", str(caught.exception).lower())


class RunUserScopeTest(HeymNodeTestBase):
    """Reads follow the run's user, the same user its credentials resolve for."""

    def setUp(self) -> None:
        super().setUp()
        self.collaborator_id = uuid.uuid4()
        self.subjects: list[uuid.UUID] = []

        def capture(user_id: uuid.UUID, **_kwargs: object) -> object:
            self.subjects.append(user_id)
            return true()

        patcher = patch("app.services.workflow_access.workflow_access_clause", side_effect=capture)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_a_collaborators_run_reads_with_the_collaborators_reach(self) -> None:
        """A collaborator's editor or API run must not read with the owner's reach."""
        self.db.execute.side_effect = [self._scalars([])]

        heym_node.execute(
            _ctx({"heymOperation": "listWorkflows"}, actor_user_id=self.collaborator_id)
        )

        self.assertEqual(self.subjects, [self.collaborator_id])
        self.assertNotIn(self.owner_id, self.subjects)
        # The actor decides, so the owning workflow is not even looked up.
        self.assertEqual(self.db.execute.call_count, 1)

    def test_a_collaborators_get_workflow_is_checked_against_the_collaborator(self) -> None:
        target = _workflow("Owner only", self.owner_id)
        self.db.execute.side_effect = [self._scalar_one(None)]

        with self.assertRaises(ValueError) as caught:
            heym_node.execute(
                _ctx(
                    {"heymOperation": "getWorkflow", "heymWorkflowId": str(target.id)},
                    actor_user_id=self.collaborator_id,
                )
            )

        self.assertIn("not found", str(caught.exception).lower())
        self.assertEqual(self.subjects, [self.collaborator_id])

    def test_a_collaborators_all_history_covers_only_the_collaborators_reach(self) -> None:
        counts, encrypted, sliced = MagicMock(), MagicMock(), MagicMock()
        counts.all.return_value = []
        encrypted.scalar_one.return_value = 0
        sliced.all.return_value = []
        self.db.execute.side_effect = [counts, encrypted, sliced]

        heym_node.execute(
            _ctx(
                {"heymOperation": "getExecutionHistory", "heymWorkflowId": "all"},
                actor_user_id=self.collaborator_id,
            )
        )

        self.assertEqual(self.subjects, [self.collaborator_id])

    def test_a_run_started_as_the_owner_reads_with_the_owners_reach(self) -> None:
        """Cron, portal and other triggered runs start with the owner as their actor."""
        self.db.execute.side_effect = [self._scalars([])]

        heym_node.execute(_ctx({"heymOperation": "listWorkflows"}, actor_user_id=self.owner_id))

        self.assertEqual(self.subjects, [self.owner_id])

    def test_a_run_without_an_actor_falls_back_to_the_workflow_owner(self) -> None:
        owning = _workflow("Owning", self.owner_id)
        self.db.execute.side_effect = [self._scalar_one(owning), self._scalars([])]

        heym_node.execute(_ctx({"heymOperation": "listWorkflows"}, workflow_id=owning.id))

        self.assertEqual(self.subjects, [self.owner_id])

    def test_a_run_without_an_actor_or_a_saved_workflow_refuses(self) -> None:
        self.db.execute.side_effect = [self._scalar_one(None)]

        with self.assertRaises(ValueError) as caught:
            heym_node.execute(_ctx({"heymOperation": "listWorkflows"}))

        self.assertIn("save the workflow", str(caught.exception).lower())
        self.assertEqual(self.subjects, [])
