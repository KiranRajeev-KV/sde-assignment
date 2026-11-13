# SQLite (STRICT tables) as the pipeline's database

The pipeline is a single-process batch CLI run by graders from a clean clone, so we store everything in one SQLite file via the stdlib `sqlite3` module, using `STRICT` tables, `CHECK`/`UNIQUE` constraints and triggers that forbid `UPDATE`/`DELETE` on the ledger. Postgres (the provided `docker-compose.yml`) was rejected for this scope: it adds a container and a driver dependency for no correctness gain with one writer. Report SQL stays portable (no SQLite-only functions) so a move is cheap.

## Consequences

- Revisit if ingest needs concurrent workers or a shared multi-tenant store; Postgres would then also let the ledger's append-only rule be enforced by `REVOKE UPDATE, DELETE` on a role instead of triggers.
