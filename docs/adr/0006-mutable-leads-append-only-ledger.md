# Leads are a mutable current-state table; only the event ledger is append-only

`leads` holds one row per lead identity (`UNIQUE(workflow_id, phone_hmac)`) and is updated in place when a merged duplicate arrives (last non-null write wins, per the spec's processing order). The `events` ledger is append-only, enforced by `BEFORE UPDATE`/`BEFORE DELETE` triggers that abort. Schema-specific lead fields live in one JSON column so a new workflow is a new schema file, not a migration; `external_ref` and `batch_id` are real columns because reports sort and group by them.

## Considered Options

- **Append-only `lead_rows` log with leads projected from it:** gives full lead history, but stores encrypted PII for every row and adds a projection step that nothing in the spec requires.
- **One table per workflow:** stronger typing, but a migration per workflow.

## Consequences

- The database enforces identity, dedupe (`event_id` PK), one rejection per `(workflow_id, batch_id, row_number)`, valid `event_type`, ledger immutability and batch-name uniqueness; domain rules (normalisation, rejection order, merge, linking) live in code.
- Lead history (which batch changed which field) is not recoverable; only per-file counters are kept.
