"""A global variable switched between number and boolean keeps the new JSON value.

Python treats 1 == True and 0 == False. The stored value is a JSON object, so
SQLAlchemy would otherwise omit that column from the UPDATE and leave the old
value in place. The same holds for Object and Array variables that keep their
type but change 1 to true or 0 to false inside.
"""

import uuid
from types import SimpleNamespace

from sqlalchemy import delete, select
from workflow_concurrency_fixtures import ConcurrencyPostgresCase

from app.api.global_variables import update_global_variable
from app.db.models import GlobalVariable
from app.db.session import async_session_maker
from app.models.schemas import GlobalVariableUpdate

# (label, old value, old type, new value, new type, expected stored value)
_CASES = (
    ("number 1 to boolean true", 1, "number", True, "boolean", True),
    ("boolean true to number 1", True, "boolean", 1, "number", 1),
    ("number 0 to boolean false", 0, "number", False, "boolean", False),
    ("boolean false to number 0", False, "boolean", 0, "number", 0),
    ("object {on: 1} to {on: true}", {"on": 1}, "object", {"on": True}, "object", {"on": True}),
    ("array [1, 0] to [true, false]", [1, 0], "array", [True, False], "array", [True, False]),
)


def _same(a: object, b: object) -> bool:
    """Equality that tells 1 from True, also inside lists and dicts."""
    if type(a) is not type(b):
        return False
    if isinstance(a, dict):
        return a.keys() == b.keys() and all(_same(a[k], b[k]) for k in a)
    if isinstance(a, list):
        return len(a) == len(b) and all(_same(x, y) for x, y in zip(a, b))
    return a == b


class GlobalVariableBooleanNumberSwitchTests(ConcurrencyPostgresCase):
    limit = None

    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        self.addAsyncCleanup(self._drop_variables)
        self.user = SimpleNamespace(id=self.user_id)

    async def _drop_variables(self) -> None:
        async with async_session_maker() as db:
            await db.execute(delete(GlobalVariable).where(GlobalVariable.owner_id == self.user_id))
            await db.commit()

    async def _switch(self, old: object, old_type: str, new: object, new_type: str) -> tuple:
        async with async_session_maker() as db:
            variable = GlobalVariable(
                owner_id=self.user_id,
                name=f"featureOn-{uuid.uuid4().hex[:8]}",
                value={"v": old},
                value_type=old_type,
            )
            db.add(variable)
            await db.commit()
            variable_id = variable.id
        async with async_session_maker() as db:
            await update_global_variable(
                variable_id,
                GlobalVariableUpdate(value=new, value_type=new_type),
                current_user=self.user,
                db=db,
            )
            await db.commit()
        async with async_session_maker() as fresh:
            stored = (
                await fresh.execute(select(GlobalVariable).where(GlobalVariable.id == variable_id))
            ).scalar_one()
        return stored.value_type, stored.value["v"]

    async def test_equal_python_values_of_different_types_are_stored(self) -> None:
        for label, old, old_type, new, new_type, expect in _CASES:
            with self.subTest(label):
                value_type, got = await self._switch(old, old_type, new, new_type)
                self.assertEqual(value_type, new_type)
                self.assertTrue(_same(got, expect), f"stored {got!r}, expected {expect!r}")

    async def test_a_number_that_is_not_equal_in_python_is_stored(self) -> None:
        value_type, got = await self._switch(True, "boolean", 2, "number")
        self.assertEqual(value_type, "number")
        self.assertTrue(_same(got, 2))
