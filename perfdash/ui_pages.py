# PUBLIC PRESENTATION SNAPSHOT - copied from the engineering dashboard.
#
# Identical to tools/performance-dashboard/perfdash/ui_pages.py EXCEPT that every
# parameterised statement text has been replaced by the shape name. That field is
# display-only and takes no part in any arithmetic: the seven page totals produced by
# this file are asserted EQUAL to the engineering tree's at build time, and the build
# fails if they are not.
"""Contestant UI page SQL timing — per-page rollup over the live ledger.

WHY THIS MODULE EXISTS SEPARATELY FROM `rollup.py`
--------------------------------------------------
`rollup.py` aggregates by OPERATION across a whole contestant JOURNEY, scaled to a 40,000
population. That is the right model for capacity questions and it is not changed here.

This module answers a different question — the one the client asked: *what does ONE page
cost, once, in SQL?* A page's cost needs per-PAGE execution counts, and those are not the
per-journey frequencies the catalogue owns. Example: `rate_limiter/key_read` runs **4×
on every single page**, but the catalogue's `executions_per_contestant` for it is **28**,
because the modelled journey issues 7 throttled requests. Both numbers are correct for
their own question. Mixing them would be wrong, so this map is kept deliberately apart and
the catalogue's journey frequencies are NOT read, written or altered by anything here.

WHERE THE EXECUTION COUNTS COME FROM
------------------------------------
Not from a model — from the real, already-verified browser E2E trace: `PERF_PROBE=1`,
port 8084, 38 requests / 238 SQL statements, reconciled exactly (156 limiter + 29 auth +
53 business). Each page below cites the trace request number it was read from. Nothing here
was measured, re-measured or estimated by this module.

WHERE THE MILLISECONDS COME FROM
--------------------------------
Every timing is resolved LIVE from the measurement ledger at render time. No total, and no
component figure, is hard-coded anywhere in this file or in the page that renders it — the
seven page totals are arithmetic over whatever the ledger currently holds. If a measurement
is superseded tomorrow, these totals move on their own.

Source of truth for the underlying evidence:
    docs/performance/CONTESTANT_UI_PAGE_SQL_TIMING_2026-08-18.md
"""

from __future__ import annotations

from typing import Any

from . import stats

SOURCE_DOC = "docs/performance/CONTESTANT_UI_PAGE_SQL_TIMING_2026-08-18.md"

BUSINESS = "Business"
AUTH = "Auth/Session"
LIMITER = "Limiter/Cache"
BUCKETS = (BUSINESS, AUTH, LIMITER)

#: Evidence tags that make a contributed figure a FLOOR rather than a value. A page whose
#: total includes any of these must say so on the total itself, never only in a footnote.
LOWER_BOUND_TAGS = ("ROLLBACK_LOWER_BOUND",)


def _row(bucket: str, operation: str, component: str, sql: str, executions: int
         ) -> dict[str, Any]:
    return {"bucket": bucket, "operation": operation, "component": component,
            "sql": sql, "executions": executions}


#: The session guard's actor read. Fires
#: exactly once per AUTHENTICATED request, so once on every page except Login (which has no
#: session yet and instead performs the credential lookup below).
_AUTH_ACTOR = ("session_guard", "user_by_id",
               "[statement shape: user_by_id]")

#: The limiter shapes every throttled `/api` request issues on the WARM path.
_LIMITER_WARM = [
    _row(LIMITER, "rate_limiter", "key_read",
         "[statement shape: key_read]", 4),
    _row(LIMITER, "rate_limiter", "locking_read",
         "[statement shape: locking_read]", 1),
    _row(LIMITER, "rate_limiter", "increment_update",
         "[statement shape: increment_update]", 1),
]

#: COLD adds the two key creations (counter + timer) for a key not yet in the table.
_LIMITER_COLD_EXTRA = [
    _row(LIMITER, "rate_limiter", "key_insert",
         "[statement shape: key_insert]", 2),
]


