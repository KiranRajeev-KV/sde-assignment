# Spec: Assignment A, Interaction Ledger & Reporting Pipeline

Status: ready-for-agent

Governing decisions: ADR-0001 to ADR-0007. Vocabulary: the "Assignment A" section of the glossary (Drop, Lead identity, Merged duplicate, Rejection, Field warning, Linked event, Orphan event, Counted call, Effective disposition, Bucket). The assignment README is the authoritative rule set; this spec records only how we satisfy it and every call the README left open.

## Problem Statement

Operations teams deliver lead batches (CSV, per workflow) and the calling system delivers call events (JSON Lines), one **drop** per day. The data is deliberately messy: six phone formats, invalid phones, missing required fields, renamed and re-ordered columns, extra columns, blank rows, mixed date and currency formats, duplicate leads across batches, out-of-order and duplicate events (including across drops), malformed lines, events for numbers never uploaded, events that arrive before their lead, overrides with no phone, and dispositions outside the catalogue.

Clients read five reports every morning. If any number is wrong they stop trusting the platform. Today there is nothing that turns drops into those reports correctly, repeatably, and without exposing customer PII at rest. Graders will run the pipeline on an unseen seed and diff the five files against expected output, then judge the schema, the ledger design, the PII approach, idempotency and tests. The author must also defend and modify the code live in an interview.

## Solution

A Python 3.11+ command-line pipeline, installed from the solution folder, backed by a single SQLite database file:

- `ingest DROP_DIR [DROP_DIR ...]` reads one or more drops in the order given, inside one transaction. It validates and normalises lead rows against the workflow schema, records **rejections**, merges **merged duplicates** into existing leads, and appends every well-formed, non-duplicate event to an append-only **interaction ledger**. Files already ingested (by content hash) are skipped, so re-running a drop changes nothing.
- `report --out DIR` derives everything from the database as it stands: it links events to leads by joining on a keyed hash of the phone, builds **counted calls**, applies **effective disposition** and **bucket** rules, and writes the five contract files byte-deterministically.

Customer names and phones never touch disk in plaintext: phones are matched by HMAC and recoverable only through encryption under a separate key; reports show a masked phone built from the last four digits. Because linking happens at report time, an **orphan event** from drop 1 counts automatically once its lead arrives in drop 2, and ingesting drops one at a time gives the same reports as ingesting them together.

## User Stories

### Running the pipeline

1. As a grader, I want to install and run the pipeline from a clean clone with a few documented commands, so that I can evaluate it without environment setup.
2. As a grader, I want `ingest` to accept one or more drop directories, so that I can ingest drops one at a time or all at once.
3. As a grader, I want `report --out DIR` to write exactly the five contract files, so that I can diff them against expected output.
4. As an operator, I want to choose the database location with a flag or environment variable, so that I can keep separate pipelines apart.
5. As an operator, I want to point the pipeline at a schemas directory, so that schema and catalogue changes do not need code changes.
6. As an operator, I want `ingest` to print, per file, whether it was ingested or skipped and its counts, so that I can see what happened on each run.
7. As an operator, I want distinct exit codes for success, data errors and usage errors, so that a scheduler can react correctly.
8. As an operator, I want a run that crashes or is refused to leave no partial state, so that the fix is always "re-run".
9. As an operator, I want `report` never to leave a half-written set of report files, so that downstream readers never see a mix of old and new.

### Lead headers

10. As an ops team member, I want headers matched case-insensitively with spaces and underscores treated alike, so that `Mobile No`, `mobile_no` and ` MOBILE  NO ` all map to `phone`.
11. As an ops team member, I want aliases from the workflow schema honoured, so that renamed columns in later batches still load.
12. As an ops team member, I want re-ordered columns to load correctly, so that column position never matters.
13. As an ops team member, I want columns that match no field ignored, so that extra columns like `agent_notes` do no harm.
14. As a data owner, I want a file where two headers map to the same field rejected with an error naming both headers, and the whole ingest rolled back, so that an ambiguous layout never silently corrupts a batch.
15. As a data owner, I want a file that lacks a column for a required field to reject each row with `missing_required:<field>`, so that the spec's per-row rule still applies.
16. As a data owner, I want a lead folder with no matching workflow schema to abort the ingest, so that a schema is never guessed.
17. As an ops team member, I want files with a UTF-8 byte-order mark to load correctly, so that spreadsheet exports work.

