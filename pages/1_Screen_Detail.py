"""Per-screen query breakdown — which statements make up each screen's database time.

Every screen is shown as the list of statement shapes that contribute to it, with each
one's execution count, contribution in milliseconds, and share of that screen's total.
All of it is computed at render time from the two evidence files; no value is written here.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from perfdash import evidence, ui_pages

st.set_page_config(page_title="Screen Detail", page_icon="🔍", layout="wide")

st.title("Screen detail — the queries behind each screen")
st.caption(
    "Statements are named by shape; no query text, table name or identifier is shown. "
    "Contribution = measured median × how many times the statement runs on that screen."
)

try:
    screens = [evidence.screen_breakdown(p["key"]) for p in ui_pages.PAGES]
    before_pages = {p["key"]: p for p in evidence.pages(evidence.BEFORE)}
    after_pages = {p["key"]: p for p in evidence.pages(evidence.AFTER)}
except evidence.EvidenceError as exc:
    st.error(f"**Evidence could not be read.**\n\n`{exc}`", icon="🚫")
    st.stop()

BUCKET_LABEL = {
    ui_pages.BUSINESS: "Application work",
    ui_pages.AUTH: "Sign-in / session",
    ui_pages.LIMITER: "Rate limiting",
}


def ms(value: float | None, places: int = 4) -> float | None:
    return None if value is None else round(value, places)


st.warning(evidence.CALIBRATION_NOTE, icon="⚠️")

st.divider()

# ======================================================================================
# Per-screen breakdown
# ======================================================================================

for s in screens:
    header = f"{s['title']}"
    if s["arabic"]:
        header += f"  ·  {s['arabic']}"
    header += (f"      BEFORE {s['before_statements']} statements / {s['before_ms']:.4f} ms"
               f"   →   AFTER {s['after_statements']} statement"
               f"{'s' if s['after_statements'] != 1 else ''} / {s['after_ms']:.4f} ms")

    with st.expander(header, expanded=(s["key"] == "login")):
        st.caption(f"`{s['route']}`")

        left, right = st.columns(2)
        left.metric("BEFORE", f"{s['before_ms']:.4f} ms",
                    f"{s['before_statements']} statements", delta_color="off")
        right.metric("AFTER", f"{s['after_ms']:.4f} ms",
                     f"{s['after_statements']} statement"
                     f"{'s' if s['after_statements'] != 1 else ''}"
                     + ("  (floor)" if s["after_is_floor"] else ""), delta_color="off")

        # ---- the query list, in the order the screen issues them --------------------
        st.markdown("**Queries**")
        st.dataframe(
            pd.DataFrame([
                {
                    "Statement shape": r["shape"],
                    "Category": r["category"],
                    "What it does": r["label"],
                    "Runs BEFORE": r["before_executions"],
                    "Runs AFTER": r["after_executions"],
                    "BEFORE p50 (ms)": ms(r["before_p50"]),
                    "AFTER p50 (ms)": ms(r["after_p50"]),
                    "Status": "REMOVED" if r["removed"] else (
                        "floor — understated" if r["is_floor"] else "active"),
                }
                for r in s["rows"]
            ]),
            width="stretch", hide_index=True,
        )

        # ---- contribution waterfall -------------------------------------------------
        st.markdown("**Contribution to this screen's database time**")

        contrib = pd.DataFrame([
            {
                "Statement shape": r["shape"],
                "Runs": r["before_executions"],
                "BEFORE contribution (ms)": ms(r["before_contribution_ms"]),
                "BEFORE share": (f"{r['before_share_pct']:.1f}%"
                                 if r["before_share_pct"] is not None else "—"),
                "AFTER contribution (ms)": ms(r["after_contribution_ms"]),
                "AFTER share": (f"{r['after_share_pct']:.1f}%"
                                if r["after_share_pct"] is not None else "—"),
            }
            for r in sorted(s["rows"],
                            key=lambda r: -(r["before_contribution_ms"] or 0))
        ])
        st.dataframe(contrib, width="stretch", hide_index=True)

        chart_before = pd.DataFrame(
            {"BEFORE contribution (ms)": [r["before_contribution_ms"] or 0.0
                                          for r in s["rows"]]},
            index=[r["shape"] for r in s["rows"]],
        )
        chart_after = pd.DataFrame(
            {"AFTER contribution (ms)": [r["after_contribution_ms"] or 0.0
                                         for r in s["rows"]]},
            index=[r["shape"] for r in s["rows"]],
        )
        bar_l, bar_r = st.columns(2)
        with bar_l:
            st.caption("BEFORE — per-statement contribution")
            st.bar_chart(chart_before, horizontal=True, height=260)
        with bar_r:
            st.caption("AFTER — per-statement contribution")
            st.bar_chart(chart_after, horizontal=True, height=260)

        # ---- bucket split ------------------------------------------------------------
        st.markdown("**By kind of work**")
        st.dataframe(
            pd.DataFrame([
                {
                    "Kind": BUCKET_LABEL[bucket],
                    "BEFORE (ms)": ms(before_pages[s["key"]]["bucket_totals"][bucket]),
                    "AFTER (ms)": ms(after_pages[s["key"]]["bucket_totals"][bucket]),
                }
                for bucket in ui_pages.BUCKETS
            ]),
            width="stretch", hide_index=True,
        )

        if s["after_is_floor"]:
            st.warning(
                "This screen's AFTER total is a **FLOOR**, not a value: it includes a write "
                "measured inside a transaction that was rolled back, so the real committed "
                "cost is higher. The reduction reported for this screen is therefore "
                "understated, not overstated.",
                icon="⚖️",
            )

        if not (s["before_is_complete"] and s["after_is_complete"]):
            st.error(
                "One or more statements on this screen have no measurement. They contribute "
                "NOTHING to the totals above — never a zero — so the totals are not usable "
                "as a comparison.",
                icon="🚫",
            )

        for item in s["conditional"]:
            st.info(
                f"**{item['name']}** — `{evidence.STATUS_CONDITIONAL}`\n\n{item['explanation']}",
                icon="🚧",
            )

st.divider()

# ======================================================================================
# Cross-screen view
# ======================================================================================

st.header("All seven screens, by kind of work")

st.dataframe(
    pd.DataFrame([
        {
            "Screen": s["title"],
            **{f"{BUCKET_LABEL[b]} — before":
               ms(before_pages[s["key"]]["bucket_totals"][b]) for b in ui_pages.BUCKETS},
            **{f"{BUCKET_LABEL[b]} — after":
               ms(after_pages[s["key"]]["bucket_totals"][b]) for b in ui_pages.BUCKETS},
        }
        for s in screens
    ]),
    width="stretch", hide_index=True,
)

_share = [
    (s["title"],
     100.0 * before_pages[s["key"]]["bucket_totals"][ui_pages.LIMITER]
     / before_pages[s["key"]]["all_sql_ms"])
    for s in screens if before_pages[s["key"]]["all_sql_ms"]
]
st.info(
    "**Rate limiting was the largest single cost on every screen.** Its share of database "
    "time before the change: "
    + " · ".join(f"{name} {pct:.1f}%" for name, pct in _share),
    icon="📊",
)
