"""A negative limit or offset on a list endpoint is a 422, not a database error."""

import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
from fastapi import FastAPI

from app.api import boards as boards_api
from app.api import files as files_api
from app.api import workflows as workflows_api
from app.api.deps import get_current_user
from app.db.session import get_db


class NegativePageParamsTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.db = AsyncMock()
        app = FastAPI()
        app.include_router(workflows_api.router, prefix="/api/workflows")
        app.include_router(files_api.router, prefix="/api/files")
        app.include_router(boards_api.router, prefix="/api/boards")
        app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=uuid.uuid4())
        app.dependency_overrides[get_db] = lambda: self.db
        self.client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://heym"
        )
        self.addAsyncCleanup(self.client.aclose)

    async def test_negative_page_params_are_rejected_before_the_database(self) -> None:
        workflow_id, board_id, card_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
        paths = [
            "/api/workflows/history/all",
            f"/api/workflows/{workflow_id}/history",
            f"/api/workflows/{workflow_id}/versions",
            "/api/files",
            f"/api/boards/{board_id}/cards/{card_id}",
        ]
        for path in paths:
            for query in ("offset=-1", "limit=-1"):
                with self.subTest(path=path, query=query):
                    response = await self.client.get(f"{path}?{query}")
                    self.assertEqual(response.status_code, 422)
        self.db.execute.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
