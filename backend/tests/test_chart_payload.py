import unittest

from app.services.chart_payload import build_chart_payload


class TestBuildChartPayload(unittest.TestCase):
    def test_url_passthrough_for_bar(self):
        config = {
            "chartType": "bar",
            "labelField": "month",
            "valueField": "revenue",
            "url": "https://example.com/report",
        }
        data = [{"month": "Jan", "revenue": 120}]
        payload = build_chart_payload(config, data)
        self.assertEqual(payload["url"], "https://example.com/report")

    def test_url_passthrough_for_numeric_and_is_trimmed(self):
        config = {"chartType": "numeric", "valueField": "count", "url": "  https://example.com  "}
        data = [{"count": 5}]
        payload = build_chart_payload(config, data)
        self.assertEqual(payload["url"], "https://example.com")

    def test_no_url_key_when_missing_or_blank(self):
        for url_val in (None, "", "   "):
            config = {"chartType": "bar", "labelField": "m", "valueField": "v", "url": url_val}
            payload = build_chart_payload(config, [{"m": "Jan", "v": 1}])
            self.assertNotIn("url", payload)

    def test_no_url_key_when_non_string(self):
        config = {"chartType": "bar", "labelField": "m", "valueField": "v", "url": 123}
        payload = build_chart_payload(config, [{"m": "Jan", "v": 1}])
        self.assertNotIn("url", payload)

    def test_bar_vertical_single_series(self):
        config = {
            "chartType": "bar",
            "orientation": "vertical",
            "labelField": "month",
            "valueField": "revenue",
        }
        data = {"data": [{"month": "Jan", "revenue": 120}, {"month": "Feb", "revenue": 150}]}
        payload = build_chart_payload(config, data)
        self.assertEqual(payload["type"], "bar")
        self.assertEqual(payload["orientation"], "vertical")
        self.assertEqual(payload["labels"], ["Jan", "Feb"])
        self.assertEqual(payload["series"], [{"name": "revenue", "data": [120, 150]}])

    def test_pie_uses_label_and_value_fields(self):
        config = {"chartType": "pie", "labelField": "name", "valueField": "count"}
        data = [{"name": "A", "count": 3}, {"name": "B", "count": 7}]
        payload = build_chart_payload(config, data)
        self.assertEqual(payload["type"], "pie")
        self.assertEqual(payload["labels"], ["A", "B"])
        self.assertEqual(payload["series"], [{"name": "count", "data": [3, 7]}])

    def test_line_multi_series(self):
        config = {
            "chartType": "line",
            "labelField": "day",
            "series": [
                {"name": "Sent", "field": "sent"},
                {"name": "Failed", "field": "failed"},
            ],
        }
        data = {
            "rows": [
                {"day": "Mon", "sent": 10, "failed": 1},
                {"day": "Tue", "sent": 12, "failed": 0},
            ]
        }
        payload = build_chart_payload(config, data)
        self.assertEqual(payload["labels"], ["Mon", "Tue"])
        self.assertEqual(
            payload["series"],
            [{"name": "Sent", "data": [10, 12]}, {"name": "Failed", "data": [1, 0]}],
        )

    def test_table_default_columns_from_first_row(self):
        config = {"chartType": "table"}
        data = [{"a": 1, "b": 2}, {"a": 3, "b": 4}]
        payload = build_chart_payload(config, data)
        self.assertEqual(payload["type"], "table")
        self.assertEqual(payload["columns"], ["a", "b"])
        self.assertEqual(payload["rows"], [[1, 2], [3, 4]])

    def test_table_explicit_columns(self):
        config = {"chartType": "table", "columns": ["b"]}
        data = [{"a": 1, "b": 2}]
        payload = build_chart_payload(config, data)
        self.assertEqual(payload["columns"], ["b"])
        self.assertEqual(payload["rows"], [[2]])

    def test_numeric_reads_value_field_from_first_row(self):
        config = {"chartType": "numeric", "valueField": "total", "unit": "USD"}
        data = {"data": [{"total": 270}]}
        payload = build_chart_payload(config, data)
        self.assertEqual(payload["type"], "numeric")
        self.assertEqual(payload["value"], 270)
        self.assertEqual(payload["unit"], "USD")

    def test_numeric_scalar_input(self):
        config = {"chartType": "numeric"}
        payload = build_chart_payload(config, {"value": 42})
        self.assertEqual(payload["value"], 42)

    def test_data_path_traversal(self):
        config = {
            "chartType": "pie",
            "labelField": "k",
            "valueField": "v",
            "dataPath": "result.items",
        }
        data = {"result": {"items": [{"k": "x", "v": 1}]}}
        payload = build_chart_payload(config, data)
        self.assertEqual(payload["labels"], ["x"])

    def test_empty_data_returns_empty_payload(self):
        config = {"chartType": "bar", "labelField": "m", "valueField": "v"}
        payload = build_chart_payload(config, {})
        self.assertEqual(payload["labels"], [])
        self.assertEqual(payload["series"], [{"name": "v", "data": []}])

    def test_title_passthrough(self):
        config = {"chartType": "numeric", "valueField": "v", "title": "Total"}
        payload = build_chart_payload(config, {"data": [{"v": 1}]})
        self.assertEqual(payload["title"], "Total")

    def test_gauge_value_with_default_range(self):
        config = {"chartType": "gauge", "valueField": "cpu", "unit": "%"}
        payload = build_chart_payload(config, {"data": [{"cpu": 72}]})
        self.assertEqual(payload["type"], "gauge")
        self.assertEqual(payload["value"], 72)
        self.assertEqual(payload["min"], 0)
        self.assertEqual(payload["max"], 100)
        self.assertEqual(payload["unit"], "%")

    def test_gauge_custom_range(self):
        config = {"chartType": "gauge", "valueField": "v", "min": 10, "max": 50}
        payload = build_chart_payload(config, {"data": [{"v": 30}]})
        self.assertEqual(payload["value"], 30)
        self.assertEqual(payload["min"], 10)
        self.assertEqual(payload["max"], 50)

    def test_scatter_builds_xy_points(self):
        config = {"chartType": "scatter", "xField": "x", "yField": "y"}
        data = {"data": [{"x": 5, "y": 12}, {"x": 8, "y": 20}]}
        payload = build_chart_payload(config, data)
        self.assertEqual(payload["type"], "scatter")
        self.assertEqual(payload["series"], [{"name": "y", "data": [[5, 12], [8, 20]]}])

    def test_scatter_falls_back_to_label_value_fields(self):
        config = {"chartType": "scatter", "labelField": "a", "valueField": "b"}
        data = [{"a": 1, "b": 2}, {"a": 3, "b": 4}]
        payload = build_chart_payload(config, data)
        self.assertEqual(payload["series"], [{"name": "b", "data": [[1, 2], [3, 4]]}])

    def test_area_multi_series(self):
        config = {
            "chartType": "area",
            "labelField": "time",
            "series": [
                {"name": "Memory", "field": "memory"},
                {"name": "CPU", "field": "cpu"},
            ],
        }
        data = {"data": [{"time": "16:00", "memory": 20, "cpu": 30}]}
        payload = build_chart_payload(config, data)
        self.assertEqual(payload["type"], "area")
        self.assertEqual(payload["labels"], ["16:00"])
        self.assertEqual(
            payload["series"],
            [{"name": "Memory", "data": [20]}, {"name": "CPU", "data": [30]}],
        )

    def test_bar_gauge_with_unit_and_default_max(self):
        config = {
            "chartType": "barGauge",
            "labelField": "name",
            "valueField": "value",
            "unit": "GB",
        }
        data = {"data": [{"name": "sda1", "value": 73.1}, {"name": "sda2", "value": 71.8}]}
        payload = build_chart_payload(config, data)
        self.assertEqual(payload["type"], "barGauge")
        self.assertEqual(payload["labels"], ["sda1", "sda2"])
        self.assertEqual(payload["series"], [{"name": "value", "data": [73.1, 71.8]}])
        self.assertEqual(payload["unit"], "GB")
        self.assertNotIn("max", payload)

    def test_bar_gauge_explicit_max(self):
        config = {"chartType": "barGauge", "labelField": "name", "valueField": "value", "max": 100}
        data = [{"name": "a", "value": 40}]
        payload = build_chart_payload(config, data)
        self.assertEqual(payload["max"], 100)

    def test_proportion_uses_labels_and_single_series(self):
        config = {"chartType": "proportion", "labelField": "name", "valueField": "value"}
        data = {
            "data": [
                {"name": "Kotlin", "value": 49.64},
                {"name": "JavaScript", "value": 23.73},
            ]
        }
        payload = build_chart_payload(config, data)
        self.assertEqual(payload["type"], "proportion")
        self.assertEqual(payload["labels"], ["Kotlin", "JavaScript"])
        self.assertEqual(payload["series"], [{"name": "value", "data": [49.64, 23.73]}])

    def test_text_static_config(self):
        config = {"chartType": "text", "text": "**Last execution** at `19:47`"}
        payload = build_chart_payload(config, {})
        self.assertEqual(payload["type"], "text")
        self.assertEqual(payload["text"], "**Last execution** at `19:47`")
        self.assertTrue(payload["text_interactive"])
        self.assertNotIn("series", payload)

    def test_text_pulls_from_value_field(self):
        config = {"chartType": "text", "valueField": "message"}
        data = {"data": [{"message": "Last run at 19:47", "other": 1}]}
        payload = build_chart_payload(config, data)
        self.assertEqual(payload["type"], "text")
        self.assertEqual(payload["text"], "Last run at 19:47")
        self.assertFalse(payload["text_interactive"])

    def test_text_value_field_takes_precedence_over_static(self):
        config = {"chartType": "text", "valueField": "message", "text": "static fallback"}
        data = [{"message": "dynamic wins"}]
        payload = build_chart_payload(config, data)
        self.assertEqual(payload["text"], "dynamic wins")
        self.assertFalse(payload["text_interactive"])

    def test_text_value_field_task_list_is_interactive(self):
        checklist = "- [x] Option 1\n- [ ] Option 2\n- [ ] Option 3"
        config = {"chartType": "text", "valueField": "message"}
        data = [{"message": checklist}]
        payload = build_chart_payload(config, data)
        self.assertEqual(payload["text"], checklist)
        self.assertTrue(payload["text_interactive"])

    def test_text_falls_back_to_first_string_field(self):
        config = {"chartType": "text"}
        data = [{"count": 5, "note": "hello world"}]
        payload = build_chart_payload(config, data)
        self.assertEqual(payload["text"], "hello world")

    def test_text_empty_when_nothing_available(self):
        config = {"chartType": "text"}
        payload = build_chart_payload(config, {})
        self.assertEqual(payload["type"], "text")
        self.assertEqual(payload["text"], "")

    def test_text_scalar_string_input(self):
        config = {"chartType": "text"}
        payload = build_chart_payload(config, "just a string")
        self.assertEqual(payload["text"], "just a string")

    def test_hitl_ignores_upstream_rows(self):
        config = {"chartType": "hitl", "title": "Reviews"}
        payload = build_chart_payload(config, [{"secret": "do-not-copy"}])
        self.assertEqual(payload, {"type": "hitl", "title": "Reviews"})


