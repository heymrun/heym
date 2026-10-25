"""The assistant may only put a credential on a node that the user can use.

The chat builder (Chat tab, `heym_chat` over MCP, the AI Builder tools) lists the
credentials the user owns or was shared, and fills `llm` and `agent` nodes with the chat's
own model credential. None of that may reach a credential shared with someone else, shared
with a team the user is not in, or private to another account: not through the prompt, not
through an id the model writes, not through the chat credential, and not by moving an id an
edited node already held into another field or node.

The real-PostgreSQL tests require a reachable database with migrations applied, like every
other `RealPostgres*` test (see AGENTS.md, "PostgreSQL Integration Tests").
"""

import unittest
import uuid
from types import SimpleNamespace
from typing import Any

from sqlalchemy import delete

from app.api.ai_assistant import _sanitize_generated_workflow_nodes
from app.db.models import (
    Credential,
    CredentialShare,
    CredentialTeamShare,
    CredentialType,
    Team,
    TeamMember,
    User,
)
from app.db.session import async_session_maker, engine
from app.services.credential_access import (
    accessible_credential_clause,
    get_accessible_credential,
    load_accessible_credential_ids,
)
from app.services.credential_catalog import (
    CatalogCredential,
    CredentialPromptMode,
    load_credential_catalog,
)
from app.services.generated_credentials import apply_generated_credentials


class AccessibleCredentialClauseTests(unittest.TestCase):
    def test_every_branch_is_bound_to_this_user_only(self) -> None:
        user_id = uuid.uuid4()

        clause = accessible_credential_clause(user_id)

        sql = str(clause)
        self.assertIn("credentials.owner_id", sql)
        self.assertIn("credential_shares.user_id", sql)
        self.assertIn("team_members.user_id", sql)
        self.assertEqual(set(clause.compile().params.values()), {user_id})


class RealPostgresAssistantCredentialScopeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        await engine.dispose()
        self.owner_id = uuid.uuid4()
        self.member_id = uuid.uuid4()
        self.outsider_id = uuid.uuid4()
        self.member_team_id = uuid.uuid4()
        self.other_team_id = uuid.uuid4()
        self.ids = {
            name: uuid.uuid4()
            for name in (
                "member_own",
                "owner_shared_with_member",
                "owner_shared_with_member_team",
                "owner_private",
                "outsider_shared_with_owner",
                "outsider_shared_with_other_team",
            )
        }
        async with async_session_maker() as session:
            session.add_all(
                [
                    User(
                        id=user_id,
                        email=f"{label}_{user_id.hex[:8]}@example.com",
                        hashed_password="x",
                        name=label,
                    )
                    for user_id, label in (
                        (self.owner_id, "owner"),
                        (self.member_id, "member"),
                        (self.outsider_id, "outsider"),
                    )
                ]
            )
            await session.flush()
            session.add_all(
                [
                    Team(id=self.member_team_id, name="Member team", creator_id=self.owner_id),
                    Team(id=self.other_team_id, name="Other team", creator_id=self.outsider_id),
                ]
            )
            await session.flush()
            session.add_all(
                [
                    TeamMember(
                        id=uuid.uuid4(), team_id=self.member_team_id, user_id=self.member_id
                    ),
                    TeamMember(id=uuid.uuid4(), team_id=self.member_team_id, user_id=self.owner_id),
                    TeamMember(
                        id=uuid.uuid4(), team_id=self.other_team_id, user_id=self.outsider_id
                    ),
                    TeamMember(id=uuid.uuid4(), team_id=self.other_team_id, user_id=self.owner_id),
                ]
            )
            owners = {
                "member_own": self.member_id,
                "owner_shared_with_member": self.owner_id,
                "owner_shared_with_member_team": self.owner_id,
                "owner_private": self.owner_id,
                "outsider_shared_with_owner": self.outsider_id,
                "outsider_shared_with_other_team": self.outsider_id,
            }
            session.add_all(
                [
                    Credential(
                        id=self.ids[name],
                        owner_id=owner_id,
                        name=f"{name}-{self.ids[name].hex[:6]}",
                        type=CredentialType.openai,
                        encrypted_config="x",
                    )
                    for name, owner_id in owners.items()
                ]
            )
            await session.flush()
            session.add_all(
                [
                    CredentialShare(
                        id=uuid.uuid4(),
                        credential_id=self.ids["owner_shared_with_member"],
                        user_id=self.member_id,
                    ),
                    CredentialShare(
                        id=uuid.uuid4(),
                        credential_id=self.ids["outsider_shared_with_owner"],
                        user_id=self.owner_id,
                    ),
                    CredentialTeamShare(
                        id=uuid.uuid4(),
                        credential_id=self.ids["owner_shared_with_member_team"],
                        team_id=self.member_team_id,
                    ),
                    CredentialTeamShare(
                        id=uuid.uuid4(),
                        credential_id=self.ids["outsider_shared_with_other_team"],
                        team_id=self.other_team_id,
                    ),
                ]
            )
            await session.commit()

    async def asyncTearDown(self) -> None:
        user_ids = [self.owner_id, self.member_id, self.outsider_id]
        async with async_session_maker() as session:
            await session.execute(delete(Credential).where(Credential.owner_id.in_(user_ids)))
            await session.execute(
                delete(TeamMember).where(
                    TeamMember.team_id.in_([self.member_team_id, self.other_team_id])
                )
            )
            await session.execute(
                delete(Team).where(Team.id.in_([self.member_team_id, self.other_team_id]))
            )
            await session.execute(delete(User).where(User.id.in_(user_ids)))
            await session.commit()
        await engine.dispose()

    def _expected(self) -> set[str]:
        return {
            str(self.ids[name])
            for name in (
                "member_own",
                "owner_shared_with_member",
                "owner_shared_with_member_team",
            )
        }

    async def test_member_sees_own_direct_and_team_shares_and_nothing_else(self) -> None:
        async with async_session_maker() as session:
            accessible = await load_accessible_credential_ids(session, self.member_id)
            catalog = await load_credential_catalog(session, self.member_id)

        self.assertEqual(accessible, self._expected())
        self.assertEqual({str(c.id) for c in catalog}, self._expected())
        shared = {str(c.id): c.shared for c in catalog}
        self.assertFalse(shared[str(self.ids["member_own"])])
        self.assertTrue(shared[str(self.ids["owner_shared_with_member"])])
        self.assertTrue(shared[str(self.ids["owner_shared_with_member_team"])])

    async def test_lists_agree_with_the_single_credential_check(self) -> None:
        """The assistant's lists and `get_accessible_credential` must never disagree."""
        async with async_session_maker() as session:
            accessible = await load_accessible_credential_ids(session, self.member_id)
            for name, credential_id in self.ids.items():
                with self.subTest(credential=name):
                    single = await get_accessible_credential(session, credential_id, self.member_id)
                    self.assertEqual(single is not None, str(credential_id) in accessible)

    async def test_revoking_a_share_removes_it(self) -> None:
        async with async_session_maker() as session:
            await session.execute(
                delete(CredentialShare).where(
                    CredentialShare.credential_id == self.ids["owner_shared_with_member"]
                )
            )
            await session.execute(
                delete(TeamMember).where(
                    TeamMember.team_id == self.member_team_id,
                    TeamMember.user_id == self.member_id,
                )
            )
            await session.commit()
            accessible = await load_accessible_credential_ids(session, self.member_id)
            catalog = await load_credential_catalog(session, self.member_id)

        self.assertEqual(accessible, {str(self.ids["member_own"])})
        self.assertEqual([c.id for c in catalog], [self.ids["member_own"]])


USER_CREDENTIAL = str(uuid.uuid4())
FOREIGN = str(uuid.uuid4())
CHAT = SimpleNamespace(id=uuid.UUID(USER_CREDENTIAL), owner_id=uuid.uuid4(), type="openai")


def _sanitize(
    nodes: list[dict[str, Any]],
    previous: list[dict[str, Any]] | None = None,
    selected: SimpleNamespace = CHAT,
) -> list[dict[str, Any]]:
    return _sanitize_generated_workflow_nodes(
        nodes,
        accessible_credential_ids={USER_CREDENTIAL},
        selected_credential=selected,
        selected_model="chat-model",
        previous_nodes=previous,
    )


def _agent(node_id: str = "a1", label: str = "writer", **data: Any) -> dict[str, Any]:
    return {"id": node_id, "type": "agent", "data": {"label": label, **data}}


