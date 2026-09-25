import unittest
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import HTTPException
from pydantic import ValidationError

from app.api.llm_pricing import (
    clear_user_customizations,
    create_custom_pricing,
    delete_pricing_override,
    list_pricing,
    sync_now,
    sync_status,
    update_pricing,
)
from app.models.schemas import LLMPricingCustomCreate, LLMPricingPatch


class _Row:
    def __init__(self, **kw):
        self.__dict__.update(kw)


def _global(model="gpt-4o", op="equals"):
    return _Row(
        id=uuid.uuid4(),
        provider="OPENAI",
        model=model,
        operator=op,
        input_per_1m_usd=Decimal("5"),
        output_per_1m_usd=Decimal("15"),
        source="helicone",
        last_synced_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )


def _override(model="gpt-4o", base_id=None, provider=None):
    return _Row(
        id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        provider=provider,
        model=model,
        input_per_1m_usd=Decimal("1"),
        output_per_1m_usd=Decimal("3"),
        note=None,
        base_pricing_id=base_id,
        updated_at=datetime.now(timezone.utc),
        created_at=datetime.now(timezone.utc),
    )


def _exec_with(items):
    scalars = MagicMock()
    scalars.all = MagicMock(return_value=items)
    result = MagicMock()
    result.scalars = MagicMock(return_value=scalars)
    return result


class ListPricingTests(unittest.IsolatedAsyncioTestCase):
    async def test_list_merges_global_with_overrides(self):
        user = MagicMock()
        user.id = uuid.uuid4()
        global_row = _global("gpt-4o")
        override_row = _override("gpt-4o", base_id=global_row.id)
        db = AsyncMock()
        db.execute = AsyncMock(
            side_effect=[
                _exec_with([global_row]),
                _exec_with([override_row]),
            ]
        )
        with patch("app.api.llm_pricing.ensure_pricing_synced", AsyncMock(return_value=False)):
            rows = await list_pricing(current_user=user, db=db)
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertTrue(row.is_override)
        self.assertFalse(row.is_custom)
        self.assertEqual(row.input_per_1m_usd, Decimal("1"))
        self.assertEqual(row.output_per_1m_usd, Decimal("3"))
        self.assertEqual(row.provider, "OPENAI")

    async def test_list_includes_custom_only_rows(self):
        user = MagicMock()
        user.id = uuid.uuid4()
        custom = _override("zai-glm-4.7", base_id=None, provider="cerebras")
        db = AsyncMock()
        db.execute = AsyncMock(
            side_effect=[
                _exec_with([]),
                _exec_with([custom]),
            ]
        )
        with patch("app.api.llm_pricing.ensure_pricing_synced", AsyncMock(return_value=False)):
            rows = await list_pricing(current_user=user, db=db)
        self.assertEqual(len(rows), 1)
        self.assertTrue(rows[0].is_custom)
        self.assertEqual(rows[0].provider, "cerebras")
        self.assertEqual(rows[0].model, "zai-glm-4.7")

    async def test_list_custom_row_masks_same_model_from_helicone(self):
        user = MagicMock()
        user.id = uuid.uuid4()
        global_row = _global("anthropic/claude-3-5-sonnet")
        custom = _override("claude-3-5-sonnet", base_id=None, provider="anthropic")
        db = AsyncMock()
        db.execute = AsyncMock(
            side_effect=[
                _exec_with([global_row, _global("anthropic/claude-3-5-sonnet", op="startsWith")]),
                _exec_with([custom]),
            ]
        )
        with patch("app.api.llm_pricing.ensure_pricing_synced", AsyncMock(return_value=False)):
            rows = await list_pricing(current_user=user, db=db)
        self.assertEqual(len(rows), 1)
        self.assertTrue(rows[0].is_custom)
        self.assertFalse(rows[0].is_override)
        self.assertEqual(rows[0].source, "user")
        self.assertEqual(rows[0].provider, "anthropic")
        self.assertEqual(rows[0].model, "claude-3-5-sonnet")
        self.assertEqual(rows[0].input_per_1m_usd, Decimal("1"))

    async def test_list_keeps_multiple_custom_rows_that_match_same_global(self):
        user = MagicMock()
        user.id = uuid.uuid4()
        global_row = _global("anthropic/claude-3-5-sonnet")
        provider_custom = _override("claude-3-5-sonnet", base_id=None, provider="anthropic")
        legacy_custom = _override("anthropic/claude-3-5-sonnet", base_id=None)
        db = AsyncMock()
        db.execute = AsyncMock(
            side_effect=[
                _exec_with([global_row]),
                _exec_with([provider_custom, legacy_custom]),
            ]
        )

        with patch("app.api.llm_pricing.ensure_pricing_synced", AsyncMock(return_value=False)):
            rows = await list_pricing(current_user=user, db=db)

        custom_rows = [row for row in rows if row.is_custom]
        self.assertEqual(len(custom_rows), 2)
        self.assertEqual(
            {(row.provider, row.model) for row in custom_rows},
            {
                ("anthropic", "claude-3-5-sonnet"),
                (None, "anthropic/claude-3-5-sonnet"),
            },
        )


