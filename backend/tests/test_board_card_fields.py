"""Typed card fields inside card_metadata: normalize, read, merge, version, filter."""

import unittest
import uuid
from datetime import date

from app.services import board_card_fields as f


class NormalizeTests(unittest.TestCase):
    def test_labels_are_trimmed_and_deduplicated_case_insensitively(self) -> None:
        self.assertEqual(f.normalize_labels([" Acme ", "acme", "NDA", ""]), ["Acme", "NDA"])

    def test_too_many_or_too_long_labels_are_refused(self) -> None:
        with self.assertRaises(f.CardFieldError):
            f.normalize_labels([f"l{i}" for i in range(11)])
        with self.assertRaises(f.CardFieldError):
            f.normalize_labels(["x" * 41])


class ReadFieldsTests(unittest.TestCase):
    def test_reads_valid_values_and_ignores_broken_ones(self) -> None:
        user_id = uuid.uuid4()
        workflow_id = uuid.uuid4()
        values = f.read_fields(
            {
                "assignee_user_id": str(user_id),
                "priority": "urgent",
                "due_date": "2026-11-10",
                "labels": ["Acme"],
                "links": [{"workflow_id": str(workflow_id)}, {"workflow_id": "nope"}],
            }
        )
        self.assertEqual(values.assignee_user_id, user_id)
        self.assertEqual(values.priority, "urgent")
        self.assertEqual(values.due_date, date(2026, 11, 10))
        self.assertEqual(values.labels, ("Acme",))
        self.assertEqual(values.links, (f.CardLinkValue(workflow_id),))

    def test_garbage_reads_as_empty(self) -> None:
        values = f.read_fields({"priority": "whenever", "due_date": "soon", "labels": "x"})
        self.assertEqual(values, f.CardFieldValues())
        self.assertEqual(f.read_fields(None), f.CardFieldValues())

    def test_links_round_trip_through_metadata(self) -> None:
        link = f.CardLinkValue(uuid.uuid4(), uuid.uuid4())
        stored = f.links_to_metadata([link])
        self.assertEqual(f.read_fields({"links": stored}).links, (link,))


class MergeTests(unittest.TestCase):
    def test_updates_change_only_named_keys_and_none_clears(self) -> None:
        existing = {"attachments": [{"file_id": "a"}], "priority": "low", "custom": 1}
        merged = f.merge_metadata(existing, updates={"priority": None, "labels": ["Acme"]})
        self.assertEqual(
            merged, {"attachments": [{"file_id": "a"}], "custom": 1, "labels": ["Acme"]}
        )

    def test_a_raw_write_cannot_drop_reserved_keys(self) -> None:
        existing = {"attachments": [{"file_id": "a"}], "priority": "high", "custom": 1}
        merged = f.merge_metadata(existing, raw={"custom": 2, "priority": "low"}, updates={})
        self.assertEqual(
            merged, {"custom": 2, "attachments": [{"file_id": "a"}], "priority": "high"}
        )


class EditVersionTests(unittest.TestCase):
    def test_changes_with_user_fields_only(self) -> None:
        base = f.edit_version("T", "C", {"priority": "low", "attachments": [1]})
        self.assertEqual(base, f.edit_version("T", "C", {"priority": "low", "attachments": [2]}))
        self.assertNotEqual(base, f.edit_version("T", "C", {"priority": "high"}))
        self.assertNotEqual(base, f.edit_version("T2", "C", {"priority": "low"}))


class FilterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.me = uuid.uuid4()
        self.today = date(2026, 11, 5)
        self.column = uuid.uuid4()

    def match(self, card_filter: f.CardFilter, values: f.CardFieldValues, **kw) -> bool:
        return card_filter.matches(
            values,
            column_id=kw.get("column_id", self.column),
            run_status=kw.get("run_status", "idle"),
            user_id=self.me,
            today=self.today,
        )

    def test_assignee_me_and_unassigned(self) -> None:
        mine = f.CardFieldValues(assignee_user_id=self.me)
        self.assertTrue(self.match(f.CardFilter(assignee="me"), mine))
        self.assertFalse(self.match(f.CardFilter(assignee="unassigned"), mine))
        self.assertTrue(self.match(f.CardFilter(assignee="unassigned"), f.CardFieldValues()))
        self.assertTrue(self.match(f.CardFilter(assignee=str(self.me)), mine))
        self.assertFalse(self.match(f.CardFilter(assignee="not-a-uuid"), mine))

    def test_due_windows(self) -> None:
        overdue = f.CardFieldValues(due_date=date(2026, 11, 4))
        today = f.CardFieldValues(due_date=self.today)
        later = f.CardFieldValues(due_date=date(2026, 11, 12))
        self.assertTrue(self.match(f.CardFilter(due="overdue"), overdue))
        self.assertFalse(self.match(f.CardFilter(due="overdue"), today))
        self.assertTrue(self.match(f.CardFilter(due="today"), today))
        self.assertTrue(self.match(f.CardFilter(due="week"), today))
        self.assertFalse(self.match(f.CardFilter(due="week"), later))
        self.assertFalse(self.match(f.CardFilter(due="week"), f.CardFieldValues()))

    def test_overdue_skips_done_column(self) -> None:
        overdue = f.CardFieldValues(due_date=date(2026, 11, 1))
        done = uuid.uuid4()
        card_filter = f.CardFilter(due="overdue", done_column_ids=frozenset({done}))
        self.assertFalse(self.match(card_filter, overdue, column_id=done))

    def test_priority_label_column_and_run_status(self) -> None:
        values = f.CardFieldValues(priority="high", labels=("Acme",))
        self.assertTrue(self.match(f.CardFilter(priority="high", label="acme"), values))
        self.assertFalse(self.match(f.CardFilter(priority="low"), values))
        self.assertFalse(self.match(f.CardFilter(column_ids=frozenset({uuid.uuid4()})), values))
        self.assertTrue(
            self.match(f.CardFilter(run_status="pending"), values, run_status="pending")
        )
        self.assertFalse(self.match(f.CardFilter(run_status="pending"), values))
