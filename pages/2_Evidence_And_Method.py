"""Provenance — where every number on this site comes from, and what it does not claim."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from perfdash import evidence

st.set_page_config(page_title="Evidence & Method", page_icon="📋", layout="wide")

st.title("Evidence & method")
st.caption(
    "This page exists so no figure on this site has to be taken on trust. It shows where "
    "each measurement came from, how it was taken, and what it deliberately does not claim."
)

try:
    prov = {state: evidence.provenance(state) for state in (evidence.BEFORE, evidence.AFTER)}
except evidence.EvidenceError as exc:
    st.error(f"**Evidence could not be read.**\n\n`{exc}`", icon="🚫")
    st.stop()

# ======================================================================================
# Provenance
# ======================================================================================

st.header("The two measurement runs")

for state in (evidence.BEFORE, evidence.AFTER):
    spec, p = evidence.STATES[state], prov[state]
    env = p["environment"]

    with st.container(border=True):
        st.subheader(spec["title"])
        if not p["environment_is_uniform"]:
            st.warning(
                "Records in this file describe more than one environment, so no single "
                "environment is claimed for the run."
            )
        st.markdown(
            f"- **Measured** {', '.join(p['recorded_at']) or 'date not recorded'}\n"
            f"- **{p['record_count']} statement shapes**, "
            f"{' / '.join(str(n) for n in p['sample_counts'])} timed samples each\n"
            f"- **Hardware** {env.get('machine', 'not recorded')} "
            f"({env.get('cpu_cores', '?')} cores)\n"
            + (f"- **Runtime** PHP {env['php_version']} ({env.get('php_thread_safety', '?')})\n"
               if env.get("php_version") else "")
            + (f"- **Rate-limiter store** `{env['limiter_store']}` · "
               f"application cache `{env.get('cache_default', '?')}` · "
               f"sessions `{env.get('session_driver', '?')}` · "
               f"queues `{env.get('queue_default', '?')}`\n"
               if env.get("limiter_store") else "")
            + f"- **Evidence file** `data/{p['file']}`\n"
            + f"- **Run identifier(s)** {', '.join(f'`{r}`' for r in p['runs'])}"
        )
        for caveat in p["caveats"]:
            st.caption(caveat)

st.divider()

# ======================================================================================
# How a page total is built
# ======================================================================================

st.header("How a screen total is calculated")

st.markdown(
    "Nothing on this site is a typed-in number. Each screen's total is built the same way, "
    "every time the page is drawn:\n\n"
    "```\n"
    "contribution of a statement = its measured median  ×  how often it runs on that screen\n"
    "screen total                = the sum of its contributions\n"
    "```\n\n"
    "The **medians** come from the timed samples in the evidence files. The **execution "
    "counts** come from a recorded trace of a real browser session walking the whole "
    "contestant journey — not from an estimate.\n\n"
    "**A statement with no measurement contributes nothing — never a zero.** If any shape a "
    "screen depends on were missing, that screen would be marked INCOMPLETE and would carry "
    "no total and no reduction, rather than silently reporting a smaller number."
)

st.divider()

# ======================================================================================
# What this does not claim
# ======================================================================================

st.header("What these figures do not claim")

st.warning(
    "**The two runs were measured on different harnesses.** The original measurement "
    "harness was not kept, so the second run re-implements its documented method. On "
    "identical read statements it lands roughly three times higher. The two runs' absolute "
    "millisecond values are therefore **not interchangeable**.\n\n"
    "What makes the comparison sound is that the rate-limiter statements — the quantity "
    "being removed — were **re-measured on the second harness**. So the amount removed and "
    "the amount remaining sit on one calibration, even though the baseline column does not.",
    icon="⚠️",
)

st.warning(
    "**Apply's total is a floor, not a value.** Its two write statements were measured "
    "inside a transaction that was rolled back, so they never paid the final commit cost. "
    "The true figure is higher — meaning the reduction reported for that screen is "
    "understated, not overstated.",
    icon="⚖️",
)

st.warning(
    "**These are single-session measurements, not a load test.** Each statement was timed "
    "on its own with no concurrent traffic. They establish what one operation costs; they "
    "do not establish behaviour under the start-of-competition burst, which is a separate "
    "exercise.",
    icon="🧪",
)

st.error(
    "**FILE LIMITER — LOCAL ISOLATION PILOT · NOT PRODUCTION ARCHITECTURE**\n\n"
    "The file-backed limiter store was used for one purpose: to prove that database-backed "
    "rate limiting was the dominant database cost. It cannot be shared between application "
    "servers and serialises on file locks, so it is **not** the recommended production "
    "answer. Redis, or another shared low-latency store, remains the production candidate.",
    icon="⛔",
)

st.divider()

# ======================================================================================
# The raw evidence
# ======================================================================================

st.header("Every measurement in the two files")

st.caption(
    "Statement shapes are named, never quoted. The full distribution behind each median is "
    "shown so the medians can be judged rather than assumed."
)

table = []
for state in (evidence.BEFORE, evidence.AFTER):
    for r in evidence.load(state):
        from perfdash import stats as _stats
        s = _stats.stats_for(r) or {}
        table.append({
            "Run": evidence.STATES[state]["short"],
            "Area": r["operation"],
            "Statement shape": r["component"],
            "What it does": r.get("label") or "",
            "Median (ms)": round(s.get("median_ms", 0.0), 4),
            "p95 (ms)": round(s["p95_ms"], 4) if s.get("p95_ms") is not None else None,
            "p99 (ms)": round(s["p99_ms"], 4) if s.get("p99_ms") is not None else None,
            "Samples": int(s.get("n") or 0),
            "Quality tags": ", ".join(r.get("evidence") or []),
        })
st.dataframe(pd.DataFrame(table), width="stretch", hide_index=True)

st.divider()

st.header("What this snapshot is")

st.markdown(
    "A **read-only presentation copy** of an internal engineering measurement tool.\n\n"
    "- It connects to **no database** and makes **no network calls**. Everything it shows "
    "is in the two evidence files shipped alongside it.\n"
    "- The evidence files are **sanitised extracts**: performance figures, sample counts, "
    "percentiles and quality tags are preserved exactly as measured; internal identifiers, "
    "file paths, machine names and query text were removed before publication.\n"
    "- **No performance number was altered.** The screen totals this snapshot produces are "
    "verified equal to the internal tool's at build time.\n"
    "- The internal tool remains the source of truth for engineering decisions."
)
