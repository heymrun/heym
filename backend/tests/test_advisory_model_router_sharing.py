"""The Model Router's transitive grant is deliberate, and bounded.

Sharing a router lets the recipient *run* requests against the credentials it points
at. It must never let them *read* those credentials. These tests pin both halves: the
grant is checked once at write time, and no key crosses any response, node output or
metadata at run time.
"""

import unittest
import uuid
from unittest import mock

from app.api.credentials import get_masked_value, get_public_credential_fields
from app.db.models import CredentialType

SECRET = "sk-router-option-key-must-never-appear"


def _router_config() -> dict:
    return {
        "decision_credential_id": str(uuid.uuid4()),
        "decision_model": "jev-latest",
        "routing_instructions": "Pick the cheapest model that works.",
        "options": [
            {
                "id": "opt_1",
                "label": "Fast",
                "credential_id": str(uuid.uuid4()),
                "model": "gpt-4o-mini",
                "criteria": "Short questions.",
                "is_default": True,
            },
            {
                "id": "opt_2",
                "label": "Deep",
                "credential_id": str(uuid.uuid4()),
                "model": "gpt-5",
                "criteria": "Hard questions.",
            },
        ],
    }


class TestNoKeyLeavesTheRouter(unittest.TestCase):
    def test_the_stored_config_holds_no_key_to_leak(self) -> None:
        self.assertNotIn("api_key", str(_router_config()))

    def test_public_fields_expose_only_a_summary(self) -> None:
        fields = get_public_credential_fields(CredentialType.model_router, _router_config())
        self.assertEqual(set(fields), {"decision_model", "option_count"})

    def test_masked_value_is_none_not_a_key(self) -> None:
        self.assertIsNone(get_masked_value(CredentialType.model_router, _router_config()))

    def test_the_config_read_endpoint_returns_no_key_field(self) -> None:
        from app.models.schemas import ModelRouterConfigResponse, ModelRouterOptionResponse

        # The endpoint returns the config in full, so the response models are the
        # boundary: a key field here would hand a collaborator the owner's credentials.
        self.assertNotIn("api_key", ModelRouterConfigResponse.model_fields)
        self.assertNotIn("api_key", ModelRouterOptionResponse.model_fields)

    def test_routing_summary_names_credentials_but_carries_no_key(self) -> None:
        from app.db.models import CredentialType as CredType
        from app.services import llm_service as llm_service_module
        from app.services.llm_service import LLMService
        from app.services.model_router import BoundOption, RouteDecision, RouterOption

        option = RouterOption(
            id="opt_1",
            label="Fast",
            credential_id=str(uuid.uuid4()),
            model="gpt-4o-mini",
            criteria="easy",
        )
        bound = BoundOption(
            option=option,
            credential_type="openai",
            api_key=SECRET,
            base_url=None,
            credential_name="OpenAI prod",
            credential_uuid=uuid.uuid4(),
        )
        router = mock.Mock()
        router.label = "Auto Model"
        router.credential_id = str(uuid.uuid4())
        router.route.return_value = RouteDecision(option=option)

        service = LLMService(credential_type=CredType.model_router, api_key="", router=router)
        with (
            mock.patch.object(llm_service_module, "load_option_credential", return_value=bound),
            mock.patch.object(llm_service_module, "create_openai_client", return_value=mock.Mock()),
        ):
            service._resolve_turn(
                model="auto", system_instruction=None, message="m", tool_names=None
            )

        summary = service.model_routing_summary()
        self.assertEqual(summary["calls"][0]["credentialName"], "OpenAI prod")
        # The summary is written into node metadata and persisted to node_results, so
        # the key must not be reachable anywhere inside it.
        self.assertNotIn(SECRET, str(summary))

    def test_routing_state_carries_no_credential_material(self) -> None:
        from app.services.model_router import build_routing_state

        state = build_routing_state(
            system_instruction="You are helpful.",
            message="What is 2+2?",
            tool_names=["search"],
        )
        self.assertEqual(set(state), {"system", "message", "tools"})

        later = build_routing_state(
            system_instruction="You are helpful.",
            message="What is 2+2?",
            tool_names=["search"],
            latest_tool_output="4",
        )
        self.assertEqual(set(later), {"system", "message", "latest_tool_output", "tools"})


class TestGrantIsCheckedAtWriteTime(unittest.TestCase):
    def test_run_time_loading_does_not_re_check_the_caller(self) -> None:
        import inspect

        from app.services import model_router

        source = inspect.getsource(model_router.load_option_credential)
        # If this ever gains a per-user check, the design changed, and the docs plus the
        # sharing notice in the credential dialog have to change with it.
        self.assertNotIn("user_id", source)
        self.assertIn("Access is not re-checked", source)

    def test_write_time_validation_exists_and_checks_access(self) -> None:
        import inspect

        from app.api import credentials as credentials_api

        source = inspect.getsource(credentials_api.validate_model_router_references)
        self.assertIn("_get_accessible_credential", source)
        self.assertIn("ROUTER_OPTION_CREDENTIAL_TYPES", source)

    def test_create_and_update_both_validate_references(self) -> None:
        import inspect

        from app.api import credentials as credentials_api

        create = inspect.getsource(credentials_api.create_credential)
        update = inspect.getsource(credentials_api.update_credential)
        # Validating only on create would let an update swap in a credential the owner
        # never had access to.
        self.assertIn("validate_model_router_references", create)
        self.assertIn("validate_model_router_references", update)


if __name__ == "__main__":
    unittest.main()
