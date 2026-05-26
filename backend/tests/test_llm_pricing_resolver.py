import unittest
import uuid
from decimal import Decimal
from unittest.mock import AsyncMock

from app.services.llm_pricing import resolve_costs_for_user


class _Row:
    """Lightweight stand-in for ORM rows returned by db.execute(...).all()."""

    def __init__(self, **kw):
        self.__dict__.update(kw)


def _global(model: str, op: str = "equals", inp: float = 1.0, out: float = 2.0) -> _Row:
    return _Row(
        provider="ANTHROPIC",
        model=model,
        operator=op,
        input_per_1m_usd=Decimal(str(inp)),
        output_per_1m_usd=Decimal(str(out)),
    )


def _override(model: str, inp: float = 0.5, out: float = 1.0) -> _Row:
    return _Row(
        model=model,
        input_per_1m_usd=Decimal(str(inp)),
        output_per_1m_usd=Decimal(str(out)),
    )


class ResolverTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.user_id = uuid.uuid4()

    def _db_with(self, globals_=(), overrides=()) -> AsyncMock:
        db = AsyncMock()
        scalars_global = AsyncMock()
        scalars_global.all = lambda: list(globals_)
        scalars_override = AsyncMock()
        scalars_override.all = lambda: list(overrides)
        exec_global = AsyncMock()
        exec_global.scalars = lambda: scalars_global
        exec_override = AsyncMock()
        exec_override.scalars = lambda: scalars_override
        db.execute = AsyncMock(side_effect=[exec_global, exec_override])
        return db

    async def test_equals_match_computes_cost(self):
        db = self._db_with(globals_=[_global("gpt-4o", "equals", 5, 15)])
        out = await resolve_costs_for_user(db, self.user_id, [("gpt-4o", 1_000_000, 1_000_000)])
        self.assertEqual(out, [(Decimal("20"), True)])

    async def test_startswith_picks_longest_match(self):
        db = self._db_with(
            globals_=[
                _global("gpt-4", "startsWith", 1, 2),
                _global("gpt-4o-mini", "startsWith", 10, 20),
            ]
        )
        out = await resolve_costs_for_user(
            db, self.user_id, [("gpt-4o-mini-2024-07-18", 1_000_000, 0)]
        )
        self.assertEqual(out, [(Decimal("10"), True)])

    async def test_includes_match(self):
        db = self._db_with(globals_=[_global("haiku", "includes", 0.25, 1.25)])
        out = await resolve_costs_for_user(
            db, self.user_id, [("claude-3-haiku-20240307", 0, 1_000_000)]
        )
        self.assertEqual(out, [(Decimal("1.25"), True)])

    async def test_override_beats_global(self):
        db = self._db_with(
            globals_=[_global("gpt-4o", "equals", 5, 15)],
            overrides=[_override("gpt-4o", 1, 3)],
        )
        out = await resolve_costs_for_user(db, self.user_id, [("gpt-4o", 1_000_000, 1_000_000)])
        self.assertEqual(out, [(Decimal("4"), True)])

    async def test_unpriced_returns_none(self):
        db = self._db_with()
        out = await resolve_costs_for_user(db, self.user_id, [("never-heard-of-it", 100, 100)])
        self.assertEqual(out, [(None, False)])

    async def test_empty_token_pairs_short_circuits(self):
        db = AsyncMock()
        out = await resolve_costs_for_user(db, self.user_id, [])
        self.assertEqual(out, [])
        db.execute.assert_not_called()

    async def test_equals_priority_over_startswith(self):
        db = self._db_with(
            globals_=[
                _global("gpt-4o", "startsWith", 10, 20),
                _global("gpt-4o", "equals", 1, 2),
            ]
        )
        out = await resolve_costs_for_user(db, self.user_id, [("gpt-4o", 1_000_000, 0)])
        self.assertEqual(out, [(Decimal("1"), True)])
