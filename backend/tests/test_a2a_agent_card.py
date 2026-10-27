"""The Agent Card: a valid A2A 1.0 card that says nothing about the user."""

import json
import unittest
import uuid

from app.services.a2a.agent_card import (
    CardWorkflow,
    extended_card,
    global_card_url,
    global_endpoint_url,
    public_card,
    server_card_url,
    server_endpoint_url,
)

BASE = "https://heym.example.com"


class CardTests(unittest.TestCase):
    def test_public_card_shape(self) -> None:
        card = public_card(endpoint_url=global_endpoint_url(BASE), public_base_url=BASE).wire()

        self.assertEqual(card["name"], "Heym Agent")
        self.assertEqual(
            card["supportedInterfaces"],
            [{"url": f"{BASE}/api/a2a", "protocolBinding": "JSONRPC", "protocolVersion": "1.0"}],
        )
        self.assertEqual(
            card["capabilities"],
            {"streaming": True, "pushNotifications": False, "extendedAgentCard": True},
        )
        self.assertEqual(card["defaultInputModes"], ["text/plain", "application/json"])
        self.assertEqual(
            card["securitySchemes"]["heymApiKey"],
            {
                "apiKeySecurityScheme": {
                    "description": "The MCP server's API key from Heym's MCP / A2A tab.",
                    "location": "header",
                    "name": "X-MCP-Key",
                }
            },
        )
        oauth = card["securitySchemes"]["heymOAuth"]["oauth2SecurityScheme"]
        self.assertTrue(oauth["flows"]["authorizationCode"]["tokenUrl"].endswith("/token"))
        self.assertEqual(
            card["securityRequirements"],
            [{"schemes": {"heymApiKey": {"list": []}}}, {"schemes": {"heymOAuth": {"list": []}}}],
        )
        self.assertEqual(card["documentationUrl"], f"{BASE}/docs/reference/a2a")
        self.assertIn("workflows", {skill["id"] for skill in card["skills"]})

    def test_urls(self) -> None:
        server_id = uuid.uuid4()
        self.assertEqual(global_card_url(BASE + "/"), f"{BASE}/.well-known/agent-card.json")
        self.assertEqual(
            server_endpoint_url(BASE, server_id), f"{BASE}/api/a2a/servers/{server_id}"
        )
        self.assertEqual(
            server_card_url(BASE, server_id),
            f"{BASE}/api/a2a/servers/{server_id}/agent-card.json",
        )

    def test_extended_card_names_the_server_and_its_workflows(self) -> None:
        workflow = CardWorkflow(id=uuid.uuid4(), name="Invoice\nParser", description=None)
        card = extended_card(
            endpoint_url=server_endpoint_url(BASE, uuid.uuid4()),
            public_base_url=BASE,
            server_name="Finance",
            workflows=[workflow],
        ).wire()

        self.assertEqual(card["name"], "Heym Agent: Finance")
        skill = card["skills"][-1]
        self.assertEqual(skill["id"], f"workflow-{workflow.id}")
        self.assertEqual(skill["name"], "Invoice Parser")
        self.assertEqual(skill["description"], "Run the workflow Invoice Parser.")

    def test_public_card_carries_no_server_or_workflow_name(self) -> None:
        text = json.dumps(
            public_card(
                endpoint_url=server_endpoint_url(BASE, uuid.uuid4()), public_base_url=BASE
            ).wire()
        )

        self.assertNotIn("Finance", text)
        self.assertNotIn("workflow-", text)
