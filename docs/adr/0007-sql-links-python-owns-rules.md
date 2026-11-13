# SQL links and selects per call; Python owns the business rules

Reporting is split at one seam: SQL performs the linking joins (ADR-0002) and returns one compact row per counted call (lead, `call_id`, initiated time, connected/failed flags), plus the `disposition.*` events of counted calls with their codes. Python then applies effective disposition (validity against the stored catalogue, override over set, latest `occurred_at` with the `event_id` tie-break), bucket, success and the daily/lead aggregations as pure functions. We chose this over the "aggregation in SQL" stretch so the rules most likely to break, and most likely to be changed live, stay in small, table-tested functions rather than one large query; the stretch goal taken instead is performance on `--scale large` (target < 2 min), with measured timings in SUBMISSION.md.

## Consequences

- Business rules exist in exactly one place (Python); SQL is limited to joins, filtering and counting (orphans, unknown dispositions).
- Choosing the winning disposition happens in Python, not SQL `ROW_NUMBER()`, because "latest *valid* override, else latest *valid* set" depends on the catalogue and is table-tested in `test_rules.py`. `ROW_NUMBER()` is still used to pick a call's linking event for overrides.
- If profiling shows the Python pass is the bottleneck, the per-call rows can be aggregated in SQL later without changing the rule functions' tests.
