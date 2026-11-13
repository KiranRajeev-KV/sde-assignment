# 02: Header mapping

**What to build:** Lead files with renamed, re-ordered or extra columns load correctly. Headers are normalised (lower-case, trim, runs of `_` or whitespace collapsed to one space) and matched against each field's name and aliases from the workflow schema; unmatched columns are ignored. Files are read as UTF-8 with an optional BOM, using a plain row reader so duplicate headers are visible. Blank rows (every cell empty or whitespace) are skipped and not counted, and row numbers count non-blank data rows from 1. A file where two headers map to the same field is rejected with an error naming both headers, and the whole ingest rolls back. A lead folder with no matching workflow schema aborts the ingest.

**Blocked by:** 01 (Walking skeleton)

**Status:** done

- [x] Seam B table tests: header normalisation (case, spaces, underscores, mixed runs), alias matching for both provided schemas, unknown column ignored, clash detected and both headers reported.
- [x] Seam A test: a batch_003-style file (aliased headers such as `Insured Name`, `Mobile No`, `Policy No`, re-ordered, plus `agent_notes`) produces the expected leads in `lead_report.csv`.
- [x] Seam A test: a file with a BOM and a blank row in the middle loads, and the blank row does not shift row numbers.
- [x] Seam A test: clashing headers fail the ingest with a data error and leave the database unchanged.
- [x] Seam A test: a lead folder with an unknown workflow fails the ingest and leaves the database unchanged.
