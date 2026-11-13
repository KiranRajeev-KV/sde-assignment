"""Store: the SQLite connection, the schema and every SQL statement (ADR-0001, ADR-0002, ADR-0006).

Callers get intent-level methods (`add_lead`, `counted_calls`, ...) and never see SQL.
The DDL is SQLite-specific (STRICT tables), but the queries stick to standard SQL.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from ledger.catalogue import Disposition

SCHEMA_VERSION = "1"

SCHEMA = """
-- Key/value pairs: the schema version and the PII key fingerprints (ADR-0004).
CREATE TABLE IF NOT EXISTS schema_meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
) STRICT;

CREATE TABLE IF NOT EXISTS leads (
    id           INTEGER PRIMARY KEY,           -- doubles as creation order
    workflow_id  TEXT NOT NULL,
    phone_hmac   BLOB NOT NULL CHECK (length(phone_hmac) = 32),
    phone_last4  TEXT NOT NULL CHECK (length(phone_last4) = 4 AND phone_last4 GLOB '[0-9][0-9][0-9][0-9]'),
    phone_enc    BLOB NOT NULL,                 -- Fernet token of the canonical phone (ADR-0003)
    name_enc     BLOB,                          -- Fernet token of the name; null if the schema has none
    external_ref TEXT NOT NULL,
    batch_id     TEXT NOT NULL,
    fields       TEXT NOT NULL,                 -- JSON object of the remaining non-PII schema fields
    UNIQUE (workflow_id, phone_hmac)
) STRICT;

CREATE TABLE IF NOT EXISTS rejections (
    workflow_id TEXT NOT NULL,
    batch_id    TEXT NOT NULL,
    row_number  INTEGER NOT NULL CHECK (row_number >= 1),
    reason      TEXT NOT NULL,                  -- no row content: rejected rows may hold PII
    PRIMARY KEY (workflow_id, batch_id, row_number)
) STRICT;

CREATE TABLE IF NOT EXISTS ingested_files (
    id             INTEGER PRIMARY KEY,
    sha256         TEXT NOT NULL UNIQUE,        -- file identity (ADR-0005)
    kind           TEXT NOT NULL CHECK (kind IN ('leads', 'events')),
    workflow_id    TEXT,                        -- leads only
    batch_id       TEXT,                        -- leads only
    source_path    TEXT NOT NULL,
    lead_rows      INTEGER CHECK (lead_rows >= 0),  -- leads: non-blank data rows
    rejected       INTEGER CHECK (rejected >= 0),
    merged         INTEGER CHECK (merged >= 0),     -- leads: merged duplicate rows
    field_warnings INTEGER CHECK (field_warnings >= 0),
    event_lines    INTEGER CHECK (event_lines >= 0),  -- events: non-blank lines
    malformed      INTEGER CHECK (malformed >= 0),
    duplicates     INTEGER CHECK (duplicates >= 0),
    UNIQUE (workflow_id, batch_id)              -- a batch is ingested once; event files (NULLs) never clash
) STRICT;

CREATE TABLE IF NOT EXISTS events (
    seq             INTEGER PRIMARY KEY,        -- insertion order
    event_id        TEXT NOT NULL UNIQUE,
    workflow_id     TEXT NOT NULL,
    call_id         TEXT NOT NULL,
    event_type      TEXT NOT NULL CHECK (event_type IN (
        'call.initiated', 'call.telephony_failed', 'call.connected',
        'call.ended', 'disposition.set', 'disposition.override')),
    occurred_at     TEXT NOT NULL,              -- UTC instant, YYYY-MM-DDTHH:MM:SSZ
    occurred_at_raw TEXT NOT NULL,              -- the source text, for traceability
    phone_hmac      BLOB CHECK (phone_hmac IS NULL OR length(phone_hmac) = 32),
    disposition_code TEXT CHECK (disposition_code IS NULL OR event_type LIKE 'disposition.%'),
    payload         TEXT NOT NULL               -- JSON, phone removed
) STRICT;

-- Reference data, replaced from dispositions.csv on every ingest; not part of the ledger.
CREATE TABLE IF NOT EXISTS dispositions (
    workflow_id TEXT NOT NULL,
    code        TEXT NOT NULL,
    is_terminal INTEGER NOT NULL CHECK (is_terminal IN (0, 1)),
    is_success  INTEGER NOT NULL CHECK (is_success IN (0, 1)),
    PRIMARY KEY (workflow_id, code)
) STRICT;

CREATE INDEX IF NOT EXISTS events_by_phone ON events (workflow_id, phone_hmac);
CREATE INDEX IF NOT EXISTS events_by_call ON events (workflow_id, call_id);

-- The events ledger is append-only, enforced by the database so even a bug cannot rewrite history.
CREATE TRIGGER IF NOT EXISTS events_no_update BEFORE UPDATE ON events
BEGIN SELECT RAISE(ABORT, 'events ledger is append-only: UPDATE refused'); END;

