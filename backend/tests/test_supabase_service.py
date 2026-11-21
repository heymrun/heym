"""Unit tests for SupabaseService and the Supabase executor branch."""

import unittest
from unittest.mock import MagicMock, patch

import httpx


def _make_config() -> dict:
    """Return a minimal Supabase credential config."""
    return {
        "supabase_url": "https://example.supabase.co",
        "supabase_key": "sb-secret-key",
        "supabase_schema": "public",
    }


def _params_to_dict(params) -> dict:
    """Normalize httpx params call arguments for assertions."""
    if isinstance(params, dict):
        return params
    return {key: value for key, value in params}


def _passthrough_client() -> MagicMock:
    """Return an injected client that preserves the module-level HTTP mocks."""
    client = MagicMock(spec=httpx.Client)
    client.get.side_effect = lambda *args, **kwargs: httpx.get(*args, **kwargs)
    client.request.side_effect = lambda *args, **kwargs: httpx.request(*args, **kwargs)
    return client


class TestSupabaseService(unittest.TestCase):
    def _make_service(self):
        from app.services.supabase_service import SupabaseService

        return SupabaseService(_make_config(), client=_passthrough_client())

    def test_select_rows_returns_rows_and_count(self) -> None:
        svc = self._make_service()
        mock_response = MagicMock()
        mock_response.is_success = True
        mock_response.headers = {"content-range": "0-1/2"}
        mock_response.json.return_value = [{"id": 1, "name": "Alice"}, {"id": 2, "name": "Bob"}]
        with patch("httpx.request", return_value=mock_response) as mock_request:
            result = svc.select_rows(
                "users",
                columns="id,name",
                filters={"active": True},
                limit=2,
                order_by="created_at",
                ascending=False,
            )
        self.assertTrue(result["success"])
        self.assertEqual(result["count"], 2)
        self.assertEqual(len(result["rows"]), 2)
        self.assertEqual(mock_request.call_args[0][0], "GET")
        params = _params_to_dict(mock_request.call_args[1]["params"])
        self.assertEqual(params["select"], "id,name")
        self.assertEqual(params["active"], "eq.true")
        self.assertEqual(params["order"], "created_at.desc")

    def test_insert_rows_returns_inserted_rows(self) -> None:
        svc = self._make_service()
        mock_response = MagicMock()
        mock_response.is_success = True
        mock_response.json.return_value = [{"id": 1, "name": "Alice"}]
        with patch("httpx.request", return_value=mock_response) as mock_request:
            result = svc.insert_rows("users", [{"name": "Alice"}])
        self.assertTrue(result["success"])
        self.assertEqual(result["count"], 1)
        self.assertEqual(mock_request.call_args[0][0], "POST")
        self.assertEqual(mock_request.call_args[1]["json"], [{"name": "Alice"}])

    def test_insert_requires_at_least_one_row(self) -> None:
        svc = self._make_service()
        with self.assertRaises(ValueError) as ctx:
            svc.insert_rows("users", [])
        self.assertIn("at least one row", str(ctx.exception))

    def test_select_rows_uses_schema_and_count_headers(self) -> None:
        svc = self._make_service()
        mock_response = MagicMock()
        mock_response.is_success = True
        mock_response.headers = {}
        mock_response.json.return_value = [{"id": 1}]
        with patch("httpx.request", return_value=mock_response) as mock_request:
            result = svc.select_rows("users", schema="private", limit=0)
        headers = mock_request.call_args[1]["headers"]
        params = _params_to_dict(mock_request.call_args[1]["params"])
        self.assertEqual(headers["Accept-Profile"], "private")
        self.assertEqual(headers["Prefer"], "count=exact")
        self.assertEqual(params["limit"], "1000")
        self.assertEqual(result["count"], 1)

    def test_select_rows_clamps_negative_limit_to_default(self) -> None:
        svc = self._make_service()
        mock_response = MagicMock()
        mock_response.is_success = True
        mock_response.headers = {}
        mock_response.json.return_value = []
        with patch("httpx.request", return_value=mock_response) as mock_request:
            svc.select_rows("users", limit=-5)
        params = _params_to_dict(mock_request.call_args[1]["params"])
        self.assertEqual(params["limit"], "100")

    def test_select_rows_paginates_when_limit_exceeds_page_size(self) -> None:
        svc = self._make_service()

        first_response = MagicMock()
        first_response.is_success = True
        first_response.headers = {"content-range": "0-999/1200"}
        first_response.json.return_value = [{"id": i} for i in range(1000)]

        second_response = MagicMock()
        second_response.is_success = True
        second_response.headers = {"content-range": "1000-1199/1200"}
        second_response.json.return_value = [{"id": i} for i in range(1000, 1200)]

        with patch("httpx.request", side_effect=[first_response, second_response]) as mock_request:
            result = svc.select_rows("users", limit=1200)

        self.assertEqual(mock_request.call_count, 2)
        first_params = _params_to_dict(mock_request.call_args_list[0][1]["params"])
        second_params = _params_to_dict(mock_request.call_args_list[1][1]["params"])
        self.assertEqual(first_params["limit"], "1000")
        self.assertEqual(second_params["limit"], "200")
        self.assertEqual(second_params["offset"], "1000")
        self.assertEqual(len(result["rows"]), 1200)
        self.assertEqual(result["count"], 1200)

    def test_select_rows_limit_zero_fetches_all_pages(self) -> None:
        svc = self._make_service()

        first_response = MagicMock()
        first_response.is_success = True
        first_response.headers = {"content-range": "0-999/1500"}
        first_response.json.return_value = [{"id": i} for i in range(1000)]

        second_response = MagicMock()
        second_response.is_success = True
        second_response.headers = {"content-range": "1000-1499/1500"}
        second_response.json.return_value = [{"id": i} for i in range(1000, 1500)]

        with patch("httpx.request", side_effect=[first_response, second_response]) as mock_request:
            result = svc.select_rows("users", limit=0)

        self.assertEqual(mock_request.call_count, 2)
        first_params = _params_to_dict(mock_request.call_args_list[0][1]["params"])
        second_params = _params_to_dict(mock_request.call_args_list[1][1]["params"])
        self.assertEqual(first_params["limit"], "1000")
        self.assertEqual(second_params["limit"], "1000")
        self.assertEqual(second_params["offset"], "1000")
        self.assertEqual(len(result["rows"]), 1500)
        self.assertEqual(result["count"], 1500)

    def test_select_rows_encodes_null_filter(self) -> None:
        svc = self._make_service()
        mock_response = MagicMock()
        mock_response.is_success = True
        mock_response.headers = {}
        mock_response.json.return_value = []
        with patch("httpx.request", return_value=mock_response) as mock_request:
            svc.select_rows("users", filters={"deleted_at": None})
        params = _params_to_dict(mock_request.call_args[1]["params"])
        self.assertEqual(params["deleted_at"], "is.null")

    def test_select_rows_sends_top_level_string_filters_verbatim(self) -> None:
        # PostgREST removes double quotes only inside in-lists and or/and groups; a
        # top-level eq."alice.smith@example.com" compares with the quotes and matches nothing.
        svc = self._make_service()
        mock_response = MagicMock()
        mock_response.is_success = True
        mock_response.headers = {}
        mock_response.json.return_value = []
        with patch("httpx.request", return_value=mock_response) as mock_request:
            svc.select_rows(
                "users",
                filters={
                    "email": "alice.smith@example.com",
                    "display_name": 'Alice "Admin", Inc.',
                },
            )
        params = _params_to_dict(mock_request.call_args[1]["params"])
        self.assertEqual(params["email"], "eq.alice.smith@example.com")
        self.assertEqual(params["display_name"], 'eq.Alice "Admin", Inc.')

    def test_select_rows_quotes_hyphenated_values_only_inside_in_lists(self) -> None:
        svc = self._make_service()
        mock_response = MagicMock()
        mock_response.is_success = True
        mock_response.headers = {}
        mock_response.json.return_value = []
        with patch("httpx.request", return_value=mock_response) as mock_request:
            svc.select_rows(
                "users",
                filters={
                    "external_id": "user-123",
                    "status": {"in": ["trial-user", "active"]},
                },
            )
        params = _params_to_dict(mock_request.call_args[1]["params"])
        self.assertEqual(params["external_id"], "eq.user-123")
        self.assertEqual(params["status"], 'in.("trial-user",active)')

    def test_select_rows_supports_operator_filters(self) -> None:
        svc = self._make_service()
        mock_response = MagicMock()
        mock_response.is_success = True
        mock_response.headers = {}
        mock_response.json.return_value = []
        with patch("httpx.request", return_value=mock_response) as mock_request:
            svc.select_rows(
                "users",
                filters={
                    "score": {"gte": 10},
                    "status": {"in": ["active", "paused"]},
                    "email": {"ilike": "*@example.com"},
                },
            )
        params = _params_to_dict(mock_request.call_args[1]["params"])
        self.assertEqual(params["score"], "gte.10")
        self.assertEqual(params["status"], "in.(active,paused)")
        self.assertEqual(params["email"], "ilike.*@example.com")

    def test_select_rows_supports_logical_groups(self) -> None:
        svc = self._make_service()
        mock_response = MagicMock()
        mock_response.is_success = True
        mock_response.headers = {}
        mock_response.json.return_value = []
        with patch("httpx.request", return_value=mock_response) as mock_request:
            svc.select_rows(
                "users",
                filters={
                    "or": [
                        {"status": "active"},
                        {"status": "pending", "score": {"gte": 5}},
                    ]
                },
            )
        params = _params_to_dict(mock_request.call_args[1]["params"])
        self.assertEqual(
            params["or"],
            "(status.eq.active,and(status.eq.pending,score.gte.5))",
        )

    def test_select_rows_keeps_quotes_inside_logical_groups(self) -> None:
        svc = self._make_service()
        mock_response = MagicMock()
        mock_response.is_success = True
        mock_response.headers = {}
        mock_response.json.return_value = []
        with patch("httpx.request", return_value=mock_response) as mock_request:
            svc.select_rows(
                "users",
                filters={
                    "or": [{"email": "a.b@example.com"}, {"name": "John Smith"}],
                    "team": "core-team",
                },
            )
        params = _params_to_dict(mock_request.call_args[1]["params"])
        self.assertEqual(params["or"], '(email.eq."a.b@example.com",name.eq."John Smith")')
        self.assertEqual(params["team"], "eq.core-team")

    def test_select_rows_sends_an_empty_top_level_string_as_empty(self) -> None:
        svc = self._make_service()
        mock_response = MagicMock()
        mock_response.is_success = True
        mock_response.headers = {}
        mock_response.json.return_value = []
        with patch("httpx.request", return_value=mock_response) as mock_request:
            svc.select_rows("users", filters={"nickname": ""})
        params = _params_to_dict(mock_request.call_args[1]["params"])
        self.assertEqual(params["nickname"], "eq.")

    def test_update_and_delete_send_top_level_string_filters_verbatim(self) -> None:
        # An update or delete filtered on a quoted value matched no row and reported
        # success with count 0.
        svc = self._make_service()
        mock_response = MagicMock()
        mock_response.is_success = True
        mock_response.headers = {}
        mock_response.json.return_value = []
        with patch("httpx.request", return_value=mock_response) as mock_request:
            svc.update_rows("users", {"plan": "pro"}, filters={"email": "a.b@example.com"})
            svc.delete_rows("users", filters={"name": {"neq": "John Smith"}})
        update_params = _params_to_dict(mock_request.call_args_list[0][1]["params"])
        delete_params = _params_to_dict(mock_request.call_args_list[1][1]["params"])
        self.assertEqual(update_params["email"], "eq.a.b@example.com")
        self.assertEqual(delete_params["name"], "neq.John Smith")

    def test_select_rows_rejects_unsupported_filter_operator(self) -> None:
        svc = self._make_service()
        with self.assertRaises(ValueError) as ctx:
            svc.select_rows("users", filters={"score": {"between": [1, 2]}})
        self.assertIn("unsupported", str(ctx.exception).lower())

    def test_update_requires_filters(self) -> None:
        svc = self._make_service()
        with self.assertRaises(ValueError) as ctx:
            svc.update_rows("users", {"name": "Alice"}, filters={})
        self.assertIn("requires at least one filter", str(ctx.exception))

    def test_update_requires_at_least_one_data_field(self) -> None:
        svc = self._make_service()
        with self.assertRaises(ValueError) as ctx:
            svc.update_rows("users", {}, filters={"id": 1})
        self.assertIn("at least one data field", str(ctx.exception))

    def test_delete_requires_filters(self) -> None:
        svc = self._make_service()
        with self.assertRaises(ValueError) as ctx:
            svc.delete_rows("users", filters={})
        self.assertIn("requires at least one filter", str(ctx.exception))

    def test_update_rows_returns_updated_rows(self) -> None:
        svc = self._make_service()
        mock_response = MagicMock()
        mock_response.is_success = True
        mock_response.json.return_value = [{"id": 1, "name": "Updated"}]
        with patch("httpx.request", return_value=mock_response) as mock_request:
            result = svc.update_rows("users", {"name": "Updated"}, filters={"id": 1}, schema="app")
        headers = mock_request.call_args[1]["headers"]
        params = _params_to_dict(mock_request.call_args[1]["params"])
        self.assertEqual(mock_request.call_args[0][0], "PATCH")
        self.assertEqual(headers["Content-Profile"], "app")
        self.assertEqual(headers["Prefer"], "return=representation")
        self.assertEqual(params["id"], "eq.1")
        self.assertEqual(result["count"], 1)

    def test_delete_rows_returns_deleted_rows(self) -> None:
        svc = self._make_service()
        mock_response = MagicMock()
        mock_response.is_success = True
        mock_response.json.return_value = [{"id": 1}]
        with patch("httpx.request", return_value=mock_response) as mock_request:
            result = svc.delete_rows("users", filters={"id": 1})
        headers = mock_request.call_args[1]["headers"]
        params = _params_to_dict(mock_request.call_args[1]["params"])
        self.assertEqual(mock_request.call_args[0][0], "DELETE")
        self.assertEqual(headers["Prefer"], "return=representation")
        self.assertEqual(params["id"], "eq.1")
        self.assertEqual(result["count"], 1)

    def test_upsert_rows_sets_merge_duplicates_prefer_header(self) -> None:
        svc = self._make_service()
        mock_response = MagicMock()
        mock_response.is_success = True
        mock_response.json.return_value = [{"id": 1}]
        with patch("httpx.request", return_value=mock_response) as mock_request:
            result = svc.insert_rows("users", [{"id": 1}], upsert=True)
        headers = mock_request.call_args[1]["headers"]
        self.assertIn("resolution=merge-duplicates", headers["Prefer"])
        self.assertEqual(result["count"], 1)

    def test_upsert_rows_passes_on_conflict_parameter(self) -> None:
        svc = self._make_service()
        mock_response = MagicMock()
        mock_response.is_success = True
        mock_response.json.return_value = [{"id": 1}]
        with patch("httpx.request", return_value=mock_response) as mock_request:
            svc.insert_rows("users", [{"id": 1}], upsert=True, on_conflict="tenant_id,email")
        params = _params_to_dict(mock_request.call_args[1]["params"])
        self.assertEqual(params["on_conflict"], "tenant_id,email")

    def test_service_strips_whitespace_from_supabase_url(self) -> None:
        from app.services.supabase_service import SupabaseService

        svc = SupabaseService(
            {
                "supabase_url": "https://example.supabase.co/  ",
                "supabase_key": "sb-secret-key",
            },
            client=_passthrough_client(),
        )
        with patch("httpx.get") as mock_get:
            mock_response = MagicMock()
            mock_response.is_success = True
            mock_response.status_code = 200
            mock_get.return_value = mock_response
            svc.test_connection()
        self.assertEqual(
            mock_get.call_args[0][0],
            "https://example.supabase.co/rest/v1/",
        )

    def test_select_rows_limit_zero_rejects_excessive_total(self) -> None:
        svc = self._make_service()
        mock_response = MagicMock()
        mock_response.is_success = True
        mock_response.headers = {"content-range": "0-999/15000"}
        mock_response.json.return_value = [{"id": i} for i in range(1000)]
        with patch("httpx.request", return_value=mock_response):
            with self.assertRaises(ValueError) as ctx:
                svc.select_rows("users", limit=0)
        self.assertIn("15000 rows", str(ctx.exception))
        self.assertIn("10000", str(ctx.exception))

    def test_service_requires_non_empty_supabase_url(self) -> None:
        from app.services.supabase_service import SupabaseService

        with self.assertRaises(ValueError) as ctx:
            SupabaseService(
                {
                    "supabase_url": "",
                    "supabase_key": "sb-secret-key",
                }
            )
        self.assertIn("supabase_url", str(ctx.exception))

    def test_service_requires_non_empty_supabase_key(self) -> None:
        from app.services.supabase_service import SupabaseService

        with self.assertRaises(ValueError) as ctx:
            SupabaseService(
                {
                    "supabase_url": "https://example.supabase.co",
                    "supabase_key": "  ",
                }
            )
        self.assertIn("supabase_key", str(ctx.exception))

    def test_test_connection_succeeds_on_postgrest_root(self) -> None:
        svc = self._make_service()
        mock_response = MagicMock()
        mock_response.is_success = True
        mock_response.status_code = 200
        with patch("httpx.get", return_value=mock_response) as mock_get:
            svc.test_connection()
        self.assertEqual(
            mock_get.call_args[0][0],
            "https://example.supabase.co/rest/v1/",
        )
        headers = mock_get.call_args[1]["headers"]
        self.assertEqual(headers["apikey"], "sb-secret-key")
        self.assertEqual(headers["Authorization"], "Bearer sb-secret-key")

    def test_test_connection_rejects_invalid_api_key(self) -> None:
        svc = self._make_service()
        mock_response = MagicMock()
        mock_response.is_success = False
        mock_response.status_code = 401
        mock_response.text = "Unauthorized"
        mock_response.json.side_effect = ValueError()
        with patch("httpx.get", return_value=mock_response):
            with self.assertRaises(ValueError) as ctx:
                svc.test_connection()
        self.assertIn("invalid or unauthorized", str(ctx.exception))

    def test_test_connection_raises_readable_error_for_other_failures(self) -> None:
        svc = self._make_service()
        mock_response = MagicMock()
        mock_response.is_success = False
        mock_response.status_code = 503
        mock_response.text = "service unavailable"
        mock_response.json.return_value = {"message": "upstream timeout"}
        with patch("httpx.get", return_value=mock_response):
            with self.assertRaises(ValueError) as ctx:
                svc.test_connection()
        self.assertIn("upstream timeout", str(ctx.exception))

    def test_error_payload_is_raised_cleanly(self) -> None:
        svc = self._make_service()
        mock_response = MagicMock()
        mock_response.is_success = False
        mock_response.status_code = 400
        mock_response.text = "bad request"
        mock_response.json.return_value = {"message": "invalid filter"}
        with patch("httpx.request", return_value=mock_response):
            with self.assertRaises(ValueError) as ctx:
                svc.select_rows("users")
        self.assertIn("invalid filter", str(ctx.exception))

    def test_select_rows_rejects_non_list_response(self) -> None:
        svc = self._make_service()
        mock_response = MagicMock()
        mock_response.is_success = True
        mock_response.headers = {}
        mock_response.json.return_value = {"id": 1}
        with patch("httpx.request", return_value=mock_response):
            with self.assertRaises(ValueError) as ctx:
                svc.select_rows("users")
        self.assertIn("non-list response", str(ctx.exception))

    def test_insert_rows_rejects_non_list_response(self) -> None:
        svc = self._make_service()
        mock_response = MagicMock()
        mock_response.is_success = True
        mock_response.json.return_value = {"id": 1}
        with patch("httpx.request", return_value=mock_response):
            with self.assertRaises(ValueError) as ctx:
                svc.insert_rows("users", [{"id": 1}])
        self.assertIn("non-list response", str(ctx.exception))

    def test_select_rows_surfaces_transport_errors_cleanly(self) -> None:
        svc = self._make_service()
        with patch("httpx.request", side_effect=httpx.ConnectTimeout("timed out")):
            with self.assertRaises(ValueError) as ctx:
                svc.select_rows("users")
        self.assertIn("select failed", str(ctx.exception).lower())

    def test_list_tables_discovers_table_paths_only(self) -> None:
        svc = self._make_service()
        with patch.object(
            svc,
            "_openapi_root",
            return_value={
                "paths": {
                    "/": {},
                    "/users": {},
                    "/profiles": {},
                    "/rpc/search_users": {},
                    "/bad-name": {},
                }
            },
        ) as mock_openapi_root:
            result = svc.list_tables(schema="app")
        self.assertTrue(result["success"])
        self.assertEqual(result["tables"], ["profiles", "users"])
        mock_openapi_root.assert_called_once_with("app")

    def test_list_columns_discovers_definition_properties(self) -> None:
        svc = self._make_service()
        with patch.object(
            svc,
            "_openapi_root",
            return_value={
                "definitions": {
                    "users": {
                        "properties": {
                            "id": {"type": "integer"},
                            "email": {"type": "string"},
                        }
                    }
                }
            },
        ) as mock_openapi_root:
            result = svc.list_columns("users", schema="app")
        self.assertTrue(result["success"])
        self.assertEqual(result["columns"], ["id", "email"])
        mock_openapi_root.assert_called_once_with("app")

    def test_parse_json_rows_requires_array_of_objects(self) -> None:
        from app.services.supabase_service import SupabaseService

        with self.assertRaises(ValueError):
            SupabaseService.parse_json_rows('{"id":1}', "supabaseRows")

    def test_parse_json_object_requires_object(self) -> None:
        from app.services.supabase_service import SupabaseService

        with self.assertRaises(ValueError):
            SupabaseService.parse_json_object('[{"id":1}]', "supabaseFilter")

    def test_parse_json_rows_rejects_non_object_items(self) -> None:
        from app.services.supabase_service import SupabaseService

        with self.assertRaises(ValueError):
            SupabaseService.parse_json_rows("[1,2,3]", "supabaseRows")

    def test_normalize_auto_map_rows_uses_rows_payload(self) -> None:
        from app.services.supabase_service import SupabaseService

        rows = SupabaseService.normalize_auto_map_rows(
            {"rows": [{"id": 1, "name": "Alice"}], "count": 1},
            ignored_fields={"id"},
        )
        self.assertEqual(rows, [{"name": "Alice"}])

    def test_normalize_auto_map_rows_accepts_single_object(self) -> None:
        from app.services.supabase_service import SupabaseService

        rows = SupabaseService.normalize_auto_map_rows({"id": 1, "name": "Alice"})
        self.assertEqual(rows, [{"id": 1, "name": "Alice"}])

    def test_normalize_auto_map_object_requires_single_object(self) -> None:
        from app.services.supabase_service import SupabaseService

        with self.assertRaises(ValueError):
            SupabaseService.normalize_auto_map_object([{"id": 1}, {"id": 2}])

    def test_select_rows_rejects_non_table_paths(self) -> None:
        svc = self._make_service()
        with self.assertRaises(ValueError) as ctx:
            svc.select_rows("rpc/list_users")
        self.assertIn("simple table name", str(ctx.exception))


