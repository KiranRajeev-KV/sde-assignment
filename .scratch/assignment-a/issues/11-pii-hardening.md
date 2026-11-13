# 11: PII hardening

**What to build:** Full PII handling per ADR-0003 and ADR-0004. The full phone and customer name are stored encrypted (Fernet) under an encryption key separate from the HMAC match key. Keys are taken from `LEDGER_MATCH_KEY` / `LEDGER_ENC_KEY`, else from an owner-only key file beside the database. That file is created, with a warning, only when the database is new. An existing database with no keys found is refused. Every run checks key fingerprints stored in the database and refuses on mismatch. Generated key files and databases are git-ignored from within the solution folder.

**Blocked by:** 01 (Walking skeleton)

**Status:** done

- [x] Seam A test: encrypted phone and name decrypt to the canonical phone and the trimmed name with the encryption key.
- [x] Seam A test: a new database without environment keys creates an owner-only key file; environment keys take precedence when set.
- [x] Seam A test: an existing database with its key file deleted is refused with a clear data error; a different match key is refused via fingerprint.
- [x] Seam A test: a byte scan of the database file finds no plaintext phone (in any input format) and no name.
- [x] Generated key files and database files are ignored by git from within the solution folder; no provided file outside it is changed.

## Comments

- 2026-11-13: Implemented. Tests in `solution/tests/test_pii.py`. Notes:
  - Each key is resolved on its own: its env var, else the key file. If either env var is unset, the key file is read, or created for a new database. Setting only one env var on a new database still creates a full key file, and that file's copy of the env-supplied key is never used.
  - Fingerprints (HMAC of a constant under each key) and `schema_version` go in `schema_meta`. They are written inside the ingest transaction, so a rolled-back first ingest leaves none. `report` only checks them and never writes. A database with no fingerprints has never committed an ingest, so there is nothing to check.
  - `name_enc` is nullable, because a schema need not have a name. The catalogue now refuses a schema with more than one PII field besides the phone. On a merge, a null incoming name keeps the stored one.
  - Last-four extraction moved into the vault (follow-up from ticket 01).
  - Not handled: a database created before this ticket has no `phone_enc` column and fails with a raw sqlite error. There are no such databases outside development, so recreate them. `schema_version` is stored but not checked yet.
  - The byte scan of the database and the reports runs on generated data, in ticket 12's property tests.
