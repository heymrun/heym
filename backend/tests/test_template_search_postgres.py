"""Template search matches name, description, tags and node type, against PostgreSQL."""

import unittest
import uuid

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import NodeTemplate, User, WorkflowTemplate
from app.services.template_service import list_node_templates, list_workflow_templates
from tests.board_pg_support import connect_or_skip, make_user


class TemplateSearchPostgresTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.engine = await connect_or_skip(self)
        self.owner = await make_user(self.engine, "template-search")
        self.other = await make_user(self.engine, "template-search-other")
        self.marker = uuid.uuid4().hex[:8]
        async with AsyncSession(self.engine) as db:
            db.add_all(
                [
                    WorkflowTemplate(
                        author_id=self.owner.id,
                        name=f"Lead sync {self.marker}",
                        description="Copies new leads",
                        tags=[f"crm{self.marker}", f"zürich{self.marker}"],
                        nodes=[{"id": "a", "type": f"hubspot{self.marker}", "data": {}}],
                        edges=[],
                        visibility="everyone",
                    ),
                    WorkflowTemplate(
                        author_id=self.other.id,
                        name=f"Private {self.marker}",
                        description=None,
                        tags=[f"crm{self.marker}"],
                        nodes=[],
                        edges=[],
                        visibility="specific_users",
                        shared_with=[],
                    ),
                    NodeTemplate(
                        author_id=self.owner.id,
                        name=f"Tuned writer {self.marker}",
                        description="Short replies",
                        tags=[f"copy{self.marker}"],
                        node_type=f"llm{self.marker}",
                        node_data={},
                        visibility="everyone",
                    ),
                ]
            )
            await db.commit()

    async def asyncTearDown(self) -> None:
        async with AsyncSession(self.engine) as db:
            for user in (self.owner, self.other):
                await db.execute(
                    delete(WorkflowTemplate).where(WorkflowTemplate.author_id == user.id)
                )
                await db.execute(delete(NodeTemplate).where(NodeTemplate.author_id == user.id))
                await db.execute(delete(User).where(User.id == user.id))
            await db.commit()
        await self.engine.dispose()

    async def _names(self, search: str | None) -> list[str]:
        async with AsyncSession(self.engine) as db:
            workflows = await list_workflow_templates(db, self.owner, search=search)
            nodes = await list_node_templates(db, self.owner, search=search)
        return sorted(t.name for t in [*workflows, *nodes] if self.marker in t.name)

    async def test_a_tag_finds_its_template(self) -> None:
        self.assertEqual(await self._names(f"CRM{self.marker}"), [f"Lead sync {self.marker}"])
        self.assertEqual(await self._names(f"copy{self.marker}"), [f"Tuned writer {self.marker}"])
        self.assertEqual(await self._names(f"Zürich{self.marker}"), [f"Lead sync {self.marker}"])

    async def test_a_node_type_finds_its_template(self) -> None:
        self.assertEqual(await self._names(f"hubspot{self.marker}"), [f"Lead sync {self.marker}"])
        self.assertEqual(await self._names(f"llm{self.marker}"), [f"Tuned writer {self.marker}"])

    async def test_name_and_description_still_match_and_visibility_still_applies(self) -> None:
        self.assertEqual(
            await self._names(f"lead sync {self.marker}"), [f"Lead sync {self.marker}"]
        )
        self.assertEqual(await self._names("short replies"), [f"Tuned writer {self.marker}"])
        # Another user's private template stays hidden even when its tag matches.
        self.assertEqual(
            await self._names(None), [f"Lead sync {self.marker}", f"Tuned writer {self.marker}"]
        )


if __name__ == "__main__":
    unittest.main()
