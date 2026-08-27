"""Smooth weighted round-robin over per-instance assignment counters.

Every assigned run increments a counter, including a MAIN_ONLY run that main was
forced to take. That single rule is what makes a percentage describe total load:
forced work spends main's quota, so the next ANYWHERE runs fall to the workers.
The consequence, which the UI and docs state: main's percentage is a ceiling,
not a floor.
"""

from __future__ import annotations

COUNTER_RESCALE_THRESHOLD = 1_000_000


def normalized_weights(weights: dict[str, int]) -> dict[str, float]:
    """Configured weights as shares of the live pool, summing to 1."""
    total = sum(weights.values())
    if total <= 0:
        return {}
    return {instance_id: weight / total for instance_id, weight in weights.items()}


def pick_instance(weights: dict[str, int], *, counters: dict[str, int]) -> str | None:
    """The instance furthest below its share. Ties break on id, so it is deterministic."""
    shares = normalized_weights(weights)
    if not shares:
        return None
    total = sum(counters.get(instance_id, 0) for instance_id in shares) + 1
    return max(
        sorted(shares),
        key=lambda instance_id: shares[instance_id] * total - counters.get(instance_id, 0),
    )


def rescale_counters(counters: dict[str, int]) -> dict[str, int]:
    """Halve every counter once the largest gets big, preserving the ratios."""
    if not counters or max(counters.values()) < COUNTER_RESCALE_THRESHOLD:
        return counters
    return {instance_id: value // 2 for instance_id, value in counters.items()}
