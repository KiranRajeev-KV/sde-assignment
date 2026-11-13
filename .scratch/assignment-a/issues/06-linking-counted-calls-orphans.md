# 06: Linking at report time, counted calls, orphans

**What to build:** At report time, events are linked to leads by joining `(workflow_id, phone HMAC)` (ADR-0002). A counted call exists only when its `call.initiated` is linked, and it belongs to that event's lead. All events sharing its `(workflow_id, call_id)` belong to that call. Events of a call with no `call.initiated` are linked (not orphans) but contribute to nothing. `lead_report.csv` shows correct `total_calls`, `connected_calls` (calls with a `call.connected`) and `last_call_at` (latest `call.initiated`, ISO-8601 IST). `orphan_events` in `data_quality.json` counts stored, non-override events that are not linked, evaluated on the current state. Overrides are counted as orphans only until ticket 07 links them through `call_id`, which ticket 07 must update. SQL returns one row per counted call; Python aggregates (ADR-0007).

**Blocked by:** 05 (Event ingestion into the append-only ledger)

**Status:** done

- [x] Seam A test: an event in drop 1 whose lead arrives in drop 2 is an orphan after drop 1 and counts towards the lead after drop 2, with `orphan_events` dropping accordingly.
- [x] Seam A test: events with an invalid phone, or for a number never uploaded, or with an unknown workflow, are orphans.
- [x] Seam A test: a call whose events carry the phone in different formats is one counted call.
- [x] Seam A test: a call with `call.connected` but no `call.initiated` adds no call and no connected call, and its events are not orphans.
- [x] Seam A test: `last_call_at` is the latest initiated time across calls, rendered in IST with seconds.
