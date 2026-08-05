"""Tests for the Cal.com API service used by the Cal.com node."""

import unittest
from unittest.mock import MagicMock, patch

import httpx

from app.services.cal_api_service import CalApiError, CalApiService


def _response(status_code: int, payload: object | None = None) -> httpx.Response:
    request = httpx.Request("GET", "https://api.cal.com/v2/webhooks")
    if payload is None:
        return httpx.Response(status_code, request=request)
    return httpx.Response(status_code, request=request, json=payload)


class CalApiServiceTests(unittest.TestCase):
    def test_requires_api_key_and_guards_base_url(self) -> None:
        with self.assertRaisesRegex(ValueError, "requires api_key"):
            CalApiService({})
        with (
            patch(
                "app.services.cal_api_service.guard_http_url",
                side_effect=ValueError("private host"),
            ),
            self.assertRaisesRegex(ValueError, "base URL is not allowed"),
        ):
            CalApiService({"api_key": "key", "base_url": "http://internal"})

    def test_list_webhooks_unwraps_cal_response(self) -> None:
        client = MagicMock()
        client.request.return_value = _response(
            200,
            {"status": "success", "data": [{"id": "one"}, {"id": "two"}]},
        )
        with patch("app.services.cal_api_service.guard_http_url"):
            service = CalApiService({"api_key": "secret"}, client=client)
        result = service.list_webhooks()
        self.assertEqual(result, [{"id": "one"}, {"id": "two"}])
        self.assertEqual(client.request.call_args.kwargs["params"], {"take": 250, "skip": 0})

    def test_create_update_and_delete_use_api_v2_paths(self) -> None:
        client = MagicMock()
        client.request.side_effect = [
            _response(201, {"data": {"id": "created"}}),
            _response(200, {"data": {"webhook": {"id": "updated"}}}),
            _response(204),
        ]
        with patch("app.services.cal_api_service.guard_http_url"):
            service = CalApiService(
                {"api_key": "secret", "base_url": "https://cal.example/v2/"},
                client=client,
            )
        self.assertEqual(service.create_webhook({"active": True}), {"id": "created"})
        self.assertEqual(
            service.update_webhook("hook", {"active": False}),
            {"id": "updated"},
        )
        service.delete_webhook("hook")
        calls = client.request.call_args_list
        self.assertEqual(calls[0].args[:2], ("POST", "https://cal.example/v2/webhooks"))
        self.assertEqual(calls[1].args[:2], ("PATCH", "https://cal.example/v2/webhooks/hook"))
        self.assertEqual(calls[2].args[:2], ("DELETE", "https://cal.example/v2/webhooks/hook"))

    def test_api_error_preserves_status_and_detail(self) -> None:
        client = MagicMock()
        client.request.return_value = _response(422, {"message": "invalid triggers"})
        with patch("app.services.cal_api_service.guard_http_url"):
            service = CalApiService({"api_key": "secret"}, client=client)
        with self.assertRaises(CalApiError) as raised:
            service.create_webhook({})
        self.assertEqual(raised.exception.status_code, 422)
        self.assertIn("invalid triggers", str(raised.exception))

    def test_network_errors_are_wrapped(self) -> None:
        client = MagicMock()
        client.request.side_effect = httpx.ConnectError("offline")
        with patch("app.services.cal_api_service.guard_http_url"):
            service = CalApiService({"api_key": "secret"}, client=client)
        with self.assertRaisesRegex(CalApiError, "Unable to reach"):
            service.list_webhooks()