PAGES: list[dict[str, Any]] = [
    {
        "key": "login",
        "title": "1 · Login",
        "route": "POST /integration/login",
        "trace_request": 6,
        "note": (
            "No session exists yet, so there is no session-guard actor read; the "
            "`users`-by-email statement IS the authentication lookup and is bucketed as "
            "Auth/Session here. `perfdash/catalog.py` counts that same statement under "
            "business SQL for its own journey model — the bucket label differs, the "
            "statement, its timing and this page's total do not."
        ),
        "rows": [
            _row(AUTH, "login", "user_lookup",
                 "[statement shape: user_lookup]", 1),
            *_LIMITER_WARM,
            *_LIMITER_COLD_EXTRA,
            # Conditional: fires only when a stale key is re-read. The traced run hit it
            # twice because the lab cache held 220 expired rows. At a genuinely cold T-0
            # every key is virgin and this would be 0. Shown as traced, and called out.
            _row(LIMITER, "rate_limiter", "expired_sweep",
                 "[statement shape: expired_sweep]", 2),
        ],
        "conditional_components": {
            "expired_sweep": (
                "CONDITIONAL — fires only when a stale limiter key is re-read. The traced "
                "run executed it twice because the lab's cache held 220 expired rows; at a "
                "genuinely cold T-0 every key is virgin and it would fire 0 times. It is "
                "shown here exactly as traced."
            ),
        },
    },
    {
        "key": "dashboard_warm",
        "title": "2a · Dashboard / My Participations (WARM — fully loaded)",
        "route": "GET /api/me/dashboard",
        "trace_request": 16,
        "note": (
            "The fully-loaded path: the contestant already holds an application, so all "
            "four business statements fire. This is the state the testing conventions "
            "require exercising."
        ),
        "rows": [
            _row(AUTH, *_AUTH_ACTOR, 1),
            *_LIMITER_WARM,
            _row(BUSINESS, "dashboard", "Q2_count_registrations",
                 "[statement shape: Q2_count_registrations]", 1),
            _row(BUSINESS, "dashboard", "Q3_registration_list",
                 "[statement shape: Q3_registration_list]", 1),
            _row(BUSINESS, "dashboard", "Q4_competition_by_pk",
                 "[statement shape: Q4_competition_by_pk]", 1),
            _row(BUSINESS, "dashboard", "Q5_result_publication",
                 "[statement shape: Q5_result_publication]", 1),
        ],
        "conditional_components": {
            "findForRegistrations (participant_results)": (
                "CONDITIONAL — NOT YET MEASURED, and deliberately carries NO number. "
                "`LeaderboardRepository::findForRegistrations()` reads the visible result: "
                "`[statement shape: participant_results read]`. "
                "CURRENT EXECUTIONS = 0. `result_publications` is EMPTY, so `publishedMap()` "
                "(the `Q5_result_publication` row above) returns all-false, "
                "`visibleRegistrationIds` short-circuits to `[]`, and the method returns "
                "before issuing any SQL — no `participant_results` statement executes today. "
                "This page's totals are therefore CORRECT AS MEASURED for the current "
                "zero-publication state, and it is not a gap: a shape that never runs costs "
                "nothing. "
                "⛔ ONCE A REAL PUBLICATION EXISTS this query fires once per dashboard load "
                "and MUST be measured from a genuine Exam-Engine-produced result. The "
                "historical and current Dashboard numbers must NOT be altered, "
                "back-filled or extrapolated to estimate that future cost — the new state "
                "gets its own measurement, recorded separately."
            ),
        },
    },
    {
        "key": "dashboard_cold",
        "title": "2b · Dashboard / My Participations (COLD — empty state, first load)",
        "route": "GET /api/me/dashboard",
        "trace_request": 9,
        "note": (
            "First load, before any application exists. The competition-hydration and "
            "result-visibility reads short-circuit on an empty id set, so only the count "
            "runs — but this is also the contestant's FIRST use of the `api-read` limiter "
            "key, so it pays the COLD limiter path (2 key creations). Fewer business "
            "statements, more limiter statements. Not an average of the WARM state."
        ),
        "rows": [
            _row(AUTH, *_AUTH_ACTOR, 1),
            *_LIMITER_WARM,
            *_LIMITER_COLD_EXTRA,
            _row(BUSINESS, "dashboard", "Q2_count_registrations",
                 "[statement shape: Q2_count_registrations]", 1),
        ],
    },
    {
        "key": "competition_list",
        "title": "3 · Available Competitions",
        "route": "GET /api/competitions",
        "trace_request": 10,
        "note": "",
        "rows": [
            _row(AUTH, *_AUTH_ACTOR, 1),
            *_LIMITER_WARM,
            _row(BUSINESS, "competition_list", "Q6_visible_count",
                 "[statement shape: Q6_visible_count]", 1),
            _row(BUSINESS, "competition_list", "Q7_visible_list",
                 "[statement shape: Q7_visible_list]", 1),
        ],
    },
    {
        "key": "competition_detail",
        "title": "4 · Competition Detail",
        "route": "GET /api/competitions/{id}",
        "trace_request": 13,
        "note": "",
        "rows": [
            _row(AUTH, *_AUTH_ACTOR, 1),
            *_LIMITER_WARM,
            _row(BUSINESS, "competition_detail", "detail_read",
                 "[statement shape: detail_read]", 1),
            _row(BUSINESS, "competition_detail", "category_read",
                 "[statement shape: category_read]", 1),
        ],
    },
    {
        "key": "apply",
        "title": "5 · Apply (write path)",
        "route": "POST /api/competitions/{id}/registrations",
        "trace_request": 14,
        "note": (
            "`api-write` is a SEPARATE limiter tier from `api-read`, so this request is "
            "always the first against its own key and always pays the COLD limiter path. "
            "Five business statements fire, in this order."
        ),
        "rows": [
            _row(AUTH, *_AUTH_ACTOR, 1),
            *_LIMITER_WARM,
            *_LIMITER_COLD_EXTRA,
            _row(BUSINESS, "apply", "competition_detail_read",
                 "[statement shape: competition_detail_read]", 1),
            _row(BUSINESS, "apply", "duplicate_precheck",
                 "[statement shape: duplicate_precheck]", 1),
            _row(BUSINESS, "apply", "shared_lock_read",
                 "[statement shape: shared_lock_read]", 1),
            _row(BUSINESS, "apply", "registration_insert",
                 "[statement shape: registration_insert]", 1),
            _row(BUSINESS, "apply", "audit_insert",
                 "[statement shape: audit_insert]", 1),
        ],
    },
    {
        "key": "application_status",
        "title": "6 · Application Status",
        "route": "GET /api/registrations/{id}",
        "trace_request": 15,
        "note": (
            "⚠️ THE RESULT STATE PANEL RENDERS ON THIS PAGE, AND COSTS THIS PAGE NOTHING. "
            "It issues NO HTTP request of its own: it reads the `GET /api/me/dashboard` "
            "payload already loaded by the journey — the same response whose "
            "`Q5_result_publication` row decides whether a result is visible at all. Its SQL "
            "cost therefore belongs to page 2a, NOT to this page, and no row, timing or "
            "statement count is assigned to it here. "
            "This is the page-versus-endpoint distinction the census draws: the screen a "
            "thing is drawn on is not necessarily the request that paid for it."
        ),
        "rows": [
            _row(AUTH, *_AUTH_ACTOR, 1),
            *_LIMITER_WARM,
            _row(BUSINESS, "application_status", "registration_read",
                 "[statement shape: registration_read]", 1),
            _row(BUSINESS, "application_status", "competition_authorization_read",
                 "[statement shape: competition_authorization_read]", 1),
        ],
    },
]


