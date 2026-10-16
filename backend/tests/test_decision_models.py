"""Request body construction for decision models."""

import unittest
import unittest.mock as mock
import uuid

import httpx

from app.services.decision_images import PreparedImage
from app.services.decision_models import (
    IMAGES_HEADER,
    DecisionProviderError,
    DecisionRequestError,
    build_decision_body,
    call_decision_model,
    needs_images_header,
    redact_assets,
)
from app.services.llm_trace import LLMTraceContext


class BuildDecisionBodyTests(unittest.TestCase):
    def test_noul_question_with_criteria(self) -> None:
        body = build_decision_body(
            model="jev-latest",
            state="Payouts failing for 3 days",
            questions=[
                {
                    "id": "is_urgent",
                    "type": "noul",
                    "instructions": "Does this convey urgency?",
                    "criteriaTrue": "Explicitly time-sensitive",
                    "criteriaFalse": "No urgency expressed",
                }
            ],
        )
        self.assertEqual(
            body,
            {
                "model": "jev-latest",
                "state": "Payouts failing for 3 days",
                "questions": {
                    "is_urgent": {
                        "type": "noul",
                        "instructions": "Does this convey urgency?",
                        "criteria": {
                            "true": "Explicitly time-sensitive",
                            "false": "No urgency expressed",
                        },
                    }
                },
            },
        )

    def test_noul_criteria_omitted_when_both_sides_blank(self) -> None:
        body = build_decision_body(
            model="jev-latest",
            state="x",
            questions=[
                {
                    "id": "q",
                    "type": "noul",
                    "instructions": "Is it?",
                    "criteriaTrue": "",
                    "criteriaFalse": "   ",
                }
            ],
        )
        self.assertNotIn("criteria", body["questions"]["q"])

    def test_choice_question_builds_an_option_map(self) -> None:
        body = build_decision_body(
            model="jev-latest",
            state="x",
            questions=[
                {
                    "id": "department",
                    "type": "choice",
                    "instructions": "Which team?",
                    "options": [
                        {"key": "billing", "description": "Payments and refunds"},
                        {"key": "technical", "description": "Bugs and outages"},
                    ],
                }
            ],
        )
        self.assertEqual(
            body["questions"]["department"]["criteria"],
            {"billing": "Payments and refunds", "technical": "Bugs and outages"},
        )

    def test_choice_option_without_a_description_becomes_null(self) -> None:
        body = build_decision_body(
            model="jev-latest",
            state="x",
            questions=[
                {
                    "id": "d",
                    "type": "choice",
                    "instructions": "Which?",
                    "options": [
                        {"key": "a", "description": ""},
                        {"key": "b", "description": "B"},
                    ],
                }
            ],
        )
        self.assertIsNone(body["questions"]["d"]["criteria"]["a"])

    def test_score_question_builds_an_ordered_level_array(self) -> None:
        body = build_decision_body(
            model="jev-latest",
            state="x",
            questions=[
                {
                    "id": "frustration",
                    "type": "score",
                    "instructions": "How frustrated?",
                    "levels": ["Calm", "Frustrated", "Very angry"],
                }
            ],
        )
        self.assertEqual(
            body["questions"]["frustration"]["criteria"],
            ["Calm", "Frustrated", "Very angry"],
        )

    def test_structured_state_is_preserved(self) -> None:
        state = {"ticket": {"messages": [{"text": "hi"}]}}
        body = build_decision_body(
            model="jev-latest",
            state=state,
            questions=[{"id": "q", "type": "noul", "instructions": "Is it?"}],
        )
        self.assertEqual(body["state"], state)

    def test_row_order_is_preserved(self) -> None:
        body = build_decision_body(
            model="jev-latest",
            state="x",
            questions=[
                {"id": "b", "type": "noul", "instructions": "B?"},
                {"id": "a", "type": "noul", "instructions": "A?"},
            ],
        )
        self.assertEqual(list(body["questions"]), ["b", "a"])

    def test_empty_id_is_rejected(self) -> None:
        with self.assertRaises(DecisionRequestError) as ctx:
            build_decision_body(
                model="m",
                state="x",
                questions=[{"id": "  ", "type": "noul", "instructions": "Is it?"}],
            )
        self.assertIn("id", str(ctx.exception))

    def test_duplicate_id_is_rejected(self) -> None:
        with self.assertRaises(DecisionRequestError) as ctx:
            build_decision_body(
                model="m",
                state="x",
                questions=[
                    {"id": "q", "type": "noul", "instructions": "A?"},
                    {"id": "q", "type": "noul", "instructions": "B?"},
                ],
            )
        self.assertIn("duplicate", str(ctx.exception).lower())

    def test_unknown_type_is_rejected(self) -> None:
        with self.assertRaises(DecisionRequestError):
            build_decision_body(
                model="m",
                state="x",
                questions=[{"id": "q", "type": "nuol", "instructions": "A?"}],
            )

    def test_blank_instructions_is_rejected(self) -> None:
        with self.assertRaises(DecisionRequestError) as ctx:
            build_decision_body(
                model="m",
                state="x",
                questions=[{"id": "q", "type": "noul", "instructions": "   "}],
            )
        self.assertIn("instructions", str(ctx.exception))

    def test_choice_without_options_is_rejected(self) -> None:
        with self.assertRaises(DecisionRequestError) as ctx:
            build_decision_body(
                model="m",
                state="x",
                questions=[{"id": "q", "type": "choice", "instructions": "Which?", "options": []}],
            )
        self.assertIn("option", str(ctx.exception).lower())

    def test_choice_with_a_duplicate_option_is_rejected(self) -> None:
        with self.assertRaises(DecisionRequestError) as ctx:
            build_decision_body(
                model="m",
                state="x",
                questions=[
                    {
                        "id": "q",
                        "type": "choice",
                        "instructions": "Which?",
                        "options": [
                            {"key": "a", "description": "first"},
                            {"key": "a", "description": "second"},
                        ],
                    }
                ],
            )
        self.assertIn("duplicate", str(ctx.exception).lower())

    def test_score_with_one_level_is_rejected(self) -> None:
        with self.assertRaises(DecisionRequestError) as ctx:
            build_decision_body(
                model="m",
                state="x",
                questions=[
                    {"id": "q", "type": "score", "instructions": "How much?", "levels": ["Calm"]}
                ],
            )
        self.assertIn("level", str(ctx.exception).lower())

    def test_no_questions_is_rejected(self) -> None:
        with self.assertRaises(DecisionRequestError):
            build_decision_body(model="m", state="x", questions=[])

    def test_blank_model_is_rejected(self) -> None:
        with self.assertRaises(DecisionRequestError) as ctx:
            build_decision_body(
                model="  ",
                state="x",
                questions=[{"id": "q", "type": "noul", "instructions": "Is it?"}],
            )
        self.assertIn("model", str(ctx.exception).lower())


