# 13: Performance stretch: large dataset under 2 minutes

**What to build:** The `--scale large` dataset (~140k leads, ~600k events) ingests (both drops) and reports in under two minutes on a laptop, with measured timings recorded in SUBMISSION.md. Profile first and optimise only what the profile shows. Likely levers: batched inserts within the single transaction, indexes created or present appropriately for bulk load, WAL journal mode, streaming the event files, and keeping the per-call SQL query index-backed. Business rules stay in Python (ADR-0007).

**Blocked by:** 12 (Property tests on generated seeds and output determinism)

**Status:** done

- [x] A documented, repeatable timing command for ingest of both drops and for report on `--scale large`, with the results (and machine description) recorded in SUBMISSION.md.
- [x] Total time is under 2 minutes, or the shortfall and its bottleneck are documented honestly.
- [x] All property and scenario tests still pass after optimisation.
