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

from . import schema, ui_pages

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
