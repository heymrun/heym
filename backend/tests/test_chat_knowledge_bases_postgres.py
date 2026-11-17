"""Knowledge base chat tools against a real PostgreSQL: who sees and searches which store."""

import unittest
import uuid
from unittest.mock import MagicMock, patch

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.api import chat_knowledge_bases as chat
from app.db.models import (
    Credential,
    CredentialType,
    Team,
    TeamMember,
    User,
    VectorStore,
    VectorStoreShare,
    VectorStoreTeamShare,
)
from app.services.encryption import encrypt_config
from app.services.vector_store import SearchResult
from tests.board_pg_support import cleanup, connect_or_skip, make_user


async def _make_store(
    engine: AsyncEngine,
    owner: User,
    name: str,
    description: str,
    encrypted_config: str = "unused",
) -> VectorStore:
    async with AsyncSession(engine, expire_on_commit=False) as db:
        credential = Credential(
            owner_id=owner.id,
            name=f"qdrant-{uuid.uuid4()}",
            type=CredentialType.qdrant,
            encrypted_config=encrypted_config,
            # A Kubernetes Secret pointer is stored as the credential's source too.
            source=encrypted_config if encrypted_config.startswith("k8s:") else None,
        )
        db.add(credential)
        await db.flush()
        store = VectorStore(
            name=name,
            description=description,
            collection_name=f"kb-{uuid.uuid4()}",
            owner_id=owner.id,
            credential_id=credential.id,
        )
        db.add(store)
        await db.commit()
        return store


class ChatKnowledgeBaseAccessTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.engine = await connect_or_skip(self)
        self.owner = await make_user(self.engine, "owner")
        self.direct = await make_user(self.engine, "direct")
        self.member = await make_user(self.engine, "member")
        self.outsider = await make_user(self.engine, "outsider")
        self.users = [self.owner, self.direct, self.member, self.outsider]
        self.policies = await _make_store(self.engine, self.owner, "Policies", "Refund policy")
        self.handbook = await _make_store(self.engine, self.owner, "handbook", "HR handbook")
        self.private = await _make_store(self.engine, self.owner, "Private", "Owner only")
        async with AsyncSession(self.engine, expire_on_commit=False) as db:
            db.add(VectorStoreShare(vector_store_id=self.policies.id, user_id=self.direct.id))
            self.team = Team(name=f"team-{uuid.uuid4()}", creator_id=self.owner.id)
            db.add(self.team)
            await db.flush()
            db.add(
                TeamMember(team_id=self.team.id, user_id=self.member.id, added_by_id=self.owner.id)
            )
            db.add(VectorStoreTeamShare(vector_store_id=self.handbook.id, team_id=self.team.id))
            # A direct share on top of team access must not list the store twice.
            db.add(VectorStoreShare(vector_store_id=self.handbook.id, user_id=self.member.id))
            await db.commit()

    async def asyncTearDown(self) -> None:
        await cleanup(self.engine, self.users, [self.team])

    async def _call(self, user: User, tool: str, **args: object) -> dict:
        async with AsyncSession(self.engine, expire_on_commit=False) as db:
            return await chat.call_knowledge_base_tool(db, user, tool, args)

    async def _names(self, user: User) -> list[tuple[str, str]]:
        listed = await self._call(user, "list_knowledge_bases")
        return [(entry["name"], entry["access"]) for entry in listed["knowledge_bases"]]

    async def test_each_user_lists_exactly_the_stores_they_reach(self) -> None:
        self.assertEqual(
            await self._names(self.owner),
            [("handbook", "owner"), ("Policies", "owner"), ("Private", "owner")],
        )
        self.assertEqual(await self._names(self.direct), [("Policies", "shared")])
        self.assertEqual(await self._names(self.member), [("handbook", "shared")])
        self.assertEqual(await self._names(self.outsider), [])

    async def test_the_prompt_block_follows_the_same_access(self) -> None:
        async with AsyncSession(self.engine) as db:
            member_block = await chat.knowledge_bases_prompt_block(db, self.member.id)
            outsider_block = await chat.knowledge_bases_prompt_block(db, self.outsider.id)

        self.assertIn(f"- handbook (id {self.handbook.id}): HR handbook", member_block)
        self.assertNotIn("Policies", member_block)
        self.assertEqual(outsider_block, "")

    async def test_an_outsider_cannot_search_or_read_a_store(self) -> None:
        service = MagicMock()
        with patch(
            "app.api.vector_stores.get_vector_store_service_from_config", return_value=service
        ):
            searched = await self._call(
                self.outsider,
                "search_knowledge_base",
                query="refund",
                knowledge_base_ids=[str(self.policies.id)],
            )
            documents = await self._call(
                self.outsider, "list_knowledge_bases", knowledge_base_id=str(self.policies.id)
            )

        self.assertEqual(searched["error"], "Knowledge base not found")
        self.assertEqual(documents, {"error": "Knowledge base not found"})
        service.search.assert_not_called()
        service.list_items.assert_not_called()

    async def test_a_team_member_searches_through_the_route(self) -> None:
        service = MagicMock()
        service.search.return_value = [
            SearchResult(id="p1", text="Ask HR.", score=0.8, metadata={"source": "hr.md"})
        ]
        with (
            patch("app.api.vector_stores.decrypt_config", return_value={}),
            patch(
                "app.api.vector_stores.get_vector_store_service_from_config",
                return_value=service,
            ),
        ):
            result = await self._call(
                self.member,
                "search_knowledge_base",
                query="leave policy",
                knowledge_base_ids=[str(self.handbook.id), str(self.private.id)],
            )

        service.search.assert_called_once_with(
            self.handbook.collection_name, "leave policy", limit=5
        )
        self.assertEqual(result["knowledge_bases"][0]["knowledge_base_name"], "handbook")
        self.assertEqual(result["knowledge_bases"][0]["results"][0]["source"], "hr.md")
        self.assertEqual(
            result["errors"],
            [{"knowledge_base_id": str(self.private.id), "error": "Knowledge base not found"}],
        )

    async def test_a_store_whose_secret_is_not_synced_is_reported_and_the_others_answer(
        self,
    ) -> None:
        healthy = await _make_store(
            self.engine, self.owner, "Benefits", "Benefits", encrypt_config({"k": "v"})
        )
        unsynced = await _make_store(
            self.engine, self.owner, "Contracts", "Contracts", "k8s:heym/contracts-qdrant"
        )
        service = MagicMock()
        service.search.return_value = [
            SearchResult(id="b1", text="Dental is covered.", score=0.7, metadata={})
        ]
        service.list_items.return_value = ([], 0)
        with patch(
            "app.api.vector_stores.get_vector_store_service_from_config", return_value=service
        ):
            result = await self._call(
                self.owner,
                "search_knowledge_base",
                query="dental",
                knowledge_base_ids=[str(healthy.id), str(unsynced.id)],
            )
            documents = await self._call(
                self.owner, "list_knowledge_bases", knowledge_base_id=str(unsynced.id)
            )

        self.assertEqual(
            [group["knowledge_base_name"] for group in result["knowledge_bases"]], ["Benefits"]
        )
        self.assertEqual(len(result["errors"]), 1)
        self.assertEqual(result["errors"][0]["knowledge_base_name"], "Contracts")
        self.assertIn("not synced from Kubernetes", result["errors"][0]["error"])
        self.assertIn("not synced from Kubernetes", documents["error"])
        service.list_items.assert_not_called()
