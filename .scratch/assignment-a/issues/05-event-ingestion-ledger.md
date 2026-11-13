# 05: Event ingestion into the append-only ledger

**What to build:** Every event line in a drop is classified and counted. Blank or whitespace-only lines are ignored and not counted. Every other line counts toward `events_total`. A line is malformed if it is not valid JSON, not a JSON object, has no `event_id`, or has an unparseable `occurred_at`, an unknown `event_type`, or a missing `call_id` or `workflow_id`. Malformed lines are counted but not stored and do not reserve their `event_id`. An `event_id` already in the ledger (from any drop or earlier in the same file) is counted as a duplicate and dropped; the first stored copy wins. All other events are appended with their UTC instant (from `Z`, offset or naive-as-IST timestamps), the original timestamp text, the phone HMAC (null if the phone is absent or invalid), and the payload without the phone. The ledger refuses UPDATE and DELETE via triggers. The event counters appear in `data_quality.json`.

**Blocked by:** 01 (Walking skeleton)

**Status:** done

- [x] Seam B table tests: `Z`, `+05:30` and naive timestamps map to the same instant for the same IST wall time; garbage timestamps are rejected.
- [x] Seam A test: a file with valid lines, truncated lines, a JSON array, an object with no `event_id`, an object with an unknown `event_type`, a blank line and an in-file duplicate gives the exact `events_total`, `malformed_events` and `duplicate_events_dropped`.
- [x] Seam A test: a duplicate delivered in a second drop is counted as a duplicate.
- [x] Seam A test: a malformed line followed by a well-formed line with the same `event_id` stores the well-formed one, not counted as a duplicate.
- [x] Seam A test: an attempted UPDATE or DELETE on the ledger fails at the database level.
- [x] No event's raw line or plaintext phone is stored.
