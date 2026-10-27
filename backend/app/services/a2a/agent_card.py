"""The Heym Agent's A2A Agent Card: public, and extended for an authenticated client.

The public card is served without authentication, so it describes the agent and how to
reach it and nothing else: no server name, no workflow, no user. The extended card adds
the named server's name and the workflows assigned to it.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass

from app.config import settings
from app.services.a2a.models import (
    A2A_PROTOCOL_VERSION,
    AgentCapabilities,
    AgentCard,
    AgentInterface,
    AgentProvider,
    AgentSkill,
    APIKeySecurityScheme,
    AuthorizationCodeOAuthFlow,
    OAuth2SecurityScheme,
    OAuthFlows,
    SecurityRequirement,
    SecurityScheme,
    StringList,
)
from app.services.heym_agent.profile import A2A_DESCRIPTION, AGENT_NAME, AGENT_SKILLS

API_KEY_SCHEME = "heymApiKey"
OAUTH_SCHEME = "heymOAuth"
_MODES = ("text/plain", "application/json")


@dataclass(frozen=True)
class CardWorkflow:
    id: uuid.UUID
    name: str
    description: str | None


def global_endpoint_url(public_base_url: str) -> str:
    return f"{public_base_url.rstrip('/')}/api/a2a"


def global_card_url(public_base_url: str) -> str:
    return f"{public_base_url.rstrip('/')}/.well-known/agent-card.json"


def server_endpoint_url(public_base_url: str, server_id: uuid.UUID) -> str:
    return f"{public_base_url.rstrip('/')}/api/a2a/servers/{server_id}"


def server_card_url(public_base_url: str, server_id: uuid.UUID) -> str:
    return f"{server_endpoint_url(public_base_url, server_id)}/agent-card.json"


def _one_line(text: str | None, fallback: str) -> str:
    return " ".join(str(text or "").split())[:200] or fallback


def _security_schemes(base: str) -> dict[str, SecurityScheme]:
    issuer = (settings.oauth_issuer or base).rstrip("/")
    return {
        API_KEY_SCHEME: SecurityScheme(
            api_key_security_scheme=APIKeySecurityScheme(
                description="The MCP server's API key from Heym's MCP / A2A tab.",
                location="header",
                name="X-MCP-Key",
            )
        ),
        OAUTH_SCHEME: SecurityScheme(
            oauth2_security_scheme=OAuth2SecurityScheme(
                description="Sign in to Heym; the same OAuth server MCP clients use.",
                flows=OAuthFlows(
                    authorization_code=AuthorizationCodeOAuthFlow(
                        authorization_url=f"{issuer}/authorize",
                        token_url=f"{issuer}/token",
                        refresh_url=f"{issuer}/token",
                        pkce_required=True,
                    )
                ),
                oauth2_metadata_url=f"{issuer}/.well-known/oauth-authorization-server",
            )
        ),
    }


def public_card(*, endpoint_url: str, public_base_url: str) -> AgentCard:
    """The card anyone can fetch for one surface's endpoint."""
    base = public_base_url.rstrip("/")
    return AgentCard(
        name=AGENT_NAME,
        description=A2A_DESCRIPTION,
        supported_interfaces=[
            AgentInterface(
                url=endpoint_url,
                protocol_binding="JSONRPC",
                protocol_version=A2A_PROTOCOL_VERSION,
            )
        ],
        provider=AgentProvider(organization="Heym", url="https://heym.run"),
        version=settings.resolved_version,
        documentation_url=f"{base}/docs/reference/a2a",
        capabilities=AgentCapabilities(
            streaming=True, push_notifications=False, extended_agent_card=True
        ),
        security_schemes=_security_schemes(base),
        security_requirements=[
            SecurityRequirement(schemes={API_KEY_SCHEME: StringList()}),
            SecurityRequirement(schemes={OAUTH_SCHEME: StringList()}),
        ],
        default_input_modes=list(_MODES),
        default_output_modes=list(_MODES),
        skills=[
            AgentSkill(
                id=skill.id,
                name=skill.name,
                description=skill.description,
                tags=list(skill.tags),
                examples=list(skill.examples),
            )
            for skill in AGENT_SKILLS
        ],
        icon_url=f"{base}/fav.svg",
    )


def extended_card(
    *,
    endpoint_url: str,
    public_base_url: str,
    server_name: str | None,
    workflows: Sequence[CardWorkflow],
) -> AgentCard:
    """The card an authenticated client gets: the server's name and its workflows."""
    card = public_card(endpoint_url=endpoint_url, public_base_url=public_base_url)
    workflow_skills = []
    for workflow in workflows:
        name = _one_line(workflow.name, "Workflow")
        workflow_skills.append(
            AgentSkill(
                id=f"workflow-{workflow.id}",
                name=name,
                description=_one_line(workflow.description, f"Run the workflow {name}."),
                tags=["workflow"],
            )
        )
    name = f"{AGENT_NAME}: {_one_line(server_name, 'MCP server')}" if server_name else AGENT_NAME
    return card.model_copy(update={"name": name, "skills": [*card.skills, *workflow_skills]})