def live_index(records: list[dict[str, Any]], superseded: set[str]) -> dict[tuple[str, str], dict[str, Any]]:
    """The one live record per (operation, component). Superseded records never resolve.

    ⚠️ THE KEY IS `(operation, component)` — NOT the ledger's `(run_id, experiment, operation,
    component)`. So this index is only unambiguous while at most one live record exists per
    shape, which is exactly the ledger's standing invariant: a second measurement of a shape
    must SUPERSEDE the first. Where that holds, the resolution here is total and order-free.

    It is not defended by this function, and it cannot be: given two live records for one
    shape, the dict comprehension keeps whichever it iterated LAST — no error, no gap, a wrong
    number. `index_collisions()` is what makes that condition visible, and `validate.py`
    asserts it is empty.

    A run that must NOT compete for live status therefore does not belong in `data/raw/`. See
    `data/experiments/README.md` and `perfdash/experiments.py`, which build their own index
    from a disjoint record list and never touch this one.
    """
    return {(r["operation"], r["component"]): r
            for r in records if r["measurement_id"] not in superseded}


def index_collisions(records: list[dict[str, Any]], superseded: set[str]) -> dict[tuple[str, str], list[str]]:
    """(operation, component) pairs carrying live records from MORE THAN ONE run.

    Each one is a shape whose unfiltered page total is ambiguous. The UI must scope by run;
    this function is what lets the validator say so out loud.
    """
    seen: dict[tuple[str, str], set[str]] = {}
    for r in records:
        if r["measurement_id"] in superseded:
            continue
        seen.setdefault((r["operation"], r["component"]), set()).add(r["run_id"])
    return {k: sorted(v) for k, v in seen.items() if len(v) > 1}