def _make_supabase_workflow(supabase_data: dict) -> tuple:
    """Build a minimal workflow: textInput → supabase → output."""
    nodes = [
        {
            "id": "start",
            "type": "textInput",
            "position": {"x": 0, "y": 0},
            "data": {"label": "start", "value": "hello", "inputFields": [{"key": "text"}]},
        },
        {
            "id": "supa",
            "type": "supabase",
            "position": {"x": 200, "y": 0},
            "data": {"label": "supaNode", **supabase_data},
        },
        {
            "id": "out",
            "type": "output",
            "position": {"x": 400, "y": 0},
            "data": {"label": "out", "message": "$supaNode", "allowDownstream": False},
        },
    ]
    edges = [
        {"id": "e1", "source": "start", "target": "supa"},
        {"id": "e2", "source": "supa", "target": "out"},
    ]
    return nodes, edges, {"text": "hello"}


class TestSupabaseExecutorBranch(unittest.TestCase):
    """Test the workflow executor Supabase branch via full WorkflowExecutor.execute()."""

    def setUp(self) -> None:
        from app.services import ssrf_guard

        patcher = patch.object(ssrf_guard.settings, "http_allow_private_urls", True)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(ssrf_guard.close_guarded_http_client)

    def _run_with_mocked_credential(self, supabase_data: dict):
        import uuid as _uuid

        from app.services.workflow_executor import WorkflowExecutor

        nodes, edges, inputs = _make_supabase_workflow(supabase_data)
        with patch("app.db.session.SessionLocal") as mock_session:
            mock_db = MagicMock()
            mock_db.__enter__ = MagicMock(return_value=mock_db)
            mock_db.__exit__ = MagicMock(return_value=False)
            mock_db.query.return_value.filter.return_value.first.return_value = MagicMock(
                encrypted_config="{}"
            )
            mock_session.return_value = mock_db
            with patch("app.services.encryption.decrypt_config", return_value=_make_config()):
                executor = WorkflowExecutor(
                    nodes=nodes,
                    edges=edges,
                    actor_user_id=_uuid.uuid4(),
                )
                return executor.execute(workflow_id=_uuid.uuid4(), initial_inputs=inputs)

    def test_missing_credential_results_in_error(self) -> None:
        import uuid as _uuid

        from app.services.workflow_executor import WorkflowExecutor

        nodes, edges, inputs = _make_supabase_workflow(
            {"credentialId": "", "supabaseOperation": "select", "supabaseTable": "users"}
        )
        executor = WorkflowExecutor(nodes=nodes, edges=edges)
        result = executor.execute(workflow_id=_uuid.uuid4(), initial_inputs=inputs)
        self.assertEqual(result.status, "error")
        supa_result = next((r for r in result.node_results if r["node_label"] == "supaNode"), None)
        self.assertIsNotNone(supa_result)
        self.assertIn("credential", supa_result.get("error", "").lower())

    def test_missing_operation_results_in_error(self) -> None:
        result = self._run_with_mocked_credential(
            {"credentialId": "cred-1", "supabaseOperation": "", "supabaseTable": "users"}
        )
        self.assertEqual(result.status, "error")
        supa_result = next((r for r in result.node_results if r["node_label"] == "supaNode"), None)
        self.assertIsNotNone(supa_result)
        self.assertIn("operation", supa_result.get("error", "").lower())

    def test_missing_table_results_in_error(self) -> None:
        result = self._run_with_mocked_credential(
            {"credentialId": "cred-1", "supabaseOperation": "select", "supabaseTable": "   "}
        )
        self.assertEqual(result.status, "error")
        supa_result = next((r for r in result.node_results if r["node_label"] == "supaNode"), None)
        self.assertIsNotNone(supa_result)
        self.assertIn("table", supa_result.get("error", "").lower())

    def test_invalid_filter_json_results_in_error(self) -> None:
        result = self._run_with_mocked_credential(
            {
                "credentialId": "cred-1",
                "supabaseOperation": "select",
                "supabaseTable": "users",
                "supabaseFilter": "{invalid",
            }
        )
        self.assertEqual(result.status, "error")
        supa_result = next((r for r in result.node_results if r["node_label"] == "supaNode"), None)
        self.assertIsNotNone(supa_result)
        self.assertIn("invalid json", supa_result.get("error", "").lower())

    def test_invalid_update_data_json_results_in_error(self) -> None:
        result = self._run_with_mocked_credential(
            {
                "credentialId": "cred-1",
                "supabaseOperation": "update",
                "supabaseTable": "users",
                "supabaseData": "{invalid",
                "supabaseFilter": '{"id": 1}',
            }
        )
        self.assertEqual(result.status, "error")
        supa_result = next((r for r in result.node_results if r["node_label"] == "supaNode"), None)
        self.assertIsNotNone(supa_result)
        self.assertIn("supabasedata", supa_result.get("error", "").lower())

    def test_empty_update_data_results_in_error(self) -> None:
        result = self._run_with_mocked_credential(
            {
                "credentialId": "cred-1",
                "supabaseOperation": "update",
                "supabaseTable": "users",
                "supabaseData": "{}",
                "supabaseFilter": '{"id": 1}',
            }
        )
        self.assertEqual(result.status, "error")
        supa_result = next((r for r in result.node_results if r["node_label"] == "supaNode"), None)
        self.assertIsNotNone(supa_result)
        self.assertIn("at least one data field", supa_result.get("error", "").lower())

    def test_missing_credential_config_results_in_error(self) -> None:
        import uuid as _uuid

        from app.services.workflow_executor import WorkflowExecutor

        nodes, edges, inputs = _make_supabase_workflow(
            {
                "credentialId": "cred-1",
                "supabaseOperation": "select",
                "supabaseTable": "users",
            }
        )
        with patch("app.db.session.SessionLocal") as mock_session:
            mock_db = MagicMock()
            mock_db.__enter__ = MagicMock(return_value=mock_db)
            mock_db.__exit__ = MagicMock(return_value=False)
            mock_db.query.return_value.filter.return_value.first.return_value = MagicMock(
                encrypted_config="{}"
            )
            mock_session.return_value = mock_db
            with patch("app.services.encryption.decrypt_config", return_value={}):
                executor = WorkflowExecutor(
                    nodes=nodes,
                    edges=edges,
                    actor_user_id=_uuid.uuid4(),
                )
                result = executor.execute(workflow_id=_uuid.uuid4(), initial_inputs=inputs)
        self.assertEqual(result.status, "error")
        supa_result = next((r for r in result.node_results if r["node_label"] == "supaNode"), None)
        self.assertIsNotNone(supa_result)
        self.assertIn("credential not found or invalid", supa_result.get("error", "").lower())

    def test_select_operation_calls_service(self) -> None:
        import uuid as _uuid

        from app.services.workflow_executor import WorkflowExecutor

        nodes, edges, inputs = _make_supabase_workflow(
            {
                "credentialId": "cred-1",
                "supabaseOperation": "select",
                "supabaseSchema": "public",
                "supabaseTable": "users",
                "supabaseSelectColumns": "id,name",
                "supabaseFilter": '{"active": true}',
                "supabaseLimit": "25",
                "supabaseOrderBy": "created_at",
                "supabaseAscending": False,
            }
        )
        expected_output = {"rows": [{"id": 1}], "count": 1, "success": True}
        with patch("app.db.session.SessionLocal") as mock_session:
            mock_db = MagicMock()
            mock_db.__enter__ = MagicMock(return_value=mock_db)
            mock_db.__exit__ = MagicMock(return_value=False)
            mock_db.query.return_value.filter.return_value.first.return_value = MagicMock(
                encrypted_config="{}"
            )
            mock_session.return_value = mock_db
            with patch("app.services.encryption.decrypt_config", return_value=_make_config()):
                with patch(
                    "app.services.supabase_service.SupabaseService.select_rows",
                    return_value=expected_output,
                ) as mock_select:
                    executor = WorkflowExecutor(
                        nodes=nodes,
                        edges=edges,
                        actor_user_id=_uuid.uuid4(),
                    )
                    result = executor.execute(workflow_id=_uuid.uuid4(), initial_inputs=inputs)
        mock_select.assert_called_once_with(
            "users",
            schema="public",
            columns="id,name",
            filters={"active": True},
            limit=25,
            order_by="created_at",
            ascending=False,
        )
        self.assertEqual(result.status, "success")

    def test_blank_schema_falls_back_to_credential_default(self) -> None:
        import uuid as _uuid

        from app.services.workflow_executor import WorkflowExecutor

        nodes, edges, inputs = _make_supabase_workflow(
            {
                "credentialId": "cred-1",
                "supabaseOperation": "select",
                "supabaseSchema": "",
                "supabaseTable": "users",
            }
        )
        credential_config = _make_config() | {"supabase_schema": "app"}
        with patch("app.db.session.SessionLocal") as mock_session:
            mock_db = MagicMock()
            mock_db.__enter__ = MagicMock(return_value=mock_db)
            mock_db.__exit__ = MagicMock(return_value=False)
            mock_db.query.return_value.filter.return_value.first.return_value = MagicMock(
                encrypted_config="{}"
            )
            mock_session.return_value = mock_db
            with patch("app.services.encryption.decrypt_config", return_value=credential_config):
                with patch(
                    "app.services.supabase_service.SupabaseService.select_rows",
                    return_value={"rows": [], "count": 0, "success": True},
                ) as mock_select:
                    executor = WorkflowExecutor(
                        nodes=nodes,
                        edges=edges,
                        actor_user_id=_uuid.uuid4(),
                    )
                    result = executor.execute(workflow_id=_uuid.uuid4(), initial_inputs=inputs)
        self.assertEqual(result.status, "success")
        self.assertEqual(mock_select.call_args[1]["schema"], "app")

    def test_select_operation_clamps_negative_limit(self) -> None:
        import uuid as _uuid

        from app.services.workflow_executor import WorkflowExecutor

        nodes, edges, inputs = _make_supabase_workflow(
            {
                "credentialId": "cred-1",
                "supabaseOperation": "select",
                "supabaseTable": "users",
                "supabaseLimit": "-5",
            }
        )
        with patch("app.db.session.SessionLocal") as mock_session:
            mock_db = MagicMock()
            mock_db.__enter__ = MagicMock(return_value=mock_db)
            mock_db.__exit__ = MagicMock(return_value=False)
            mock_db.query.return_value.filter.return_value.first.return_value = MagicMock(
                encrypted_config="{}"
            )
            mock_session.return_value = mock_db
            with patch("app.services.encryption.decrypt_config", return_value=_make_config()):
                with patch(
                    "app.services.supabase_service.SupabaseService.select_rows",
                    return_value={"rows": [], "count": 0, "success": True},
                ) as mock_select:
                    executor = WorkflowExecutor(
                        nodes=nodes,
                        edges=edges,
                        actor_user_id=_uuid.uuid4(),
                    )
                    result = executor.execute(workflow_id=_uuid.uuid4(), initial_inputs=inputs)
        self.assertEqual(result.status, "success")
        self.assertEqual(mock_select.call_args[1]["limit"], 100)

    def test_invalid_table_path_results_in_error(self) -> None:
        result = self._run_with_mocked_credential(
            {
                "credentialId": "cred-1",
                "supabaseOperation": "select",
                "supabaseTable": "rpc/list_users",
            }
        )
        self.assertEqual(result.status, "error")
        supa_result = next((r for r in result.node_results if r["node_label"] == "supaNode"), None)
        self.assertIsNotNone(supa_result)
        self.assertIn("simple table name", supa_result.get("error", "").lower())

    def test_upsert_operation_calls_service(self) -> None:
        import uuid as _uuid

        from app.services.workflow_executor import WorkflowExecutor

        nodes, edges, inputs = _make_supabase_workflow(
            {
                "credentialId": "cred-1",
                "supabaseOperation": "upsert",
                "supabaseTable": "users",
                "supabaseRows": '[{"id": 1, "name": "Alice"}]',
            }
        )
        with patch("app.db.session.SessionLocal") as mock_session:
            mock_db = MagicMock()
            mock_db.__enter__ = MagicMock(return_value=mock_db)
            mock_db.__exit__ = MagicMock(return_value=False)
            mock_db.query.return_value.filter.return_value.first.return_value = MagicMock(
                encrypted_config="{}"
            )
            mock_session.return_value = mock_db
            with patch("app.services.encryption.decrypt_config", return_value=_make_config()):
                with patch(
                    "app.services.supabase_service.SupabaseService.insert_rows",
                    return_value={"rows": [{"id": 1}], "count": 1, "success": True},
                ) as mock_insert:
                    executor = WorkflowExecutor(
                        nodes=nodes,
                        edges=edges,
                        actor_user_id=_uuid.uuid4(),
                    )
                    result = executor.execute(workflow_id=_uuid.uuid4(), initial_inputs=inputs)
        mock_insert.assert_called_once_with(
            "users",
            [{"id": 1, "name": "Alice"}],
            schema="public",
            upsert=True,
            on_conflict="",
        )
        self.assertEqual(result.status, "success")

    def test_insert_operation_with_empty_rows_results_in_error(self) -> None:
        result = self._run_with_mocked_credential(
            {
                "credentialId": "cred-1",
                "supabaseOperation": "insert",
                "supabaseTable": "users",
                "supabaseRows": "[]",
            }
        )
        self.assertEqual(result.status, "error")
        supa_result = next((r for r in result.node_results if r["node_label"] == "supaNode"), None)
        self.assertIsNotNone(supa_result)
        self.assertIn("at least one row", supa_result.get("error", "").lower())

    def test_upsert_operation_with_empty_rows_results_in_error(self) -> None:
        result = self._run_with_mocked_credential(
            {
                "credentialId": "cred-1",
                "supabaseOperation": "upsert",
                "supabaseTable": "users",
                "supabaseRows": "[]",
            }
        )
        self.assertEqual(result.status, "error")
        supa_result = next((r for r in result.node_results if r["node_label"] == "supaNode"), None)
        self.assertIsNotNone(supa_result)
        self.assertIn("at least one row", supa_result.get("error", "").lower())

    def test_upsert_operation_passes_on_conflict(self) -> None:
        import uuid as _uuid

        from app.services.workflow_executor import WorkflowExecutor

        nodes, edges, inputs = _make_supabase_workflow(
            {
                "credentialId": "cred-1",
                "supabaseOperation": "upsert",
                "supabaseTable": "users",
                "supabaseRows": '[{"id": 1, "email": "alice@example.com"}]',
                "supabaseOnConflict": "tenant_id,email",
            }
        )
        with patch("app.db.session.SessionLocal") as mock_session:
            mock_db = MagicMock()
            mock_db.__enter__ = MagicMock(return_value=mock_db)
            mock_db.__exit__ = MagicMock(return_value=False)
            mock_db.query.return_value.filter.return_value.first.return_value = MagicMock(
                encrypted_config="{}"
            )
            mock_session.return_value = mock_db
            with patch("app.services.encryption.decrypt_config", return_value=_make_config()):
                with patch(
                    "app.services.supabase_service.SupabaseService.insert_rows",
                    return_value={"rows": [{"id": 1}], "count": 1, "success": True},
                ) as mock_insert:
                    executor = WorkflowExecutor(
                        nodes=nodes,
                        edges=edges,
                        actor_user_id=_uuid.uuid4(),
                    )
                    result = executor.execute(workflow_id=_uuid.uuid4(), initial_inputs=inputs)
        self.assertEqual(result.status, "success")
        self.assertEqual(mock_insert.call_args[1]["on_conflict"], "tenant_id,email")

    def test_insert_operation_calls_service(self) -> None:
        import uuid as _uuid

        from app.services.workflow_executor import WorkflowExecutor

        nodes, edges, inputs = _make_supabase_workflow(
            {
                "credentialId": "cred-1",
                "supabaseOperation": "insert",
                "supabaseTable": "users",
                "supabaseRows": '[{"name": "Alice"}]',
            }
        )
        with patch("app.db.session.SessionLocal") as mock_session:
            mock_db = MagicMock()
            mock_db.__enter__ = MagicMock(return_value=mock_db)
            mock_db.__exit__ = MagicMock(return_value=False)
            mock_db.query.return_value.filter.return_value.first.return_value = MagicMock(
                encrypted_config="{}"
            )
            mock_session.return_value = mock_db
            with patch("app.services.encryption.decrypt_config", return_value=_make_config()):
                with patch(
                    "app.services.supabase_service.SupabaseService.insert_rows",
                    return_value={
                        "rows": [{"id": 1, "name": "Alice"}],
                        "count": 1,
                        "success": True,
                    },
                ) as mock_insert:
                    executor = WorkflowExecutor(
                        nodes=nodes,
                        edges=edges,
                        actor_user_id=_uuid.uuid4(),
                    )
                    result = executor.execute(workflow_id=_uuid.uuid4(), initial_inputs=inputs)
        mock_insert.assert_called_once_with(
            "users",
            [{"name": "Alice"}],
            schema="public",
            upsert=False,
        )
        self.assertEqual(result.status, "success")

    def test_insert_auto_map_uses_single_upstream_object(self) -> None:
        import uuid as _uuid

        from app.services.workflow_executor import WorkflowExecutor

        nodes, edges, inputs = _make_supabase_workflow(
            {
                "credentialId": "cred-1",
                "supabaseOperation": "insert",
                "supabaseTable": "users",
                "supabaseRowsInputMode": "auto",
                "supabaseIgnoredInputFields": "ignored",
            }
        )
        inputs = {"text": "hello", "ignored": "drop-me"}
        with patch("app.db.session.SessionLocal") as mock_session:
            mock_db = MagicMock()
            mock_db.__enter__ = MagicMock(return_value=mock_db)
            mock_db.__exit__ = MagicMock(return_value=False)
            mock_db.query.return_value.filter.return_value.first.return_value = MagicMock(
                encrypted_config="{}"
            )
            mock_session.return_value = mock_db
            with patch("app.services.encryption.decrypt_config", return_value=_make_config()):
                with patch(
                    "app.services.supabase_service.SupabaseService.insert_rows",
                    return_value={"rows": [{"text": "hello"}], "count": 1, "success": True},
                ) as mock_insert:
                    executor = WorkflowExecutor(
                        nodes=nodes,
                        edges=edges,
                        actor_user_id=_uuid.uuid4(),
                    )
                    result = executor.execute(workflow_id=_uuid.uuid4(), initial_inputs=inputs)
        self.assertEqual(result.status, "success")
        mock_insert.assert_called_once_with(
            "users",
            [{"text": "hello"}],
            schema="public",
            upsert=False,
        )

    def test_update_operation_calls_service(self) -> None:
        import uuid as _uuid

        from app.services.workflow_executor import WorkflowExecutor

        nodes, edges, inputs = _make_supabase_workflow(
            {
                "credentialId": "cred-1",
                "supabaseOperation": "update",
                "supabaseTable": "users",
                "supabaseData": '{"name": "Updated"}',
                "supabaseFilter": '{"id": 1}',
            }
        )
        with patch("app.db.session.SessionLocal") as mock_session:
            mock_db = MagicMock()
            mock_db.__enter__ = MagicMock(return_value=mock_db)
            mock_db.__exit__ = MagicMock(return_value=False)
            mock_db.query.return_value.filter.return_value.first.return_value = MagicMock(
                encrypted_config="{}"
            )
            mock_session.return_value = mock_db
            with patch("app.services.encryption.decrypt_config", return_value=_make_config()):
                with patch(
                    "app.services.supabase_service.SupabaseService.update_rows",
                    return_value={"rows": [{"id": 1}], "count": 1, "success": True},
                ) as mock_update:
                    executor = WorkflowExecutor(
                        nodes=nodes,
                        edges=edges,
                        actor_user_id=_uuid.uuid4(),
                    )
                    result = executor.execute(workflow_id=_uuid.uuid4(), initial_inputs=inputs)
        mock_update.assert_called_once_with(
            "users",
            {"name": "Updated"},
            schema="public",
            filters={"id": 1},
        )
        self.assertEqual(result.status, "success")

    def test_update_auto_map_uses_single_upstream_object(self) -> None:
        import uuid as _uuid

        from app.services.workflow_executor import WorkflowExecutor

        nodes, edges, inputs = _make_supabase_workflow(
            {
                "credentialId": "cred-1",
                "supabaseOperation": "update",
                "supabaseTable": "users",
                "supabaseDataInputMode": "auto",
                "supabaseIgnoredInputFields": "id",
                "supabaseFilter": '{"id": 1}',
            }
        )
        inputs = {"id": 1, "status": "processed"}
        with patch("app.db.session.SessionLocal") as mock_session:
            mock_db = MagicMock()
            mock_db.__enter__ = MagicMock(return_value=mock_db)
            mock_db.__exit__ = MagicMock(return_value=False)
            mock_db.query.return_value.filter.return_value.first.return_value = MagicMock(
                encrypted_config="{}"
            )
            mock_session.return_value = mock_db
            with patch("app.services.encryption.decrypt_config", return_value=_make_config()):
                with patch(
                    "app.services.supabase_service.SupabaseService.update_rows",
                    return_value={"rows": [{"id": 1}], "count": 1, "success": True},
                ) as mock_update:
                    executor = WorkflowExecutor(
                        nodes=nodes,
                        edges=edges,
                        actor_user_id=_uuid.uuid4(),
                    )
                    result = executor.execute(workflow_id=_uuid.uuid4(), initial_inputs=inputs)
        self.assertEqual(result.status, "success")
        mock_update.assert_called_once_with(
            "users",
            {"status": "processed"},
            schema="public",
            filters={"id": 1},
        )

    def test_delete_operation_calls_service(self) -> None:
        import uuid as _uuid

        from app.services.workflow_executor import WorkflowExecutor

        nodes, edges, inputs = _make_supabase_workflow(
            {
                "credentialId": "cred-1",
                "supabaseOperation": "delete",
                "supabaseTable": "users",
                "supabaseFilter": '{"id": 1}',
            }
        )
        with patch("app.db.session.SessionLocal") as mock_session:
            mock_db = MagicMock()
            mock_db.__enter__ = MagicMock(return_value=mock_db)
            mock_db.__exit__ = MagicMock(return_value=False)
            mock_db.query.return_value.filter.return_value.first.return_value = MagicMock(
                encrypted_config="{}"
            )
            mock_session.return_value = mock_db
            with patch("app.services.encryption.decrypt_config", return_value=_make_config()):
                with patch(
                    "app.services.supabase_service.SupabaseService.delete_rows",
                    return_value={"rows": [{"id": 1}], "count": 1, "success": True},
                ) as mock_delete:
                    executor = WorkflowExecutor(
                        nodes=nodes,
                        edges=edges,
                        actor_user_id=_uuid.uuid4(),
                    )
                    result = executor.execute(workflow_id=_uuid.uuid4(), initial_inputs=inputs)
        mock_delete.assert_called_once_with(
            "users",
            schema="public",
            filters={"id": 1},
        )
        self.assertEqual(result.status, "success")

    def test_blank_supabase_url_in_credential_results_in_error(self) -> None:
        import uuid as _uuid

        from app.services.workflow_executor import WorkflowExecutor

        nodes, edges, inputs = _make_supabase_workflow(
            {
                "credentialId": "cred-1",
                "supabaseOperation": "select",
                "supabaseTable": "users",
            }
        )
        with patch("app.db.session.SessionLocal") as mock_session:
            mock_db = MagicMock()
            mock_db.__enter__ = MagicMock(return_value=mock_db)
            mock_db.__exit__ = MagicMock(return_value=False)
            mock_db.query.return_value.filter.return_value.first.return_value = MagicMock(
                encrypted_config="{}"
            )
            mock_session.return_value = mock_db
            with patch(
                "app.services.encryption.decrypt_config",
                return_value={
                    "supabase_url": "",
                    "supabase_key": "sb-secret-key",
                },
            ):
                executor = WorkflowExecutor(
                    nodes=nodes,
                    edges=edges,
                    actor_user_id=_uuid.uuid4(),
                )
                result = executor.execute(workflow_id=_uuid.uuid4(), initial_inputs=inputs)
        self.assertEqual(result.status, "error")
        supa_result = next((r for r in result.node_results if r["node_label"] == "supaNode"), None)
        self.assertIsNotNone(supa_result)
        self.assertIn("supabase_url", supa_result.get("error", "").lower())

    def test_blank_supabase_key_in_credential_results_in_error(self) -> None:
        import uuid as _uuid

        from app.services.workflow_executor import WorkflowExecutor

        nodes, edges, inputs = _make_supabase_workflow(
            {
                "credentialId": "cred-1",
                "supabaseOperation": "select",
                "supabaseTable": "users",
            }
        )
        with patch("app.db.session.SessionLocal") as mock_session:
            mock_db = MagicMock()
            mock_db.__enter__ = MagicMock(return_value=mock_db)
            mock_db.__exit__ = MagicMock(return_value=False)
            mock_db.query.return_value.filter.return_value.first.return_value = MagicMock(
                encrypted_config="{}"
            )
            mock_session.return_value = mock_db
            with patch(
                "app.services.encryption.decrypt_config",
                return_value={
                    "supabase_url": "https://example.supabase.co",
                    "supabase_key": " ",
                },
            ):
                executor = WorkflowExecutor(
                    nodes=nodes,
                    edges=edges,
                    actor_user_id=_uuid.uuid4(),
                )
                result = executor.execute(workflow_id=_uuid.uuid4(), initial_inputs=inputs)
        self.assertEqual(result.status, "error")
        supa_result = next((r for r in result.node_results if r["node_label"] == "supaNode"), None)
        self.assertIsNotNone(supa_result)
        self.assertIn("supabase_key", supa_result.get("error", "").lower())

    def test_insert_auto_map_rejects_multiple_upstream_sources(self) -> None:
        import uuid as _uuid

        from app.services.workflow_executor import WorkflowExecutor

        nodes = [
            {
                "id": "a",
                "type": "set",
                "position": {"x": 0, "y": 0},
                "data": {"label": "a", "mappings": [{"key": "name", "value": "Alice"}]},
            },
            {
                "id": "b",
                "type": "set",
                "position": {"x": 0, "y": 120},
                "data": {"label": "b", "mappings": [{"key": "role", "value": "admin"}]},
            },
            {
                "id": "supa",
                "type": "supabase",
                "position": {"x": 220, "y": 60},
                "data": {
                    "label": "supaNode",
                    "credentialId": "cred-1",
                    "supabaseOperation": "insert",
                    "supabaseTable": "users",
                    "supabaseRowsInputMode": "auto",
                },
            },
        ]
        edges = [
            {"id": "e1", "source": "a", "target": "supa"},
            {"id": "e2", "source": "b", "target": "supa"},
        ]
        with patch("app.db.session.SessionLocal") as mock_session:
            mock_db = MagicMock()
            mock_db.__enter__ = MagicMock(return_value=mock_db)
            mock_db.__exit__ = MagicMock(return_value=False)
            mock_db.query.return_value.filter.return_value.first.return_value = MagicMock(
                encrypted_config="{}"
            )
            mock_session.return_value = mock_db
            with patch("app.services.encryption.decrypt_config", return_value=_make_config()):
                executor = WorkflowExecutor(
                    nodes=nodes,
                    edges=edges,
                    actor_user_id=_uuid.uuid4(),
                )
                result = executor.execute(workflow_id=_uuid.uuid4(), initial_inputs={})
        self.assertEqual(result.status, "error")
        supa_result = next((r for r in result.node_results if r["node_label"] == "supaNode"), None)
        self.assertIsNotNone(supa_result)
        self.assertIn("exactly one upstream input source", supa_result.get("error", "").lower())
