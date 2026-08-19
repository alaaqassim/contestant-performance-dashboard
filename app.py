"""Contestant journey performance — public presentation snapshot.

Entry point for Streamlit Community Cloud. Read-only: no database, no network, no CMS.
Every figure is computed at render time from the two sanitised evidence files in `data/`.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from perfdash import evidence

st.set_page_config(
    page_title="Contestant Journey Performance",
    page_icon="📊",
    layout="wide",
)

st.title("Contestant Journey — Database Performance")
st.caption(
    "How much database time each screen a contestant sees actually costs — measured, "
    "before and after one configuration change."
)

try:
    rows = evidence.compare()
except evidence.EvidenceError as exc:
    st.error(
        f"**The evidence files could not be read, so this page shows nothing.**\n\n`{exc}`\n\n"
        f"No figure is substituted when a measurement is missing.",
        icon="🚫",
    )
    st.stop()

# ======================================================================================
# The headline
# ======================================================================================

_within = [r for r in rows if r["after_within_target"]]
_best = max(rows, key=lambda r: r["reduction_pct"] or 0)

c1, c2, c3 = st.columns(3)
c1.metric("Screens meeting the ≤ 5 ms target", f"{len(_within)} / {len(rows)}")
c2.metric("Largest single reduction",
          f"{_best['reduction_pct']:.1f}%", _best["short_title"])
c3.metric("Database statements removed per journey",
          f"−{sum(r['statement_reduction'] for r in rows)}")

st.divider()

# ======================================================================================
# The seven surfaces
# ======================================================================================

st.header("The seven contestant screens")
st.caption(
    "Read each row as: what this screen used to cost in database time → what it costs now."
)

for row in rows:
    label = f"**{row['short_title']}**"
    if row["arabic"]:
        label += f" · {row['arabic']}"

    box = st.container(border=True)
    with box:
        head, before, arrow, after, cut, status = st.columns([3, 2, 1, 2, 2, 2])
        head.markdown(label)
        head.caption(row["route"])

        if not row["comparable"]:
            before.markdown("**—**")
            arrow.markdown("→")
            after.markdown("**—**")
            cut.markdown("**not comparable**")
            status.markdown("⚠️ INCOMPLETE")
            st.caption(
                "A measurement is missing on one side, so no reduction is claimed: "
                f"BEFORE gaps {row['before_gaps'] or 'none'}, "
                f"AFTER gaps {row['after_gaps'] or 'none'}."
            )
            continue

        before.metric("Before", f"{row['before_ms']:.4f} ms",
                      f"{row['before_statements']} statements", delta_color="off")
        arrow.markdown("<h3 style='text-align:center;margin-top:1.2rem'>→</h3>",
                       unsafe_allow_html=True)
        after.metric("After", f"{row['after_ms']:.4f} ms",
                     f"{row['after_statements']} statements", delta_color="off")
        cut.metric("Reduction", f"{row['reduction_pct']:.1f}%",
                   f"−{row['delta_ms']:.4f} ms", delta_color="off")

        if row["after_within_target"]:
            status.success(f"TARGET ≤ {evidence.TARGET_MS:.0f} ms ✅")
        else:
            status.error(f"TARGET ≤ {evidence.TARGET_MS:.0f} ms ❌")

        if row["after_is_floor"]:
            st.caption(
                "⚖️ **This total is a FLOOR, not a value.** "
                + ", ".join(row["after_floor_components"])
                + " were measured inside a transaction that was rolled back, so they never "
                "paid the final commit cost. The real figure is higher — which means the "
                "reduction shown here is understated, not overstated."
            )

st.divider()

# ======================================================================================
# What changed, in one paragraph
# ======================================================================================

st.header("What changed")

st.markdown(
    "Every request a contestant makes passes through a **rate limiter** — the component "
    "that stops one account from hammering the system. The framework stores its counters "
    "in whichever cache is configured, and no dedicated store had been configured, so the "
    "counters were being written **into the main relational database**.\n\n"
    "Each of those writes had to be flushed durably to disk, on every single request. "
    "Measured across the seven contestant screens, that machinery — not the application's "
    "own queries — accounted for **most of the database time on every one of them**.\n\n"
    "Pointing the limiter at a different store, and changing nothing else, removed it from "
    "the request path entirely. What remains is the application's real work, and every "
    "screen now sits under the 5 ms target."
)

st.error(
    "**FILE LIMITER — LOCAL ISOLATION PILOT · NOT PRODUCTION ARCHITECTURE**\n\n"
    "The \"after\" measurements were taken with a **file-backed** limiter store. That was "
    "chosen for one reason only: it is the simplest way to take the database out of the "
    "picture and prove that database-backed rate limiting was the dominant cost.\n\n"
    "**It is not the recommended production architecture.** A file-backed store cannot be "
    "shared between application servers and serialises on file locks; under the 40,000-"
    "contestant start-of-competition burst it would contend worse than the database it "
    "replaced.\n\n"
    "**Redis — or another shared, low-latency limiter store — remains the production "
    "candidate.** This pilot is the evidence that justifies adopting one, not a proposal to "
    "ship files.",
    icon="⛔",
)

st.divider()

# ======================================================================================
# Summary table
# ======================================================================================

st.header("Summary")

st.dataframe(
    pd.DataFrame([
        {
            "Screen": r["short_title"],
            "الشاشة": r["arabic"],
            "Statements before": r["before_statements"],
            "Statements after": r["after_statements"],
            "Statements removed": r["statement_reduction"],
            "Before (ms)": round(r["before_ms"], 4) if r["before_ms"] is not None else None,
            "After (ms)": round(r["after_ms"], 4) if r["after_ms"] is not None else None,
            "Saved (ms)": round(r["delta_ms"], 4) if r["delta_ms"] is not None else None,
            "Reduction": f"{r['reduction_pct']:.1f}%" if r["reduction_pct"] is not None else "—",
            f"≤ {evidence.TARGET_MS:.0f} ms": ("✅" if r["after_within_target"] else "❌")
                                              if r["after_within_target"] is not None else "—",
            "Note": "floor — understated" if r["after_is_floor"] else "",
        }
        for r in rows
    ]),
    width="stretch", hide_index=True,
)

st.caption(
    "**These are database times, not page load times.** The limiter did not stop running — "
    "its state moved somewhere that is not the database, and left this budget. A screen "
    "falling under 5 ms of database time is not the same as its page getting that much "
    "faster."
)

st.info(
    "**Where the numbers come from** — see **Evidence & Method** in the sidebar for the "
    "measurement dates, sample counts, percentiles and the full method. Nothing on this "
    "page is typed in; every figure is calculated from the two evidence files shipped with "
    "this app.",
    icon="📋",
)
