# 01: Walking skeleton: one lead, one call, end to end

**What to build:** A grader can install the solution package, run `python -m ledger ingest DROP` on a drop containing one lead file (canonical headers, one valid row) and one event file (one `call.initiated` for that lead's phone), then run `python -m ledger report --out DIR` and get a `lead_report.csv` with exactly one correct row. This establishes the package, the CLI (global `--db` and `--schemas`, defaulting per the spec), the pipeline API (`ingest(database, drop directories, schemas directory)` / `report(database, output directory)`, i.e. Seam A), the rules module skeleton (Seam B), the SQLite store with STRICT tables (ADR-0001), and the report-time join (ADR-0002) at their thinnest. PII is never stored in plaintext even here: the phone is stored only as an HMAC plus last four digits (ADR-0003), using a match key read from the environment or else from an auto-created key file beside the database (full key handling comes in ticket 11). The customer name is not stored yet.

**Blocked by:** None (can start immediately)

**Status:** done

- [x] The package installs from the solution folder with its runtime dependency, and `python -m ledger --help` lists `ingest` and `report`.
- [x] The phone is normalised to canonical form for the simplest valid input; the lead is stored with phone HMAC, phone last four, external reference and batch id (file stem); the event is stored in the ledger with its phone HMAC and UTC instant, and no `lead_id`.
- [x] `lead_report.csv` has the contract header and one row: workflow, external reference, `batch_001`, `+91******` plus last 4 digits, bucket `in_progress_dialed`, total calls 1, connected calls 0, `last_call_at` as ISO-8601 in IST with `+05:30`, empty current disposition, `false` for ever-success.
- [x] Seam A test: build the tiny drop in a temporary directory, ingest, report, and assert the exact file contents.
- [x] CLI smoke test: the same flow as a subprocess exits 0 and writes `lead_report.csv`.
- [x] A grep of the database file finds neither the phone nor the name in plaintext.

## Comments

- 2026-11-12: Implemented in `solution/` (package `ledger`, tests in `solution/tests`). Notes for later tickets:
  - Lead rows with an invalid phone or a missing reference are refused with a `DataError` (exit 1, rolled back) until ticket 03 adds rejections. The generated data therefore fails until then.
  - The default `--schemas` resolves from the package's place in the repository, so it assumes an editable install (`pip install -e solution`). With a non-editable install, pass `--schemas`. Document this in ticket 14.
  - Review follow-ups left to the tickets that own the code:
    - Split `pipeline.py` into lead ingester, event ingester and report builder (02/05/08).
    - Move value trimming and validation into `rules` (02/03).
    - Move lead aggregation into `rules` (07/08).
    - Move last-four extraction into the vault (11).
