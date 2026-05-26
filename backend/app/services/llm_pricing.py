"""LLM pricing resolver: matches trace models against global pricing rows + user overrides."""

import uuid
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import LLMPricing, LLMPricingOverride


def _match_global_rule(model: str, rules: list[LLMPricing]) -> LLMPricing | None:
    """Apply Helicone operator semantics. Priority: equals > startsWith > includes.
    Within startsWith/includes, the longest matching rule.model wins (most specific).
    """
    equals_match = next((r for r in rules if r.operator == "equals" and r.model == model), None)
    if equals_match is not None:
        return equals_match

    starts = [r for r in rules if r.operator == "startsWith" and model.startswith(r.model)]
    if starts:
        return max(starts, key=lambda r: len(r.model))

    includes = [r for r in rules if r.operator == "includes" and r.model in model]
    if includes:
        return max(includes, key=lambda r: len(r.model))

    return None


async def resolve_costs_for_user(
    db: AsyncSession,
    user_id: uuid.UUID,
    model_token_pairs: list[tuple[str, int, int]],
) -> list[tuple[Decimal | None, bool]]:
    """For each (model, prompt_tokens, completion_tokens), return (cost_usd, is_priced).

    Fetches all global + user-override rows once and resolves in-memory.
    """
    if not model_token_pairs:
        return []

    global_result = await db.execute(select(LLMPricing))
    global_rules: list[LLMPricing] = list(global_result.scalars().all())

    override_result = await db.execute(
        select(LLMPricingOverride).where(LLMPricingOverride.user_id == user_id)
    )
    overrides: list[LLMPricingOverride] = list(override_result.scalars().all())
    override_by_model = {o.model: o for o in overrides}

    out: list[tuple[Decimal | None, bool]] = []
    for model, prompt_tok, completion_tok in model_token_pairs:
        prompt_tok = max(0, int(prompt_tok or 0))
        completion_tok = max(0, int(completion_tok or 0))

        override = override_by_model.get(model)
        if override is not None:
            cost = (
                Decimal(prompt_tok) * override.input_per_1m_usd
                + Decimal(completion_tok) * override.output_per_1m_usd
            ) / Decimal(1_000_000)
            out.append((cost, True))
            continue

        rule = _match_global_rule(model, global_rules)
        if rule is None:
            out.append((None, False))
            continue

        cost = (
            Decimal(prompt_tok) * rule.input_per_1m_usd
            + Decimal(completion_tok) * rule.output_per_1m_usd
        ) / Decimal(1_000_000)
        out.append((cost, True))

    return out