class UpdatePricingTests(unittest.IsolatedAsyncioTestCase):
    async def test_patch_creates_override(self):
        user = MagicMock()
        user.id = uuid.uuid4()
        global_row = _global("gpt-4o")
        db = AsyncMock()
        scalar1 = MagicMock()
        scalar1.scalar_one_or_none = MagicMock(return_value=global_row)
        scalar2 = MagicMock()
        scalar2.scalar_one_or_none = MagicMock(return_value=None)
        db.execute = AsyncMock(side_effect=[scalar1, scalar2])
        db.add = MagicMock()
        db.commit = AsyncMock()
        db.refresh = AsyncMock()

        payload = LLMPricingPatch(input_per_1m_usd=Decimal("2"), output_per_1m_usd=Decimal("6"))
        result = await update_pricing(
            model_name="gpt-4o", payload=payload, current_user=user, db=db
        )
        db.add.assert_called_once()
        added = db.add.call_args[0][0]
        self.assertEqual(added.user_id, user.id)
        self.assertEqual(added.model, "gpt-4o")
        self.assertEqual(added.base_pricing_id, global_row.id)
        self.assertEqual(result.input_per_1m_usd, Decimal("2"))

    async def test_patch_updates_existing_override(self):
        user = MagicMock()
        user.id = uuid.uuid4()
        existing = _override("gpt-4o", base_id=uuid.uuid4())
        db = AsyncMock()
        scalar1 = MagicMock()
        scalar1.scalar_one_or_none = MagicMock(return_value=None)
        scalar2 = MagicMock()
        scalar2.scalar_one_or_none = MagicMock(return_value=existing)
        db.execute = AsyncMock(side_effect=[scalar1, scalar2])
        db.commit = AsyncMock()
        db.refresh = AsyncMock()
        payload = LLMPricingPatch(input_per_1m_usd=Decimal("9"), output_per_1m_usd=Decimal("10"))
        result = await update_pricing(
            model_name="gpt-4o", payload=payload, current_user=user, db=db
        )
        self.assertEqual(existing.input_per_1m_usd, Decimal("9"))
        self.assertEqual(result.output_per_1m_usd, Decimal("10"))

    async def test_patch_keeps_custom_duplicate_as_custom(self):
        user = MagicMock()
        user.id = uuid.uuid4()
        global_row = _global("anthropic/claude-3-5-sonnet")
        existing = _override("claude-3-5-sonnet", base_id=None, provider="anthropic")
        db = AsyncMock()
        scalar1 = MagicMock()
        scalar1.scalar_one_or_none = MagicMock(return_value=global_row)
        scalar2 = MagicMock()
        scalar2.scalar_one_or_none = MagicMock(return_value=existing)
        db.execute = AsyncMock(side_effect=[scalar1, scalar2])
        db.commit = AsyncMock()
        db.refresh = AsyncMock()
        payload = LLMPricingPatch(input_per_1m_usd=Decimal("9"), output_per_1m_usd=Decimal("10"))
        result = await update_pricing(
            model_name="claude-3-5-sonnet",
            payload=payload,
            current_user=user,
            db=db,
        )
        self.assertTrue(result.is_custom)
        self.assertFalse(result.is_override)
        self.assertEqual(result.provider, "anthropic")
        self.assertEqual(result.source, "user")

    async def test_patch_404_when_neither_exists(self):
        user = MagicMock()
        user.id = uuid.uuid4()
        db = AsyncMock()
        scalar = MagicMock()
        scalar.scalar_one_or_none = MagicMock(return_value=None)
        db.execute = AsyncMock(side_effect=[scalar, scalar])
        with self.assertRaises(HTTPException) as ctx:
            await update_pricing(
                model_name="ghost",
                payload=LLMPricingPatch(
                    input_per_1m_usd=Decimal("1"), output_per_1m_usd=Decimal("2")
                ),
                current_user=user,
                db=db,
            )
        self.assertEqual(ctx.exception.status_code, 404)


