"""Pipeline API: `ingest` drops into the database, then `report` from it.

This module does the file I/O and wiring; the rules live in `rules.py`, the SQL in `store.py`.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import shutil
import tempfile
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from ledger import rules
from ledger.catalogue import Catalogue, WorkflowSchema, load_catalogue
from ledger.errors import DataError
from ledger.store import EventCounters, LeadCounters, Store
from ledger.vault import Vault

DAILY_OVERVIEW_HEADER = [
    "workflow_id",
    "date",
    "total_calls",
    "connected_calls",
    "connectivity_rate",
    "success_leads",
]
BATCH_SUMMARY_HEADER = ["workflow_id", "batch_id", "total_leads", *rules.BUCKETS]
LEAD_REPORT_HEADER = [
    "workflow_id",
    "external_ref",
    "batch_id",
    "phone_masked",
    "bucket",
    "total_calls",
    "connected_calls",
    "last_call_at",
    "current_disposition",
    "ever_success",
]
REJECTIONS_HEADER = ["workflow_id", "batch_id", "row_number", "reason"]


@dataclass
class FileResult:
    path: Path
    kind: Literal["leads", "events"]
    status: Literal["ingested", "skipped"]
    counts: dict[str, int] = field(default_factory=dict)
    same_as: str | None = None  # for a skipped file: where the same content was first ingested from


def ingest(database: Path, drops: list[Path], schemas_dir: Path) -> list[FileResult]:
    """Ingest drop directories in the order given, in one transaction.

    Any DataError rolls back the whole call, so a refused run leaves the database untouched.
    """
    database = Path(database)
    drops = [Path(drop) for drop in drops]
    for drop in drops:
        if not drop.is_dir():
            raise DataError(f"drop directory not found: {drop}")
    catalogue = load_catalogue(Path(schemas_dir))
    vault = Vault.for_database(database)
    results: list[FileResult] = []
    with _open_store(database, vault) as store, store.transaction():
        store.record_key_fingerprints(vault.fingerprints())
        store.replace_dispositions(catalogue.dispositions)
        for drop in drops:
            results += _ingest_lead_files(store, vault, catalogue, drop)
            results += _ingest_event_files(store, vault, drop)
    return results


def report(database: Path, out_dir: Path) -> None:
    """Write the report files derived from the database as it stands.

    All five are written to a temporary directory inside `out_dir`, then renamed into
    place, so a failure leaves the previous reports untouched.
    """
    database = Path(database)
    if not database.exists():
        raise DataError(f"database not found: {database}")
    with _open_store(database, Vault.for_database(database)) as store:
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        # Staged inside out_dir so it is on the same filesystem, which makes os.replace atomic.
        staging = Path(tempfile.mkdtemp(prefix=".report-", dir=out_dir))
        try:
            _write_reports(store, staging)
            for path in sorted(staging.iterdir()):
                os.replace(path, out_dir / path.name)
        finally:
            shutil.rmtree(staging, ignore_errors=True)


def _open_store(database: Path, vault: Vault) -> Store:
    """Open the database, refusing keys other than those it was created with (ADR-0004).

    A database with no stored fingerprints has never committed an ingest, so holds no
    data under any key; its first ingest records them.
    """
    store = Store.open(database)
    try:
        vault.check_fingerprints(store.key_fingerprints())
    except BaseException:
        store.close()
        raise
    return store


def _write_reports(store: Store, staging: Path) -> None:
    """Load what the reports need from the store, apply the rules, and write all five files."""
    leads = store.leads()
    rejections = store.rejections()
    lead_counters = store.lead_counters()
    event_counters = store.event_counters()
    rejections_by_reason = store.rejections_by_reason()
    orphan_events = store.orphan_events()
    unknown_disposition_events = store.unknown_disposition_events()
    stored_dispositions = store.dispositions()
    dispositions_by_call: dict[tuple[str, str], list[rules.DispositionEvent]] = defaultdict(list)
    for d in store.call_dispositions():
        dispositions_by_call[(d.workflow_id, d.call_id)].append(
            rules.DispositionEvent(
                d.event_id,
                "override" if d.event_type == "disposition.override" else "set",
                d.code,
                rules.parse_instant(d.occurred_at),
            )
        )
    workflow_of_lead = {lead.id: lead.workflow_id for lead in leads}
    codes: dict[str, set[str]] = defaultdict(set)
    success_codes: dict[str, set[str]] = defaultdict(set)
    terminal_codes: dict[str, set[str]] = defaultdict(set)
    for entry in stored_dispositions:
        codes[entry.workflow_id].add(entry.code)
        if entry.is_success:
            success_codes[entry.workflow_id].add(entry.code)
        if entry.is_terminal:
            terminal_codes[entry.workflow_id].add(entry.code)
    calls_by_lead: dict[int, list[rules.Call]] = defaultdict(list)
    for row in store.counted_calls():
        workflow_id = workflow_of_lead[row.lead_id]
        effective = rules.effective_disposition(
            dispositions_by_call[(workflow_id, row.call_id)], codes[workflow_id]
        )
        calls_by_lead[row.lead_id].append(
            rules.Call(
                row.call_id,
                rules.parse_instant(row.initiated_at),
                row.connected,
                effective,
                row.telephony_failed,
            )
        )

    rows = []
    batches: dict[tuple[str, str], dict[str, int]] = defaultdict(lambda: dict.fromkeys(rules.BUCKETS, 0))
    for lead in leads:
        calls = calls_by_lead[lead.id]
        bucket = rules.bucket(calls, terminal_codes[lead.workflow_id])
        batches[(lead.workflow_id, lead.batch_id)][bucket] += 1
        masked = rules.mask_phone(lead.phone_last4)
        sort_key = (lead.workflow_id, lead.external_ref, lead.batch_id, masked, lead.id)
        rows.append(
            (
                sort_key,
                [
                    lead.workflow_id,
                    lead.external_ref,
                    lead.batch_id,
                    masked,
                    bucket,
                    str(len(calls)),
                    str(sum(c.connected for c in calls)),
                    rules.format_ist(max(c.initiated_at for c in calls)) if calls else "",
                    rules.current_disposition(calls) or "",
                    "true" if rules.ever_success(calls, success_codes[lead.workflow_id]) else "false",
                ],
            )
        )
    rows.sort(key=lambda r: r[0])
    _write_csv(
        staging / "batch_summary.csv",
        BATCH_SUMMARY_HEADER,
        [
            [workflow_id, batch_id, str(sum(counts.values())), *(str(counts[b]) for b in rules.BUCKETS)]
            for (workflow_id, batch_id), counts in sorted(batches.items())
        ],
    )
    _write_csv(
        staging / "daily_overview.csv",
        DAILY_OVERVIEW_HEADER,
        _daily_overview_rows(calls_by_lead, workflow_of_lead, success_codes),
    )
    _write_csv(staging / "lead_report.csv", LEAD_REPORT_HEADER, [r[1] for r in rows])
    _write_csv(
        staging / "rejections.csv",
        REJECTIONS_HEADER,
        [[r.workflow_id, r.batch_id, str(r.row_number), r.reason] for r in rejections],
    )
    # Key order is part of the output contract (assignment-a-data/README.md).
    quality = {
        "lead_rows_total": lead_counters.rows,
        "lead_rows_rejected": lead_counters.rejected,
        "rejections_by_reason": rejections_by_reason,
        "duplicate_lead_rows_merged": lead_counters.merged,
        "field_warnings": lead_counters.field_warnings,
        "events_total": event_counters.lines,
        "malformed_events": event_counters.malformed,
        "duplicate_events_dropped": event_counters.duplicates,
        "orphan_events": orphan_events,
        "unknown_disposition_events": unknown_disposition_events,
    }
    _write_json(staging / "data_quality.json", quality)


def _daily_overview_rows(
    calls_by_lead: dict[int, list[rules.Call]],
    workflow_of_lead: dict[int, str],
    success_codes: dict[str, set[str]],
) -> list[list[str]]:
    """Build daily_overview rows: one per workflow per IST date on which a counted call started."""
    days: dict[tuple[str, str], dict[int, list[rules.Call]]] = defaultdict(lambda: defaultdict(list))
    for lead_id, calls in calls_by_lead.items():
        for call in calls:
            days[(workflow_of_lead[lead_id], rules.ist_date(call.initiated_at))][lead_id].append(call)
    rows = []
    for (workflow_id, date), calls_by_lead_that_day in sorted(days.items()):
        calls = [c for day_calls in calls_by_lead_that_day.values() for c in day_calls]
        connected = sum(c.connected for c in calls)
        success_leads = sum(
            rules.ever_success(day_calls, success_codes[workflow_id])
            for day_calls in calls_by_lead_that_day.values()
        )
        rows.append(
            [
                workflow_id,
                date,
                str(len(calls)),
                str(connected),
                rules.connectivity_rate(connected, len(calls)),
                str(success_leads),
            ]
        )
    return rows


def _ingest_lead_files(store: Store, vault: Vault, catalogue: Catalogue, drop: Path) -> list[FileResult]:
    results = []
    workflow_dirs = sorted(p for p in (drop / "leads").glob("*") if p.is_dir())
    # Resolve every folder first: an unknown workflow aborts before any of its rows are read.
    schemas = {d: catalogue.schema(d.name) for d in workflow_dirs}
    for path in sorted((drop / "leads").glob("*/*.csv")):
        results.append(_ingest_lead_file(store, vault, schemas[path.parent], path))
    return results


def _ingest_lead_file(store: Store, vault: Vault, schema: WorkflowSchema, path: Path) -> FileResult:
    batch_id = path.stem
    content, sha256, skipped = _read_unless_ingested(store, path, "leads")
    if skipped:
        return skipped
    if store.batch_was_ingested(workflow_id=schema.workflow_id, batch_id=batch_id):
        raise DataError(
            f"{path}: batch {schema.workflow_id}/{batch_id} was already ingested with different content"
        )
    rows = rejected = merged = field_warnings = 0
    with io.StringIO(content.decode("utf-8-sig"), newline="") as f:
        reader = csv.reader(f)
        header = next(reader, [])
        try:
            columns = rules.map_headers(header, schema.accepted_headers)
        except DataError as error:
            raise DataError(f"{path}: {error}") from None
        for cells in reader:
            if all(not cell.strip() for cell in cells):
                continue  # blank rows are skipped before row numbering
            rows += 1
            result = rules.validate_row(schema.fields, _row_values(schema, columns, cells))
            if isinstance(result, rules.Rejection):
                rejected += 1
                store.add_rejection(
                    workflow_id=schema.workflow_id,
                    batch_id=batch_id,
                    row_number=rows,
                    reason=result.reason,
                )
                continue
            field_warnings += result.field_warnings
            merged += _merge_or_add_lead(store, vault, schema, result.values, batch_id)
    store.record_lead_file(
        sha256=sha256,
        workflow_id=schema.workflow_id,
        batch_id=batch_id,
        source_path=str(path),
        counters=LeadCounters(rows, rejected, merged, field_warnings),
    )
    counts = {"rows": rows, "rejected": rejected, "merged": merged, "field_warnings": field_warnings}
    return FileResult(path, "leads", "ingested", counts)


def _read_unless_ingested(
    store: Store, path: Path, kind: Literal["leads", "events"]
) -> tuple[bytes, str, FileResult | None]:
    """Return the file's bytes and SHA-256, plus a skipped result if that hash is known (ADR-0005).

    Rows are parsed from these same bytes, so the recorded hash always matches what was ingested.
    """
    content = path.read_bytes()
    sha256 = hashlib.sha256(content).hexdigest()
    same_as = store.ingested_file_path(sha256)
    skipped = FileResult(path, kind, "skipped", same_as=same_as) if same_as is not None else None
    return content, sha256, skipped


def _row_values(schema: WorkflowSchema, columns: dict[str, int], cells: list[str]) -> dict[str, str | None]:
    """Return each schema field's trimmed cell, or None if the column is absent or the cell empty."""
    values: dict[str, str | None] = {}
    for f in schema.fields:
        index = columns.get(f.name)
        cell = cells[index].strip() if index is not None and index < len(cells) else ""
        values[f.name] = cell or None
    return values


