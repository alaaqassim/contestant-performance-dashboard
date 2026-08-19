"""Loads the two sanitised evidence files this presentation is built from.

This module replaces the engineering dashboard's `store.py` + `experiments.py`. Those read
an append-only ledger into SQLite and enforce a live/superseded model that a read-only
presentation does not need and must not carry: the public snapshot ships no database, opens
no connection, and reaches no network.

WHAT IT READS
    data/before-database-limiter.jsonl   the measured baseline
    data/after-file-limiter-pilot.jsonl  the file rate-limiter isolation pilot

Both are resolved RELATIVE TO THIS FILE, so the app runs from any working directory on any
operating system. Both are parsed through `schema.parse` — the same validator the
engineering ledger uses — so a malformed or truncated artifact fails loudly rather than
rendering a smaller number.

NOTHING HERE DECLARES A VALUE. Every millisecond, count, delta and percentage the app shows
is arithmetic over these two files, performed at render time by `ui_pages`.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from . import schema, stats, ui_pages

#: `parents[1]` is the snapshot root — never an absolute path, never a drive letter.
DATA_DIR = Path(__file__).resolve().parents[1] / "data"

BEFORE = "before"
AFTER = "after"

STATES: dict[str, dict[str, Any]] = {
    BEFORE: {
        "file": "before-database-limiter.jsonl",
        "title": "BEFORE — rate limiter counting into the database",
        "short": "BEFORE",
        # Nothing is excluded: in the baseline every shape genuinely executed.
        "zero_execution_operations": (),
    },
    AFTER: {
        "file": "after-file-limiter-pilot.jsonl",
        "title": "AFTER — FILE LIMITER · LOCAL ISOLATION PILOT",
        "short": "AFTER",
        # The five rate-limiter shapes are still MEASURED — their cost stays visible — but
        # they execute zero times, proven by a live statement trace of the whole journey in
        # which not one cache-table statement appears. A statement that never runs is not a
        # hole in a cost model, so it is removed from the page rather than charged to it.
        "zero_execution_operations": ("rate_limiter",),
    },
}

#: The measurement whose page total is a FLOOR carries this tag. Kept as a named constant
#: because the presentation must never quietly round a floor into a value.
FLOOR_TAG = "ROLLBACK_LOWER_BOUND"


class EvidenceError(RuntimeError):
    """An evidence file is missing, malformed, or internally inconsistent."""


def path_for(state: str) -> Path:
    try:
        return DATA_DIR / STATES[state]["file"]
    except KeyError as exc:
        raise EvidenceError(f"unknown state '{state}'") from exc


def load(state: str) -> list[dict[str, Any]]:
    """Parse one evidence file through the ledger's own validator."""
    path = path_for(state)
    if not path.exists():
        raise EvidenceError(f"evidence file not found: {path.name}")

    records: list[dict[str, Any]] = []
    for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("//"):
            continue
        try:
            records.append(schema.parse(json.loads(line), where=f"{path.name}:{lineno}").to_dict())
        except Exception as exc:                       # noqa: BLE001 - surfaced to the UI
            raise EvidenceError(f"{path.name}:{lineno} is not a valid measurement: {exc}") from exc

    if not records:
        raise EvidenceError(f"{path.name} contains no measurements")
    return records


def pages(state: str) -> list[dict[str, Any]]:
    """The seven contestant surfaces, costed from that state's records alone.

    The `superseded` set is empty by construction: a presentation snapshot carries one
    measurement per shape per state, with no corrections to resolve.
    """
    spec = STATES[state]
    return ui_pages.all_pages(load(state), set(), spec["zero_execution_operations"])


def provenance(state: str) -> dict[str, Any]:
    """Environment and sampling facts read OUT OF the file, never declared about it."""
    records = load(state)
    environments = {json.dumps(r.get("environment") or {}, sort_keys=True) for r in records}
    return {
        "file": STATES[state]["file"],
        "runs": sorted({r["run_id"] for r in records}),
        "record_count": len(records),
        "recorded_at": sorted({r.get("recorded_at") for r in records if r.get("recorded_at")}),
        "sample_counts": sorted({len(r.get("samples_ms") or []) for r in records}),
        "environment": json.loads(next(iter(environments))) if len(environments) == 1 else {},
        "environment_is_uniform": len(environments) == 1,
        "caveats": sorted({r.get("conditions_caveats") for r in records
                           if r.get("conditions_caveats")}),
    }


