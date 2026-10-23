"""HITL widget source filter: which steps wait, and the filter on the widget's chart node."""

import uuid
from unittest import TestCase

from app.services import slack_operations
from app.services.hitl_widget_filter import (
    WAITING_SLACK_OPERATIONS,
    HitlWidgetFilter,
    ReviewStep,
    hitl_filter_changed,
    hitl_widget_filter,
    pending_for_widgets,
    review_step_kind,
    review_steps,
    with_hitl_widget_filter,
)


def _agent(node_id: str, label: str, *, hitl: bool = True) -> dict:
    return {"id": node_id, "type": "agent", "data": {"label": label, "hitlEnabled": hitl}}


def _slack(node_id: str, label: str, operation: str | None) -> dict:
    data: dict = {"label": label}
    if operation is not None:
        data["slackOperation"] = operation
    return {"id": node_id, "type": "slack", "data": data}


def _chart(**data: object) -> dict:
    return {"id": "chart", "type": "chartOutput", "data": {"label": "reviews", **data}}


class ReviewStepTest(TestCase):
    def test_waiting_slack_operations_match_the_slack_node(self) -> None:
        self.assertEqual(WAITING_SLACK_OPERATIONS, slack_operations.WAITING_OPERATIONS)

    def test_agent_waits_only_with_hitl_enabled(self) -> None:
        self.assertEqual(review_step_kind(_agent("a1", "Approver")), "agent")
        self.assertIsNone(review_step_kind(_agent("a2", "Writer", hitl=False)))

    def test_slack_waits_only_on_approval_buttons_and_forms(self) -> None:
        for operation in ("requestApproval", "sendButtons", "sendForm"):
            self.assertEqual(review_step_kind(_slack("s1", "Ask", operation)), "slack")
        self.assertIsNone(review_step_kind(_slack("s2", "Post", "sendMessage")))
        self.assertIsNone(review_step_kind(_slack("s3", "Default", None)))

    def test_codex_and_other_nodes_are_not_review_steps(self) -> None:
        self.assertIsNone(review_step_kind({"id": "c1", "type": "codex", "data": {}}))
        self.assertIsNone(review_step_kind({"id": "x", "type": "set", "data": {}}))
        self.assertIsNone(review_step_kind("not a node"))

    def test_review_steps_lists_id_label_and_kind_in_graph_order(self) -> None:
        nodes = [
            _agent("a1", "Approver"),
            {"id": "x", "type": "set", "data": {"label": "data"}},
            _slack("s1", "Ask finance", "requestApproval"),
            {"id": "", "type": "agent", "data": {"hitlEnabled": True}},
        ]
        self.assertEqual(
            review_steps(nodes),
            [
                ReviewStep("a1", "Approver", "agent"),
                ReviewStep("s1", "Ask finance", "slack"),
            ],
        )

    def test_a_step_without_a_label_is_named_by_its_id(self) -> None:
        node = {"id": "a9", "type": "agent", "data": {"hitlEnabled": True}}
        self.assertEqual(review_steps([node]), [ReviewStep("a9", "a9", "agent")])

    def test_review_steps_tolerates_a_graph_that_is_not_a_list(self) -> None:
        self.assertEqual(review_steps(None), [])
        self.assertEqual(review_steps({"nodes": []}), [])


