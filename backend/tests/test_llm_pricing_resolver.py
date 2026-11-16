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


def _override(
    model: str,
    inp: float = 0.5,
    out: float = 1.0,
    provider: str | None = None,
    base_pricing_id: uuid.UUID | None = None,
) -> _Row:
    return _Row(
        provider=provider,
        model=model,
        input_per_1m_usd=Decimal(str(inp)),
        output_per_1m_usd=Decimal(str(out)),
        base_pricing_id=base_pricing_id,
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

    async def test_zero_output_price_charges_input_only(self):
        db = self._db_with(overrides=[_override("local-llm", inp=2, out=0)])
        out = await resolve_costs_for_user(db, self.user_id, [("local-llm", 1_000_000, 1_000_000)])
        self.assertEqual(out, [(Decimal("2"), True)])

    async def test_free_model_counts_as_priced(self):
        db = self._db_with(overrides=[_override("ollama-llama3", inp=0, out=0)])
        out = await resolve_costs_for_user(db, self.user_id, [("ollama-llama3", 1_000, 1_000)])
        self.assertEqual(out, [(Decimal("0"), True)])

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

    async def test_custom_exact_model_beats_helicone_rule(self):
        db = self._db_with(
            globals_=[_global("claude", "includes", 5, 15)],
            overrides=[_override("claude-3-5-sonnet", 1, 3, provider="anthropic")],
        )
        out = await resolve_costs_for_user(
            db,
            self.user_id,
            [("claude-3-5-sonnet", 1_000_000, 1_000_000)],
        )
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


class EditedRuleTests(unittest.IsolatedAsyncioTestCase):
    """A price set in the pricing table applies to every model that row covers."""

    def setUp(self) -> None:
        self.user_id = uuid.uuid4()

    async def _cost(self, model: str, globals_=(), overrides=()) -> object:
        db = ResolverTests._db_with(self, globals_=globals_, overrides=overrides)
        return (await resolve_costs_for_user(db, self.user_id, [(model, 1_000_000, 0)]))[0]

    async def test_an_edited_includes_row_applies_to_a_dated_model_name(self) -> None:
        cost = await self._cost(
            "claude-3-opus-20240229",
            globals_=[_global("claude-3-opus", op="includes", inp=15)],
            overrides=[_override("claude-3-opus", inp=1, base_pricing_id=uuid.uuid4())],
        )
        self.assertEqual(cost, (Decimal("1"), True))

    async def test_an_edited_starts_with_row_applies_to_a_longer_name(self) -> None:
        cost = await self._cost(
            "gpt-4o-2024-08-06",
            globals_=[_global("gpt-4o", op="startsWith", inp=5)],
            overrides=[_override("gpt-4o", inp=2, base_pricing_id=uuid.uuid4())],
        )
        self.assertEqual(cost, (Decimal("2"), True))

    async def test_an_unedited_rule_keeps_its_price(self) -> None:
        cost = await self._cost(
            "claude-3-opus-20240229",
            globals_=[_global("claude-3-opus", op="includes", inp=15)],
            overrides=[_override("gpt-4o", inp=2, base_pricing_id=uuid.uuid4())],
        )
        self.assertEqual(cost, (Decimal("15"), True))

    async def test_an_exact_custom_row_still_beats_an_edited_rule(self) -> None:
        cost = await self._cost(
            "claude-3-opus-20240229",
            globals_=[_global("claude-3-opus", op="includes", inp=15)],
            overrides=[
                _override("claude-3-opus", inp=1, base_pricing_id=uuid.uuid4()),
                _override("claude-3-opus-20240229", inp=7),
            ],
        )
        self.assertEqual(cost, (Decimal("7"), True))

    async def test_a_provider_model_custom_row_prices_the_full_name(self) -> None:
        cost = await self._cost(
            "anthropic/claude-3-5-sonnet",
            globals_=[_global("anthropic/claude-3-5-sonnet", inp=3)],
            overrides=[_override("claude-3-5-sonnet", inp=1, provider="anthropic")],
        )
        self.assertEqual(cost, (Decimal("1"), True))