def compare() -> list[dict[str, Any]]:
    """Pair the two states surface by surface. Every field is arithmetic over the two files.

    A surface whose EITHER side is incomplete reports `comparable=False` and carries NO
    delta. An incomplete side means a shape has no measurement, and subtracting a total that
    is missing a component from one that is not would manufacture a saving nobody measured.
    """
    out: list[dict[str, Any]] = []
    for b, a in zip(pages(BEFORE), pages(AFTER), strict=True):
        if b["key"] != a["key"]:
            raise EvidenceError(f"surface order diverged: {b['key']} vs {a['key']}")

        comparable = b["is_complete"] and a["is_complete"]
        delta = b["all_sql_ms"] - a["all_sql_ms"] if comparable else None
        out.append({
            "key": b["key"],
            "title": b["title"],
            "short_title": SHORT_TITLES.get(b["key"], b["title"]),
            "arabic": ARABIC_TITLES.get(b["key"], ""),
            "route": b["route"],
            "comparable": comparable,
            "before_statements": b["query_count"],
            "after_statements": a["query_count"],
            "statement_reduction": b["query_count"] - a["query_count"],
            "before_ms": b["all_sql_ms"] if b["is_complete"] else None,
            "after_ms": a["all_sql_ms"] if a["is_complete"] else None,
            "delta_ms": delta,
            "reduction_pct": (100.0 * delta / b["all_sql_ms"])
                             if comparable and b["all_sql_ms"] else None,
            "after_within_target": (a["all_sql_ms"] <= TARGET_MS) if a["is_complete"] else None,
            "after_is_floor": a["is_lower_bound"],
            "after_floor_components": a["lower_bound_components"],
            "before_gaps": [f"{g['operation']}/{g['component']}" for g in b["gaps"]],
            "after_gaps": [f"{g['operation']}/{g['component']}" for g in a["gaps"]],
        })
    return out


#: The acceptance target these surfaces are measured against.
TARGET_MS = 5.0

#: Short names for an audience reading a slide, not a query plan.
SHORT_TITLES = {
    "login": "Login",
    "dashboard_warm": "My Participations (loaded)",
    "dashboard_cold": "My Participations (first load)",
    "competition_list": "Available Competitions",
    "competition_detail": "Competition Detail",
    "apply": "Apply to a Competition",
    "application_status": "Application Status",
}

ARABIC_TITLES = {
    "login": "تسجيل الدخول",
    "dashboard_warm": "مشاركاتي",
    "dashboard_cold": "مشاركاتي — أول تحميل",
    "competition_list": "المسابقات المتاحة",
    "competition_detail": "تفاصيل المسابقة",
    "apply": "التقديم على المسابقة",
    "application_status": "حالة الطلب",
}


# ======================================================================================
# Query-level view
# ======================================================================================
#
# The screens are what a contestant experiences; the QUERY SHAPES are what the database
# actually executes. This section resolves the second, and everything it returns is derived
# from the two evidence files — no timing, count or percentage is declared here.
#
# A shape is named SEMANTICALLY (`auth.user_lookup`, `limiter.key_read`). The statement text
# is not in the artifact and is not reconstructed.

#: Bucket -> the category the presentation uses.
CATEGORY = {
    ui_pages.LIMITER: "Rate Limiter",
    ui_pages.AUTH: "Authentication",
    ui_pages.BUSINESS: "Business",
}

#: Bucket -> the prefix a shape is displayed under.
PREFIX = {
    ui_pages.LIMITER: "limiter",
    ui_pages.AUTH: "auth",
    ui_pages.BUSINESS: "business",
}