class GeneratedNodesNeverGetAForeignCredentialTests(unittest.TestCase):
    def test_a_chat_credential_the_user_cannot_use_is_never_written(self) -> None:
        foreign_chat = SimpleNamespace(id=uuid.UUID(FOREIGN), owner_id=uuid.uuid4(), type="openai")

        (node,) = _sanitize([_agent(credentialId="YOUR_CREDENTIAL_ID")], selected=foreign_chat)

        self.assertEqual(node["data"]["credentialId"], "")

    def test_a_foreign_id_the_model_writes_on_a_new_node_is_dropped(self) -> None:
        (agent, browser) = _sanitize(
            [
                _agent(
                    credentialId=FOREIGN,
                    fallbackCredentialId=FOREIGN,
                    fallbackModel="m",
                    guardrailCredentialId=FOREIGN,
                    guardrailModel="m",
                ),
                {
                    "id": "p1",
                    "type": "playwright",
                    "data": {
                        "label": "browse",
                        "credentialId": FOREIGN,
                        "playwrightSteps": [
                            {"action": "aiStep", "credentialId": FOREIGN, "model": "m"}
                        ],
                    },
                },
            ]
        )

        self.assertEqual(agent["data"]["credentialId"], USER_CREDENTIAL)
        for field in ("fallbackCredentialId", "guardrailCredentialId"):
            self.assertEqual(agent["data"][field], "")
        self.assertEqual(browser["data"]["credentialId"], "")
        self.assertEqual(browser["data"]["playwrightSteps"][0]["credentialId"], "")
        self.assertEqual(browser["data"]["playwrightSteps"][0]["model"], "")

    def test_an_edit_cannot_move_an_id_the_node_held_into_another_field(self) -> None:
        previous = [_agent(credentialId=USER_CREDENTIAL, guardrailCredentialId=FOREIGN)]

        (node,) = _sanitize(
            [
                _agent(
                    credentialId=FOREIGN,
                    fallbackCredentialId=FOREIGN,
                    guardrailCredentialId=FOREIGN,
                )
            ],
            previous=previous,
        )

        self.assertEqual(node["data"]["credentialId"], USER_CREDENTIAL)
        self.assertEqual(node["data"]["fallbackCredentialId"], "")
        self.assertEqual(node["data"]["guardrailCredentialId"], FOREIGN)

    def test_an_edit_cannot_copy_an_id_onto_a_new_node(self) -> None:
        previous = [_agent(credentialId=FOREIGN)]

        nodes = _sanitize(
            [_agent(credentialId=FOREIGN), _agent("a2", "second", credentialId=FOREIGN)],
            previous=previous,
        )

        self.assertEqual(nodes[0]["data"]["credentialId"], FOREIGN)
        self.assertEqual(nodes[1]["data"]["credentialId"], USER_CREDENTIAL)

    def test_an_edit_cannot_move_a_step_credential_to_another_step(self) -> None:
        def browser(steps: list[dict[str, Any]]) -> dict[str, Any]:
            return {
                "id": "p1",
                "type": "playwright",
                "data": {"label": "b", "playwrightSteps": steps},
            }

        previous = [browser([{"action": "aiStep", "credentialId": FOREIGN, "model": "m"}])]

        (node,) = _sanitize(
            [
                browser(
                    [
                        {"action": "aiStep", "credentialId": FOREIGN, "model": "m"},
                        {"action": "aiStep", "credentialId": FOREIGN, "model": "m"},
                    ]
                )
            ],
            previous=previous,
        )

        steps = node["data"]["playwrightSteps"]
        self.assertEqual(steps[0]["credentialId"], FOREIGN)
        self.assertEqual(steps[1]["credentialId"], "")


class CredentialPassNeverResolvesAForeignCredentialTests(unittest.TestCase):
    def test_a_foreign_id_or_name_is_cleared_and_asked_for(self) -> None:
        catalog = [
            CatalogCredential(uuid.UUID(USER_CREDENTIAL), "team-slack", CredentialType.slack)
        ]
        for value in (FOREIGN, "someone-elses-slack"):
            with self.subTest(value=value):
                result = apply_generated_credentials(
                    [
                        {
                            "id": "s1",
                            "type": "slack",
                            "data": {"label": "post", "credentialId": value},
                        }
                    ],
                    catalog=catalog,
                    choices=[],
                    previous_nodes=None,
                    mode=CredentialPromptMode.ASK_AND_LINK,
                )

                self.assertEqual(result.nodes[0]["data"]["credentialId"], "")
                self.assertEqual(len(result.needs), 1)


if __name__ == "__main__":
    unittest.main()
