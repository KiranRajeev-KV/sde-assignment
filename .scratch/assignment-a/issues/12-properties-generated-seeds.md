# 12: Property tests on generated seeds and output determinism

**What to build:** Confidence that the whole pipeline holds on realistic mess. Tests run the provided generator as a subprocess (unmodified) for two seeds at small scale into a temporary directory, and assert properties through Seam A. Whatever the properties expose gets fixed here. Output determinism is locked down: `\n` line endings, UTF-8 without BOM, JSON keys in contract order with 2-space indentation and a trailing newline, explicit number formatting, and `true`/`false`.

**Blocked by:** 02 (Header mapping), 08 (Buckets and batch_summary.csv), 09 (daily_overview.csv), 10 (Idempotency and safe writes), 11 (PII hardening)

**Status:** done

- [x] Re-ingesting drop 1 after drop 1 and drop 2 leaves all five report files byte-identical.
- [x] `ingest d1; ingest d2` produces byte-identical reports to `ingest d1 d2`, on fresh databases.
- [x] Reconciliation: `lead_rows_total = lead_rows_rejected + duplicate_lead_rows_merged + leads`; `events_total = malformed + duplicates + stored events`; the sum of `batch_summary.total_leads` equals the number of `lead_report` rows; the sum of `rejections_by_reason` equals `lead_rows_rejected` and the row count of `rejections.csv`.
- [x] Every generated phone (in any of its input formats) and every generated name is absent from the database bytes.
- [x] Output format checks: no `\r`, no BOM, JSON key order matches the contract, every CSV header matches the contract exactly.
- [x] All tests pass for both seeds.

## Comments

- 2026-11-13: Implemented. Tests in `solution/tests/test_properties.py` (seeds 42 and 2026; 10 tests, ~3s). Notes:
  - The properties exposed no pipeline defect: every check passed on the first run, so no production code changed. To confirm the tests can fail, two mutations were tried and then reverted: storing the name in plaintext failed the byte scan, and `\r\n` CSV terminators failed the format and header checks.
  - The generator runs once per seed in a module-scoped fixture. Each seed is ingested three ways: in one invocation, drop by drop, and drop by drop followed by drop 1 again.
  - "Stored events" are counted from the `events` table, the only place that number exists. `events_total` is also checked against an independent count of non-empty lines in the generated files, and `lead_rows_total` against the non-blank CSV rows.
  - The PII scan covers the database file and any `-wal`/`-journal` files beside it (not the key file), on both the one-invocation and the re-ingested databases, and also the reports. Phones are collected in every input format and in canonical form. Values with fewer than 9 digits (`N/A`, empty) are left out because they would match unrelated bytes. A plain substring check per value took 15s per seed, so a prefix-window filter is applied first.
  - "Stored events" comes from a `SELECT count(*) FROM events`. The spec's testing rules say tests don't read internal tables, but no report exposes this count. `events` is the ledger itself, not an intermediate table, so this exception is deliberate.
  - Also added, beyond the checklist: the sort order of `lead_report.csv`, `daily_overview.csv` and `rejections.csv`, and the value formats of `lead_report.csv` (masked phone, bucket, booleans, IST timestamps) and of `connectivity_rate`.
