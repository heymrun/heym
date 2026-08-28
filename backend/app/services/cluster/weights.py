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


def seed_weights(current: dict[str, tuple[bool, int]]) -> dict[str, int] | None:
    """Give every never-configured instance a share, or None if there is none.

    `current` maps instance id to (weight_configured, weight). An instance is a
    newcomer only while `weight_configured` is False, so this runs once per
    machine: an operator who deliberately sets a worker to 0 is never fought.

    Newcomers take an equal share of the pool and the configured instances are
    scaled down proportionally, so a deliberate 70/30 still reads as 70/30
    afterwards. The result always totals exactly 100; the rounding remainder
    goes to the largest configured instance, which is main in practice.
    """
    newcomers = sorted(i for i, (configured, _w) in current.items() if not configured)
    if not newcomers:
        return None

    pool_size = len(current)
    share = 100 // pool_size
    seeded = {instance_id: share for instance_id in newcomers}

    configured = {i: w for i, (c, w) in current.items() if c}
    configured_total = sum(configured.values())
    remaining = 100 - share * len(newcomers)

    if configured_total > 0:
        for instance_id, weight in configured.items():
            seeded[instance_id] = int(weight * remaining / configured_total)
    else:
        # Nothing configured to scale against: split what is left evenly.
        for instance_id in configured:
            seeded[instance_id] = remaining // max(len(configured), 1)

    drift = 100 - sum(seeded.values())
    if drift:
        largest = max(seeded, key=lambda i: (seeded[i], i))
        seeded[largest] += drift
    return seeded
