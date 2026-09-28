"""Data table handling for workflows the chat builder generates."""

import unittest
import uuid
from typing import Any

from app.services.data_table_catalog import CatalogColumn, CatalogDataTable
from app.services.generated_data_tables import (
    DataTableChoice,
    DataTableNeed,
    DataTablePassResult,
    DataTableWarning,
    apply_generated_data_tables,
    data_table_warnings_payload,
    format_data_table_choices,
    parse_data_table_choices,
    requires_data_table_payload,
    resolve_data_table,
)

LEAD_COLUMNS = (CatalogColumn("email", "string", unique=True), CatalogColumn("name", "string"))
LEADS = CatalogDataTable(uuid.uuid4(), "leads", "Website leads", "owner", None, LEAD_COLUMNS)
ARCHIVE = CatalogDataTable(uuid.uuid4(), "archive", None, "owner", None, LEAD_COLUMNS)
ORDERS = CatalogDataTable(
    uuid.uuid4(), "orders", None, "read", "ops", (CatalogColumn("sku", "string"),)
)
CATALOG = [LEADS, ARCHIVE, ORDERS]


def _node(
    table: str | None = None,
    *,
    operation: str = "insert",
    data: str = '{"email": "$form.email"}',
    node_id: str = "save",
    label: str = "saveLead",
) -> dict[str, Any]:
    fields: dict[str, Any] = {
        "label": label,
        "dataTableOperation": operation,
        "dataTableData": data,
    }
    if table is not None:
        fields["dataTableId"] = table
    return {"id": node_id, "type": "dataTable", "position": {"x": 0, "y": 0}, "data": fields}


def _run(
    nodes: list[dict[str, Any]],
    *,
    choices: list[DataTableChoice] | None = None,
    previous: list[dict[str, Any]] | None = None,
) -> DataTablePassResult:
    return apply_generated_data_tables(
        nodes, catalog=CATALOG, choices=choices or [], previous_nodes=previous
    )


def _table_id(result: DataTablePassResult) -> object:
    return result.nodes[0]["data"].get("dataTableId")


class ResolveTests(unittest.TestCase):
    def test_an_id_resolves_in_any_case(self) -> None:
        self.assertEqual(resolve_data_table(str(LEADS.id), CATALOG), LEADS)
        self.assertEqual(resolve_data_table(str(LEADS.id).upper(), CATALOG), LEADS)

    def test_an_exact_name_resolves_and_the_owned_table_wins_a_shared_twin(self) -> None:
        twin = CatalogDataTable(uuid.uuid4(), "leads", None, "write", "ops", LEAD_COLUMNS)

        self.assertEqual(resolve_data_table("leads", [twin, LEADS]), LEADS)

    def test_a_name_two_shared_tables_carry_is_ambiguous(self) -> None:
        first = CatalogDataTable(uuid.uuid4(), "shared", None, "write", "a", LEAD_COLUMNS)
        second = CatalogDataTable(uuid.uuid4(), "shared", None, "write", "b", LEAD_COLUMNS)

        self.assertIsNone(resolve_data_table("shared", [first, second]))

    def test_placeholders_and_other_values_do_not_resolve(self) -> None:
        for value in ("datatable-uuid", "Leads", str(uuid.uuid4()), "", None, 42):
            self.assertIsNone(resolve_data_table(value, CATALOG))