class WidgetFilterTest(TestCase):
    def test_reads_workflow_and_step_from_the_hitl_chart(self) -> None:
        workflow_id = uuid.uuid4()
        nodes = [
            _chart(chartType="hitl", hitlWorkflowId=str(workflow_id), hitlNodeId="a1"),
        ]
        self.assertEqual(hitl_widget_filter(nodes), HitlWidgetFilter(workflow_id, "a1"))

    def test_workflow_alone_means_every_step(self) -> None:
        workflow_id = uuid.uuid4()
        nodes = [_chart(chartType="hitl", hitlWorkflowId=str(workflow_id), hitlNodeId="  ")]
        self.assertEqual(hitl_widget_filter(nodes), HitlWidgetFilter(workflow_id, None))

    def test_no_filter_without_a_valid_workflow_id(self) -> None:
        self.assertIsNone(hitl_widget_filter([_chart(chartType="hitl")]))
        self.assertIsNone(hitl_widget_filter([_chart(chartType="hitl", hitlNodeId="a1")]))
        self.assertIsNone(
            hitl_widget_filter([_chart(chartType="hitl", hitlWorkflowId="not-a-uuid")])
        )

    def test_a_chart_that_is_not_hitl_has_no_filter(self) -> None:
        nodes = [_chart(chartType="bar", hitlWorkflowId=str(uuid.uuid4()))]
        self.assertIsNone(hitl_widget_filter(nodes))
        self.assertIsNone(hitl_widget_filter(None))

    def test_with_filter_sets_both_fields_on_a_copy(self) -> None:
        workflow_id = uuid.uuid4()
        other = {"id": "x", "type": "set", "data": {"label": "data"}}
        nodes = [other, _chart(chartType="hitl")]

        updated = with_hitl_widget_filter(nodes, HitlWidgetFilter(workflow_id, "a1"))

        self.assertNotIn("hitlWorkflowId", nodes[1]["data"])
        self.assertEqual(updated[0], other)
        self.assertEqual(updated[1]["data"]["hitlWorkflowId"], str(workflow_id))
        self.assertEqual(updated[1]["data"]["hitlNodeId"], "a1")

    def test_with_filter_for_every_step_drops_the_step(self) -> None:
        workflow_id = uuid.uuid4()
        nodes = [_chart(chartType="hitl", hitlWorkflowId=str(uuid.uuid4()), hitlNodeId="a1")]

        updated = with_hitl_widget_filter(nodes, HitlWidgetFilter(workflow_id))

        self.assertEqual(updated[0]["data"]["hitlWorkflowId"], str(workflow_id))
        self.assertNotIn("hitlNodeId", updated[0]["data"])

    def test_with_no_filter_clears_both_fields(self) -> None:
        nodes = [_chart(chartType="hitl", hitlWorkflowId=str(uuid.uuid4()), hitlNodeId="a1")]

        updated = with_hitl_widget_filter(nodes, None)

        self.assertEqual(updated[0]["data"], {"label": "reviews", "chartType": "hitl"})

    def test_changed_compares_the_filters_not_the_graphs(self) -> None:
        workflow_id = str(uuid.uuid4())
        before = [_chart(chartType="hitl", hitlWorkflowId=workflow_id)]
        moved = [{**before[0], "position": {"x": 40, "y": 0}}]
        retargeted = [_chart(chartType="hitl", hitlWorkflowId=workflow_id, hitlNodeId="a1")]

        self.assertFalse(hitl_filter_changed(before, moved))
        self.assertTrue(hitl_filter_changed(before, retargeted))
        self.assertTrue(hitl_filter_changed(before, [_chart(chartType="hitl")]))


class PendingForWidgetsTest(TestCase):
    def setUp(self) -> None:
        self.invoices = uuid.uuid4()
        self.hiring = uuid.uuid4()
        self.shared = uuid.uuid4()
        # The viewer's own queue, which an unfiltered widget shows.
        self.own = {
            (self.invoices, "approver"): 3,
            (self.invoices, "finance"): 2,
            (self.hiring, "screen"): 4,
        }
        # The filtered workflows the viewer can open, owned or shared with them.
        self.chosen = {
            (self.invoices, "approver"): 3,
            (self.invoices, "finance"): 2,
            (self.shared, "legal"): 6,
        }

    def test_an_unfiltered_widget_counts_the_own_queue(self) -> None:
        self.assertEqual(pending_for_widgets(self.own, {}, [None]), 9)

    def test_a_workflow_filter_counts_all_its_steps(self) -> None:
        filters = [HitlWidgetFilter(self.invoices)]
        self.assertEqual(pending_for_widgets(self.own, self.chosen, filters), 5)

    def test_a_step_filter_counts_that_step(self) -> None:
        filters = [HitlWidgetFilter(self.invoices, "finance")]
        self.assertEqual(pending_for_widgets(self.own, self.chosen, filters), 2)

    def test_a_shared_workflow_counts_its_reviews_next_to_the_own_queue(self) -> None:
        filters = [None, HitlWidgetFilter(self.shared)]
        self.assertEqual(pending_for_widgets(self.own, self.chosen, filters), 15)

    def test_overlapping_widgets_count_a_review_once(self) -> None:
        filters = [
            None,
            HitlWidgetFilter(self.invoices),
            HitlWidgetFilter(self.invoices, "approver"),
        ]
        self.assertEqual(pending_for_widgets(self.own, self.chosen, filters), 9)

    def test_a_workflow_the_viewer_cannot_open_adds_nothing(self) -> None:
        filters = [HitlWidgetFilter(uuid.uuid4()), HitlWidgetFilter(self.shared, "legal")]
        self.assertEqual(pending_for_widgets(self.own, self.chosen, filters), 6)

    def test_no_widgets_count_nothing(self) -> None:
        self.assertEqual(pending_for_widgets(self.own, self.chosen, []), 0)