class DeletePricingTests(unittest.IsolatedAsyncioTestCase):
    async def test_delete_removes_existing_override(self):
        user = MagicMock()
        user.id = uuid.uuid4()
        override = _override("gpt-4o", base_id=uuid.uuid4())
        db = AsyncMock()
        scalar = MagicMock()
        scalar.scalar_one_or_none = MagicMock(return_value=override)
        db.execute = AsyncMock(return_value=scalar)
        db.delete = AsyncMock()
        db.commit = AsyncMock()
        await delete_pricing_override(model_name="gpt-4o", current_user=user, db=db)
        db.delete.assert_awaited_once_with(override)
        db.commit.assert_awaited_once()

    async def test_delete_404_when_missing(self):
        user = MagicMock()
        user.id = uuid.uuid4()
        db = AsyncMock()
        scalar = MagicMock()
        scalar.scalar_one_or_none = MagicMock(return_value=None)
        db.execute = AsyncMock(return_value=scalar)
        with self.assertRaises(HTTPException) as ctx:
            await delete_pricing_override(model_name="ghost", current_user=user, db=db)
        self.assertEqual(ctx.exception.status_code, 404)


class CustomCreateTests(unittest.IsolatedAsyncioTestCase):
    async def test_creates_custom_row(self):
        user = MagicMock()
        user.id = uuid.uuid4()
        db = AsyncMock()
        scalar = MagicMock()
        scalar.scalar_one_or_none = MagicMock(return_value=None)
        db.execute = AsyncMock(return_value=scalar)
        db.add = MagicMock()
        db.commit = AsyncMock()

        async def _refresh_side_effect(row):
            row.id = uuid.uuid4()
            row.updated_at = datetime.now(timezone.utc)

        db.refresh = AsyncMock(side_effect=_refresh_side_effect)
        payload = LLMPricingCustomCreate(
            model="org/private-model",
            input_per_1m_usd=Decimal("2"),
            output_per_1m_usd=Decimal("4"),
        )
        result = await create_custom_pricing(payload=payload, current_user=user, db=db)
        db.add.assert_called_once()
        added = db.add.call_args[0][0]
        self.assertIsNone(added.base_pricing_id)
        self.assertEqual(added.provider, "org")
        self.assertEqual(added.model, "private-model")
        self.assertEqual(result.model, "private-model")
        self.assertTrue(result.is_custom)
        self.assertEqual(result.provider, "org")

    async def test_creates_custom_row_with_zero_prices(self):
        user = MagicMock()
        user.id = uuid.uuid4()
        db = AsyncMock()
        scalar = MagicMock()
        scalar.scalar_one_or_none = MagicMock(return_value=None)
        db.execute = AsyncMock(return_value=scalar)
        db.add = MagicMock()
        db.commit = AsyncMock()

        async def _refresh_side_effect(row):
            row.id = uuid.uuid4()
            row.updated_at = datetime.now(timezone.utc)

        db.refresh = AsyncMock(side_effect=_refresh_side_effect)
        payload = LLMPricingCustomCreate(
            model="ollama/llama3",
            input_per_1m_usd=Decimal("0"),
            output_per_1m_usd=Decimal("0"),
        )
        result = await create_custom_pricing(payload=payload, current_user=user, db=db)
        added = db.add.call_args[0][0]
        self.assertEqual(added.input_per_1m_usd, Decimal("0"))
        self.assertEqual(added.output_per_1m_usd, Decimal("0"))
        self.assertEqual(result.output_per_1m_usd, Decimal("0"))

    async def test_create_custom_without_provider_keeps_model_only(self):
        user = MagicMock()
        user.id = uuid.uuid4()
        db = AsyncMock()
        scalar = MagicMock()
        scalar.scalar_one_or_none = MagicMock(return_value=None)
        db.execute = AsyncMock(return_value=scalar)
        db.add = MagicMock()
        db.commit = AsyncMock()

        async def _refresh_side_effect(row):
            row.id = uuid.uuid4()
            row.updated_at = datetime.now(timezone.utc)

        db.refresh = AsyncMock(side_effect=_refresh_side_effect)
        payload = LLMPricingCustomCreate(
            model="zai-glm-4.7",
            input_per_1m_usd=Decimal("2"),
            output_per_1m_usd=Decimal("4"),
        )
        result = await create_custom_pricing(payload=payload, current_user=user, db=db)
        added = db.add.call_args[0][0]
        self.assertIsNone(added.provider)
        self.assertEqual(added.model, "zai-glm-4.7")
        self.assertIsNone(result.provider)
        self.assertEqual(result.model, "zai-glm-4.7")

    async def test_create_custom_422_when_provider_prefix_has_no_model(self):
        user = MagicMock()
        user.id = uuid.uuid4()
        db = AsyncMock()
        with self.assertRaises(HTTPException) as ctx:
            await create_custom_pricing(
                payload=LLMPricingCustomCreate(
                    model="cerebras/",
                    input_per_1m_usd=Decimal("1"),
                    output_per_1m_usd=Decimal("2"),
                ),
                current_user=user,
                db=db,
            )
        self.assertEqual(ctx.exception.status_code, 422)
        db.execute.assert_not_called()

    async def test_creates_custom_409_when_duplicate(self):
        user = MagicMock()
        user.id = uuid.uuid4()
        existing = _override("private-model", provider="org")
        db = AsyncMock()
        scalar = MagicMock()
        scalar.scalar_one_or_none = MagicMock(return_value=existing)
        db.execute = AsyncMock(return_value=scalar)
        with self.assertRaises(HTTPException) as ctx:
            await create_custom_pricing(
                payload=LLMPricingCustomCreate(
                    model="org/private-model",
                    input_per_1m_usd=Decimal("1"),
                    output_per_1m_usd=Decimal("2"),
                ),
                current_user=user,
                db=db,
            )
        self.assertEqual(ctx.exception.status_code, 409)


