"""Slack's response_url is a ~30-minute bearer webhook that posts into the
originating channel with no further auth. It must not reach persisted run
data, same as Discord's interaction token.
"""

import unittest

from app.api.slack import _redact_response_url

_URL = "https://hooks.slack.com/actions/T000/B000/XXXXXXXXXXXXXXXXXXXXXXXX"


class SlackResponseUrlRedactionTests(unittest.TestCase):
    def test_url_is_dropped_from_run_inputs(self) -> None:
        inputs = {
            "triggered_by": "Slack",
            "event": {"response_url": _URL, "type": "slash_command"},
        }

        redacted = _redact_response_url(inputs, _URL)

        self.assertEqual(redacted["event"]["response_url"], "[redacted]")

    def test_other_fields_are_kept(self) -> None:
        inputs = {"event": {"response_url": _URL, "type": "slash_command"}}

        redacted = _redact_response_url(inputs, _URL)

        self.assertEqual(redacted["event"]["type"], "slash_command")

    def test_node_output_copy_is_redacted_too(self) -> None:
        node_results = [
            {
                "node_type": "slackTrigger",
                "output": {"event": {"response_url": _URL, "id": "456"}},
            }
        ]

        redacted = _redact_response_url(node_results, _URL)

        self.assertEqual(redacted[0]["output"]["event"]["response_url"], "[redacted]")
        self.assertEqual(redacted[0]["output"]["event"]["id"], "456")

    def test_url_embedded_in_a_string_is_scrubbed(self) -> None:
        outputs = {"message": f"Posting a follow-up to {_URL} now"}

        redacted = _redact_response_url(outputs, _URL)

        self.assertNotIn(_URL, redacted["message"])

    def test_nested_sub_workflow_structures_are_reached(self) -> None:
        payload = {"runs": [{"nodes": [{"out": {"event": {"response_url": _URL}}}]}]}

        redacted = _redact_response_url(payload, _URL)

        self.assertEqual(
            redacted["runs"][0]["nodes"][0]["out"]["event"]["response_url"], "[redacted]"
        )

    def test_original_structure_is_left_intact_for_the_followup_sender(self) -> None:
        event = {"response_url": _URL, "type": "slash_command"}
        inputs = {"event": event}

        _redact_response_url(inputs, _URL)

        # The follow-up sender reads this same object after the run finishes.
        self.assertEqual(event["response_url"], _URL)
        self.assertEqual(inputs["event"]["response_url"], _URL)

    def test_unrelated_values_are_untouched(self) -> None:
        payload = {"response_url": "some-other-value", "count": 3, "flag": None}

        self.assertEqual(_redact_response_url(payload, _URL), payload)


if __name__ == "__main__":
    unittest.main()
