"""Credential handling for workflows the chat builder generates."""

import unittest
import uuid
from typing import Any

from app.db.models import CredentialType
from app.services.credential_catalog import CatalogCredential, CredentialPromptMode
from app.services.generated_credentials import (
    CredentialChoice,
    CredentialNeed,
    CredentialPassResult,
    apply_generated_credentials,
    credentials_to_assign_payload,
    format_credential_choices,
    parse_credential_choices,
    requires_credentials_payload,
)

GITHUB_WORK = CatalogCredential(uuid.uuid4(), "github-work", CredentialType.github)
GITHUB_OTHER = CatalogCredential(uuid.uuid4(), "github-other", CredentialType.github)
SLACK_MAIN = CatalogCredential(uuid.uuid4(), "slack-main", CredentialType.slack)
CODEX_MAIN = CatalogCredential(uuid.uuid4(), "codex-main", CredentialType.codex)
CATALOG = [GITHUB_WORK, GITHUB_OTHER, SLACK_MAIN, CODEX_MAIN]
APPLY = CredentialPromptMode.APPLY_CHOICES
OFF = CredentialPromptMode.OFF


def _node(
    node_type: str,
    credential_id: str | None = None,
    *,
    node_id: str = "n1",
    label: str = "fetchRepos",
) -> dict[str, Any]:
    data: dict[str, Any] = {"label": label}
    if credential_id is not None:
        data["credentialId"] = credential_id
    return {"id": node_id, "type": node_type, "position": {"x": 0, "y": 0}, "data": data}


def _run(
    nodes: list[dict[str, Any]],
    *,
    choices: list[CredentialChoice] | None = None,
    previous: list[dict[str, Any]] | None = None,
    mode: CredentialPromptMode = APPLY,
) -> CredentialPassResult:
    return apply_generated_credentials(
        nodes, catalog=CATALOG, choices=choices or [], previous_nodes=previous, mode=mode
    )


def _github_need(node: str = "fetchRepos") -> CredentialNeed:
    return CredentialNeed(
        node=node,
        node_type="github",
        field="credentialId",
        credential_types=("github",),
        existing=("github-other", "github-work"),
    )


class ResolveTests(unittest.TestCase):
    def test_owned_id_of_the_right_type_is_kept(self) -> None:
        result = _run([_node("github", str(GITHUB_WORK.id))])

        self.assertEqual(result.nodes[0]["data"]["credentialId"], str(GITHUB_WORK.id))
        self.assertEqual(result.needs, [])

    def test_uppercase_id_is_normalized(self) -> None:
        result = _run([_node("github", str(GITHUB_WORK.id).upper())])

        self.assertEqual(result.nodes[0]["data"]["credentialId"], str(GITHUB_WORK.id))

    def test_exact_credential_name_is_rewritten_to_its_id(self) -> None:
        result = _run([_node("github", "github-work")])

        self.assertEqual(result.nodes[0]["data"]["credentialId"], str(GITHUB_WORK.id))

    def test_unowned_id_is_cleared_and_reported(self) -> None:
        result = _run([_node("github", str(uuid.uuid4()))])

        self.assertEqual(result.nodes[0]["data"]["credentialId"], "")
        self.assertEqual(result.needs, [_github_need()])

    def test_wrong_type_id_is_cleared(self) -> None:
        result = _run([_node("github", str(SLACK_MAIN.id))])

        self.assertEqual(result.nodes[0]["data"]["credentialId"], "")

    def test_placeholder_is_cleared(self) -> None:
        result = _run([_node("github", "YOUR_CREDENTIAL_ID")])

        self.assertEqual(result.nodes[0]["data"]["credentialId"], "")

    def test_input_nodes_are_not_mutated(self) -> None:
        nodes = [_node("github", "github-work")]

        _run(nodes)

        self.assertEqual(nodes[0]["data"]["credentialId"], "github-work")

    def test_nodes_without_credential_fields_pass_through(self) -> None:
        nodes = [_node("textInput"), _node("llm", "YOUR_CREDENTIAL_ID", node_id="n2")]

        result = _run(nodes)

        self.assertEqual(result.nodes, nodes)
        self.assertEqual(result.needs, [])


