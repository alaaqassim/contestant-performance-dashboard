# Contestant Journey — Database Performance

A small, read-only site that shows what each screen of a competition contestant's journey
costs in database time, measured before and after one configuration change.

It exists to answer a single question in a form that does not require reading SQL:

> **How much of each screen's database time was the application's own work, and how much
> was infrastructure the application did not need to be paying for?**

---

## What it shows

Seven contestant-facing screens — Login, My Participations (first load and loaded),
Available Competitions, Competition Detail, Apply, and Application Status — each with:

* the number of database statements it issues, before and after
* its total database time, before and after
* the absolute and percentage reduction
* whether it meets the ≤ 5 ms acceptance target
* the measurement date, sample count and percentiles behind every figure

And, as the detail layer, **every individual database statement**: its category, which
screens it runs on and how many times, its p50/p95/p99 in both states, whether it still
executes, and — from the recorded access plan, not from the timing — whether it is healthy.

Statements are named semantically (`limiter.key_read`, `auth.user_lookup`,
`business.registration_read`). The parameterised statement text is not published and is not
reconstructed anywhere in this repository.

---

## ⛔ File limiter — local isolation pilot, **not** production architecture

The "after" measurements were taken with the framework's rate limiter pointed at a
**file-backed store** instead of the relational database.

That was chosen for exactly one reason: it is the simplest way to take the database out of
the picture and **prove that database-backed rate limiting was the dominant database cost**.

**It is not the recommended production architecture.** A file-backed store cannot be shared
between application servers and serialises on file locks; under the start-of-competition
burst it would contend worse than the database it replaced.

**Redis — or another shared, low-latency limiter store — remains the production candidate.**
This pilot is the evidence that justifies adopting one. It is not a proposal to ship files.

---

## Running it locally

Python 3.11 or newer.

```bash
python -m venv .venv
# Linux / macOS
source .venv/bin/activate
# Windows
.venv\Scripts\activate

pip install -r requirements.txt
streamlit run app.py
```

Then open the URL Streamlit prints (by default <http://localhost:8501>).

To check the evidence rather than take it on trust:

```bash
python verify.py
```

It proves the displayed figures are derived rather than written in — by breaking a
*disposable copy* of the evidence and confirming the results break in the matching way
(altering one query's samples moves only that query and only the screen it runs on; removing
a query produces a visible gap rather than a cheaper screen), then confirming the real
artifacts are byte-identical afterwards.

Nothing else is required. There is no database to create, no environment file to fill in and
no service to start.

---

## Deployment entrypoint

```
app.py
```

On Streamlit Community Cloud, set the main file path to `app.py`. `requirements.txt` is
picked up automatically. No `packages.txt` is needed — the app has no system-level
dependencies.

The additional pages under `pages/` are discovered automatically by Streamlit and appear in
the sidebar.

---

## Data and provenance

Two files, both shipped with the app:

| File | Contents |
|---|---|
| `data/before-database-limiter.jsonl` | the measured baseline — rate limiter counting into the database |
| `data/after-file-limiter-pilot.jsonl` | the file rate-limiter isolation pilot |

`data/PROVENANCE.md` records how they were derived and exactly what was removed.

**No figure in this app is written into the source code.** Every millisecond, statement
count, delta and percentage is calculated at render time from those two files. Change a
sample and the displayed comparison changes; remove a measurement and the affected screen
reports a gap rather than a smaller total.

The figures are **single-session measurements, not a load test.** Each statement was timed on
its own with no concurrent traffic: they establish what one operation costs, not how the
system behaves under a burst.

The two runs were measured on **different harnesses** and their absolute values are not
interchangeable — the "Evidence & Method" page states this in full, along with why the
comparison is nonetheless sound.

---

## Public-safety note

This is a **sanitised presentation snapshot** of an internal engineering tool. Before
publication the evidence was reduced to what a public audience needs:

**Preserved exactly as measured** — timing values, statement counts, percentiles, sample
counts, execution frequencies, measurement state, the before/after distinction, and the
`ROLLBACK_LOWER_BOUND` floor semantics. **No performance number was altered.** The screen
totals this snapshot produces are verified equal to the internal tool's at build time.

**Removed before publication** — query text, table and index names, internal database names,
machine names, absolute file paths, repository commit hashes, row-level identifiers, and
internal engineering commentary. Statements are referred to by **shape name** only
(`user_lookup`, `competition_detail_read`, `registration_read`, …).

The app contains **no credentials, no personal data, no contestant records and no database
connection of any kind.** It reads two local files and nothing else. The `.gitignore` excludes
environment files, secrets and database files so none can be added by accident.

The internal engineering tool, not this snapshot, remains the source of truth for engineering
decisions.
