"""Self-verification for this snapshot. Run `python verify.py` — no dependencies beyond the app.

WHAT IT IS FOR
--------------
Every number this site displays is claimed to be computed from `data/*.jsonl` rather than
written into the page code. That is easy to say and easy to get wrong, so this script proves
it — by breaking a DISPOSABLE COPY of the evidence and checking that the displayed results
break in the matching way.

A checker that can only pass proves nothing. Each control below is paired with the negative
case it must detect.

The real artifacts are never opened for writing. Their SHA-256 digests are taken before and
after and compared, and the run fails if either moved.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import sys
import tempfile
from pathlib import Path

from perfdash import evidence, ui_pages

ROOT = Path(__file__).resolve().parent
PASSED: list[str] = []
FAILED: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    (PASSED if ok else FAILED).append(label if ok else f"{label} :: {detail}")
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if not ok else ""))


def digests() -> dict[str, str]:
    return {state: hashlib.sha256(evidence.path_for(state).read_bytes()).hexdigest()
            for state in (evidence.BEFORE, evidence.AFTER)}


BASELINE_DIGESTS = digests()

# ======================================================================================
print("\nEvidence loads, and every screen resolves")
# ======================================================================================

rows = evidence.compare()
catalog = evidence.query_catalog()
totals = evidence.query_totals()

check("all seven contestant screens are present",
      len(rows) == 7, str([r["key"] for r in rows]))
check("every screen is comparable — no gaps on either side",
      all(r["comparable"] for r in rows),
      str([r["key"] for r in rows if not r["comparable"]]))
check("every screen meets the target after the change",
      all(r["after_within_target"] for r in rows),
      str({r["key"]: r["after_ms"] for r in rows if not r["after_within_target"]}))
check("Apply keeps its ROLLBACK floor",
      next(r for r in rows if r["key"] == "apply")["after_is_floor"])

check("every catalogued shape carries a measured median in both states",
      all(q["before_p50"] is not None and q["after_p50"] is not None for q in catalog),
      str([q["shape"] for q in catalog
           if q["before_p50"] is None or q["after_p50"] is None]))
check("every catalogued shape carries p95 and p99, not just a median",
      all(q["before_p95"] is not None and q["before_p99"] is not None
          and q["after_p95"] is not None and q["after_p99"] is not None for q in catalog))
check("percentiles are ordered p50 <= p95 <= p99 in both states",
      all(q["before_p50"] <= q["before_p95"] <= q["before_p99"]
          and q["after_p50"] <= q["after_p95"] <= q["after_p99"] for q in catalog),
      str([q["shape"] for q in catalog
           if not (q["before_p50"] <= q["before_p95"] <= q["before_p99"])]))

# ======================================================================================
print("\nThe query view reconciles with the screen view")
# ======================================================================================

check("journey statement totals equal the sum over the seven screens",
      totals["before_statements"] == sum(r["before_statements"] for r in rows)
      and totals["after_statements"] == sum(r["after_statements"] for r in rows))
check("journey millisecond totals equal the sum over the seven screens",
      abs(totals["before_ms"] - sum(r["before_ms"] for r in rows)) < 1e-9
      and abs(totals["after_ms"] - sum(r["after_ms"] for r in rows)) < 1e-9)
check("statements eliminated is exactly before minus after",
      totals["statements_eliminated"]
      == totals["before_statements"] - totals["after_statements"])

for state, pages_of in ((evidence.BEFORE, "before"), (evidence.AFTER, "after")):
    for page in evidence.pages(state):
        breakdown = evidence.screen_breakdown(page["key"])
        contributed = sum(r[f"{pages_of}_contribution_ms"] or 0.0 for r in breakdown["rows"])
        check(f"{pages_of} `{page['key']}` total equals the sum of its query contributions",
              abs(contributed - page["all_sql_ms"]) < 1e-9,
              f"{contributed:.9f} != {page['all_sql_ms']:.9f}")

for page_key in (p["key"] for p in ui_pages.PAGES):
    breakdown = evidence.screen_breakdown(page_key)
    for state in ("before", "after"):
        shares = [r[f"{state}_share_pct"] for r in breakdown["rows"]
                  if r[f"{state}_share_pct"] is not None]
        check(f"{state} `{page_key}` contribution shares total 100%",
              abs(sum(shares) - 100.0) < 1e-6 if shares else True,
              f"{sum(shares):.6f}")

check("every removed shape reports zero executions after the change",
      all(q["after_executions"] == 0 for q in catalog if q["removed"]))
check("every surviving shape keeps the execution count it had before",
      all(q["after_executions"] == q["before_executions"]
          for q in catalog if not q["removed"]))
check("no surviving shape is given an improvement figure across the two harnesses",
      all(q["improvement_pct"] is None for q in catalog if not q["removed"]))

# ======================================================================================
print("\nNo timing is written into the page code")
# ======================================================================================

DISPLAYED = [f"{v:.4f}" for v in
             [r["before_ms"] for r in rows] + [r["after_ms"] for r in rows]
             + [q["before_p50"] for q in catalog] + [q["after_p50"] for q in catalog]]

for source in sorted(ROOT.glob("pages/*.py")) + [ROOT / "app.py",
                                                 ROOT / "perfdash" / "evidence.py"]:
    text = source.read_text(encoding="utf-8")
    leaked = sorted({v for v in DISPLAYED if v in text})
    check(f"no displayed timing appears as a literal in {source.name}",
          not leaked, str(leaked))

# ======================================================================================
print("\nCONTROLS — the displayed result must change when the evidence changes")
# ======================================================================================

real_after = evidence.path_for(evidence.AFTER)
real_dir = evidence.DATA_DIR

with tempfile.TemporaryDirectory() as td:
    scratch = Path(td)
    for state in (evidence.BEFORE, evidence.AFTER):
        shutil.copy2(evidence.path_for(state), scratch / evidence.STATES[state]["file"])

    evidence.DATA_DIR = scratch                       # disposable copy only
    try:
        baseline = {q["shape"]: q["after_p50"] for q in evidence.query_catalog()}
        baseline_pages = {r["key"]: r["after_ms"] for r in evidence.compare()}
        check("the disposable copy reproduces the real result exactly",
              baseline == {q["shape"]: q["after_p50"] for q in catalog})

        lines = (scratch / evidence.STATES[evidence.AFTER]["file"]).read_text(
            encoding="utf-8").splitlines()

        # ---- control 1: alter ONE query's samples --------------------------------
        TARGET = "detail_read"                        # runs on Competition Detail only
        altered = []
        for line in lines:
            record = json.loads(line)
            if record["component"] == TARGET:
                record["samples_ms"] = [s * 10 for s in record["samples_ms"]]
            altered.append(json.dumps(record, ensure_ascii=False, sort_keys=True))
        (scratch / evidence.STATES[evidence.AFTER]["file"]).write_text(
            "\n".join(altered) + "\n", encoding="utf-8")

        moved = {q["shape"]: q["after_p50"] for q in evidence.query_catalog()}
        moved_pages = {r["key"]: r["after_ms"] for r in evidence.compare()}
        changed_shapes = [s for s in baseline if abs(moved[s] - baseline[s]) > 1e-12]
        changed_pages = [k for k in baseline_pages
                         if abs(moved_pages[k] - baseline_pages[k]) > 1e-12]

        check("CONTROL: altering one query's samples changes THAT query's median",
              changed_shapes == [f"business.{TARGET}"], str(changed_shapes))
        check("...by exactly the factor applied, so the arithmetic is the evidence's",
              abs(moved[f"business.{TARGET}"] - baseline[f"business.{TARGET}"] * 10) < 1e-9)
        check("...and it changes ONLY the screen that query runs on",
              changed_pages == ["competition_detail"], str(changed_pages))
        check("...leaving every other query untouched",
              len(changed_shapes) == 1 and len(baseline) - 1
              == sum(1 for s in baseline if abs(moved[s] - baseline[s]) <= 1e-12))

        # ---- control 2: remove a query entirely ----------------------------------
        kept = [line for line in lines if json.loads(line)["component"] != TARGET]
        (scratch / evidence.STATES[evidence.AFTER]["file"]).write_text(
            "\n".join(kept) + "\n", encoding="utf-8")

        holed = evidence.screen_breakdown("competition_detail")
        holed_rows = evidence.compare()
        gap_row = next(r for r in holed["rows"] if r["shape"].endswith(TARGET))

        check("CONTROL: removing a query makes its screen INCOMPLETE, not cheaper",
              not holed["after_is_complete"])
        check("...and the missing query shows an ABSENT contribution, not a zero",
              gap_row["after_contribution_ms"] is None
              and gap_row["after_p50"] is None)
        check("...and its statement count is still reported, so the gap cannot hide",
              holed["after_statements"]
              == next(r for r in rows if r["key"] == "competition_detail")["after_statements"])
        check("...and the comparison refuses a delta for that screen",
              next(r for r in holed_rows if r["key"] == "competition_detail")["delta_ms"]
              is None)
        check("...while every other screen is unaffected",
              all(abs(r["after_ms"] - baseline_pages[r["key"]]) < 1e-12
                  for r in holed_rows
                  if r["key"] != "competition_detail" and r["after_ms"] is not None))
    finally:
        evidence.DATA_DIR = real_dir

# ======================================================================================
print("\nThe real artifacts were never written to")
# ======================================================================================

final = digests()
check("the BEFORE evidence file is byte-identical",
      final[evidence.BEFORE] == BASELINE_DIGESTS[evidence.BEFORE])
check("the AFTER evidence file is byte-identical",
      final[evidence.AFTER] == BASELINE_DIGESTS[evidence.AFTER])
check("the restored result matches the result from the start of this run",
      {q["shape"]: q["after_p50"] for q in evidence.query_catalog()}
      == {q["shape"]: q["after_p50"] for q in catalog})

print(f"\n{'=' * 66}")
print(f"  {len(PASSED)} passed, {len(FAILED)} failed")
for failure in FAILED:
    print(f"    - {failure}")
print(f"{'=' * 66}\n")
sys.exit(1 if FAILED else 0)
