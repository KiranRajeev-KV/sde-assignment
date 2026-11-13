# Events are linked to leads at report time, not at ingest

The ledger stores every event that is not malformed and not a duplicate, including events that currently match no lead, and stores no `lead_id`. Linking is a join evaluated on every `report`: `(workflow_id, phone_hmac)` against leads, and `disposition.override` via `(workflow_id, call_id)` to the call's other events. Orphan and unknown-disposition counts are therefore derived from current state, an event that was an orphan after drop_1 counts automatically once its lead arrives in drop_2, and drop-by-drop ingest gives the same reports as all-at-once ingest because a join is order-independent.

## Considered Options

- **Link at ingest, quarantine table for orphans, re-link on every ingest:** rejected. Promoting quarantined rows means updating or moving ledger rows (at odds with append-only), late overrides need a second resolution pass, and the result depends on ingest order unless every edge case is handled.

## Consequences

- Ingest is incremental (drop_2 never re-reads drop_1's files); reporting is a full recompute over the database. This is the stated trade-off against the "truly incremental" stretch goal.
- `events_total`, `malformed_events` and `duplicate_events_dropped` cannot be derived from the ledger (those lines are not stored), so they are recorded per ingested file.
- Report cost grows with the whole ledger, not the latest drop; acceptable at ~600k events with indexes on `(workflow_id, phone_hmac)` and `(workflow_id, call_id)`.
