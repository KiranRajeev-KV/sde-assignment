# 10: Idempotency and safe writes

**What to build:** Re-running `ingest` on anything already ingested changes nothing (ADR-0005). Each file's identity is the SHA-256 of its bytes. A recorded hash is skipped regardless of path or name and reported as skipped. A lead file whose `(workflow_id, batch_id)` was already ingested with a different hash is a data error. Each `ingest` invocation, covering all drops given in argument order, is one transaction, so any data error or crash leaves no partial state. `report` writes all five files into a temporary directory and renames them into place. The CLI prints a per-file summary and exits 0 on success, 1 on data errors, 2 on usage errors.

**Blocked by:** 03 (Value rules, rejections and field warnings), 04 (Merged duplicates and defaults), 05 (Event ingestion into the append-only ledger)

**Status:** done

- [x] Seam A test: ingesting the same drop twice leaves every counter and every report file identical.
- [x] Seam A test: a copy of an ingested drop at a different path is fully skipped.
- [x] Seam A test: a modified file under an already-used batch name fails the whole invocation, including other drops given in the same call, and leaves the database unchanged.
- [x] Seam A test: a failure injected midway through an ingest leaves no rows from that invocation.
- [x] CLI tests: the exit codes for success, a data error and a usage error; skipped files are reported as skipped.

**Note from 03:** `ingested_files.sha256` is recorded but not yet unique, so that identical files (e.g. two header-only batches) don't crash before skipping exists. This ticket makes it the unique key, adds `UNIQUE (workflow_id, batch_id)`, and checks the hash before processing a file's rows.

## Comments

**Implementation notes (deliberate limits):**
- The new `UNIQUE` constraints are in `CREATE TABLE IF NOT EXISTS`, so they reach only databases created from now on; rebuild an older database by re-ingesting its drops. The pipeline checks before inserting either way.
- `report` renames the five files one at a time: each file is replaced atomically and all five are fully written before the first rename, but the set is not swapped as one unit. A hard kill can leave a `.report-*` staging directory inside `--out`.
- The disposition catalogue is reference data and is still replaced from `dispositions.csv` on every ingest, even when every file is skipped.
- Invalid UTF-8 in a lead file still raises `UnicodeDecodeError` rather than a `DataError` (unchanged from 03).