### Lead rows and values

18. As an ops team member, I want blank rows skipped and not counted, so that stray empty lines do not affect row numbers or totals.
19. As an ops team member, I want row numbers to count non-blank data rows from 1, so that rejection row numbers point at the right row.
20. As an ops team member, I want every value trimmed and empty values treated as missing, so that whitespace never causes a false failure.
21. As an ops team member, I want phones in any of the six real-world formats normalised to `+91XXXXXXXXXX`, so that the same customer is recognised everywhere.
22. As a data owner, I want phones that are not valid Indian mobiles (wrong length, bad leading digit, landline, foreign, `N/A`) treated as invalid, so that we never dial a bad number.
23. As an ops team member, I want dates accepted in `YYYY-MM-DD`, `DD/MM/YYYY`, `DD-MM-YYYY` and `DD-Mon-YYYY` (month name case-insensitive, day-first), so that mixed date formats load.
24. As a data owner, I want impossible dates (like 31/02) and non-dates treated as invalid, so that bad dates are never stored.
25. As an ops team member, I want amounts with `₹`, `Rs`, `Rs.` or `INR` prefixes and thousands commas accepted, so that mixed currency formats load.
26. As a data owner, I want negative or non-numeric amounts treated as invalid and valid amounts rounded half-up to 2 places, so that stored amounts are clean.
27. As an ops team member, I want enum values compared case-insensitively and stored lower-case, so that `HI` and `hi` are the same language.
28. As a client, I want each rejected row to carry exactly one reason, the first failure found walking fields in schema order, so that the reason is predictable.
29. As a client, I want a missing required field reported as `missing_required:<field>` and a present-but-invalid phone as `invalid_phone`, so that I know how to fix the upload.
30. As a client, I want an invalid optional value stored as missing and counted as a **field warning** (only on rows that are not rejected), so that one bad optional cell never loses a lead.
31. As a client, I want field warnings counted on merged duplicate rows too, so that every bad value I sent is visible.

### Lead identity and merging

32. As a client, I want leads identified by workflow and canonical phone, so that the same person uploaded twice is one lead.
33. As a client, I want the first valid row for an identity to create the lead and fix its `batch_id` permanently, so that batch reporting is stable.
34. As a client, I want each later valid row for the same identity counted as a merged duplicate that overwrites only its non-null fields, so that corrections in later uploads take effect.
35. As a client, I want a rejected row never to merge into or count as a duplicate of an existing lead, so that bad rows never change good data.
36. As a client, I want a later merged row to be able to change a lead's external reference, so that last-write-wins applies to every field the spec allows.
37. As a client, I want schema defaults (such as language `en`) applied only where a field is still missing after merging, so that a default never overrides real data.
38. As a data owner, I want the stored lead to keep "missing" distinct from "defaulted", so that we can tell what the client actually sent.
39. As a client, I want drops processed in the order ingested, files in filename order and rows in file order, so that merge results are deterministic.

### Events and the ledger

40. As an engineer, I want every non-empty event line counted in `events_total`, including malformed and duplicate lines, so that the total reconciles with the raw files.
41. As an engineer, I want blank or whitespace-only event lines ignored and not counted, so that trailing newlines do not inflate totals.
42. As an engineer, I want lines that are not valid JSON, have no `event_id`, are not JSON objects, or carry an unparseable `occurred_at`, an unknown `event_type`, or a missing `call_id` or `workflow_id` counted as malformed and not stored, so that the ledger only holds events that can be reported on.
43. As an engineer, I want a malformed line not to reserve its `event_id`, so that a later well-formed copy is still accepted.
44. As an engineer, I want an `event_id` already seen in any drop counted as a duplicate and dropped, with the first stored copy winning, so that redelivery never double-counts.
45. As an engineer, I want a duplicate of an orphan event counted as a duplicate, so that the spec's check order holds.
46. As an engineer, I want events with an unnormalisable phone or an unknown workflow stored and counted as orphans, so that calls to rejected or never-uploaded numbers stay visible in data quality.
47. As an auditor, I want the ledger to reject any update or delete at the database level, so that history cannot be rewritten even by a bug.
48. As an auditor, I want each ledger event to keep its original timestamp text alongside the normalised UTC instant, so that I can trace any value back to its source.
49. As an engineer, I want timestamps in UTC (`Z`), offset and naive forms accepted, with naive read as IST, so that all three formats compare correctly.