class DataTableRowTests(unittest.TestCase):
    ROWS = {
        "rows": [
            {"id": "r1", "data": {"vendor": "Acme", "amount": 120}, "created_at": "2026-10-01"},
            {"id": "r2", "data": {"vendor": "Globex", "amount": 80}, "created_at": "2026-10-02"},
        ],
        "count": 2,
    }

    def test_a_table_of_data_table_rows_shows_their_columns(self) -> None:
        payload = build_chart_payload(
            {"chartType": "table", "dataPath": "rows", "columns": ["vendor", "amount"]}, self.ROWS
        )

        self.assertEqual(payload["rows"], [["Acme", 120], ["Globex", 80]])

    def test_without_columns_the_table_shows_the_id_and_every_column(self) -> None:
        payload = build_chart_payload({"chartType": "table", "dataPath": "rows"}, self.ROWS)

        self.assertEqual(payload["columns"], ["id", "vendor", "amount"])
        self.assertEqual(payload["rows"][0], ["r1", "Acme", 120])

    def test_a_bar_chart_names_data_table_columns(self) -> None:
        payload = build_chart_payload(
            {
                "chartType": "bar",
                "dataPath": "rows",
                "labelField": "vendor",
                "valueField": "amount",
            },
            self.ROWS,
        )

        self.assertEqual(payload["labels"], ["Acme", "Globex"])

    def test_other_rows_with_a_data_key_are_left_as_they_are(self) -> None:
        rows = [{"name": "a", "data": {"x": 1}}, {"id": "b", "data": [1, 2]}]

        payload = build_chart_payload({"chartType": "table"}, rows)

        self.assertEqual(payload["columns"], ["name", "data"])
        self.assertEqual(payload["rows"][0], ["a", {"x": 1}])