STATUS_REMOVED = "REMOVED FROM SQL PATH"
STATUS_ACTIVE = "STILL ACTIVE"
STATUS_CONDITIONAL = "CONDITIONAL — NOT YET MEASURED"


def _stats(record: dict[str, Any] | None) -> dict[str, Any]:
    """p50 / p95 / p99 / n for one record, or all-None when there is no record.

    None is not zero. A shape with no measurement must render as blank, never as 0.0000.
    """
    summary = stats.stats_for(record) if record else None
    if not summary:
        return {"p50": None, "p95": None, "p99": None, "n": 0}
    return {
        "p50": summary.get("median_ms"),
        "p95": summary.get("p95_ms"),
        "p99": summary.get("p99_ms"),
        "n": int(summary.get("n") or 0),
    }


def _screen_map() -> dict[tuple[str, str], dict[str, int]]:
    """(operation, component) -> {screen key: executions on that screen}."""
    out: dict[tuple[str, str], dict[str, int]] = {}
    for page in ui_pages.PAGES:
        for row in page["rows"]:
            out.setdefault((row["operation"], row["component"]), {})[page["key"]] = \
                row["executions"]
    return out


def _bucket_of(operation: str, component: str) -> str:
    for page in ui_pages.PAGES:
        for row in page["rows"]:
            if (row["operation"], row["component"]) == (operation, component):
                return row["bucket"]
    return ui_pages.BUSINESS


def health(record: dict[str, Any] | None) -> tuple[str, str]:
    """(verdict, why) for one shape, derived ONLY from what the artifact records.

    The inputs are the access-plan class, the rows examined, and the dataset-scope evidence
    tag the measurement carries. Nothing is inferred from the timing alone, and no EXPLAIN
    is re-run or invented: if the artifact does not say, this returns "not recorded".
    """
    if not record:
        return "—", "no measurement"

    db = record.get("database") or {}
    tags = set(record.get("evidence") or [])
    access = db.get("access_type")
    rows = db.get("rows_examined")
    indexed = db.get("indexed")

    if access is None:
        return "NOT RECORDED", "the artifact carries no access plan for this shape"

    if db.get("write"):
        floor = FLOOR_TAG in tags
        return ("WRITE PATH" + (" — FLOOR" if floor else ""),
                "a write; its cost is dominated by the durable commit, not by lookup"
                + (". Measured inside a rolled-back transaction, so the true cost is higher"
                   if floor else ""))

    if access == "ALL" or not indexed:
        return ("NEEDS PRODUCTION-SCALE VALIDATION",
                f"full scan ({access}); it examined {rows} row(s) only because the table was "
                f"small in this dataset. Cheap here, unproven at scale")

    if "REPRESENTATIVE_TABLE_SIZE" in tags:
        return ("HEALTHY — NO OPTIMISATION REQUIRED",
                f"indexed {access} access examining {rows} row(s), measured against a "
                f"representative table size")

    if "SMALL_TABLE_ONLY" in tags:
        return ("HEALTHY AT THIS DATASET SIZE",
                f"indexed {access} access examining {rows} row(s), but the table was small in "
                f"this dataset, so the result does not yet prove behaviour at full scale")

    return (f"INDEXED ({access})", f"examined {rows} row(s)")


def _best_label(before_rec: dict[str, Any] | None, after_rec: dict[str, Any] | None,
                component: str) -> str:
    """The most informative label available, ignoring one that merely repeats the name."""
    for record in (before_rec, after_rec):
        label = (record or {}).get("label") or ""
        if label and label.strip() != component:
            return label
    return (before_rec or after_rec or {}).get("label") or ""