### Linking and calls

50. As a client, I want events linked to leads by workflow and normalised phone, so that every call is attributed to the right customer.
51. As a client, I want a supervisor override (which has no phone) linked through its call to that call's lead, so that corrections always apply.
52. As a client, I want an event that was an orphan after drop 1 to count once its lead arrives in drop 2, so that reports always reflect everything ingested so far.
53. As a client, I want an override that arrives in a later drop than the rest of its call to apply, so that late corrections are not lost.
54. As a client, I want orphan counts in data quality to reflect the final state, so that resolved orphans are not counted as orphans.
55. As a client, I want a call to count only if its `call.initiated` event is linked, and to belong to that event's lead, so that whoever initiated the call owns it.
56. As a client, I want all events sharing the call's workflow and `call_id` to belong to that counted call, so that one call is never split or double-counted.
57. As a client, I want events of a call with no `call.initiated` to be linked but contribute to nothing, so that partial calls never inflate any report.
58. As a client, I want unknown dispositions checked only on linked events, counted, and ignored, so that typos in the catalogue never become outcomes.
59. As a supervisor, I want an unknown-code override to be ignored so the call falls back to its valid `disposition.set`, so that a bad correction does not erase a good outcome.

### Derived facts

60. As a client, I want a call's effective disposition to be its latest valid override by time, else its latest valid set, else none, so that human corrections take precedence.
61. As a client, I want ties on equal time broken by the larger `event_id`, so that the result never depends on ingest order.
62. As a client, I want a call counted as connected if it has a `call.connected` event, so that connectivity is measured consistently.
63. As a client, I want each lead's bucket to be the first match of `yet_to_reach_out`, `completed`, `in_progress_telephony_failed`, `in_progress_dialed`, so that every lead is in exactly one bucket.
64. As a client, I want a call's date to be the IST date of its `call.initiated`, even if it connected after midnight, so that daily numbers are stable.

### Reports

65. As a client, I want a batch summary per workflow and batch with total leads and bucket counts, so that I can see how each upload is doing.
66. As a client, I want a daily overview per workflow and IST date with calls, connected calls, connectivity rate to exactly 4 decimals (half-up) and success leads, so that I can track daily health.
67. As a client, I want success leads per day counted as distinct leads with a success-outcome call on that date, so that a lead called twice is counted once.
68. As a client, I want one lead report row per lead with batch, masked phone, bucket, call counts, last call time in IST, current disposition and ever-success, so that I can follow up on individuals.
69. As a client, I want the current disposition taken from the most recent call (by initiated time, ties to larger `call_id`) that has one, so that it reflects the latest known outcome.
70. As a client, I want the lead report sorted by workflow and external reference, with ties broken by batch, masked phone and creation order, so that the file is deterministic.
71. As a client, I want a rejections file with workflow, batch, row number and reason and no PII, so that I can fix my uploads without exposing customers.
72. As a client, I want a data quality file with every contract counter, rejection reasons listed only if they occurred and sorted by key, so that I can see exactly what was wrong with my data.
73. As a grader, I want byte-deterministic output (fixed key order, `\n` line endings, UTF-8 without BOM, explicit number formatting, `true`/`false` booleans, empty strings for null), so that exact diffs pass.

### PII protection

