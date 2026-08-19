"""Query-level evidence — every database statement shape, before and after.

This is the detail layer. The other pages answer "what does each screen cost"; this one
answers "which statements make up that cost, how often does each run, and what happened to
it". Every figure is computed at render time from the two evidence files.

Statements are named SEMANTICALLY (`limiter.key_read`, `auth.user_lookup`). The parameterised
statement text is not in the published artifact and is not reconstructed here.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from perfdash import evidence

st.set_page_config(page_title="Query Performance", page_icon="🔎", layout="wide")

st.title("Query performance — statement by statement")
st.caption(
    "The seven contestant screens, decomposed into the individual database statements behind "
    "them. Statements are named by shape; no query text, table name or identifier is shown."
)

try:
    catalog = evidence.query_catalog()
    totals = evidence.query_totals()
except evidence.EvidenceError as exc:
    st.error(f"**Evidence could not be read, so this page shows nothing.**\n\n`{exc}`",
             icon="🚫")
    st.stop()


def ms(value: float | None, places: int = 4) -> float | None:
    return None if value is None else round(value, places)


# ======================================================================================
# Journey-wide summary
# ======================================================================================

st.header("Across the whole contestant journey")

a, b, c, d = st.columns(4)
a.metric("Statements BEFORE", totals["before_statements"],
         f"{totals['screens']} screens", delta_color="off")
b.metric("Statements AFTER", totals["after_statements"],
         f"−{totals['statements_eliminated']} eliminated", delta_color="off")
c.metric("Database time BEFORE", f"{totals['before_ms']:.4f} ms",
         f"{totals['shapes_total']} shapes", delta_color="off")
d.metric("Database time AFTER", f"{totals['after_ms']:.4f} ms",
         f"−{totals['ms_saved']:.4f} ms  ({totals['reduction_pct']:.1f}%)",
         delta_color="off")

e, f, g, h = st.columns(4)
e.metric("Rate-limiter share BEFORE", f"{totals['before_limiter_pct']:.1f}%",
         f"{totals['before_limiter_ms']:.4f} ms", delta_color="off")
f.metric("Rate-limiter share AFTER", f"{totals['after_limiter_ms']:.4f} ms",
         "removed entirely", delta_color="off")
g.metric("Business share AFTER", f"{totals['after_business_pct']:.1f}%",
         f"{totals['after_business_ms']:.4f} ms", delta_color="off")
h.metric("Shapes removed / active", f"{totals['shapes_removed']} / {totals['shapes_active']}",
         f"{totals['conditional_count']} conditional", delta_color="off")

st.caption(
    "Every figure above is a sum over the two evidence files — statement counts from the "
    "recorded browser trace, milliseconds from the timed samples."
)

st.divider()

# ======================================================================================
# The calibration caveat, before any per-query number is read
# ======================================================================================

st.warning(evidence.CALIBRATION_NOTE, icon="⚠️")

st.divider()

# ======================================================================================
# Rate-limiter shapes removed
# ======================================================================================

st.header("Database rate-limiter queries removed")

limiter = [q for q in catalog if q["category"] == "Rate Limiter"]

st.info(
    "**These were infrastructure queries, not business-domain queries.** None of them asked "
    "anything about a competition, a contestant or a registration. They were the rate "
    "limiter's own counters — bookkeeping about how many requests an account had made — "
    "being written into the main relational database because no dedicated store had been "
    "configured for them.\n\n"
    "Three of the five were WRITES, and each had to be flushed durably to disk on every "
    "throttled request. That is why infrastructure, rather than the application's own "
    "queries, dominated the budget.",
    icon="🧾",
)

st.dataframe(
    pd.DataFrame([
        {
            "Statement shape": q["shape"],
            "What it did": q["label"],
            "BEFORE p50 (ms)": ms(q["before_p50"]),
            "BEFORE p95 (ms)": ms(q["before_p95"]),
            "BEFORE p99 (ms)": ms(q["before_p99"]),
            "BEFORE executions": q["before_executions"],
            "AFTER executions": q["after_executions"],
            "SQL time eliminated (ms)": ms(q["sql_time_eliminated"]),
            "Status": q["status"],
        }
        for q in sorted(limiter, key=lambda q: -(q["sql_time_eliminated"] or 0))
    ]),
    width="stretch", hide_index=True,
)

_eliminated = sum(q["sql_time_eliminated"] or 0 for q in limiter)
_execs = sum(q["before_executions"] for q in limiter)
st.success(
    f"**All {len(limiter)} shapes now execute zero times.** Together they ran "
    f"**{_execs} times** across the journey and accounted for **{_eliminated:.4f} ms** — "
    f"{totals['before_limiter_pct']:.1f}% of all database time on the seven screens. "
    f"They were not made faster; they left the request path.",
    icon="✅",
)

with st.expander("Their measured cost, kept on the record"):
    st.caption(
        "Still measured in the after run, so the comparison cannot quietly hide what it "
        "removed. These are the after-run readings for statements that no longer execute."
    )
    st.dataframe(
        pd.DataFrame([
            {"Statement shape": q["shape"],
             "AFTER p50 (ms)": ms(q["after_p50"]),
             "AFTER p95 (ms)": ms(q["after_p95"]),
             "AFTER p99 (ms)": ms(q["after_p99"]),
             "Samples": q["after_n"],
             "Executions on any screen": q["after_executions"]}
            for q in limiter
        ]),
        width="stretch", hide_index=True,
    )

st.divider()

# ======================================================================================
# Remaining business + auth shapes
# ======================================================================================

st.header("Remaining queries")
st.caption(
    "What the database still does once the limiter is out of the way — the application's "
    "own work. Ranked by p95 first, then median, then how often each runs."
)

remaining = [q for q in catalog if not q["removed"]]
remaining.sort(key=lambda q: (-(q["after_p95"] or 0), -(q["after_p50"] or 0),
                              -q["after_executions"]))

st.dataframe(
    pd.DataFrame([
        {
            "Statement shape": q["shape"],
            "Category": q["category"],
            "What it does": q["label"],
            "Screens": ", ".join(q["screens"]),
            "Executions": q["after_executions"],
            "p50 (ms)": ms(q["after_p50"]),
            "p95 (ms)": ms(q["after_p95"]),
            "p99 (ms)": ms(q["after_p99"]),
            "Samples": q["after_n"],
            "Access health": q["health"],
        }
        for q in remaining
    ]),
    width="stretch", hide_index=True,
)

_healthy = [q for q in remaining if q["health"].startswith("HEALTHY — ")]
_scale = [q for q in remaining if "PRODUCTION-SCALE" in q["health"]]
_small = [q for q in remaining if q["health"].startswith("HEALTHY AT THIS DATASET")]
_writes = [q for q in remaining if q["health"].startswith("WRITE PATH")]

st.markdown("**How each verdict was reached** — from the access plan and dataset scope "
            "recorded with the measurement, never from the timing alone:")
st.dataframe(
    pd.DataFrame([
        {"Statement shape": q["shape"], "Verdict": q["health"], "Because": q["health_reason"]}
        for q in remaining
    ]),
    width="stretch", hide_index=True,
)

if _healthy:
    st.success(
        f"**{len(_healthy)} of {len(remaining)} remaining statements are HEALTHY — NO "
        f"OPTIMISATION REQUIRED.** Each uses indexed access against a table measured at a "
        f"representative size: " + ", ".join(q["shape"] for q in _healthy),
        icon="✅",
    )

if _small:
    st.info(
        f"**{len(_small)} use indexed access, but were measured against a small table.** "
        f"They are cheap here and the plan is right, but this dataset does not yet prove "
        f"behaviour at full scale: " + ", ".join(q["shape"] for q in _small),
        icon="ℹ️",
    )

if _scale:
    st.warning(
        f"**{len(_scale)} still need production-scale validation.** They perform a full scan "
        f"rather than an indexed lookup. That cost nothing measurable here because the table "
        f"held very few rows, but a full scan is a property of the plan, not of the timing, "
        f"and it does not stay cheap as the table grows: "
        + ", ".join(q["shape"] for q in _scale),
        icon="⚠️",
    )

if _writes:
    st.warning(
        f"**{len(_writes)} are writes**, whose cost is dominated by the durable commit rather "
        f"than by lookup: " + ", ".join(q["shape"] for q in _writes)
        + ". Those marked FLOOR were measured inside a transaction that was rolled back and "
          "never paid that commit, so their real cost is higher than shown.",
        icon="⚖️",
    )

st.divider()

# ======================================================================================
# Full catalog
# ======================================================================================

st.header("Every measured statement shape")

st.dataframe(
    pd.DataFrame([
        {
            "Statement shape": q["shape"],
            "Category": q["category"],
            "Screens": ", ".join(q["screens"]),
            "Executions BEFORE": q["before_executions"],
            "Executions AFTER": q["after_executions"],
            "BEFORE p50": ms(q["before_p50"]), "BEFORE p95": ms(q["before_p95"]),
            "BEFORE p99": ms(q["before_p99"]),
            "AFTER p50": ms(q["after_p50"]), "AFTER p95": ms(q["after_p95"]),
            "AFTER p99": ms(q["after_p99"]),
            "Improvement": "100% — removed" if q["removed"] else "no change made",
            "Status": q["status"],
        }
        for q in sorted(catalog, key=lambda q: (q["category"], q["shape"]))
    ]),
    width="stretch", hide_index=True,
)

with st.expander("Where each statement runs, and how many times per screen"):
    st.dataframe(
        pd.DataFrame([
            {"Statement shape": q["shape"], "Screen": screen, "Executions on that screen": n,
             "Status": q["status"]}
            for q in sorted(catalog, key=lambda q: (q["category"], q["shape"]))
            for screen, n in q["executions_per_screen"].items()
        ]),
        width="stretch", hide_index=True,
    )

st.divider()

# ======================================================================================
# Conditional shapes
# ======================================================================================

st.header("Conditional statements — code paths that did not execute")

conditional = evidence.conditional_queries()

st.error(
    "**These carry NO number, deliberately.** A statement that never ran has no measured "
    "cost, and writing 0 ms would report a measurement that was never taken. They are listed "
    "so a screen's statement count is not mistaken for everything the code can do.",
    icon="🚧",
)

for item in conditional:
    with st.container(border=True):
        st.markdown(f"**{item['name']}** · {item['screen']}")
        st.markdown(f"`{evidence.STATUS_CONDITIONAL}`")
        st.caption(item["explanation"])

st.info(
    "The result-reading path is the significant one. It will be measurable as soon as a "
    "genuine published competition result exists: today no result has been published, so the "
    "code short-circuits before issuing the statement. That measurement is owed, not "
    "missing — and until it is taken, this dashboard will not put a figure against it.",
    icon="📋",
)