def resolve_row(row: dict[str, Any], index: dict[tuple[str, str], dict[str, Any]]) -> dict[str, Any]:
    """Attach the LIVE measurement to one execution-map row.

    An unresolvable or valueless component yields `measured=False` and contributes NOTHING.
    It must never be silently treated as 0 ms — that is the failure this instrument exists
    to prevent, and `validate.py` asserts it directly.
    """
    record = index.get((row["operation"], row["component"]))
    resolved = dict(row)
    resolved.update({
        "measured": False, "p50": None, "p95": None, "p99": None, "n": 0,
        "contribution_ms": None, "evidence": [], "generation": None,
        "write": None, "index_used": None, "access_type": None,
    })
    if record is None:
        resolved["gap_reason"] = "no live record in the ledger"
        return resolved

    resolved["generation"] = record.get("measurement_generation")
    resolved["run_id"] = record.get("run_id")
    # What the RUN itself says about how often this shape executes. A run that moved the shape
    # off the request path declares 0, and `page_totals` drops the row rather than charging it.
    resolved["declared_executions"] = record.get("executions_per_contestant")
    resolved["evidence"] = list(record.get("evidence") or [])
    db = record.get("database") or {}
    resolved["write"] = db.get("write")
    resolved["index_used"] = db.get("index_used")
    resolved["access_type"] = db.get("access_type")

    summary = stats.stats_for(record)
    if not summary or summary.get("median_ms") is None:
        resolved["gap_reason"] = f"record is {record.get('measurement_generation')} — carries no value"
        return resolved

    resolved.update({
        "measured": True,
        "p50": summary["median_ms"],
        "p95": summary.get("p95_ms"),
        "p99": summary.get("p99_ms"),
        "n": int(summary.get("n") or 0),
        # THE rule: page contribution = measured median x executions on that page.
        "contribution_ms": summary["median_ms"] * row["executions"],
        "gap_reason": "",
    })
    return resolved


def page_totals(
    page: dict[str, Any],
    index: dict[tuple[str, str], dict[str, Any]],
    zero_execution_operations: tuple[str, ...] = (),
) -> dict[str, Any]:
    """One page's resolved rows and bucket totals, computed from live measurements only.

    `zero_execution_operations` names operations that a given STATE removed from the request
    path entirely — they are dropped from the page rather than charged to it or reported as
    gaps, because a shape that never runs is not a hole in a cost model. The file-limiter
    pilot passes `("rate_limiter",)`, and the claim is backed by a live SQL trace in which not
    one `cache` statement appears.

    ⚠️ IT IS NOT DERIVED FROM `executions_per_contestant`. That field is a PER-JOURNEY
    frequency and the baseline's `expired_sweep` carries 0 there while still executing twice
    on the Login PAGE — the exact per-page-versus-per-journey distinction this module exists
    to keep apart. Using it as the drop signal silently removed two real statements from the
    Login baseline and cut roughly ten milliseconds off its total. (The figures are
    deliberately not quoted here: no page total may appear as a literal in this module.)
    """
    rows = [resolve_row(r, index) for r in page["rows"]]

    if zero_execution_operations:
        rows = [r for r in rows if r["operation"] not in zero_execution_operations]

    buckets = {b: 0.0 for b in BUCKETS}
    for r in rows:
        if r["measured"]:
            buckets[r["bucket"]] += r["contribution_ms"]

    gaps = [r for r in rows if not r["measured"]]
    lower_bound_rows = [r for r in rows
                        if r["measured"] and set(r["evidence"]) & set(LOWER_BOUND_TAGS)]

    return {
        **{k: v for k, v in page.items() if k != "rows"},
        "rows": rows,
        "bucket_totals": buckets,
        "all_sql_ms": sum(buckets.values()),
        "query_count": sum(r["executions"] for r in rows),
        "shape_count": len(rows),
        "gaps": gaps,
        "is_complete": not gaps,
        "is_lower_bound": bool(lower_bound_rows),
        "lower_bound_components": [r["component"] for r in lower_bound_rows],
        "lower_bound_tags": sorted({t for r in lower_bound_rows
                                    for t in set(r["evidence"]) & set(LOWER_BOUND_TAGS)}),
    }


def all_pages(
    records: list[dict[str, Any]],
    superseded: set[str],
    zero_execution_operations: tuple[str, ...] = (),
) -> list[dict[str, Any]]:
    """Every page's totals over one record list. Default arguments = the live ledger view."""
    index = live_index(records, superseded)
    return [page_totals(p, index, zero_execution_operations) for p in PAGES]


def distinct_shapes(pages: list[dict[str, Any]]) -> list[tuple[str, str]]:
    """Every distinct (operation, component) the six pages depend on."""
    seen: list[tuple[str, str]] = []
    for page in pages:
        for row in page["rows"]:
            key = (row["operation"], row["component"])
            if key not in seen:
                seen.append(key)
    return seen


def status_label(page: dict[str, Any]) -> str:
    if not page["is_complete"]:
        return "INCOMPLETE"
    return "COMPLETE (floor)" if page["is_lower_bound"] else "COMPLETE"