class ApplyTests(unittest.TestCase):
    def test_a_catalog_id_is_kept(self) -> None:
        result = _run([_node(str(LEADS.id))])

        self.assertEqual(_table_id(result), str(LEADS.id))
        self.assertEqual(result.needs, [])

    def test_an_exact_name_becomes_its_id(self) -> None:
        self.assertEqual(_table_id(_run([_node("leads")])), str(LEADS.id))

    def test_a_placeholder_is_cleared_and_becomes_a_need(self) -> None:
        result = _run([_node("datatable-uuid")])

        self.assertEqual(_table_id(result), "")
        self.assertEqual(result.needs, [DataTableNeed("saveLead", "insert", True)])

    def test_a_read_only_table_is_cleared_for_writing_but_kept_for_reading(self) -> None:
        writing = _run([_node(str(ORDERS.id))])
        reading = _run([_node(str(ORDERS.id), operation="find", data="")])

        self.assertEqual(_table_id(writing), "")
        self.assertEqual(_table_id(reading), str(ORDERS.id))

    def test_a_single_fitting_choice_fills_an_empty_new_node(self) -> None:
        result = _run([_node("")], choices=[DataTableChoice(str(LEADS.id))])

        self.assertEqual(_table_id(result), str(LEADS.id))
        self.assertEqual(result.needs, [])

    def test_two_fitting_choices_do_not_guess(self) -> None:
        result = _run([_node("")], choices=[DataTableChoice("leads"), DataTableChoice("archive")])

        self.assertEqual(_table_id(result), "")
        self.assertEqual(len(result.needs), 1)

    def test_a_leave_empty_choice_saves_the_node_without_a_need(self) -> None:
        result = _run([_node("datatable-uuid")], choices=[DataTableChoice("")])

        self.assertEqual(_table_id(result), "")
        self.assertEqual(result.needs, [])

    def test_an_unchanged_existing_node_keeps_its_value(self) -> None:
        missing = str(uuid.uuid4())

        result = _run([_node(missing)], previous=[_node(missing)])

        self.assertEqual(_table_id(result), missing)
        self.assertEqual(result.needs, [])

    def test_an_existing_node_matched_by_label_reverts_a_broken_value(self) -> None:
        previous = [_node(str(LEADS.id), node_id="old-id")]

        result = _run([_node("datatable-uuid", node_id="new-id")], previous=previous)

        self.assertEqual(_table_id(result), str(LEADS.id))
        self.assertEqual(result.needs, [])

    def test_other_node_types_are_untouched(self) -> None:
        http = {"id": "h", "type": "http", "data": {"label": "call", "dataTableId": "x"}}

        self.assertEqual(_run([http]).nodes, [http])


class ColumnWarningTests(unittest.TestCase):
    def test_keys_the_table_lacks_are_reported(self) -> None:
        result = _run([_node("leads", data='{"email": "$f.email", "phone": "$f.phone"}')])

        self.assertEqual(result.warnings, [DataTableWarning("saveLead", "leads", ("phone",))])

    def test_row_metadata_keys_are_allowed_in_filters(self) -> None:
        node = _node("leads", operation="find", data="")
        node["data"]["dataTableFilter"] = '{"created_at": {"$gt": "2026-06-01"}, "email": "a"}'

        self.assertEqual(_run([node]).warnings, [])

    def test_templates_that_are_not_json_are_skipped(self) -> None:
        self.assertEqual(_run([_node("leads", data='{"email": $form.email}')]).warnings, [])

    def test_a_json_object_value_is_checked_too(self) -> None:
        node = _node("leads")
        node["data"]["dataTableData"] = {"email": "$f.email", "age": "$f.age"}

        self.assertEqual(_run([node]).warnings[0].unknown_columns, ("age",))


class ChoiceAndPayloadTests(unittest.TestCase):
    def test_choices_parse_ids_names_and_leave_empty(self) -> None:
        raw = [
            {"table_id": " leads "},
            {"table_id": ""},
            {"name": "x"},
            "leads",
            {"table_id": None},
        ]

        self.assertEqual(
            parse_data_table_choices(raw), [DataTableChoice("leads"), DataTableChoice("")]
        )
        self.assertEqual(parse_data_table_choices("leads"), [])

    def test_choices_render_as_builder_instructions(self) -> None:
        text = format_data_table_choices(
            [DataTableChoice("leads"), DataTableChoice(""), DataTableChoice("nope")], CATALOG
        )

        self.assertIn(
            f"- `leads` (id `{LEADS.id}`), columns: email string unique, name string", text
        )
        self.assertIn("- leave the table empty", text)
        self.assertIn("`nope` is not one of the user's tables", text)
        self.assertEqual(format_data_table_choices([], CATALOG), "")

    def test_requires_payload_names_each_node_and_operation(self) -> None:
        payload = requires_data_table_payload([DataTableNeed("saveLead", "insert", True)])

        self.assertEqual(payload["status"], "requires_data_table")
        self.assertEqual(
            payload["needs"], [{"node": "saveLead", "operation": "insert", "writes": True}]
        )
        self.assertIn("data_table_choices", payload["instructions"])

    def test_warnings_payload_is_empty_without_warnings(self) -> None:
        self.assertEqual(data_table_warnings_payload([]), {})
        payload = data_table_warnings_payload([DataTableWarning("saveLead", "leads", ("phone",))])
        self.assertEqual(
            payload["data_table_warnings"],
            [{"node": "saveLead", "table": "leads", "unknown_columns": ["phone"]}],
        )
        self.assertIn("DataTable tab", payload["data_table_warnings_note"])


if __name__ == "__main__":
    unittest.main()