74. As a data protection officer, I want no customer name or phone stored in plaintext anywhere in the database, so that a leaked database file does not expose customers.
75. As a data protection officer, I want phones matched with a keyed HMAC rather than a plain hash, so that the small phone-number space cannot be brute-forced.
76. As a dialler owner, I want full phone and name recoverable via encryption under a separate key, so that the lead store remains a usable system of record.
77. As a data protection officer, I want the ledger to keep only the phone HMAC, never the raw event line, so that event phones are protected too.
78. As a data protection officer, I want rejections to store no row content, so that rejected rows do not leak PII.
79. As a grader, I want keys taken from environment variables or else an auto-created owner-only key file beside a new database, so that I can run from a clean clone.
80. As an operator, I want the pipeline to refuse to run against an existing database with missing or different keys, so that a key mix-up never silently turns every earlier event into an orphan.

### Idempotency and order-independence

81. As an operator, I want a file whose content hash was already ingested to be skipped regardless of path or name, so that re-running a drop changes nothing.
82. As an operator, I want re-ingesting a drop to leave `events_total`, duplicate counts and merge counts unchanged, so that data quality numbers stay true.
83. As a data owner, I want a lead batch name reused with different content to be a hard error, so that a `batch_id` never silently means two uploads.
84. As a grader, I want ingesting drop 1 then drop 2 to produce byte-identical reports to ingesting both in one command, so that the pipeline is order-safe.

### Performance

85. As an operator, I want the large dataset (~140k leads, ~600k events) to ingest and report in under two minutes on a laptop, with measured timings reported, so that the approach is shown to scale.

### Maintainability

86. As the author in an interview, I want every business rule in one small pure function with a table-driven test, so that I can change a rule live and see exactly what breaks.

## Implementation Decisions

### Modules

- **Rules (pure, no I/O).** Header normalisation and mapping (including clash detection); value normalisers for phone, date, decimal, enum and string; row validation returning either a rejection reason or the normalised values plus a field-warning count; merge of a new row into an existing lead's fields; default application; effective disposition from a call's disposition candidates; bucket from a lead's calls; success and connectivity rules; half-up decimal formatting. This is the module most likely to change and the only home of business rules (ADR-0007).
- **Schema catalogue.** Loads workflow schemas and the disposition catalogue from the schemas directory into in-memory structures (fields in schema order, aliases, required, PII, reference and default flags; per-workflow codes with terminal and success flags).
- **PII vault.** Resolves keys (environment variables first, else a key file beside the database created only for a new database, owner-only permissions), verifies the stored key fingerprint, and exposes: phone HMAC, last-four extraction, encrypt and decrypt. Two independent keys: match key and encryption key (ADR-0003, ADR-0004).
- **Store.** Owns the SQLite connection, schema creation, transactions and all SQL. Exposes intent-level operations (record ingested file, upsert lead, add rejection, append events with duplicate counting, load per-call rows for reporting). Uses STRICT tables and portable SQL (ADR-0001).
- **Lead ingester.** Walks a drop's lead files (sorted by workflow then filename), maps headers, validates rows, writes rejections, creates or merges leads, and records per-file counts.
- **Event ingester.** Streams event files (sorted by filename), classifies each non-empty line as malformed, duplicate or stored, and records per-file counts. It does no linking (ADR-0002).
- **Pipeline API.** `ingest(database, drop directories, schemas directory)` returns per-file results; `report(database, output directory)` writes the five files. This is the primary test seam.
- **Report builder.** Takes the per-call rows from the store, applies the rules module, aggregates, and writes the five files deterministically via a temporary directory and atomic rename.
- **CLI.** A thin argument parser over the pipeline API: global `--db` (default from `LEDGER_DB`, else a database file in the working directory) and `--schemas` (default: the provided schemas directory, resolved relative to the installed package); subcommands `ingest DROP_DIR...` and `report --out DIR`; exit 0 on success, 1 on data errors, 2 on usage errors.

### Database schema (ADR-0001, ADR-0006)

