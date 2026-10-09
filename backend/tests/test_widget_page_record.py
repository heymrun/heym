"""AI-built widgets read `$page.record` as the plain value it is, never as an object."""

import unittest

from app.services.widget_page_record import (
    detail_page_context,
    example_record,
    repair_page_record_paths,
)
from app.services.workflow_executor import WorkflowExecutor


class RepairPageRecordPathsTests(unittest.TestCase):
    def test_fields_of_the_record_are_dropped(self) -> None:
        cases = {
            '{"vendor_id": "$page.record.id"}': '{"vendor_id": "$page.record"}',
            "$page.record.vendor_id": "$page.record",
            "$page.record.data.vendor_id": "$page.record",
            "Vendor $page.record.id.": "Vendor $page.record.",
            "$page.record.id.upper()": "$page.record.upper()",
        }
        for written, repaired in cases.items():
            self.assertEqual(repair_page_record_paths(written), repaired, written)

    def test_what_a_string_has_and_other_paths_stay(self) -> None:
        for kept in (
            "$page.record",
            "$page.record.length",
            "$page.record.upper()",
            "$page.record.replace('-', '')",
            "$vendor.record.id",
            "$findVendor.rows.first().id",
        ):
            self.assertEqual(repair_page_record_paths(kept), kept)

    def test_every_string_in_the_nodes_is_repaired(self) -> None:
        nodes = [
            {
                "id": "find",
                "type": "dataTable",
                "position": {"x": 0, "y": 0},
                "data": {
                    "dataTableFilter": '{"vendor_id": "$page.record.id"}',
                    "dataTableLimit": 1,
                    "mappings": [{"key": "vendor", "value": "$page.record.vendor_id"}],
                },
            }
        ]

        repaired = repair_page_record_paths(nodes)

        self.assertEqual(repaired[0]["data"]["dataTableFilter"], '{"vendor_id": "$page.record"}')
        self.assertEqual(repaired[0]["data"]["mappings"][0]["value"], "$page.record")
        self.assertEqual(repaired[0]["data"]["dataTableLimit"], 1)
        self.assertEqual(nodes[0]["data"]["dataTableFilter"], '{"vendor_id": "$page.record.id"}')

    def test_the_repaired_filter_finds_the_record_in_a_run(self) -> None:
        executor = WorkflowExecutor(nodes=[], edges=[], test_mode=True)
        executor.page_params = {"record": "V-1002"}
        written = '{\n  "vendor_id": "$page.record.id"\n}'

        self.assertIn("$page.record.id", executor.evaluate_message_template(written, {}))
        self.assertEqual(
            executor.evaluate_message_template(repair_page_record_paths(written), {}),
            '{\n  "vendor_id": "V-1002"\n}',
        )


class DetailPageContextTests(unittest.TestCase):
    def test_the_first_record_a_cached_table_shows(self) -> None:
        payload = {
            "type": "table",
            "columns": ["name", "vendor_id"],
            "rows": [["A", " "], ["B", "V-2"]],
        }

        self.assertEqual(example_record(payload, "vendor_id"), "V-2")
        self.assertIsNone(example_record(payload, "missing"))
        self.assertIsNone(example_record({"type": "bar"}, "vendor_id"))
        self.assertIsNone(example_record(None, "vendor_id"))

    def test_the_model_is_told_the_record_column_and_how_to_filter_by_it(self) -> None:
        context = detail_page_context(["vendor_id"], "V-1001")

        self.assertIn("row's vendor_id value as $page.record", context)
        self.assertIn('such as "V-1001"', context)
        self.assertIn("rows whose vendor_id equals $page.record", context)
        self.assertIn('{"vendor_id": "$page.record"}', context)
        self.assertIn("Never write $page.record.id", context)

    def test_several_record_columns_and_none(self) -> None:
        self.assertIn("vendor_id or code value", detail_page_context(["vendor_id", "code"], None))
        self.assertNotIn("such as", detail_page_context(["vendor_id"], None))
        self.assertEqual(detail_page_context([], "V-1"), "")


if __name__ == "__main__":
    unittest.main()
