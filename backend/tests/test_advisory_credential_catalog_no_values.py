"""The assistant's credential catalog must never carry a credential's value.

The catalog is sent to an LLM on every assistant turn. It may hold names, types and ids,
which are not secrets; a value would leak to the model provider and into chat history.
"""

import unittest
import uuid
from unittest.mock import AsyncMock, MagicMock

from app.db.models import CredentialType
from app.services.credential_catalog import (
    CatalogCredential,
    CredentialPromptMode,
    format_credentials_prompt,
    load_credential_catalog,
)
from app.services.generated_credentials import (
    CredentialChoice,
    CredentialNeed,
    format_credential_choices,
    requires_credentials_payload,
)


class CatalogNeverCarriesValuesTests(unittest.IsolatedAsyncioTestCase):
    async def test_catalog_query_selects_only_id_name_and_type(self) -> None:
        result = MagicMock()
        result.all.return_value = []
        db = MagicMock()
        db.execute = AsyncMock(return_value=result)

        await load_credential_catalog(db, uuid.uuid4())

        statement = db.execute.await_args.args[0]
        self.assertEqual([c.name for c in statement.selected_columns], ["id", "name", "type"])

    def test_catalog_entries_have_no_field_for_a_value(self) -> None:
        self.assertEqual(set(CatalogCredential.__dataclass_fields__), {"id", "name", "type"})

    def test_off_mode_names_no_credential(self) -> None:
        credential = CatalogCredential(uuid.uuid4(), "github-work", CredentialType.github)

        prompt = format_credentials_prompt([credential], CredentialPromptMode.OFF)

        self.assertNotIn("github-work", prompt)
        self.assertNotIn(str(credential.id), prompt)

    def test_choices_and_needs_carry_names_only(self) -> None:
        text = format_credential_choices([CredentialChoice(CredentialType.github, "github-work")])
        payload = requires_credentials_payload(
            [CredentialNeed("fetchRepos", "github", "credentialId", ("github",), ("github-work",))]
        )

        self.assertIn("github-work", text)
        self.assertEqual(
            set(payload["needs"][0]),
            {"node", "node_type", "field", "credential_types", "existing"},
        )


if __name__ == "__main__":
    unittest.main()