- **schema_meta**: key/value pairs, including the schema version and key fingerprints.
- **ingested_files**: primary key is the file's SHA-256. It records kind (leads or events), workflow and batch (leads only), source path, run identifier, timestamp, and counters (events: lines, malformed, duplicates; leads: rows, rejected, merged, field warnings). Unique on (workflow, batch) for lead files; event files leave those null and are exempt.
- **leads**: surrogate id; workflow; phone HMAC; phone last four (length-checked); encrypted phone; encrypted name; external reference (not null); batch id (not null); remaining schema fields as a JSON object holding normalised values, with null where missing; creation sequence. Unique on (workflow, phone HMAC). The table is mutable: merges update it in place.
- **rejections**: workflow, batch, row number (≥ 1), reason. Primary key (workflow, batch, row number). No row content.
- **events** (the ledger): `event_id` primary key; insertion sequence; workflow; call id; event type (CHECK against the six types); occurred-at as a UTC instant plus the original text; phone HMAC (nullable); payload JSON with the phone removed. Indexes on (workflow, phone HMAC) and (workflow, call id). Triggers before UPDATE and before DELETE abort with an append-only error.
- **dispositions**: (workflow, code) primary key, with terminal and success flags, loaded from the catalogue.

### Ingest semantics

- One transaction for the whole `ingest` invocation; drop directories are processed in argument order. Within a drop, lead files come before event files. This order is for readable output only; results do not depend on it.
- File identity is the SHA-256 of its bytes. A hash already recorded means skip. A lead file whose (workflow, batch) is already recorded with a different hash is a data error that rolls back the invocation (ADR-0005).
- Leads: CSVs are read as UTF-8 with an optional BOM, using a plain row reader (not a dict reader) so that clashing headers are detectable. Blank rows are skipped before row numbering. Validation walks fields in schema order: the first missing required field or invalid phone becomes the single rejection reason. Otherwise, each invalid optional field becomes null plus one field warning. A valid row whose identity exists is a merged duplicate: its non-null fields overwrite, including the external reference. Defaults are not stored; they are applied when lead fields are read.
- A required field of a type other than string or phone that is present but invalid does not occur in the provided schemas. The rules treat it as a rejection named after the field, and this is documented as an assumption.
- Events: each non-empty line is counted. A line is malformed if it is not a JSON object, has no `event_id`, or fails structural validation (type, timestamp, call id, workflow id). Otherwise it is inserted with insert-or-ignore on `event_id`; an ignored insert counts as a duplicate. The phone is normalised with the lead phone rules: a valid phone is stored as its HMAC, an invalid or absent phone as null.

### Report semantics (ADR-0002, ADR-0007)

- SQL produces one row per counted call: the lead (via the linked `call.initiated`), call id, initiated instant, connected flag, telephony-failed flag, the winning valid `disposition.set` code and the winning valid `disposition.override` code. Winners are chosen by latest occurred-at, ties to the larger `event_id`, considering only catalogue codes for that workflow. Overrides attach through (workflow, call id) to the counted call.
- Orphan count: stored events that are not linked. A non-override event is linked if its (workflow, phone HMAC) matches a lead. An override is linked if any non-override event of the same (workflow, call id) is linked, and its lead is that of the call's `call.initiated` if there is one, else that of the earliest such event.
- Unknown-disposition count: linked `disposition.*` events whose code is not in the catalogue for that workflow.
- Python applies effective disposition, bucket and success, and aggregates batch, daily and lead rows. It formats the IST timestamp as `YYYY-MM-DDTHH:MM:SS+05:30` and the connectivity rate with exact decimals rounded half-up to 4 places.
- Data-quality lead counters and event line counters are summed from the ingested-files table; orphan and unknown-disposition counts are derived from the current state.
- Output: CSVs with a header row, `\n` terminators, UTF-8 without BOM, and no index. JSON keys in contract order, indented by 2, with a trailing newline. `rejections_by_reason` includes only reasons that occurred, with sorted keys. Files are written to a temporary directory and then renamed into place.

### Dependencies

- Runtime: the `cryptography` package only, for Fernet. Development: `pytest`. Everything else uses the standard library.

## Testing Decisions

