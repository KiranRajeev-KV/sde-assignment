# 04: Merged duplicates and defaults

**What to build:** Lead identity is `(workflow_id, canonical phone)`, enforced by a unique constraint on the phone HMAC. Drops are processed in the order ingested, files in filename order, rows in file order. The first valid row for an identity creates the lead and fixes its `batch_id` permanently. Each later valid row for that identity is a merged duplicate: it overwrites only its non-null fields (last write wins), including the external reference, and is counted in `duplicate_lead_rows_merged`. Rejected rows never merge or count as duplicates. Field warnings on merged rows still count. Defaults (e.g. `preferred_language` → `en`) are not stored; they are applied wherever lead fields are read, to fields still null after merging (ADR-0006).

**Blocked by:** 03 (Value rules, rejections and field warnings)

**Status:** done

- [x] Seam B table tests: merge overwrites only non-null fields; a null never erases a value; the external reference can change; default application fills only nulls.
- [x] Seam A test: the same identity in `batch_001` and `batch_002` gives one lead with `batch_id` `batch_001`, the later non-null values, and a merged count of 1.
- [x] Seam A test: a merged row that changes the external reference moves the lead's position in `lead_report.csv` sort order.
- [x] Seam A test: a rejected row with an existing identity changes nothing and is not counted as merged.
- [x] Seam A test: a duplicate row with an invalid optional value counts a field warning and keeps the earlier valid value.
- [x] The stored lead keeps null where the client sent nothing; a defaulted value is not persisted.

**Note:** `rules.apply_defaults` is the read-side rule; no current report outputs a defaulted field, so nothing calls it yet. Any future read of lead fields (e.g. a report column) must go through it. The CLI's per-file line now also prints `merged=N`.