class ChoiceTests(unittest.TestCase):
    def test_choice_fills_an_empty_required_field(self) -> None:
        choices = [CredentialChoice(CredentialType.github, "github-work")]

        result = _run([_node("github", "")], choices=choices)

        self.assertEqual(result.nodes[0]["data"]["credentialId"], str(GITHUB_WORK.id))
        self.assertEqual(result.needs, [])

    def test_single_choice_wins_over_a_different_credential_on_a_new_node(self) -> None:
        choices = [CredentialChoice(CredentialType.github, "github-work")]

        result = _run([_node("github", str(GITHUB_OTHER.id))], choices=choices)

        self.assertEqual(result.nodes[0]["data"]["credentialId"], str(GITHUB_WORK.id))

    def test_choice_naming_a_missing_credential_is_still_a_need(self) -> None:
        choices = [CredentialChoice(CredentialType.github, "does-not-exist")]

        result = _run([_node("github", "")], choices=choices)

        self.assertEqual(result.needs, [_github_need()])

    def test_declined_choice_saves_the_field_empty_without_a_need(self) -> None:
        choices = [CredentialChoice(CredentialType.github, "")]

        result = _run([_node("github", "")], choices=choices)

        self.assertEqual(result.nodes[0]["data"]["credentialId"], "")
        self.assertEqual(result.needs, [])

    def test_declined_choice_clears_a_credential_the_builder_added_anyway(self) -> None:
        choices = [CredentialChoice(CredentialType.github, "")]

        result = _run([_node("github", str(GITHUB_WORK.id))], choices=choices)

        self.assertEqual(result.nodes[0]["data"]["credentialId"], "")

    def test_new_node_without_a_choice_is_a_need(self) -> None:
        result = _run([_node("github")])

        self.assertEqual(result.needs, [_github_need()])

    def test_codex_needs_both_of_its_credentials(self) -> None:
        result = _run([_node("codex", label="fixBug")])

        self.assertEqual(
            [need.field for need in result.needs], ["credentialId", "githubCredentialId"]
        )
        self.assertEqual(result.needs[0].existing, ("codex-main",))

    def test_optional_field_is_never_a_need(self) -> None:
        result = _run([_node("rag", label="search")])

        self.assertEqual(result.needs, [])


class ExistingNodeTests(unittest.TestCase):
    def test_unchanged_value_is_kept_even_when_not_owned(self) -> None:
        """A shared credential the user picked earlier survives the edit."""
        shared_id = str(uuid.uuid4())
        previous = [_node("github", shared_id)]

        result = _run([_node("github", shared_id)], previous=previous)

        self.assertEqual(result.nodes[0]["data"]["credentialId"], shared_id)

    def test_existing_node_without_a_credential_is_never_a_need(self) -> None:
        previous = [_node("github", "")]

        result = _run([_node("github", "")], previous=previous)

        self.assertEqual(result.needs, [])

    def test_garbage_written_over_an_existing_value_is_reverted(self) -> None:
        previous = [_node("github", str(GITHUB_WORK.id))]

        result = _run([_node("github", "YOUR_CREDENTIAL_ID")], previous=previous)

        self.assertEqual(result.nodes[0]["data"]["credentialId"], str(GITHUB_WORK.id))

    def test_node_matched_by_label_and_type_counts_as_existing(self) -> None:
        previous = [_node("github", "", node_id="old-id")]

        result = _run([_node("github", "", node_id="new-id")], previous=previous)

        self.assertEqual(result.needs, [])

    def test_type_change_makes_the_node_new(self) -> None:
        previous = [_node("slack", "", label="notify")]

        result = _run([_node("github", "", label="notify")], previous=previous)

        self.assertEqual(result.needs, [_github_need("notify")])