- **What makes a good test:** it exercises behaviour through a public seam and asserts on observable outcomes: report file contents, counters, exit codes, and database-level refusals. It never asserts on internal SQL, intermediate tables or private helpers, so the store and query layer can be refactored freely. Each test names the rule or scenario it protects.
- **Level 1, rules module (Seam B):** table-driven tests with no database.
  - Phone: all six formats plus `N/A`, a landline, a `+1` number, 9 digits and a bad leading digit.
  - Date: four formats, a case-insensitive month, `31/02`, `2026-13-01`, `soon`, `TBD`.
  - Decimal: `₹`, `Rs`, `Rs.`, `INR`, commas, negative, `-`, `N/A`, words, half-up rounding.
  - Enum: case, whitespace, invalid values, empty.
  - Header normalisation, alias mapping and clash detection.
  - Rejection order: schema-order walk, a missing name plus a bad phone gives the name reason, `N/A` gives `invalid_phone`.
  - Merge: non-null overwrite and external reference change. Default application.
  - Effective disposition: override beats set, an unknown override falls back to the set, equal-time tie goes to the larger `event_id`, none.
  - Bucket: each branch and first-match precedence. Connectivity rate half-up (`5/160` gives `0.0313`).
- **Level 2, pipeline API with hand-built drops (Seam A):** tiny fixture drops built inside each test, one scenario each.
  - An orphan resolved by a later drop's lead; an override arriving a drop after its call.
  - A merged row changing the external reference; a rejected row whose identity already exists.
  - A malformed line not reserving its `event_id`; a call without `call.initiated` contributing nothing.
  - Clashing headers rolling back the ingest; a reused batch name rolling back the ingest.
  - The ledger refusing UPDATE and DELETE; a key-fingerprint mismatch refusing to run.
  - Re-ingest skipping by content hash under a different path.
- **Level 3, properties on generated data (Seam A):** the provided generator is run as a subprocess for 2–3 seeds at small scale, into a temporary directory. The generator is never modified.
  - Re-ingesting drop 1 leaves all five report files byte-identical.
  - Ingesting drop 1 then drop 2 is byte-identical to ingesting both in one invocation.
  - Reconciliation: lead rows total = rejected + merged + lead count. Events total = malformed + duplicates + stored events. The sum of batch-summary totals = lead-report rows. The sum of rejection reasons = rejected rows.
  - A byte scan of the database file and key-less exports finds no generated phone (in any format) or name.
- **CLI smoke test:** one subprocess run of ingest then report on a small drop, asserting exit code 0 and the lead report row, plus exit code 1 for a data error and 2 for a usage error.
- **Prior art:** none in the repository; the solution folder is empty apart from a placeholder README. These tests set the pattern.
- **Known limit:** tests cannot catch a misreading of the spec that is internally consistent. The decisions table in SUBMISSION.md is the mitigation.

## Out of Scope

- Any change to provided files outside the solution folder: the assignment data directory (README, schemas, generator), `docker-compose.yml`, and the root `.gitignore`. Exceptions: the documentation already updated during design (the glossary's appended section, the ADRs, and SUBMISSION.md, which the candidate must fill in). Ignoring generated key files is handled inside the solution folder.
- Stretch goals not picked: truly incremental reporting (the trade-off is documented in ADR-0002), aggregation in SQL (rejected in ADR-0007), and the production note for 100k leads/day (optional, only if time remains after everything else passes).
- PostgreSQL support, concurrent ingest, and multi-tenant storage.
- Key rotation and re-hashing.
- Lead history or audit of which batch changed which lead field.
- Detecting duplicate events whose content differs (the first stored copy wins without comparison).
- Ingesting drops in an order other than the one given, or discovering drops automatically from a parent directory.

## Further Notes

- The half-up rounding of the connectivity rate is a deliberate, documented guess about the graders' reference output. If an exact diff disagrees on a single row, check that first.
- Several rules cover inputs the generator never produces: header clashes, `occurred_at` ties, calls without `call.initiated`, structurally invalid events, and external-reference collisions. They exist to be defensible, not to change the grading diff.
- Build order: rules and level-1 tests, then store and ingest, then report and level-2 tests, then level-3 properties on generated seeds. Only after that, the performance work with timings recorded in SUBMISSION.md.
