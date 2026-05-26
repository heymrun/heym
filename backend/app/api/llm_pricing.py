"""LLM pricing API: merged global + per-user override view, sync, custom rows."""

from datetime import datetime, timezone
from urllib.parse import unquote

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.models import LLMPricing, LLMPricingOverride, User
from app.db.session import get_db
from app.models.schemas import (
    LLMPricingCustomCreate,
    LLMPricingPatch,
    LLMPricingRow,
    LLMPricingSyncStatus,
)
from app.services.llm_pricing_sync import ensure_pricing_synced

router = APIRouter()


def _global_to_row(g: LLMPricing) -> LLMPricingRow:
    return LLMPricingRow(
        id=g.id,
        provider=g.provider,
        model=g.model,
        operator=g.operator,
        input_per_1m_usd=g.input_per_1m_usd,
        output_per_1m_usd=g.output_per_1m_usd,
        source=g.source,
        is_override=False,
        is_custom=False,
        override_id=None,
        updated_at=g.updated_at,
    )


def _apply_override(base: LLMPricingRow, override: LLMPricingOverride) -> LLMPricingRow:
    return base.model_copy(
        update={
            "input_per_1m_usd": override.input_per_1m_usd,
            "output_per_1m_usd": override.output_per_1m_usd,
            "is_override": True,
            "override_id": override.id,
            "updated_at": override.updated_at,
        }
    )


def _custom_to_row(o: LLMPricingOverride) -> LLMPricingRow:
    return LLMPricingRow(
        id=o.id,
        provider=None,
        model=o.model,
        operator="equals",
        input_per_1m_usd=o.input_per_1m_usd,
        output_per_1m_usd=o.output_per_1m_usd,
        source="user",
        is_override=False,
        is_custom=True,
        override_id=o.id,
        updated_at=o.updated_at,
    )


@router.get("", response_model=list[LLMPricingRow])
async def list_pricing(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[LLMPricingRow]:
    """Merged view: every global row, with this user's overrides applied,
    plus the user's custom-only rows appended."""
    await ensure_pricing_synced(db, force=False)

    globals_result = await db.execute(select(LLMPricing))
    globals_list: list[LLMPricing] = list(globals_result.scalars().all())

    overrides_result = await db.execute(
        select(LLMPricingOverride).where(LLMPricingOverride.user_id == current_user.id)
    )
    overrides_list: list[LLMPricingOverride] = list(overrides_result.scalars().all())
    overrides_by_model = {o.model: o for o in overrides_list}
    custom_overrides = [o for o in overrides_list if o.base_pricing_id is None]

    rows: list[LLMPricingRow] = []
    seen_models: set[str] = set()
    for g in globals_list:
        base = _global_to_row(g)
        if g.model in overrides_by_model:
            rows.append(_apply_override(base, overrides_by_model[g.model]))
        else:
            rows.append(base)
        seen_models.add(g.model)

    for o in custom_overrides:
        if o.model in seen_models:
            continue
        rows.append(_custom_to_row(o))

    # Sort: user-added customs first, then customized overrides, then defaults.
    # Within each group, by provider then model so the table feels stable.
    def _sort_key(r: LLMPricingRow) -> tuple[int, str, str]:
        if r.is_custom:
            group = 0
        elif r.is_override:
            group = 1
        else:
            group = 2
        return (group, r.provider or "ZZZ", r.model)

    rows.sort(key=_sort_key)
    return rows


@router.get("/sync-status", response_model=LLMPricingSyncStatus)
async def sync_status(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> LLMPricingSyncStatus:
    last_synced_result = await db.execute(select(func.max(LLMPricing.last_synced_at)))
    last_synced = last_synced_result.scalar_one_or_none()

    total_result = await db.execute(select(func.count()).select_from(LLMPricing))
    override_result = await db.execute(
        select(func.count())
        .select_from(LLMPricingOverride)
        .where(LLMPricingOverride.user_id == current_user.id)
    )
    return LLMPricingSyncStatus(
        last_synced_at=last_synced,
        total_rows=total_result.scalar_one(),
        override_rows=override_result.scalar_one(),
    )


@router.post("/sync", status_code=status.HTTP_202_ACCEPTED)
async def sync_now(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    await ensure_pricing_synced(db, force=True)
    return Response(status_code=status.HTTP_202_ACCEPTED)


@router.delete("", status_code=status.HTTP_204_NO_CONTENT)
async def clear_user_customizations(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Delete all of this user's pricing overrides and custom rows.
    Global Helicone-managed rows are not touched."""
    await db.execute(
        delete(LLMPricingOverride).where(LLMPricingOverride.user_id == current_user.id)
    )
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.patch("/{model_name:path}", response_model=LLMPricingRow)
async def update_pricing(
    model_name: str,
    payload: LLMPricingPatch,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> LLMPricingRow:
    model_name = unquote(model_name)

    global_result = await db.execute(
        select(LLMPricing).where(LLMPricing.model == model_name).limit(1)
    )
    global_row = global_result.scalar_one_or_none()

    override_result = await db.execute(
        select(LLMPricingOverride).where(
            LLMPricingOverride.user_id == current_user.id,
            LLMPricingOverride.model == model_name,
        )
    )
    override = override_result.scalar_one_or_none()

    if global_row is None and override is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Model not found. Use POST /custom to add a new model.",
        )

    if override is None:
        override = LLMPricingOverride(
            user_id=current_user.id,
            model=model_name,
            input_per_1m_usd=payload.input_per_1m_usd,
            output_per_1m_usd=payload.output_per_1m_usd,
            note=payload.note,
            base_pricing_id=global_row.id if global_row is not None else None,
        )
        db.add(override)
    else:
        override.input_per_1m_usd = payload.input_per_1m_usd
        override.output_per_1m_usd = payload.output_per_1m_usd
        override.note = payload.note
        override.updated_at = datetime.now(timezone.utc)

    await db.commit()
    await db.refresh(override)

    if global_row is not None:
        return _apply_override(_global_to_row(global_row), override)
    return _custom_to_row(override)


@router.delete("/{model_name:path}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_pricing_override(
    model_name: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    model_name = unquote(model_name)
    result = await db.execute(
        select(LLMPricingOverride).where(
            LLMPricingOverride.user_id == current_user.id,
            LLMPricingOverride.model == model_name,
        )
    )
    override = result.scalar_one_or_none()
    if override is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No override found")
    await db.delete(override)
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/custom", response_model=LLMPricingRow, status_code=status.HTTP_201_CREATED)
async def create_custom_pricing(
    payload: LLMPricingCustomCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> LLMPricingRow:
    result = await db.execute(
        select(LLMPricingOverride).where(
            LLMPricingOverride.user_id == current_user.id,
            LLMPricingOverride.model == payload.model,
        )
    )
    if result.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A row for this model already exists for your user.",
        )

    row = LLMPricingOverride(
        user_id=current_user.id,
        model=payload.model,
        input_per_1m_usd=payload.input_per_1m_usd,
        output_per_1m_usd=payload.output_per_1m_usd,
        note=payload.note,
        base_pricing_id=None,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return _custom_to_row(row)
