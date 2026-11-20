"""A blank required field fails with the node's own message and sends nothing.

evaluate_message_template renders a blank template as the whole input context, so these
nodes render required fields with evaluate_nonempty_message_template.
"""

from __future__ import annotations

import unittest
import uuid
from unittest.mock import MagicMock, patch

from app.services.workflow_executor import WorkflowExecutor


def run(node_type: str, data: dict, extra_patches: list) -> tuple[str, str]:
    nodes = [
        {
            "id": "start",
            "type": "textInput",
            "position": {"x": 0, "y": 0},
            "data": {"label": "start", "inputFields": [{"key": "id"}]},
        },
        {
            "id": "n",
            "type": node_type,
            "position": {"x": 200, "y": 0},
            "data": {"label": "n", "credentialId": "cred-1", **data},
        },
    ]
    edges = [{"id": "e1", "source": "start", "target": "n"}]
    db = MagicMock()
    db.__enter__ = MagicMock(return_value=db)
    db.__exit__ = MagicMock(return_value=False)
    db.query.return_value.filter.return_value.first.return_value = MagicMock(encrypted_config="{}")
    config = {
        "api_key": "k",
        "supabase_url": "https://db.example.com",
        "supabase_key": "k",
        "flaresolverr_url": "https://fs.example.com/v1",
        "redis_host": "redis.example.com",
    }
    patches = [
        patch("app.db.session.SessionLocal", return_value=db),
        patch("app.services.encryption.decrypt_config", return_value=config),
        *extra_patches,
    ]
    for p in patches:
        p.start()
    try:
        executor = WorkflowExecutor(nodes=nodes, edges=edges, actor_user_id=uuid.uuid4())
        executor._get_accessible_data_table = MagicMock(return_value=MagicMock(columns=[]))
        result = executor.execute(
            workflow_id=uuid.uuid4(),
            initial_inputs={"headers": {}, "query": {}, "body": {"id": "7"}},
        )
    finally:
        for p in reversed(patches):
            p.stop()
    row = next(r for r in result.node_results if r["node_label"] == "n")
    return row["status"], str(row.get("error") or "")[:100]


class Recorder:
    def __init__(self) -> None:
        self.seen: list[str] = []

    def __call__(self, *args: object, **kwargs: object) -> MagicMock:
        self.seen.append(" ".join(str(a) for a in args) + " " + str(kwargs))
        response = MagicMock(status_code=200, text="{}")
        response.json.return_value = {"tables": [], "records": [], "solution": {}}
        return response


def cases() -> dict[str, tuple[str, dict, dict, str]]:
    return {
        "Supabase select, no table": (
            "supabase",
            {"supabaseOperation": "select"},
            {"supabaseTable": "orders"},
            "Supabase table is required",
        ),
        "Data Table getById, no row id": (
            "dataTable",
            {"dataTableId": str(uuid.uuid4()), "dataTableOperation": "getById"},
            {"dataTableRowId": str(uuid.uuid4())},
            "DataTable getById requires a row ID",
        ),
        "Crawler, URL cleared": (
            "crawler",
            {"crawlerUrl": ""},
            {"crawlerUrl": "https://example.com"},
            "Crawler node requires a URL to crawl",
        ),
        "Redis set, no key": (
            "redis",
            {"redisOperation": "set", "redisValue": "v"},
            {"redisKey": "session:7"},
            "Redis node requires a key",
        ),
    }


def clients() -> tuple[list, Recorder]:
    recorder = Recorder()
    supabase_select = MagicMock(side_effect=lambda *a, **k: recorder(*a, **k) and {"rows": []})
    http = MagicMock()
    http.post.side_effect = recorder
    redis = MagicMock()
    redis.set.side_effect = lambda *a, **k: recorder(*a, **k) and True
    return [
        patch("app.services.supabase_service.SupabaseService.__init__", return_value=None),
        patch("app.services.supabase_service.SupabaseService.select_rows", supabase_select),
        patch("app.services.ssrf_guard.get_guarded_carrier_http_client", return_value=http),
        patch("app.services.ssrf_guard.guard_carrier_url"),
        patch("app.services.redis_pool.get_redis_connection", return_value=redis),
    ], recorder


class BlankRequiredFieldTests(unittest.TestCase):
    def test_a_blank_required_field_fails_with_the_node_message(self) -> None:
        for name, (node_type, base, _filled, guard) in cases().items():
            with self.subTest(name):
                extra, recorder = clients()
                status, error = run(node_type, base, extra)

                self.assertEqual(status, "error")
                self.assertIn(guard, error)
                self.assertEqual(recorder.seen, [])

    def test_a_filled_field_still_reaches_the_client(self) -> None:
        for name, (node_type, base, filled, guard) in cases().items():
            with self.subTest(name):
                extra, recorder = clients()
                status, error = run(node_type, {**base, **filled}, extra)

                self.assertEqual(status, "success", error)
                if node_type != "dataTable":
                    self.assertTrue(recorder.seen)
                    self.assertFalse(any("start" in seen for seen in recorder.seen))


if __name__ == "__main__":
    unittest.main()
