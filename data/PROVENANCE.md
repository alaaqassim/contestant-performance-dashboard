# Provenance of the evidence in this snapshot

Both files in this directory are **sanitised extracts** of an internal, append-only
measurement ledger. They were produced mechanically from that ledger, not transcribed.

## What was preserved, exactly as measured

* every timing sample, and therefore every median, p95 and p99
* statement counts and per-screen execution frequencies
* the provenance of each figure: how it was generated, from what source, for which phase
* the full evidence-tag list, including **`ROLLBACK_LOWER_BOUND`** (the tag that makes the
  Apply screen's total a FLOOR), **`SMALL_TABLE_ONLY`** and **`REPRESENTATIVE_TABLE_SIZE`**
  (which is what lets a query be called healthy, or not, without guessing)
* the access plan CLASS (`const`, `ref`, `ALL`, `insert`), the rows examined, and whether
  an index was used — the facts a reader needs to judge a query, minus the schema
* the BEFORE / AFTER distinction, carried by separate files and separate run identifiers
* the content hash of each original record, so any figure here can be traced back to the
  internal ledger entry it came from

**No performance number was altered, rounded or recomputed.** The build asserts that the
seven screen totals produced from these files equal the internal tool's, and fails if they
do not.

## What was removed, and why

The reasons below describe *categories*. They deliberately do not reproduce the values
that were removed.

| Field | Reason |
|---|---|
| `database.sql_fingerprint` | the parameterised statement text |
| `database.table` | the table name |
| `database.index_used` | the index name, which would disclose schema. REPLACED by a boolean `indexed` recording only WHETHER an index was used |
| `notes` | long internal engineering commentary; it contained a loopback address, a security-related keyword, statement text and row-level identifiers |
| `conditions_caveats` | internal caveat prose containing an absolute local path and row-level identifiers. REPLACED with curated public text; the machine-readable evidence tags (including ROLLBACK_LOWER_BOUND) are preserved unchanged |
| `supersedes` | ledger bookkeeping — ids of retired records not present in the snapshot |
| `ledger_file` | internal store bookkeeping (source ledger filename) |
| `ingested_at` | internal store bookkeeping (ingest timestamp) |
| `extra / http / load / contention_mode` | empty on every record; dropped rather than shipped as nulls |
| `environment.git_commit` | commit hash of a private repository |
| `environment.php_binary` | an absolute local interpreter path |
| `environment.database` | internal database name |
| `environment.machine (value)` | the workstation hostname, replaced with a non-identifying description. The field itself is kept because the validator requires it for a fresh benchmark |
| `environment.dataset_size (value)` | row-level identifiers redacted. Every COUNT and index cardinality is preserved verbatim, because dataset scale is real provenance |
| `ui_pages.py statement text` | each parameterised statement replaced by its shape name. The field is display-only and takes no part in any arithmetic; the build asserts the screen totals are unchanged |

## The files

| File | Run | Records |
|---|---|---|
| `before-database-limiter.jsonl` | the measured baseline | 22 |
| `after-file-limiter-pilot.jsonl` | the file rate-limiter isolation pilot | 22 |

Each line is one measurement envelope, validated on load by `perfdash/schema.py` —
the same validator the internal ledger uses. A truncated or malformed file makes the app
report an error; it never makes it show a smaller number.
