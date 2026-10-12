"""Small, dependency-free statistics helpers used by the detector."""

from __future__ import annotations

import math
from collections.abc import Sequence


def poisson_sf(k: int, mu: float) -> float:
    """P(X >= k) for X ~ Poisson(mu)."""
    if k <= 0:
        return 1.0
    if mu <= 0:
        return 0.0
    # 1 - P(X <= k-1), summed in log space for stability.
    term = math.exp(-mu)
    cumulative = term
    for i in range(1, k):
        term *= mu / i
        cumulative += term
    return max(0.0, 1.0 - cumulative)


def quantile(values: Sequence[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * q
    low = math.floor(position)
    high = math.ceil(position)
    if low == high:
        return ordered[low]
    return ordered[low] + (ordered[high] - ordered[low]) * (position - low)


def median(values: Sequence[float]) -> float | None:
    return quantile(values, 0.5)


def trimmed_low_mean(values: Sequence[float], keep: float = 0.6) -> float:
    """Mean of the lowest ``keep`` fraction: a baseline that ignores incident buckets."""
    if not values:
        return 0.0
    ordered = sorted(values)
    count = max(1, int(len(ordered) * keep))
    return sum(ordered[:count]) / count
