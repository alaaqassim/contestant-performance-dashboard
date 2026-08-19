"""Per-screen breakdown — where the database time goes on each surface."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from perfdash import evidence, ui_pages

st.set_page_config(page_title="Screen Detail", page_icon="🔍", layout="wide")

st.title("Screen detail — where the time goes")
st.caption(
    "Each screen broken into the three kinds of work it does. Statements are named by "
    "shape; no query text is shown."
)

try:
    before_pages = {p["key"]: p for p in evidence.pages(evidence.BEFORE)}
    after_pages = {p["key"]: p for p in evidence.pages(evidence.AFTER)}
    rows = evidence.compare()
except evidence.EvidenceError as exc:
    st.error(f"**Evidence could not be read.**\n\n`{exc}`", icon="🚫")
    st.stop()

BUCKET_LABEL = {
    ui_pages.BUSINESS: "Application work",
    ui_pages.AUTH: "Sign-in / session",
    ui_pages.LIMITER: "Rate limiting",
}

# ======================================================================================
# Where the cost sat, before and after
# ======================================================================================

st.header("What each screen was actually spending time on")

split = pd.DataFrame([
    {
        "Screen": r["short_title"],
        **{f"{BUCKET_LABEL[b]} — before": round(before_pages[r["key"]]["bucket_totals"][b], 4)
           for b in ui_pages.BUCKETS},
        **{f"{BUCKET_LABEL[b]} — after": round(after_pages[r["key"]]["bucket_totals"][b], 4)
           for b in ui_pages.BUCKETS},
    }
    for r in rows
])
st.dataframe(split, width="stretch", hide_index=True)

_limiter_share = [
    (r["short_title"],
     100.0 * before_pages[r["key"]]["bucket_totals"][ui_pages.LIMITER]
     / before_pages[r["key"]]["all_sql_ms"])
    for r in rows if before_pages[r["key"]]["all_sql_ms"]
]
st.info(
    "**Rate limiting was the largest single cost on every screen.** Its share of database "
    "time before the change: "
    + " · ".join(f"{name} {share:.1f}%" for name, share in _limiter_share),
    icon="📊",
)

st.divider()

# ======================================================================================
# Per-screen expanders
# ======================================================================================

st.header("Statement-level detail")
st.caption(
    "Each statement shape, how often it runs on that screen, and its measured median. "
    "Contribution = median × number of executions."
)

for r in rows:
    header = f"{r['short_title']}"
    if r["arabic"]:
        header += f"  ·  {r['arabic']}"
    header += f"   —   {r['before_ms']:.4f} ms → {r['after_ms']:.4f} ms" \
        if r["comparable"] else "   —   incomplete"

    with st.expander(header):
        st.caption(f"`{r['route']}`")
        for state, page in (("BEFORE", before_pages[r["key"]]),
                            ("AFTER", after_pages[r["key"]])):
            st.markdown(f"**{state}** — {page['query_count']} statements, "
                        f"{page['all_sql_ms']:.4f} ms total")
            measured = [row for row in page["rows"] if row["measured"]]
            if not measured:
                st.caption("No statements remain on this screen in this state.")
                continue
            st.dataframe(
                pd.DataFrame([
                    {
                        "Kind": BUCKET_LABEL[row["bucket"]],
                        "Statement shape": row["component"],
                        "What it does": row["label"] if row.get("label") else "",
                        "Runs": row["executions"],
                        "Median (ms)": round(row["p50"], 4),
                        "p95 (ms)": round(row["p95"], 4) if row["p95"] is not None else None,
                        "p99 (ms)": round(row["p99"], 4) if row["p99"] is not None else None,
                        "Samples": row["n"],
                        "Contribution (ms)": round(row["contribution_ms"], 4),
                        "Note": "floor — understated"
                                if evidence.FLOOR_TAG in row["evidence"] else "",
                    }
                    for row in measured
                ]),
                width="stretch", hide_index=True,
            )

st.divider()

# ======================================================================================
# What left the request path
# ======================================================================================

st.header("What was removed, and what it had cost")

after_records = evidence.load(evidence.AFTER)
dropped_ops = evidence.STATES[evidence.AFTER]["zero_execution_operations"]
idle_index = ui_pages.live_index(after_records, set())
idle = sorted({(r["operation"], r["component"]) for r in after_records
               if r["operation"] in dropped_ops})

st.markdown(
    f"**{len(idle)} statement shapes stopped running altogether** — they were not made "
    f"cheaper, they left the request path. They are still measured below, so the comparison "
    f"cannot quietly hide what it removed."
)

st.dataframe(
    pd.DataFrame([
        {
            "Statement shape": comp,
            "What it did": (idle_index[(op, comp)].get("label") or ""),
            "Median cost when it ran (ms)": round(
                (ui_pages.stats.stats_for(idle_index[(op, comp)]) or {}).get("median_ms", 0.0), 4),
            "Times it now runs": 0,
        }
        for op, comp in idle
    ]),
    width="stretch", hide_index=True,
)

st.caption(
    "The two most expensive shapes here are database WRITES. Every throttled request "
    "performed at least one, and each had to be flushed durably to disk — which is why "
    "rate limiting dominated the budget rather than the application's own queries."
)
