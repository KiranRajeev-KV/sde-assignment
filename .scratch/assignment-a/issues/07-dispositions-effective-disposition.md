# 07: Dispositions: catalogue, overrides, effective disposition

**What to build:** The disposition catalogue is loaded per workflow. A `disposition.override` (no phone) links through `(workflow_id, call_id)` to the lead of the call's `call.initiated`, or failing that the earliest linked non-override event of that call. This works even when the override arrives in a later drop. Unknown-disposition events are counted only among linked `disposition.*` events whose code is not in that workflow's catalogue, and are ignored. A call's effective disposition is its latest valid override by `occurred_at`, else its latest valid set, else none. Ties on equal `occurred_at` go to the larger `event_id`. `lead_report.csv` gains `current_disposition` (from the most recent call by initiated time that has one; ties go to the larger `call_id`) and `ever_success`. `orphan_events` now treats overrides per their call linkage.

**Blocked by:** 06 (Linking at report time, counted calls, orphans)

**Status:** done

- [x] Seam B table tests: override beats set; an unknown-code override falls back to the valid set; an unknown set with a valid override gives the override; equal-time tie goes to the larger `event_id`; nothing valid gives none.
- [x] Seam A test: an override in drop 2 for a call ingested in drop 1 changes `current_disposition` after drop 2.
- [x] Seam A test: an override whose call's other events are orphans is itself an orphan; once the lead arrives it is linked.
- [x] Seam A test: `unknown_disposition_events` counts linked `RENEWD`-style codes and not orphan ones.
- [x] Seam A test: `current_disposition` skips a later call that has no disposition and uses the latest call that has one; `ever_success` is true if any call's effective disposition is a success.
