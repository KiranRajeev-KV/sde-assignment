# Idempotency is decided per file by content hash, inside one transaction per ingest

Event-level dedupe alone is not enough: re-reading a file would re-count `events_total`, `duplicate_events_dropped` and `duplicate_lead_rows_merged`. So each file is identified by the SHA-256 of its bytes and recorded in an `ingested_files` table; a hash already recorded is skipped regardless of path or name. A lead file whose `(workflow_id, batch_id)` was already ingested with a *different* hash is a hard error, because `batch_id` is permanent lead identity and must not silently mean two uploads. Each `ingest` invocation runs in a single transaction, so a crash or refusal leaves no partial state and the fix is simply to re-run.

## Considered Options

- **By path:** breaks when the data directory is copied or moved.
- **By drop directory:** too coarse to handle a partially-ingested or corrected drop.

## Consequences

- A byte-identical file under a new name (e.g. `batch_004.csv` copied from `batch_001.csv`) is skipped, not merged.
- Event files have no name-based identity; a new event file with a new hash is always ingested, and its per-line counts (`lines`, `malformed`, `duplicates`) are stored on its `ingested_files` row.