def _image(name: str, data: bytes = b"jpeg-bytes", fmt: str = "jpg") -> PreparedImage:
    return PreparedImage(name=name, format=fmt, data=data, width=400, height=300)


_NOUL = [{"id": "is_dog", "type": "noul", "instructions": "Is there a dog in `photo`?"}]


class BuildDecisionBodyImageTests(unittest.TestCase):
    def test_a_text_only_body_has_no_assets(self) -> None:
        body = build_decision_body(model="jev-latest", state="x", questions=_NOUL)
        self.assertNotIn("assets", body)
        self.assertEqual(body["state"], "x")

    def test_an_image_is_listed_once_and_referenced_from_the_state(self) -> None:
        body = build_decision_body(
            model="jev-latest", state=None, questions=_NOUL, images=[_image("photo")]
        )
        reference = body["state"]["photo"]
        self.assertEqual(uuid.UUID(reference).version, 4)
        self.assertEqual(
            body["assets"],
            {reference: {"type": "image", "format": "jpg", "data_base64": "anBlZy1ieXRlcw=="}},
        )

    def test_every_image_gets_its_own_reference(self) -> None:
        body = build_decision_body(
            model="jev-latest",
            state="",
            questions=_NOUL,
            images=[_image("photo"), _image("poster", fmt="png")],
        )
        self.assertNotEqual(body["state"]["photo"], body["state"]["poster"])
        self.assertEqual(set(body["assets"]), {body["state"]["photo"], body["state"]["poster"]})
        self.assertEqual(body["assets"][body["state"]["poster"]]["format"], "png")

    def test_references_are_fresh_on_every_request(self) -> None:
        first = build_decision_body(
            model="m", state=None, questions=_NOUL, images=[_image("photo")]
        )
        second = build_decision_body(
            model="m", state=None, questions=_NOUL, images=[_image("photo")]
        )
        self.assertNotEqual(first["state"]["photo"], second["state"]["photo"])

    def test_an_empty_state_becomes_the_images(self) -> None:
        for state in (None, "", "   "):
            with self.subTest(state=state):
                body = build_decision_body(
                    model="m", state=state, questions=_NOUL, images=[_image("photo")]
                )
                self.assertEqual(list(body["state"]), ["photo"])

    def test_an_object_state_gains_the_images(self) -> None:
        state = {"location": "front door"}
        body = build_decision_body(
            model="m", state=state, questions=_NOUL, images=[_image("photo")]
        )
        self.assertEqual(body["state"]["location"], "front door")
        self.assertIn("photo", body["state"])
        self.assertEqual(state, {"location": "front door"}, "the resolved state is not mutated")

    def test_a_text_state_is_kept_under_context(self) -> None:
        body = build_decision_body(
            model="m", state="Found near the park", questions=_NOUL, images=[_image("photo")]
        )
        self.assertEqual(body["state"]["context"], "Found near the park")
        self.assertIn("photo", body["state"])

    def test_a_list_state_is_kept_under_context(self) -> None:
        body = build_decision_body(
            model="m", state=["a", "b"], questions=_NOUL, images=[_image("photo")]
        )
        self.assertEqual(body["state"]["context"], ["a", "b"])

    def test_an_image_colliding_with_a_state_field_is_rejected(self) -> None:
        with self.assertRaises(DecisionRequestError) as ctx:
            build_decision_body(
                model="m", state={"photo": "old"}, questions=_NOUL, images=[_image("photo")]
            )
        self.assertIn("collides", str(ctx.exception))

    def test_an_image_named_context_collides_with_a_text_state(self) -> None:
        with self.assertRaises(DecisionRequestError):
            build_decision_body(
                model="m", state="some text", questions=_NOUL, images=[_image("context")]
            )

    def test_an_image_name_must_be_an_identifier(self) -> None:
        for name in ("", "2photo", "my photo", "photo-1", "photo\n"):
            with self.subTest(name=name), self.assertRaises(DecisionRequestError):
                build_decision_body(model="m", state=None, questions=_NOUL, images=[_image(name)])

    def test_a_duplicate_image_name_is_rejected(self) -> None:
        with self.assertRaises(DecisionRequestError) as ctx:
            build_decision_body(
                model="m", state=None, questions=_NOUL, images=[_image("photo"), _image("photo")]
            )
        self.assertIn("Duplicate image name", str(ctx.exception))