def query_catalog() -> list[dict[str, Any]]:
    """Every measured shape, both states, with where and how often it runs.

    `after_executions` is 0 for a shape the configuration removed from the request path.
    That is the run's own claim, backed by a live statement trace, and it is what makes the
    shape's ENTIRE contribution disappear rather than merely shrink.
    """
    before = {(r["operation"], r["component"]): r for r in load(BEFORE)}
    after = {(r["operation"], r["component"]): r for r in load(AFTER)}
    screens = _screen_map()
    dropped = set(STATES[AFTER]["zero_execution_operations"])

    out: list[dict[str, Any]] = []
    for key in sorted(set(before) | set(after)):
        operation, component = key
        bucket = _bucket_of(operation, component)
        b, a = _stats(before.get(key)), _stats(after.get(key))
        per_screen = screens.get(key, {})
        before_execs = sum(per_screen.values())
        removed = operation in dropped
        after_execs = 0 if removed else before_execs

        verdict, why = health(after.get(key) or before.get(key))

        out.append({
            "key": key,
            "shape": f"{PREFIX[bucket]}.{component}",
            "component": component,
            "operation": operation,
            "category": CATEGORY[bucket],
            "bucket": bucket,
            # Prefer whichever record carries a DESCRIPTIVE label. The after run fell back
            # to the bare component name for some shapes; the baseline names them properly,
            # and a reader is owed the description rather than the identifier repeated.
            "label": _best_label(before.get(key), after.get(key), component),
            "screens": [SHORT_TITLES[k] for k in
                        (p["key"] for p in ui_pages.PAGES) if k in per_screen],
            "screen_keys": [k for k in (p["key"] for p in ui_pages.PAGES) if k in per_screen],
            "executions_per_screen": {SHORT_TITLES[k]: v for k, v in per_screen.items()},
            "before_p50": b["p50"], "before_p95": b["p95"], "before_p99": b["p99"],
            "before_n": b["n"],
            "after_p50": a["p50"], "after_p95": a["p95"], "after_p99": a["p99"],
            "after_n": a["n"],
            "before_executions": before_execs,
            "after_executions": after_execs,
            "removed": removed,
            "status": STATUS_REMOVED if removed else STATUS_ACTIVE,
            # A removed shape's improvement is total and unambiguous: its whole contribution
            # is gone. For a SURVIVING shape the two medians are NOT comparable — see
            # `calibration_note` — so no improvement figure is offered for one.
            "sql_time_eliminated": (b["p50"] * before_execs) if removed and b["p50"] else None,
            "improvement_pct": 100.0 if removed else None,
            "health": verdict,
            "health_reason": why,
            "is_floor": FLOOR_TAG in set(
                (after.get(key) or before.get(key) or {}).get("evidence") or []),
            "evidence": sorted(set((after.get(key) or before.get(key) or {}).get("evidence")
                                   or [])),
        })
    return out


#: Why a surviving shape's two medians must not be subtracted from one another.
CALIBRATION_NOTE = (
    "The two runs were measured on DIFFERENT harnesses. Nothing was changed about the "
    "business or authentication queries, yet every one of them reads HIGHER in the after "
    "run — that difference is the harness, not a regression. No per-query improvement "
    "figure is shown for a surviving shape, because there was no per-query change to report. "
    "It also means the after-state screen totals are CONSERVATIVE: they were built from the "
    "more expensive readings and still land under the target."
)


