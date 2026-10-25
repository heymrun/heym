"""Model credentials on generated `llm` and `agent` nodes.

The chat runs on one model credential (the Chat tab's pick, or the one set for `heym_chat`
in the MCP tab), owned or shared with the user. A new model node gets that credential and
model; a node the workflow already had keeps its own.
"""

import unittest
import uuid
from types import SimpleNamespace
from typing import Any

from app.api.ai_assistant import _sanitize_generated_workflow_nodes
from app.db.models import CredentialType

USER_ID = uuid.uuid4()
OWNER_ID = uuid.uuid4()
SHARED_LLM = SimpleNamespace(id=uuid.uuid4(), owner_id=OWNER_ID, type=CredentialType.google)
OWN_LLM = SimpleNamespace(id=uuid.uuid4(), owner_id=USER_ID, type=CredentialType.openai)


def _node(node_type: str = "agent", node_id: str = "n1", **data: Any) -> dict[str, Any]:
    return {"id": node_id, "type": node_type, "data": {"label": "writer", **data}}


def _sanitize(
    nodes: list[dict[str, Any]],
    *,
    selected: SimpleNamespace = SHARED_LLM,
    model: str = "gemini-2.5-flash",
    accessible: set[str] | None = None,
    previous: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    return _sanitize_generated_workflow_nodes(
        nodes,
        accessible_credential_ids=accessible
        if accessible is not None
        else {str(SHARED_LLM.id), str(OWN_LLM.id)},
        selected_credential=selected,
        selected_model=model,
        previous_nodes=previous,
    )


class NewModelNodeTests(unittest.TestCase):
    def test_a_shared_chat_credential_fills_a_new_node(self) -> None:
        """Account B runs heym_chat on a credential account A shared with them."""
        for node_type in ("llm", "agent"):
            with self.subTest(node_type=node_type):
                (node,) = _sanitize([_node(node_type, credentialId="YOUR_CREDENTIAL_ID")])

                self.assertEqual(node["data"]["credentialId"], str(SHARED_LLM.id))
                self.assertEqual(node["data"]["model"], "gemini-2.5-flash")

    def test_an_empty_or_missing_credential_is_never_saved(self) -> None:
        for data in ({"credentialId": ""}, {}, {"credentialId": str(uuid.uuid4())}):
            with self.subTest(data=data):
                (node,) = _sanitize([_node(**data)])

                self.assertEqual(node["data"]["credentialId"], str(SHARED_LLM.id))

    def test_a_model_written_next_to_a_placeholder_gives_way_to_the_chat_model(self) -> None:
        (node,) = _sanitize([_node(credentialId="YOUR_CREDENTIAL_ID", model="gpt-4o")])

        self.assertEqual(node["data"]["model"], "gemini-2.5-flash")

    def test_a_listed_credential_the_model_picked_is_kept_with_its_model(self) -> None:
        (node,) = _sanitize([_node(credentialId=str(OWN_LLM.id), model="gpt-4o-mini")])

        self.assertEqual(node["data"]["credentialId"], str(OWN_LLM.id))
        self.assertEqual(node["data"]["model"], "gpt-4o-mini")

    def test_a_shared_fallback_credential_is_kept(self) -> None:
        (node,) = _sanitize(
            [
                _node(
                    credentialId="YOUR_CREDENTIAL_ID",
                    fallbackCredentialId=str(SHARED_LLM.id),
                    fallbackModel="gemini-2.5-pro",
                )
            ]
        )

        self.assertEqual(node["data"]["fallbackCredentialId"], str(SHARED_LLM.id))
        self.assertEqual(node["data"]["fallbackModel"], "gemini-2.5-pro")

    def test_a_chat_credential_the_user_cannot_use_leaves_the_node_empty(self) -> None:
        stranger = SimpleNamespace(id=uuid.uuid4(), owner_id=OWNER_ID, type=CredentialType.openai)

        (node,) = _sanitize([_node(credentialId="YOUR_CREDENTIAL_ID")], selected=stranger)

        self.assertEqual(node["data"]["credentialId"], "")

    def test_a_chat_credential_that_is_not_a_model_credential_is_not_used(self) -> None:
        slack = SimpleNamespace(id=uuid.uuid4(), owner_id=USER_ID, type=CredentialType.slack)

        (node,) = _sanitize(
            [_node(credentialId="YOUR_CREDENTIAL_ID")],
            selected=slack,
            accessible={str(slack.id)},
        )

        self.assertEqual(node["data"]["credentialId"], "")


class EditedModelNodeTests(unittest.TestCase):
    other_credential = str(uuid.uuid4())

    def _previous(self, **data: Any) -> list[dict[str, Any]]:
        return [_node(**{"credentialId": self.other_credential, "model": "gpt-5", **data})]

    def test_an_unchanged_credential_is_kept_even_when_this_user_cannot_read_it(self) -> None:
        """A collaborator editing the owner's workflow must not swap in their own model."""
        (node,) = _sanitize(
            [_node(credentialId=self.other_credential, model="gpt-5")],
            previous=self._previous(),
        )

        self.assertEqual(node["data"]["credentialId"], self.other_credential)
        self.assertEqual(node["data"]["model"], "gpt-5")

    def test_a_placeholder_on_an_existing_node_restores_its_credential_and_model(self) -> None:
        (node,) = _sanitize(
            [_node(credentialId="YOUR_CREDENTIAL_ID", model="")], previous=self._previous()
        )

        self.assertEqual(node["data"]["credentialId"], self.other_credential)
        self.assertEqual(node["data"]["model"], "gpt-5")

    def test_a_model_copied_next_to_a_placeholder_does_not_replace_the_nodes_model(
        self,
    ) -> None:
        (node,) = _sanitize(
            [_node(credentialId="YOUR_CREDENTIAL_ID", model="gpt-4o")], previous=self._previous()
        )

        self.assertEqual(node["data"]["credentialId"], self.other_credential)
        self.assertEqual(node["data"]["model"], "gpt-5")

    def test_changing_only_the_model_of_an_existing_node_is_honoured(self) -> None:
        (node,) = _sanitize(
            [_node(credentialId=self.other_credential, model="gpt-5-mini")],
            previous=self._previous(),
        )

        self.assertEqual(node["data"]["credentialId"], self.other_credential)
        self.assertEqual(node["data"]["model"], "gpt-5-mini")

    def test_a_node_matched_by_label_keeps_its_credential(self) -> None:
        (node,) = _sanitize(
            [_node(node_id="renamed-id", credentialId="")], previous=self._previous()
        )

        self.assertEqual(node["data"]["credentialId"], self.other_credential)

    def test_switching_to_another_listed_credential_is_honoured(self) -> None:
        (node,) = _sanitize(
            [_node(credentialId=str(OWN_LLM.id), model="gpt-4o-mini")],
            previous=self._previous(),
        )

        self.assertEqual(node["data"]["credentialId"], str(OWN_LLM.id))
        self.assertEqual(node["data"]["model"], "gpt-4o-mini")

    def test_an_existing_node_without_a_credential_gets_the_chat_credential(self) -> None:
        (node,) = _sanitize(
            [_node(credentialId="YOUR_CREDENTIAL_ID")],
            previous=self._previous(credentialId="", model=""),
        )

        self.assertEqual(node["data"]["credentialId"], str(SHARED_LLM.id))
        self.assertEqual(node["data"]["model"], "gemini-2.5-flash")

    def test_a_node_added_by_the_edit_gets_the_chat_credential(self) -> None:
        nodes = _sanitize(
            [
                _node(credentialId=self.other_credential, model="gpt-5"),
                _node("llm", node_id="n2", label="summary", credentialId="YOUR_CREDENTIAL_ID"),
            ],
            previous=self._previous(),
        )

        self.assertEqual(nodes[0]["data"]["credentialId"], self.other_credential)
        self.assertEqual(nodes[1]["data"]["credentialId"], str(SHARED_LLM.id))

    def test_unchanged_fallback_and_guardrail_credentials_are_kept(self) -> None:
        fallback = str(uuid.uuid4())
        guardrail = str(uuid.uuid4())
        extra = {
            "fallbackCredentialId": fallback,
            "fallbackModel": "gpt-4o",
            "guardrailCredentialId": guardrail,
            "guardrailModel": "gpt-4o-mini",
        }

        (node,) = _sanitize(
            [_node(credentialId=self.other_credential, model="gpt-5", **extra)],
            previous=self._previous(**extra),
        )

        self.assertEqual(node["data"]["fallbackCredentialId"], fallback)
        self.assertEqual(node["data"]["fallbackModel"], "gpt-4o")
        self.assertEqual(node["data"]["guardrailCredentialId"], guardrail)
        self.assertEqual(node["data"]["guardrailModel"], "gpt-4o-mini")

    def test_an_unknown_id_on_a_new_node_is_still_replaced(self) -> None:
        """Keeping old values must not let a generated id the user cannot use through."""
        (node,) = _sanitize(
            [_node(node_id="n2", label="other", credentialId=self.other_credential)],
            previous=None,
        )

        self.assertEqual(node["data"]["credentialId"], str(SHARED_LLM.id))


if __name__ == "__main__":
    unittest.main()