class OffModeTests(unittest.TestCase):
    def test_new_nodes_get_no_credential_and_are_listed_for_the_ui(self) -> None:
        result = _run([_node("github", str(GITHUB_WORK.id))], mode=OFF)

        self.assertEqual(result.nodes[0]["data"]["credentialId"], "")
        self.assertEqual(result.needs, [_github_need()])

    def test_existing_nodes_keep_their_old_value_whatever_the_builder_wrote(self) -> None:
        previous = [_node("github", str(GITHUB_WORK.id))]

        result = _run([_node("github", str(GITHUB_OTHER.id))], previous=previous, mode=OFF)

        self.assertEqual(result.nodes[0]["data"]["credentialId"], str(GITHUB_WORK.id))
        self.assertEqual(result.needs, [])

    def test_choices_are_ignored(self) -> None:
        choices = [CredentialChoice(CredentialType.github, "github-work")]

        result = _run([_node("github", "")], choices=choices, mode=OFF)

        self.assertEqual(result.nodes[0]["data"]["credentialId"], "")


class ChoiceParsingTests(unittest.TestCase):
    def test_valid_entries_are_parsed_and_malformed_ones_skipped(self) -> None:
        raw = [
            {"credential_type": "github", "credential_name": " github-work "},
            {
                "credential_type": "google_sheets",
                "credential_name": "sheet",
                "header_key": "Authorization",
            },
            {"credential_type": "slack", "credential_name": ""},
            {"credential_type": "not-a-type", "credential_name": "x"},
            "github",
            {"credential_name": "no-type"},
        ]

        self.assertEqual(
            parse_credential_choices(raw),
            [
                CredentialChoice(CredentialType.github, "github-work"),
                CredentialChoice(CredentialType.google_sheets, "sheet", "Authorization"),
                CredentialChoice(CredentialType.slack, ""),
            ],
        )

    def test_non_list_is_empty(self) -> None:
        self.assertEqual(parse_credential_choices(None), [])
        self.assertEqual(parse_credential_choices({"credential_type": "github"}), [])

    def test_choices_render_as_builder_instructions(self) -> None:
        text = format_credential_choices(
            [
                CredentialChoice(CredentialType.github, "github-work"),
                CredentialChoice(CredentialType.google_sheets, "sheet", "Authorization"),
                CredentialChoice(CredentialType.slack, ""),
            ]
        )

        self.assertEqual(
            text,
            "Credential choices the user made:\n"
            "- github: use `github-work`\n"
            "- google_sheets: use `sheet` with header key `Authorization` for http requests\n"
            "- slack: no credential (leave the field empty, send http requests without "
            "authentication)",
        )
        self.assertEqual(format_credential_choices([]), "")


class PayloadTests(unittest.TestCase):
    def test_requires_credentials_payload_lists_needs_by_name_and_type(self) -> None:
        payload = requires_credentials_payload([_github_need()])

        self.assertEqual(payload["status"], "requires_credentials")
        self.assertEqual(
            payload["needs"],
            [
                {
                    "node": "fetchRepos",
                    "node_type": "github",
                    "field": "credentialId",
                    "credential_types": ["github"],
                    "existing": ["github-other", "github-work"],
                }
            ],
        )
        self.assertIn("credential_choices", payload["instructions"])

    def test_assign_in_ui_payload_is_empty_without_needs(self) -> None:
        self.assertEqual(credentials_to_assign_payload([]), {})

    def test_assign_in_ui_payload_names_nodes_and_types(self) -> None:
        payload = credentials_to_assign_payload([_github_need()])

        self.assertEqual(
            payload["credentials_to_assign_in_ui"],
            [{"node": "fetchRepos", "node_type": "github", "credential_types": ["github"]}],
        )


if __name__ == "__main__":
    unittest.main()
