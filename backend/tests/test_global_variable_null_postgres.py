"""A global variable that holds null is listed instead of failing the whole list.

A global Variable node whose expression found nothing stores `None`. The list and get
response models did not accept it, so GET /api/global-variables answered 500.
"""

import asyncio
import uuid
from types import SimpleNamespace

from sqlalchemy import delete
from workflow_concurrency_fixtures import ConcurrencyPostgresCase

from app.api import global_variables as api
from app.api.workflows import _persist_global_variables_from_execution
from app.db.models import GlobalVariable
from app.db.session import async_session_maker
from app.services.workflow_executor import execute_workflow

NODES = [
    {
        "id": "s",
        "type": "textInput",
        "position": {"x": 0, "y": 0},
        "data": {"label": "start", "inputFields": [{"key": "customer"}]},
    },
    {
        "id": "v",
        "type": "variable",
        "position": {"x": 200, "y": 0},
        "data": {
            "label": "save",
            "variableName": "lastCustomer",
            "variableValue": "$start.body.customer",
            "variableType": "auto",
            "isGlobal": True,
        },
    },
]
EDGES = [{"id": "e1", "source": "s", "target": "v"}]


class GlobalVariableNullTests(ConcurrencyPostgresCase):
    limit = None

    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        self.addAsyncCleanup(self._drop_variables)
        self.user = SimpleNamespace(id=self.user_id)

    async def _drop_variables(self) -> None:
        async with async_session_maker() as db:
            await db.execute(delete(GlobalVariable).where(GlobalVariable.owner_id == self.user_id))
            await db.commit()

    async def _run(self, body: dict) -> None:
        result = await asyncio.to_thread(
            execute_workflow,
            uuid.uuid4(),
            NODES,
            EDGES,
            {"headers": {}, "query": {}, "body": body},
        )
        async with async_session_maker() as db:
            await _persist_global_variables_from_execution(
                db, self.user_id, NODES, {}, result.node_results, []
            )
            await db.commit()

    async def _listed(self) -> list[tuple[str, object]]:
        async with async_session_maker() as db:
            rows = await api.list_global_variables(current_user=self.user, db=db)
        return [(row.name, row.value) for row in rows]

    async def test_a_variable_holding_null_is_listed(self) -> None:
        await self._run({})

        self.assertEqual(await self._listed(), [("lastCustomer", None)])

    async def test_a_variable_holding_null_can_be_opened(self) -> None:
        await self._run({})
        async with async_session_maker() as db:
            variable_id = (await api.list_global_variables(current_user=self.user, db=db))[0].id
            fetched = await api.get_global_variable(variable_id, current_user=self.user, db=db)

        self.assertIsNone(fetched.value)

    async def test_a_value_still_lists_as_before(self) -> None:
        await self._run({"customer": "Ada"})

        self.assertEqual(await self._listed(), [("lastCustomer", "Ada")])