def screen_breakdown(screen_key: str) -> dict[str, Any]:
    """One screen's query shapes, with each one's contribution and share of the total.

    Percentages are of that screen's own measured total in that state. A shape with no
    measurement contributes nothing and holds no share — never a zero that reads as free.
    """
    before = {p["key"]: p for p in pages(BEFORE)}[screen_key]
    after = {p["key"]: p for p in pages(AFTER)}[screen_key]
    catalog = {q["key"]: q for q in query_catalog()}

    after_rows = {(r["operation"], r["component"]): r for r in after["rows"]}

    rows = []
    for row in before["rows"]:
        key = (row["operation"], row["component"])
        q = catalog[key]
        a = after_rows.get(key)
        b_contrib = row["contribution_ms"] if row["measured"] else None
        a_contrib = a["contribution_ms"] if (a and a["measured"]) else None
        rows.append({
            "shape": q["shape"],
            "category": q["category"],
            "label": q["label"],
            "before_executions": row["executions"],
            "after_executions": a["executions"] if a else 0,
            "before_p50": row["p50"] if row["measured"] else None,
            "after_p50": a["p50"] if (a and a["measured"]) else None,
            "before_contribution_ms": b_contrib,
            "after_contribution_ms": a_contrib,
            "before_share_pct": (100.0 * b_contrib / before["all_sql_ms"])
                                if b_contrib and before["all_sql_ms"] else None,
            "after_share_pct": (100.0 * a_contrib / after["all_sql_ms"])
                               if a_contrib and after["all_sql_ms"] else None,
            "removed": a is None,
            "status": STATUS_REMOVED if a is None else STATUS_ACTIVE,
            "is_floor": FLOOR_TAG in set(row["evidence"] or []),
        })

    return {
        "key": screen_key,
        "title": SHORT_TITLES[screen_key],
        "arabic": ARABIC_TITLES.get(screen_key, ""),
        "route": before["route"],
        "before_statements": before["query_count"],
        "after_statements": after["query_count"],
        "before_ms": before["all_sql_ms"],
        "after_ms": after["all_sql_ms"],
        "before_is_complete": before["is_complete"],
        "after_is_complete": after["is_complete"],
        "after_is_floor": after["is_lower_bound"],
        "rows": rows,
        "conditional": conditional_for(screen_key),
    }


def conditional_for(screen_key: str) -> list[dict[str, str]]:
    """Shapes a screen declares as CONDITIONAL — code paths that exist but did not execute.

    These carry NO number. A path that never ran has no measured cost, and writing 0 ms
    would state a measurement that was never taken. It is listed so the screen's statement
    count cannot be mistaken for the whole of what the code can do.
    """
    page = next(p for p in ui_pages.PAGES if p["key"] == screen_key)
    return [{"name": name, "explanation": text}
            for name, text in (page.get("conditional_components") or {}).items()]


def conditional_queries() -> list[dict[str, str]]:
    """Every conditional shape across all screens."""
    out = []
    for page in ui_pages.PAGES:
        for item in conditional_for(page["key"]):
            out.append({**item, "screen": SHORT_TITLES[page["key"]]})
    return out


def query_totals() -> dict[str, Any]:
    """Journey-wide totals across the seven screens. Every figure is a sum of the above."""
    before_pages, after_pages = pages(BEFORE), pages(AFTER)

    def bucket_sum(pgs, bucket):
        return sum(p["bucket_totals"][bucket] for p in pgs)

    b_stmts = sum(p["query_count"] for p in before_pages)
    a_stmts = sum(p["query_count"] for p in after_pages)
    b_ms = sum(p["all_sql_ms"] for p in before_pages)
    a_ms = sum(p["all_sql_ms"] for p in after_pages)

    catalog = query_catalog()
    return {
        "screens": len(before_pages),
        "before_statements": b_stmts,
        "after_statements": a_stmts,
        "statements_eliminated": b_stmts - a_stmts,
        "before_ms": b_ms,
        "after_ms": a_ms,
        "ms_saved": b_ms - a_ms,
        "reduction_pct": (100.0 * (b_ms - a_ms) / b_ms) if b_ms else None,
        "before_limiter_ms": bucket_sum(before_pages, ui_pages.LIMITER),
        "before_limiter_pct": (100.0 * bucket_sum(before_pages, ui_pages.LIMITER) / b_ms)
                              if b_ms else None,
        "before_business_ms": bucket_sum(before_pages, ui_pages.BUSINESS),
        "before_auth_ms": bucket_sum(before_pages, ui_pages.AUTH),
        "after_limiter_ms": bucket_sum(after_pages, ui_pages.LIMITER),
        "after_business_ms": bucket_sum(after_pages, ui_pages.BUSINESS),
        "after_business_pct": (100.0 * bucket_sum(after_pages, ui_pages.BUSINESS) / a_ms)
                              if a_ms else None,
        "after_auth_ms": bucket_sum(after_pages, ui_pages.AUTH),
        "shapes_total": len(catalog),
        "shapes_removed": sum(1 for q in catalog if q["removed"]),
        "shapes_active": sum(1 for q in catalog if not q["removed"]),
        "conditional_count": len(conditional_queries()),
    }
