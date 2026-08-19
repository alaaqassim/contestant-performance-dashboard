"""Percentiles and summary statistics.

ONE implementation, used everywhere, verified once by `validate.py`.

Method: **nearest-rank**, not interpolation. With the sample counts this instrument
actually sees — often a handful of SQL timings — interpolation invents values that lie
between two observations and were never measured. Nearest-rank always returns a value
that was genuinely observed, which is the property that matters for evidence.

    rank = ceil(p/100 * n),  clamped to [1, n],  value = sorted[rank - 1]

Consequences worth knowing before quoting a P99:
  * n = 1  -> median = P95 = P99 = the single observation. The dashboard labels this.
  * n < 20 -> P95 is the maximum. n < 100 -> P99 is the maximum.
A percentile computed from too few samples is reported with a warning rather than hidden.
"""

from __future__ import annotations

import math
from typing import Any

#: Below these sample counts the named percentile degenerates to the maximum.
MIN_SAMPLES_FOR = {"p95_ms": 20, "p99_ms": 100}


def percentile(sorted_values: list[float], p: float) -> float:
    """Nearest-rank percentile of an already-sorted, non-empty list."""
    if not sorted_values:
        raise ValueError("percentile of an empty sample set")
    n = len(sorted_values)
    rank = math.ceil((p / 100.0) * n)
    rank = max(1, min(rank, n))
    return sorted_values[rank - 1]


def summarise(samples: list[float]) -> dict[str, float] | None:
    """Median / P95 / P99 / min / max / mean / n from raw samples."""
    if not samples:
        return None
    ordered = sorted(float(v) for v in samples)
    n = len(ordered)
    return {
        "n": float(n),
        "min_ms": ordered[0],
        "median_ms": percentile(ordered, 50),
        "p95_ms": percentile(ordered, 95),
        "p99_ms": percentile(ordered, 99),
        "max_ms": ordered[-1],
        "mean_ms": sum(ordered) / n,
    }


def stats_for(record: dict[str, Any]) -> dict[str, float] | None:
    """Resolve a record's statistics: computed from samples, else pre-aggregated.

    Raw samples always win. A source that can only emit aggregates (an external load
    tool, a transcribed historical figure) supplies `stats` instead.
    """
    samples = record.get("samples_ms") or []
    if samples:
        return summarise(list(samples))

    stats = record.get("stats")
    if not stats:
        return None

    resolved = {k: v for k, v in dict(stats).items() if v is not None}
    if not resolved:
        return None

    # A single documented figure with no distribution: median is the only honest slot.
    # Do NOT fabricate P95/P99 from it — leave them absent so the UI shows "—".
    if "median_ms" not in resolved:
        for alias in ("duration_ms", "value_ms", "ms", "mean_ms"):
            if alias in resolved:
                resolved["median_ms"] = resolved[alias]
                break
    resolved.setdefault("n", 0.0)
    return resolved


def percentile_confidence(stats: dict[str, float] | None, key: str) -> str:
    """A human warning when a percentile rests on too few samples. '' when fine."""
    if not stats or key not in stats:
        return ""
    n = int(stats.get("n") or 0)
    needed = MIN_SAMPLES_FOR.get(key)
    if not needed:
        return ""
    if n == 0:
        return "pre-aggregated — sample count unknown"
    if n == 1:
        return "1 sample — this is the single observation, not a percentile"
    if n < needed:
        return f"only {n} samples — {key.replace('_ms', '').upper()} degenerates to the maximum"
    return ""


def range_of(samples: list[float]) -> str:
    """'0.41' or '250 – 970' — for figures documented as a range, not a point."""
    if not samples:
        return "—"
    lo, hi = min(samples), max(samples)
    if math.isclose(lo, hi):
        return f"{lo:,.4g}"
    return f"{lo:,.4g} – {hi:,.4g}"