class PriceValidationTests(unittest.TestCase):
    def test_zero_prices_are_accepted(self):
        patch_payload = LLMPricingPatch(
            input_per_1m_usd=Decimal("0.5"), output_per_1m_usd=Decimal("0")
        )
        create_payload = LLMPricingCustomCreate(
            model="local-model", input_per_1m_usd=Decimal("0"), output_per_1m_usd=Decimal("0")
        )
        self.assertEqual(patch_payload.output_per_1m_usd, Decimal("0"))
        self.assertEqual(create_payload.input_per_1m_usd, Decimal("0"))

    def test_negative_prices_are_rejected(self):
        for field in ("input_per_1m_usd", "output_per_1m_usd"):
            prices = {
                "input_per_1m_usd": Decimal("1"),
                "output_per_1m_usd": Decimal("1"),
                field: Decimal("-0.01"),
            }
            with self.subTest(field=field):
                with self.assertRaises(ValidationError):
                    LLMPricingPatch(**prices)
                with self.assertRaises(ValidationError):
                    LLMPricingCustomCreate(model="local-model", **prices)


class ClearCustomizationsTests(unittest.IsolatedAsyncioTestCase):
    async def test_clear_executes_scoped_delete_and_commits(self):
        user = MagicMock()
        user.id = uuid.uuid4()
        db = AsyncMock()
        db.execute = AsyncMock()
        db.commit = AsyncMock()

        response = await clear_user_customizations(current_user=user, db=db)

        self.assertEqual(response.status_code, 204)
        # Single DELETE issued, then commit
        self.assertEqual(db.execute.await_count, 1)
        db.commit.assert_awaited_once()


class SyncEndpointTests(unittest.IsolatedAsyncioTestCase):
    async def test_sync_status_returns_counts(self):
        user = MagicMock()
        user.id = uuid.uuid4()
        db = AsyncMock()
        s1 = MagicMock()
        s1.scalar_one_or_none = MagicMock(return_value=datetime.now(timezone.utc))
        s2 = MagicMock()
        s2.scalar_one = MagicMock(return_value=42)
        s3 = MagicMock()
        s3.scalar_one = MagicMock(return_value=3)
        db.execute = AsyncMock(side_effect=[s1, s2, s3])
        result = await sync_status(current_user=user, db=db)
        self.assertEqual(result.total_rows, 42)
        self.assertEqual(result.override_rows, 3)

    async def test_sync_now_triggers_force(self):
        user = MagicMock()
        user.id = uuid.uuid4()
        db = AsyncMock()
        with patch(
            "app.api.llm_pricing.ensure_pricing_synced", AsyncMock(return_value=True)
        ) as ensure_mock:
            await sync_now(current_user=user, db=db)
        ensure_mock.assert_awaited_once_with(db, force=True)