def _merge_or_add_lead(
    store: Store, vault: Vault, schema: WorkflowSchema, values: dict[str, str | None], batch_id: str
) -> bool:
    """Store a validated row: a new lead, or a merged duplicate of an existing identity.

    The phone is kept as HMAC, last four and Fernet token, the name as a Fernet token
    (ADR-0003); the reference is a column and the other non-PII fields JSON. Defaults are
    not stored (ADR-0006). Returns True if merged.
    """
    phone = values[schema.phone_field.name]
    reference = schema.reference_field.name
    # The catalogue makes both fields required, so reaching this is a bug, not bad input.
    if phone is None or values[reference] is None:
        raise RuntimeError("validate_row accepted a row without its phone or reference")
    incoming = {f.name: values[f.name] for f in schema.fields if not f.pii}
    name = values[schema.name_field.name] if schema.name_field else None
    name_enc = vault.encrypt(name) if name is not None else None
    phone_hmac = vault.phone_hmac(phone)
    existing = store.find_lead(workflow_id=schema.workflow_id, phone_hmac=phone_hmac)
    if existing is not None:
        incoming = rules.merge_lead_values({reference: existing.external_ref, **existing.fields}, incoming)
    external_ref = incoming.pop(reference)
    assert external_ref is not None
    fields_json = json.dumps(incoming, sort_keys=True)
    if existing is not None:
        store.update_lead(existing.id, external_ref=external_ref, name_enc=name_enc, fields_json=fields_json)
        return True
    store.add_lead(
        workflow_id=schema.workflow_id,
        phone_hmac=phone_hmac,
        phone_last4=vault.last4(phone),
        phone_enc=vault.encrypt(phone),
        name_enc=name_enc,
        external_ref=external_ref,
        batch_id=batch_id,
        fields_json=fields_json,
    )
    return False


