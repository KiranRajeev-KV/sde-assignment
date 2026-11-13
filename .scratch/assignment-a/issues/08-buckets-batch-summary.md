# 08: Buckets and batch_summary.csv

**What to build:** Each lead gets its bucket, the first match of: `yet_to_reach_out` (no counted calls); `completed` (any call's effective disposition is terminal); `in_progress_telephony_failed` (every call has a `call.telephony_failed`); `in_progress_dialed` (everything else). The bucket rule is a pure function. `lead_report.csv` shows the real bucket, and `batch_summary.csv` gives, per workflow and batch, total leads and the count in each bucket, sorted by workflow and batch.

**Blocked by:** 04 (Merged duplicates and defaults), 07 (Dispositions: catalogue, overrides, effective disposition)

**Status:** done

- [x] Seam B table tests: each bucket branch; precedence (a terminal call wins over all-failed; a lead with one failed and one non-failed call is `in_progress_dialed`); a non-terminal effective disposition does not complete.
- [x] Seam B test: an override that turns a terminal outcome into a non-terminal one moves the lead out of `completed`.
- [x] Seam A test: a drop with leads in all four buckets across two batches yields the exact `batch_summary.csv`, and bucket columns sum to `total_leads`.
- [x] Seam A test: a merged lead counts only in its first batch.
