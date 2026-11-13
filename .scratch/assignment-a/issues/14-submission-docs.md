# 14: SUBMISSION.md, AI_USAGE.md and run instructions

**What to build:** A reviewer can go from a clean clone to reports and tests using only SUBMISSION.md, and understands the design and its trade-offs. Fill in the remaining SUBMISSION.md sections. The "Decisions & assumptions" table already exists; reconcile it with anything that changed during the build. Remaining sections: candidate details (left for the candidate), exact run and test commands, the design and the schema with the reasons for it (referencing ADR-0001 to ADR-0007), failure modes considered and those not handled, the testing approach (three levels plus CLI smoke, and the known limit), results (timings from ticket 13 if done, and anything surprising in the data), and "if I had another day". Fill in AI_USAGE.md honestly.

**Blocked by:** 12 (Property tests on generated seeds and output determinism)

**Status:** done

- [x] Following the "How to run" commands verbatim from a clean clone produces the five reports and a passing test suite.
- [x] The design section explains the tables, the append-only ledger, report-time linking and the PII approach, and links the ADRs.
- [x] The decisions table matches the implemented behaviour; every row that changed is updated.
- [x] Failure modes list both what is handled (re-runs, crashes mid-ingest, malformed input, duplicates, key mix-ups) and what is not (key rotation, concurrent ingest, differing duplicate content).
- [x] AI_USAGE.md is filled in; candidate-only fields are clearly left for the candidate.
