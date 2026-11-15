"""Sharing finds a colleague by the address they sign in with, in any letter case.

Accounts keep the address as typed and sign-in ignores case (`find_user_by_email`); the
share endpoints compared exactly, so `jane.doe@corp.example` was "User not found" for an
account registered as `Jane.Doe@corp.example`.
"""

from __future__ import annotations

import re
import unittest
import uuid
from pathlib import Path

import httpx
from fastapi import FastAPI
from sqlalchemy import delete
from workflow_concurrency_fixtures import ConcurrencyPostgresCase

from app.api import workflows as workflows_api
from app.api.deps import get_current_user
from app.db.models import User, WorkflowShare
from app.db.session import async_session_maker

API_DIR = Path(__file__).resolve().parents[1] / "app" / "api"


class ShareLookupSourceTests(unittest.TestCase):
    def test_no_router_looks_a_user_up_by_exact_email(self) -> None:
        offenders = [
            f"{path.name}:{number}"
            for path in sorted(API_DIR.glob("*.py"))
            for number, line in enumerate(path.read_text().splitlines(), start=1)
            if re.search(r"User\.email\s*==", line)
        ]
        self.assertEqual(offenders, [], "use services.user_lookup.find_user_by_email")


class WorkflowShareEmailCaseTests(ConcurrencyPostgresCase):
    limit = None

    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        self.jane_id = uuid.uuid4()
        self.jane_email = f"Jane.Doe.{self.jane_id.hex[:8]}@corp.example"
        async with async_session_maker() as db:
            db.add(User(id=self.jane_id, email=self.jane_email, hashed_password="x", name="Jane"))
            await db.commit()
            self.owner = await db.get(User, self.user_id)
        self.addAsyncCleanup(self._remove_jane)

    async def _remove_jane(self) -> None:
        async with async_session_maker() as db:
            await db.execute(delete(WorkflowShare).where(WorkflowShare.user_id == self.jane_id))
            await db.execute(delete(User).where(User.id == self.jane_id))
            await db.commit()

    async def _share(self, email: str) -> httpx.Response:
        app = FastAPI()
        app.include_router(workflows_api.router, prefix="/api/workflows")
        app.dependency_overrides[get_current_user] = lambda: self.owner
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://heym") as client:
            return await client.post(
                f"/api/workflows/{self.workflow_id}/shares", json={"email": email}
            )

    async def test_sharing_ignores_the_letter_case_of_the_address(self) -> None:
        response = await self._share(f"  {self.jane_email.lower()} ")

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["email"], self.jane_email)

    async def test_an_unknown_address_is_still_not_found(self) -> None:
        response = await self._share(f"nobody-{uuid.uuid4().hex[:8]}@corp.example")

        self.assertEqual(response.status_code, 404)


class TemplateSharedWithEmailCaseTests(unittest.TestCase):
    def test_a_template_shared_with_an_address_is_visible_in_any_letter_case(self) -> None:
        from types import SimpleNamespace

        from app.db.models import TemplateVisibility
        from app.services.template_service import _is_template_visible

        template = SimpleNamespace(
            author_id=uuid.uuid4(),
            visibility=TemplateVisibility.specific_users,
            shared_with=[" jane.doe@corp.example "],
            shared_with_teams=[],
        )
        jane = SimpleNamespace(id=uuid.uuid4(), email="Jane.Doe@corp.example")
        other = SimpleNamespace(id=uuid.uuid4(), email="john@corp.example")

        self.assertTrue(_is_template_visible(template, jane, set()))
        self.assertFalse(_is_template_visible(template, other, set()))