def _ingest_event_files(store: Store, vault: Vault, drop: Path) -> list[FileResult]:
    return [_ingest_event_file(store, vault, path) for path in sorted((drop / "events").glob("*.jsonl"))]


def _ingest_event_file(store: Store, vault: Vault, path: Path) -> FileResult:
    """Classify each non-blank line as malformed, duplicate or stored.

    Events are not linked to leads here; that happens at report time (ADR-0002).
    """
    content, sha256, skipped = _read_unless_ingested(store, path, "events")
    if skipped:
        return skipped
    lines = malformed = duplicates = 0
    # Iterate over bytes so a line that is not valid UTF-8 counts as malformed instead of crashing.
    with io.BytesIO(content) as f:
        for line in f:
            if not line.strip():
                continue  # blank lines are not counted
            lines += 1
            parsed = rules.parse_event_line(line)
            if parsed is None:
                # Not stored, so a later well-formed line with the same event_id is not a duplicate.
                malformed += 1
            elif not _append_event(store, vault, parsed):
                duplicates += 1
    store.record_event_file(
        sha256=sha256,
        source_path=str(path),
        counters=EventCounters(lines, malformed, duplicates),
    )
    counts = {"lines": lines, "malformed": malformed, "duplicates": duplicates}
    return FileResult(path, "events", "ingested", counts)


def _append_event(store: Store, vault: Vault, event: rules.ParsedEvent) -> bool:
    """Append the event with its phone as an HMAC only. Return False if it is a duplicate."""
    return store.append_event(
        event_id=event.event_id,
        workflow_id=event.workflow_id,
        call_id=event.call_id,
        event_type=event.event_type,
        occurred_at=event.occurred_at,
        occurred_at_raw=event.occurred_at_raw,
        phone_hmac=vault.phone_hmac(event.phone) if event.phone else None,
        disposition_code=event.disposition_code,
        payload_json=json.dumps(event.payload, sort_keys=True),
    )


def _write_json(path: Path, content: dict[str, Any]) -> None:
    path.write_text(json.dumps(content, indent=2) + "\n", encoding="utf-8")


def _write_csv(path: Path, header: list[str], rows: list[list[str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f, lineterminator="\n")
        writer.writerow(header)
        writer.writerows(rows)
