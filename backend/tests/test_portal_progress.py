import unittest

from app.services.portal_progress import PortalProgressTracker, compact_portal_progress_path


class PortalProgressTests(unittest.TestCase):
    def test_compact_portal_progress_path_collapses_repeated_loop_segments(self) -> None:
        node_labels = [
            "fetchWaitingList",
            "initArray",
            *(
                [
                    "processRecords",
                    "createRecordMarkdown",
                    "addToMarkdownArray",
                ]
                * 68
            ),
            "output",
        ]

        self.assertEqual(
            compact_portal_progress_path(node_labels),
            [
                "fetchWaitingList",
                "initArray",
                "processRecords(68)",
                "createRecordMarkdown(68)",
                "addToMarkdownArray(68)",
                "output",
            ],
        )

    def test_portal_progress_tracker_enriches_node_start_events(self) -> None:
        tracker = PortalProgressTracker()

        sequence = [
            "fetchWaitingList",
            "initArray",
            "processRecords",
            "createRecordMarkdown",
            "addToMarkdownArray",
            "processRecords",
            "createRecordMarkdown",
            "addToMarkdownArray",
            "output",
        ]

        last_event: dict[str, object] = {}
        for label in sequence:
            last_event = tracker.observe_event(
                {
                    "type": "node_start",
                    "node_id": label,
                    "node_label": label,
                }
            )

        self.assertEqual(
            last_event.get("progress_path"),
            [
                "fetchWaitingList",
                "initArray",
                "processRecords(2)",
                "createRecordMarkdown(2)",
                "addToMarkdownArray(2)",
                "output",
            ],
        )

    def test_portal_progress_tracker_leaves_other_events_unchanged(self) -> None:
        tracker = PortalProgressTracker()
        event = {"type": "execution_complete", "status": "success"}

        self.assertIs(tracker.observe_event(event), event)