class BoxQuestionTests(unittest.TestCase):
    def test_a_box_sends_instructions_only(self) -> None:
        body = build_decision_body(
            model="jev-1.14.0",
            state=None,
            questions=[
                {
                    "id": "dog",
                    "type": "box",
                    "instructions": "the dog in `photo`",
                    "criteriaTrue": "left over from a noul",
                    "levels": ["left", "over"],
                }
            ],
            images=[_image("photo")],
        )
        self.assertEqual(
            body["questions"]["dog"], {"type": "box", "instructions": "the dog in `photo`"}
        )

    def test_a_box_without_an_image_is_rejected_before_sending(self) -> None:
        with self.assertRaises(DecisionRequestError) as ctx:
            build_decision_body(
                model="jev-1.14.0",
                state="x",
                questions=[{"id": "dog", "type": "box", "instructions": "the dog"}],
            )
        self.assertIn("needs an image", str(ctx.exception))


class ImagesHeaderTests(unittest.TestCase):
    def test_assets_need_the_header(self) -> None:
        self.assertTrue(needs_images_header({"assets": {"r": {}}, "questions": {}}))

    def test_a_box_question_needs_the_header(self) -> None:
        self.assertTrue(needs_images_header({"questions": {"q": {"type": "box"}}}))

    def test_a_text_only_body_does_not(self) -> None:
        self.assertFalse(needs_images_header({"state": "x", "questions": {"q": {"type": "noul"}}}))

    def test_an_empty_assets_map_does_not(self) -> None:
        self.assertFalse(needs_images_header({"assets": {}, "questions": {}}))

    def test_a_hand_written_body_of_another_shape_does_not(self) -> None:
        self.assertFalse(needs_images_header({"questions": ["not", "a", "map"]}))


class RedactAssetsTests(unittest.TestCase):
    def test_image_data_is_replaced_by_its_size(self) -> None:
        body = {
            "model": "m",
            "assets": {"r": {"type": "image", "format": "jpg", "data_base64": "anBlZy1ieXRlcw=="}},
        }
        redacted = redact_assets(body)
        self.assertEqual(
            redacted["assets"]["r"],
            {"type": "image", "format": "jpg", "data_base64": "[base64 image, 10 bytes]"},
        )
        self.assertEqual(body["assets"]["r"]["data_base64"], "anBlZy1ieXRlcw==")

    def test_a_body_without_assets_is_returned_as_is(self) -> None:
        body = {"model": "m", "state": "x"}
        self.assertIs(redact_assets(body), body)


