"""Measurement envelope — schema version 1.

ONE record describes ONE measurement of ONE component of ONE operation.

The design goal that governs every choice here: a measurement taken tomorrow, for an
experiment that does not exist yet, must be ingestible WITHOUT editing this file.
That is achieved by three rules:

  1. Experiments, operations, components and evidence tags are DATA, not enums.
     No allow-list is consulted for them. A new `CQ-40K-10` simply appears.
  2. Typed sub-blocks (`database`, `http`, `load`) are OPTIONAL and independent.
     A record carrying none of them is still valid; k6 output lands in `load`
     later without touching the reader.
  3. Unknown top-level keys are PRESERVED into `extra` rather than rejected.

What IS validated is provenance, because provenance is the whole point of the
instrument: a fast number measured under invalid conditions is worse than no number.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

SCHEMA_VERSION = 1

# --------------------------------------------------------------------------------------
# Controlled vocabularies.
#
# These four ARE closed, because the dashboard's arithmetic branches on them. Everything
# else about a measurement is open.
# --------------------------------------------------------------------------------------

MEASUREMENT_TYPES = ("database", "cpu", "http", "load", "model")

#: How the number came to exist. The UI must never blur these four together.
GENERATIONS = (
    "historical_baseline",  # transcribed from a contract document, measured earlier
    "fresh_benchmark",      # measured by a benchmark run, on a known machine, at a known time
    "modelled",             # arithmetic from documented parameters — NOT measured
    "unmeasured",           # a known gap, deliberately carrying no number
)

SOURCES = ("contract_document", "benchmark_run", "model")

#: Which load model the record belongs to. Totals never cross this boundary.
PATH_PHASES = ("current", "future")

# --------------------------------------------------------------------------------------
# Evidence vocabulary (brief §17). Open for extension — unknown tags are kept and shown,
# they simply carry no strength weighting.
# --------------------------------------------------------------------------------------

EVIDENCE_WEAKENING = {
    "SMALL_TABLE_ONLY": "Measured against a table far smaller than production scale.",
    "ROLLBACK_LOWER_BOUND": "Transaction was rolled back — never paid the commit fsync.",
    "SINGLE_SESSION": "One session only. Says nothing about behaviour under contention.",
    "LOCAL_HARDWARE": "Developer laptop, not target hardware.",
    "IN_PROCESS_PROBE": "Measured inside the process, not at the HTTP boundary.",
    "MODELLED": "Derived by arithmetic, not observed.",
    "SINGLE_WORKER_SERVER": "Dev server serves one request at a time (B-39).",
}

EVIDENCE_STRENGTHENING = {
    "MEASURED": "An observed value.",
    "REPRESENTATIVE_TABLE_SIZE": "Table grown to production-representative row count.",
    "CONTENTION_TESTED": "Measured with concurrent workers, not a single session.",
    "TARGET_HARDWARE": "Measured on target hardware.",
    "HTTP_BOUNDARY": "Counted at the request boundary, not by an in-process probe.",
    "COMMITTED_WRITE": "Write was committed — includes the fsync.",
}

EVIDENCE_NEUTRAL = {
    "UNMEASURED": "No measurement exists.",
    "FUTURE": "Describes a path that does not execute today.",
}

ALL_EVIDENCE = {**EVIDENCE_WEAKENING, **EVIDENCE_STRENGTHENING, **EVIDENCE_NEUTRAL}

#: Top-level keys the reader understands. Anything else is funnelled into `extra`.
KNOWN_KEYS = {
    "schema_version", "measurement_id", "recorded_at", "run_id", "experiment",
    "operation", "component", "measurement_type", "measurement_generation", "source",
    "source_reference", "conditions_caveats", "path_phase", "executions_per_contestant",
    "samples_ms", "stats", "evidence", "supersedes", "concurrency", "contention_mode",
    "database", "http", "load", "environment", "extra", "label", "notes",
}


class ValidationError(ValueError):
    """Raised when an envelope cannot be trusted as evidence."""


@dataclass
class Measurement:
    """A validated measurement envelope."""

    run_id: str
    experiment: str
    operation: str
    measurement_type: str
    measurement_generation: str
    source: str
    component: str = ""
    label: str = ""
    source_reference: str = ""
    conditions_caveats: str = ""
    path_phase: str = "current"
    executions_per_contestant: float = 1.0
    samples_ms: list[float] = field(default_factory=list)
    stats: dict[str, float] | None = None
    evidence: list[str] = field(default_factory=list)
    supersedes: str | list[str] | None = None
    concurrency: int = 1
    contention_mode: str = ""      # "same_key" | "different_keys" | "" (brief §13)
    recorded_at: str = ""
    measurement_id: str = ""
    database: dict[str, Any] = field(default_factory=dict)
    http: dict[str, Any] = field(default_factory=dict)
    load: dict[str, Any] = field(default_factory=dict)
    environment: dict[str, Any] = field(default_factory=dict)
    extra: dict[str, Any] = field(default_factory=dict)
    notes: str = ""

    # -- derived ------------------------------------------------------------------------

    @property
    def has_value(self) -> bool:
        return bool(self.samples_ms) or bool(self.stats)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "measurement_id": self.measurement_id,
            "recorded_at": self.recorded_at,
            "run_id": self.run_id,
            "experiment": self.experiment,
            "operation": self.operation,
            "component": self.component,
            "label": self.label,
            "measurement_type": self.measurement_type,
            "measurement_generation": self.measurement_generation,
            "source": self.source,
            "source_reference": self.source_reference,
            "conditions_caveats": self.conditions_caveats,
            "path_phase": self.path_phase,
            "executions_per_contestant": self.executions_per_contestant,
            "samples_ms": self.samples_ms,
            "stats": self.stats,
            "evidence": self.evidence,
            "supersedes": self.supersedes,
            "concurrency": self.concurrency,
            "contention_mode": self.contention_mode,
            "database": self.database,
            "http": self.http,
            "load": self.load,
            "environment": self.environment,
            "notes": self.notes,
            "extra": self.extra,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, sort_keys=True)


def _require(payload: dict[str, Any], key: str, where: str) -> Any:
    value = payload.get(key)
    if value is None or (isinstance(value, str) and not value.strip()):
        raise ValidationError(f"{where}: missing required field '{key}'")
    return value


def _coerce_samples(raw: Any, where: str) -> list[float]:
    if raw is None or raw == "":
        return []
    if isinstance(raw, (int, float)):
        raw = [raw]
    if not isinstance(raw, list):
        raise ValidationError(f"{where}: 'samples_ms' must be a list of numbers")
    out: list[float] = []
    for item in raw:
        try:
            out.append(float(item))
        except (TypeError, ValueError) as exc:
            raise ValidationError(f"{where}: sample {item!r} is not a number") from exc
    if any(v < 0 for v in out):
        raise ValidationError(f"{where}: negative durations are not measurements")
    return out


#: Fields that make one measurement distinct from another — identity is CONTENT, not time.
#:
#: `recorded_at` is deliberately ABSENT. It was in this basis until a re-run of the same
#: `record.py` command produced a second envelope identical in every respect except its
#: timestamp, and therefore a different id that no dedup could catch. The ledger ended up
#: holding two records for one measurement, inflating every count that reads it. Identity
#: must answer "is this the same measurement?", and a clock reading cannot answer that.
#:
#: What this means in practice: re-recording the same measurement inside one `run_id`
#: collapses to one record, which is what you want. To capture a genuinely separate
#: session, change `run_id` — that is precisely what a run id is for.
_ID_BASIS = (
    "run_id", "experiment", "operation", "component", "measurement_type",
    "measurement_generation", "samples_ms", "stats",
    "concurrency", "contention_mode",
    # A correction may change NOTHING a reader can see except these two. Omitting them
    # made a correction collide with the record it corrects, so the ledger silently
    # dropped it while the append reported success — the worst possible failure for an
    # append-only evidence store, because it looks exactly like it worked.
    "supersedes", "executions_per_contestant",
)


def content_id(payload: dict[str, Any]) -> str:
    """The identity a payload SHOULD have under the current basis.

    Exposed so remediation and ingestion can ask "what is this measurement, regardless of
    the id it happens to carry?" without duplicating the hashing rule.
    """
    return _derive_id(payload)


def _supersedes(raw: Any) -> str | list[str] | None:
    """One predecessor, or several.

    A re-measurement usually retires exactly one record, and that stays a bare string so
    every id already in the ledger keeps its value. But a single fresh measurement can
    legitimately retire more than one predecessor — Q3 retired both the historical baseline
    it re-measures and the earlier fresh record that lacked the pointer — and one field
    cannot express that. A list is accepted and preserved verbatim; the stored FORM is never
    normalised, because `supersedes` is part of the identity basis and rewriting a string
    into a one-element list would change the id of every record that has one.
    """
    if not raw:
        return None
    if isinstance(raw, (list, tuple)):
        targets = [str(item).strip() for item in raw if str(item).strip()]
        return targets or None
    return str(raw).strip() or None


def superseded_targets(raw: Any) -> list[str]:
    """Whatever `supersedes` holds, as a flat list of ids."""
    value = _supersedes(raw)
    if value is None:
        return []
    return list(value) if isinstance(value, list) else [value]


def _derive_id(payload: dict[str, Any]) -> str:
    """Deterministic id, so re-ingesting the same envelope is idempotent."""
    basis = json.dumps(
        {k: payload.get(k) for k in _ID_BASIS},
        sort_keys=True,
        ensure_ascii=False,
        default=str,
    )
    return hashlib.sha256(basis.encode("utf-8")).hexdigest()[:20]


_ISO_HINT = re.compile(r"^\d{4}-\d{2}-\d{2}")


def parse(payload: dict[str, Any], *, where: str = "<envelope>") -> Measurement:
    """Validate one envelope and return it, or raise ValidationError.

    Validation is strict about PROVENANCE and permissive about TAXONOMY.
    """
    if not isinstance(payload, dict):
        raise ValidationError(f"{where}: envelope must be a JSON object")

    version = payload.get("schema_version", SCHEMA_VERSION)
    try:
        version = int(version)
    except (TypeError, ValueError) as exc:
        raise ValidationError(f"{where}: schema_version must be an integer") from exc
    if version > SCHEMA_VERSION:
        raise ValidationError(
            f"{where}: schema_version {version} is newer than this dashboard "
            f"understands (v{SCHEMA_VERSION}). Upgrade the dashboard rather than "
            f"downgrading the measurement."
        )

    run_id = str(_require(payload, "run_id", where)).strip()
    experiment = str(_require(payload, "experiment", where)).strip()
    operation = str(_require(payload, "operation", where)).strip()

    mtype = str(_require(payload, "measurement_type", where)).strip().lower()
    if mtype not in MEASUREMENT_TYPES:
        raise ValidationError(
            f"{where}: measurement_type '{mtype}' unknown; expected one of {MEASUREMENT_TYPES}"
        )

    generation = str(_require(payload, "measurement_generation", where)).strip().lower()
    if generation not in GENERATIONS:
        raise ValidationError(
            f"{where}: measurement_generation '{generation}' unknown; "
            f"expected one of {GENERATIONS}"
        )

    source = str(payload.get("source") or "").strip().lower()
    if not source:
        source = {
            "historical_baseline": "contract_document",
            "fresh_benchmark": "benchmark_run",
            "modelled": "model",
            "unmeasured": "model",
        }[generation]
    if source not in SOURCES:
        raise ValidationError(f"{where}: source '{source}' unknown; expected one of {SOURCES}")

    path_phase = str(payload.get("path_phase") or "current").strip().lower()
    if path_phase not in PATH_PHASES:
        raise ValidationError(
            f"{where}: path_phase '{path_phase}' unknown; expected one of {PATH_PHASES}"
        )

    samples = _coerce_samples(payload.get("samples_ms"), where)
    stats = payload.get("stats")
    if stats is not None:
        if not isinstance(stats, dict):
            raise ValidationError(f"{where}: 'stats' must be an object")
        stats = {k: (float(v) if v is not None else None) for k, v in stats.items()}
        if not stats:
            stats = None

    # ---- Provenance rules. These are the reason this validator exists. ----------------

    # An UNMEASURED record must not smuggle in a number. This is the rule that stops the
    # dashboard from ever displaying a synthetic value as though it were observed.
    if generation == "unmeasured" and (samples or stats):
        raise ValidationError(
            f"{where}: measurement_generation is 'unmeasured' but the record carries a "
            f"numeric value. An unmeasured item must have no number at all."
        )

    # A historical transcription must say exactly where it was transcribed from.
    if generation == "historical_baseline":
        if not str(payload.get("source_reference") or "").strip():
            raise ValidationError(
                f"{where}: historical_baseline requires 'source_reference' naming the "
                f"document and section/query it was transcribed from."
            )

    environment = dict(payload.get("environment") or {})
    concurrency = payload.get("concurrency", 1)
    try:
        concurrency = int(concurrency)
    except (TypeError, ValueError) as exc:
        raise ValidationError(f"{where}: concurrency must be an integer") from exc
    if concurrency < 1:
        raise ValidationError(f"{where}: concurrency must be >= 1")

    recorded_at = str(payload.get("recorded_at") or "").strip()

    # A fresh benchmark must be reproducible: when, where, how big, how concurrent.
    # The `record` CLI fills every one of these automatically, so complying costs nothing.
    if generation == "fresh_benchmark":
        missing = []
        if not recorded_at:
            missing.append("recorded_at")
        for key in ("machine", "cpu_cores", "dataset_size"):
            if environment.get(key) in (None, ""):
                missing.append(f"environment.{key}")
        if missing:
            raise ValidationError(
                f"{where}: fresh_benchmark is missing {', '.join(missing)}. "
                f"A fresh measurement that cannot be reproduced is not evidence. "
                f"Use `python record.py` to fill these automatically."
            )

    if recorded_at and not _ISO_HINT.match(recorded_at):
        raise ValidationError(
            f"{where}: recorded_at '{recorded_at}' is not an ISO-8601 date/time"
        )
    if not recorded_at:
        recorded_at = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")

    evidence = payload.get("evidence") or []
    if isinstance(evidence, str):
        evidence = [evidence]
    evidence = [str(tag).strip().upper().replace("-", "_").replace(" ", "_")
                for tag in evidence if str(tag).strip()]

    # Keep the evidence list honest about the generation it belongs to.
    implied = {
        "historical_baseline": "MEASURED",
        "fresh_benchmark": "MEASURED",
        "modelled": "MODELLED",
        "unmeasured": "UNMEASURED",
    }[generation]
    if implied not in evidence:
        evidence.append(implied)
    if generation == "modelled" and "MEASURED" in evidence:
        raise ValidationError(
            f"{where}: a modelled record cannot carry the MEASURED evidence tag."
        )
    if path_phase == "future" and "FUTURE" not in evidence:
        evidence.append("FUTURE")

    try:
        epc = float(payload.get("executions_per_contestant", 1) or 0)
    except (TypeError, ValueError) as exc:
        raise ValidationError(f"{where}: executions_per_contestant must be numeric") from exc
    if epc < 0:
        raise ValidationError(f"{where}: executions_per_contestant must be >= 0")

    for block in ("database", "http", "load", "extra"):
        if payload.get(block) is not None and not isinstance(payload[block], dict):
            raise ValidationError(f"{where}: '{block}' must be an object")

    # Forward compatibility: retain anything we did not recognise.
    extra = dict(payload.get("extra") or {})
    for key, value in payload.items():
        if key not in KNOWN_KEYS:
            extra[key] = value

    measurement = Measurement(
        run_id=run_id,
        experiment=experiment,
        operation=operation,
        component=str(payload.get("component") or "").strip(),
        label=str(payload.get("label") or "").strip(),
        measurement_type=mtype,
        measurement_generation=generation,
        source=source,
        source_reference=str(payload.get("source_reference") or "").strip(),
        conditions_caveats=str(payload.get("conditions_caveats") or "").strip(),
        path_phase=path_phase,
        executions_per_contestant=epc,
        samples_ms=samples,
        stats=stats,
        evidence=sorted(set(evidence)),
        supersedes=_supersedes(payload.get("supersedes")),
        concurrency=concurrency,
        contention_mode=str(payload.get("contention_mode") or "").strip().lower(),
        recorded_at=recorded_at,
        database=dict(payload.get("database") or {}),
        http=dict(payload.get("http") or {}),
        load=dict(payload.get("load") or {}),
        environment=environment,
        notes=str(payload.get("notes") or "").strip(),
        extra=extra,
    )

    measurement.measurement_id = (
        str(payload.get("measurement_id") or "").strip() or _derive_id(measurement.to_dict())
    )
    return measurement