CREATE TRIGGER IF NOT EXISTS events_no_delete BEFORE DELETE ON events
BEGIN SELECT RAISE(ABORT, 'events ledger is append-only: DELETE refused'); END;
"""


# CTE prefix that yields `linked`: every event that links to a lead, with that lead (ADR-0002).
# - A non-override event links by (workflow_id, phone HMAC).
# - An override carries no phone, so it links through (workflow_id, call_id) to the lead of
#   that call's `call.initiated`, or failing that to the lead of the call's earliest linked
#   event (an `occurred_at` tie goes to the smaller `event_id`).
_LINKED_EVENTS = """
WITH by_phone AS (
    SELECT e.seq, e.event_id, e.workflow_id, e.call_id, e.event_type, e.occurred_at,
           e.disposition_code, l.id AS lead_id,
           ROW_NUMBER() OVER (
               PARTITION BY e.workflow_id, e.call_id
               ORDER BY CASE WHEN e.event_type = 'call.initiated' THEN 0 ELSE 1 END,
                        e.occurred_at, e.event_id
           ) AS call_rank
    FROM events e
    JOIN leads l ON l.workflow_id = e.workflow_id AND l.phone_hmac = e.phone_hmac
    WHERE e.event_type <> 'disposition.override'
),
linked AS (
    SELECT seq, event_id, workflow_id, call_id, event_type, occurred_at, disposition_code, lead_id
    FROM by_phone
    UNION ALL
    SELECT o.seq, o.event_id, o.workflow_id, o.call_id, o.event_type, o.occurred_at,
           o.disposition_code, c.lead_id
    FROM events o
    JOIN by_phone c ON c.workflow_id = o.workflow_id AND c.call_id = o.call_id AND c.call_rank = 1
    WHERE o.event_type = 'disposition.override'
)
"""


@dataclass(frozen=True)
class LeadRow:
    id: int
    workflow_id: str
    external_ref: str
    batch_id: str
    phone_last4: str
    fields: dict[str, str | None]  # as stored: None where the client sent nothing; defaults not applied


@dataclass(frozen=True)
class RejectionRow:
    workflow_id: str
    batch_id: str
    row_number: int
    reason: str


@dataclass(frozen=True)
class LeadCounters:
    """Lead row counters, for one lead file or summed over all of them."""

    rows: int
    rejected: int
    merged: int
    field_warnings: int


@dataclass(frozen=True)
class EventCounters:
    """Event line counters, for one event file or summed over all of them."""

    lines: int
    malformed: int
    duplicates: int


@dataclass(frozen=True)
class CallRow:
    """One counted call: a linked `call.initiated`, plus whether its call_id connected or failed."""

    lead_id: int
    call_id: str
    initiated_at: str  # UTC storage form
    connected: bool
    telephony_failed: bool


@dataclass(frozen=True)
class CallDispositionRow:
    """A `disposition.*` event of a counted call."""

    workflow_id: str
    call_id: str
    event_id: str
    event_type: str
    code: str | None
    occurred_at: str  # UTC storage form


class Store:
    def __init__(self, connection: sqlite3.Connection):
        self._db = connection

    @classmethod
    def open(cls, database: Path) -> Store:
        # Autocommit mode: transactions are opened explicitly with BEGIN in `transaction()`.
        connection = sqlite3.connect(database, isolation_level=None)
        connection.executescript(SCHEMA)
        return cls(connection)

    def close(self) -> None:
        self._db.close()

    def __enter__(self) -> Store:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def transaction(self) -> _Transaction:
        """Return a context manager that commits on success and rolls back on any exception."""
        return _Transaction(self._db)

    def key_fingerprints(self) -> dict[str, str]:
        """Return the stored PII key fingerprints; empty if no ingest has committed yet."""
        rows = self._db.execute(
            "SELECT key, value FROM schema_meta WHERE key LIKE '%!_fingerprint' ESCAPE '!'"
        )
        return dict(rows.fetchall())

    def record_key_fingerprints(self, fingerprints: dict[str, str]) -> None:
        """Store the key fingerprints and schema version, keeping any already stored.

        Call inside the ingest transaction so they commit together with the first data.
        """
        self._db.executemany(
            "INSERT INTO schema_meta (key, value) VALUES (?, ?) ON CONFLICT (key) DO NOTHING",
            [("schema_version", SCHEMA_VERSION), *fingerprints.items()],
        )

    def find_lead(self, *, workflow_id: str, phone_hmac: bytes) -> LeadRow | None:
        """Return the lead with this identity, or None."""
        row = self._db.execute(
            "SELECT id, workflow_id, external_ref, batch_id, phone_last4, fields FROM leads"
            " WHERE workflow_id = ? AND phone_hmac = ?",
            (workflow_id, phone_hmac),
        ).fetchone()
        return _lead_row(row) if row else None

    def update_lead(
        self, lead_id: int, *, external_ref: str, name_enc: bytes | None, fields_json: str
    ) -> None:
        """Apply a merged duplicate. Identity and batch_id never change; a None name keeps the stored one."""
        self._db.execute(
            "UPDATE leads SET external_ref = ?, name_enc = COALESCE(?, name_enc), fields = ? WHERE id = ?",
            (external_ref, name_enc, fields_json, lead_id),
        )

    def add_lead(
        self,
        *,
        workflow_id: str,
        phone_hmac: bytes,
        phone_last4: str,
        phone_enc: bytes,
        name_enc: bytes | None,
        external_ref: str,
        batch_id: str,
        fields_json: str,
    ) -> None:
        self._db.execute(
            "INSERT INTO leads (workflow_id, phone_hmac, phone_last4, phone_enc, name_enc, external_ref,"
            " batch_id, fields) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (workflow_id, phone_hmac, phone_last4, phone_enc, name_enc, external_ref, batch_id, fields_json),
        )

    def add_rejection(self, *, workflow_id: str, batch_id: str, row_number: int, reason: str) -> None:
        self._db.execute(
            "INSERT INTO rejections (workflow_id, batch_id, row_number, reason) VALUES (?, ?, ?, ?)",
            (workflow_id, batch_id, row_number, reason),
        )

    def ingested_file_path(self, sha256: str) -> str | None:
        """Return the path a file with this content hash was first ingested from, or None."""
        row = self._db.execute(
            "SELECT source_path FROM ingested_files WHERE sha256 = ?", (sha256,)
        ).fetchone()
        return row[0] if row else None

    def batch_was_ingested(self, *, workflow_id: str, batch_id: str) -> bool:
        """Return whether a lead file was already ingested for this batch, whatever its content."""
        row = self._db.execute(
            "SELECT 1 FROM ingested_files WHERE workflow_id = ? AND batch_id = ?", (workflow_id, batch_id)
        ).fetchone()
        return row is not None

    def record_lead_file(
        self,
        *,
        sha256: str,
        workflow_id: str,
        batch_id: str,
        source_path: str,
        counters: LeadCounters,
    ) -> None:
        self._db.execute(
            "INSERT INTO ingested_files (sha256, kind, workflow_id, batch_id, source_path, lead_rows,"
            " rejected, merged, field_warnings) VALUES (?, 'leads', ?, ?, ?, ?, ?, ?, ?)",
            (
                sha256,
                workflow_id,
                batch_id,
                source_path,
                counters.rows,
                counters.rejected,
                counters.merged,
                counters.field_warnings,
            ),
        )

    def record_event_file(self, *, sha256: str, source_path: str, counters: EventCounters) -> None:
        self._db.execute(
            "INSERT INTO ingested_files (sha256, kind, source_path, event_lines, malformed, duplicates)"
            " VALUES (?, 'events', ?, ?, ?, ?)",
            (sha256, source_path, counters.lines, counters.malformed, counters.duplicates),
        )

    def append_event(
        self,
        *,
        event_id: str,
        workflow_id: str,
        call_id: str,
        event_type: str,
        occurred_at: str,
        occurred_at_raw: str,
        phone_hmac: bytes | None,
        disposition_code: str | None,
        payload_json: str,
    ) -> bool:
        """Append an event. Return False, storing nothing, if its event_id is already stored.

        The first stored copy wins; a duplicate's content is not compared.
        """
        cursor = self._db.execute(
            "INSERT INTO events (event_id, workflow_id, call_id, event_type, occurred_at,"
            " occurred_at_raw, phone_hmac, disposition_code, payload) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)"
            " ON CONFLICT (event_id) DO NOTHING",
            (
                event_id,
                workflow_id,
                call_id,
                event_type,
                occurred_at,
                occurred_at_raw,
                phone_hmac,
                disposition_code,
                payload_json,
            ),
        )
        return cursor.rowcount == 1

    def replace_dispositions(self, dispositions: tuple[Disposition, ...]) -> None:
        """Make the stored disposition catalogue exactly `dispositions`."""
        self._db.execute("DELETE FROM dispositions")
        self._db.executemany(
            "INSERT INTO dispositions (workflow_id, code, is_terminal, is_success) VALUES (?, ?, ?, ?)",
            [(d.workflow_id, d.code, int(d.is_terminal), int(d.is_success)) for d in dispositions],
        )

    def dispositions(self) -> list[Disposition]:
        rows = self._db.execute(
            "SELECT workflow_id, code, is_terminal, is_success FROM dispositions ORDER BY workflow_id, code"
        )
        return [Disposition(w, c, bool(t), bool(s)) for w, c, t, s in rows]

    def leads(self) -> list[LeadRow]:
        rows = self._db.execute(
            "SELECT id, workflow_id, external_ref, batch_id, phone_last4, fields FROM leads ORDER BY id"
        )
        return [_lead_row(row) for row in rows]

    def rejections(self) -> list[RejectionRow]:
        rows = self._db.execute(
            "SELECT workflow_id, batch_id, row_number, reason FROM rejections"
            " ORDER BY workflow_id, batch_id, row_number"
        )
        return [RejectionRow(*row) for row in rows]

    def rejections_by_reason(self) -> dict[str, int]:
        """Return the count per rejection reason, keys sorted (the report relies on this order)."""
        rows = self._db.execute("SELECT reason, COUNT(*) FROM rejections GROUP BY reason ORDER BY reason")
        return dict(rows.fetchall())

    def lead_counters(self) -> LeadCounters:
        row = self._db.execute(
            "SELECT COALESCE(SUM(lead_rows), 0), COALESCE(SUM(rejected), 0), COALESCE(SUM(merged), 0),"
            " COALESCE(SUM(field_warnings), 0) FROM ingested_files WHERE kind = 'leads'"
        ).fetchone()
        return LeadCounters(*row)

    def event_counters(self) -> EventCounters:
        row = self._db.execute(
            "SELECT COALESCE(SUM(event_lines), 0), COALESCE(SUM(malformed), 0),"
            " COALESCE(SUM(duplicates), 0) FROM ingested_files WHERE kind = 'events'"
        ).fetchone()
        return EventCounters(*row)

    def counted_calls(self) -> list[CallRow]:
        """Return one row per counted call, linked to its lead at query time (ADR-0002)."""
        rows = self._db.execute(
            """
            SELECT l.id, i.call_id, i.occurred_at,
                   EXISTS (SELECT 1 FROM events c
                           WHERE c.workflow_id = i.workflow_id AND c.call_id = i.call_id
                             AND c.event_type = 'call.connected'),
                   EXISTS (SELECT 1 FROM events f
                           WHERE f.workflow_id = i.workflow_id AND f.call_id = i.call_id
                             AND f.event_type = 'call.telephony_failed')
            FROM events i
            JOIN leads l ON l.workflow_id = i.workflow_id AND l.phone_hmac = i.phone_hmac
            WHERE i.event_type = 'call.initiated'
            """
        )
        return [
            CallRow(lead_id, call_id, at, bool(connected), bool(failed))
            for lead_id, call_id, at, connected, failed in rows
        ]

    def call_dispositions(self) -> list[CallDispositionRow]:
        """Return the linked `disposition.*` events of every counted call, valid codes or not.

        An event is included only if it links to the same lead as its call's `call.initiated`.
        """
        rows = self._db.execute(
            _LINKED_EVENTS
            + """
            SELECT d.workflow_id, d.call_id, d.event_id, d.event_type, d.disposition_code, d.occurred_at
            FROM linked d
            WHERE d.event_type IN ('disposition.set', 'disposition.override')
              AND EXISTS (SELECT 1 FROM by_phone i
                          WHERE i.workflow_id = d.workflow_id AND i.call_id = d.call_id
                            AND i.event_type = 'call.initiated' AND i.lead_id = d.lead_id)
            """
        )
        return [CallDispositionRow(*row) for row in rows]

    def orphan_events(self) -> int:
        """Return how many stored events link to no lead at query time (ADR-0002)."""
        [count] = self._db.execute(
            _LINKED_EVENTS + "SELECT (SELECT COUNT(*) FROM events) - (SELECT COUNT(*) FROM linked)"
        ).fetchone()
        return count

    def unknown_disposition_events(self) -> int:
        """Return how many linked `disposition.*` events have a code outside their workflow's catalogue.

        An event with no code (absent or not text) counts as unknown too.
        """
        [count] = self._db.execute(
            _LINKED_EVENTS
            + """
            SELECT COUNT(*) FROM linked e
            WHERE e.event_type IN ('disposition.set', 'disposition.override')
              AND NOT EXISTS (SELECT 1 FROM dispositions d
                              WHERE d.workflow_id = e.workflow_id AND d.code = e.disposition_code)
            """
        ).fetchone()
        return count


def _lead_row(row: tuple) -> LeadRow:
    lead_id, workflow_id, external_ref, batch_id, phone_last4, fields_json = row
    return LeadRow(lead_id, workflow_id, external_ref, batch_id, phone_last4, json.loads(fields_json))


class _Transaction:
    def __init__(self, db: sqlite3.Connection):
        self._db = db

    def __enter__(self) -> None:
        self._db.execute("BEGIN")

    def __exit__(self, exc_type: type[BaseException] | None, *exc: object) -> None:
        self._db.execute("ROLLBACK" if exc_type else "COMMIT")