def _trace_context() -> LLMTraceContext:
    return LLMTraceContext(user_id=uuid.uuid4(), credential_id=uuid.uuid4())


def _response(status_code: int, payload: object) -> httpx.Response:
    return httpx.Response(
        status_code=status_code,
        json=payload,
        request=httpx.Request("POST", "https://api.typesafe.ai/v1/systemone"),
    )


class CallDecisionModelTests(unittest.TestCase):
    def setUp(self) -> None:
        self.body = {"model": "jev-latest", "state": "x", "questions": {}}

    def _call(self, response: httpx.Response, **kwargs: object) -> object:
        client = mock.MagicMock()
        client.post.return_value = response
        client.__enter__.return_value = client
        client.__exit__.return_value = False
        with (
            mock.patch("app.services.decision_models.guard_http_url") as guard,
            mock.patch(
                "app.services.decision_models.build_guarded_http_client", return_value=client
            ),
            mock.patch("app.services.decision_models.record_llm_trace", return_value=None) as rec,
        ):
            self.guard = guard
            self.record = rec
            self.client = client
            return call_decision_model(
                base_url=str(kwargs.get("base_url", "https://api.typesafe.ai")),
                api_key=str(kwargs.get("api_key", "sk-test")),
                body=self.body,
                timeout=30.0,
                trace_context=_trace_context(),
            )

    def test_successful_call_returns_the_payload_unchanged(self) -> None:
        payload = {
            "model": "jev-1.13.0",
            "answers": {"is_urgent": {"type": "noul", "noul": 0.95}},
            "usage": {"input_tokens": 296, "output_tokens": 20},
        }
        self.assertEqual(self._call(_response(200, payload)), payload)

    def test_the_url_is_guarded_before_dialling(self) -> None:
        self._call(_response(200, {"answers": {}}))
        self.guard.assert_called_once()
        self.assertIn("typesafe", self.guard.call_args.args[0])

    def test_the_endpoint_path_is_appended_once(self) -> None:
        self._call(_response(200, {"answers": {}}), base_url="https://api.typesafe.ai/")
        self.assertEqual(self.client.post.call_args.args[0], "https://api.typesafe.ai/v1/systemone")

    def test_an_explicit_endpoint_path_is_not_doubled(self) -> None:
        self._call(_response(200, {"answers": {}}), base_url="https://api.typesafe.ai/v1/systemone")
        self.assertEqual(self.client.post.call_args.args[0], "https://api.typesafe.ai/v1/systemone")

    def test_a_base_path_is_preserved(self) -> None:
        self._call(_response(200, {"answers": {}}), base_url="https://gw.test/decision")
        self.assertEqual(
            self.client.post.call_args.args[0], "https://gw.test/decision/v1/systemone"
        )

    def test_the_api_key_travels_in_the_authorization_header(self) -> None:
        self._call(_response(200, {"answers": {}}))
        headers = self.client.post.call_args.kwargs["headers"]
        self.assertEqual(headers["Authorization"], "Bearer sk-test")

    def test_no_authorization_header_without_a_key(self) -> None:
        self._call(_response(200, {"answers": {}}), api_key="")
        headers = self.client.post.call_args.kwargs["headers"]
        self.assertNotIn("Authorization", headers)

    def test_a_trace_is_recorded_with_usage(self) -> None:
        self._call(
            _response(
                200,
                {
                    "model": "jev-1.13.0",
                    "answers": {},
                    "usage": {"input_tokens": 296, "output_tokens": 20},
                },
            )
        )
        self.record.assert_called_once()
        kwargs = self.record.call_args.kwargs
        self.assertEqual(kwargs["request_type"], "decision.systemone")
        self.assertEqual(kwargs["prompt_tokens"], 296)
        self.assertEqual(kwargs["completion_tokens"], 20)
        self.assertEqual(kwargs["total_tokens"], 316)
        self.assertEqual(kwargs["model"], "jev-1.13.0")

    def test_401_names_the_credential(self) -> None:
        with self.assertRaises(DecisionProviderError) as ctx:
            self._call(_response(401, {"error": "bad key"}))
        self.assertIn("API key", str(ctx.exception))

    def test_422_carries_the_provider_detail(self) -> None:
        with self.assertRaises(DecisionProviderError) as ctx:
            self._call(_response(422, {"detail": "questions.q.criteria must be an array"}))
        self.assertIn("criteria must be an array", str(ctx.exception))

    def test_429_says_the_condition_is_transient(self) -> None:
        with self.assertRaises(DecisionProviderError) as ctx:
            self._call(_response(429, {"error": "slow down"}))
        self.assertIn("transient", str(ctx.exception).lower())

    def test_529_says_the_condition_is_transient(self) -> None:
        with self.assertRaises(DecisionProviderError) as ctx:
            self._call(_response(529, {"error": "overloaded"}))
        self.assertIn("transient", str(ctx.exception).lower())

    def test_a_refusal_carries_its_status_code(self) -> None:
        with self.assertRaises(DecisionProviderError) as ctx:
            self._call(_response(429, {"error": "slow down"}))
        self.assertEqual(ctx.exception.status_code, 429)

    def test_a_transport_failure_has_no_status_code(self) -> None:
        client = mock.MagicMock()
        client.post.side_effect = httpx.ConnectError("refused")
        client.__enter__.return_value = client
        client.__exit__.return_value = False
        with (
            mock.patch("app.services.decision_models.guard_http_url"),
            mock.patch(
                "app.services.decision_models.build_guarded_http_client", return_value=client
            ),
            self.assertRaises(DecisionProviderError) as ctx,
        ):
            call_decision_model(
                base_url="https://api.typesafe.ai",
                api_key="",
                body=self.body,
                timeout=30.0,
            )
        self.assertIsNone(ctx.exception.status_code)

    def test_a_failure_is_traced_too(self) -> None:
        with self.assertRaises(DecisionProviderError):
            self._call(_response(401, {"error": "bad key"}))
        self.record.assert_called_once()
        self.assertIsNotNone(self.record.call_args.kwargs["error"])

    def test_text_only_requests_do_not_opt_into_images(self) -> None:
        self._call(_response(200, {"answers": {}}))
        self.assertNotIn(IMAGES_HEADER, self.client.post.call_args.kwargs["headers"])

    def test_a_request_with_images_opts_in_and_traces_no_image_data(self) -> None:
        self.body = {
            "model": "jev-latest",
            "state": {"photo": "ref-1"},
            "assets": {"ref-1": {"type": "image", "format": "jpg", "data_base64": "QUJD"}},
            "questions": {"q": {"type": "noul", "instructions": "Dog in `photo`?"}},
        }
        self._call(_response(200, {"answers": {}}))
        kwargs = self.client.post.call_args.kwargs
        self.assertEqual(kwargs["headers"][IMAGES_HEADER], "true")
        self.assertEqual(kwargs["json"]["assets"]["ref-1"]["data_base64"], "QUJD")
        traced = self.record.call_args.kwargs["request"]
        self.assertEqual(traced["assets"]["ref-1"]["data_base64"], "[base64 image, 3 bytes]")

    def test_a_box_question_opts_in(self) -> None:
        self.body = {
            "model": "jev-1.14.0",
            "state": "x",
            "questions": {"q": {"type": "box", "instructions": "the mug"}},
        }
        self._call(_response(200, {"answers": {}}))
        self.assertEqual(self.client.post.call_args.kwargs["headers"][IMAGES_HEADER], "true")

    def test_413_says_the_request_is_too_large(self) -> None:
        with self.assertRaises(DecisionProviderError) as ctx:
            self._call(_response(413, {"detail": "expanded request over 32 MiB"}))
        message = str(ctx.exception)
        self.assertIn("too large", message)
        self.assertIn("expanded request over 32 MiB", message)

    def test_a_non_json_response_is_reported_clearly(self) -> None:
        raw = httpx.Response(
            status_code=200,
            text="<html>gateway</html>",
            request=httpx.Request("POST", "https://api.typesafe.ai/v1/systemone"),
        )
        with self.assertRaises(DecisionProviderError) as ctx:
            self._call(raw)
        self.assertIn("JSON", str(ctx.exception))


class DecisionEgressGuardTests(unittest.TestCase):
    """The base URL is user-supplied, so the SSRF guard must hold with no mocks."""

    def _call(self, base_url: str) -> None:
        call_decision_model(
            base_url=base_url,
            api_key="",
            body={"model": "m", "state": "x", "questions": {}},
            timeout=2.0,
        )

    def test_cloud_metadata_is_blocked(self) -> None:
        with self.assertRaises(Exception) as ctx:
            self._call("http://169.254.169.254")
        self.assertIn("not allowed", str(ctx.exception))

    def test_localhost_is_blocked(self) -> None:
        with self.assertRaises(Exception) as ctx:
            self._call("http://localhost:8765")
        self.assertIn("not allowed", str(ctx.exception))

    def test_private_range_is_blocked(self) -> None:
        with self.assertRaises(Exception) as ctx:
            self._call("http://10.0.0.5")
        self.assertIn("not allowed", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
