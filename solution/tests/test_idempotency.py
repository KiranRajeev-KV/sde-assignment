"""Re-ingesting changes nothing, and a refused or failed run leaves no trace (ADR-0005)."""

import shutil
from pathlib import Path

import pytest
from conftest import LEAD_HEADER, call_events, motor_lead, write_events, write_leads

from ledger import rules
from ledger.errors import DataError
from ledger.pipeline import ingest, report


def messy_drop(drop: Path) -> Path:
    """Write a drop that hits every counter: merged duplicate, rejection, malformed and duplicate event."""
    write_leads(
        drop,
        "motor_renewal",
        "batch_001",
        LEAD_HEADER,
        [
            motor_lead("9876543210", "POL-0001"),
            motor_lead("9876543210", "POL-0001B"),  # merged duplicate
            motor_lead("12345", "POL-0002"),  # invalid phone: rejected
            motor_lead("9876500001", "POL-0003"),
        ],
    )
    lines = call_events("a", "9876543210", "call.connected", "disposition.set", code="RENEWED")
    write_events(drop, [*lines, lines[0], "{not json"])
    return drop


def reports(database: Path, out: Path) -> dict[str, str]:
    """Write the reports and return each file's content by name."""
    report(database, out)
    return {p.name: p.read_text(encoding="utf-8") for p in sorted(out.iterdir())}


def test_a_copy_of_an_ingested_drop_at_another_path_is_fully_skipped(tmp_path, schemas_dir):
    database = tmp_path / "ledger.db"
    drop = messy_drop(tmp_path / "drop_1")
    ingest(database, [drop], schemas_dir)
    before = reports(database, tmp_path / "before")
    copy = shutil.copytree(drop, tmp_path / "elsewhere" / "renamed_drop")

    results = ingest(database, [copy], schemas_dir)

    assert [(r.kind, r.status) for r in results] == [("leads", "skipped"), ("events", "skipped")]
    assert reports(database, tmp_path / "after") == before


def test_a_modified_file_under_a_used_batch_name_refuses_the_whole_invocation(tmp_path, schemas_dir):
    database = tmp_path / "ledger.db"
    ingest(database, [messy_drop(tmp_path / "drop_1")], schemas_dir)
    before = reports(database, tmp_path / "before")
    new_drop = tmp_path / "drop_2"  # valid on its own and passed first, so its rows must be rolled back
    write_leads(new_drop, "motor_renewal", "batch_002", LEAD_HEADER, [motor_lead("9876500002", "POL-0004")])
    write_events(new_drop, call_events("b", "9876500002", "call.connected"))
    corrected = tmp_path / "drop_1_corrected"
    write_leads(corrected, "motor_renewal", "batch_001", LEAD_HEADER, [motor_lead("9876500003", "POL-0005")])

    with pytest.raises(DataError, match="batch motor_renewal/batch_001 was already ingested"):
        ingest(database, [new_drop, corrected], schemas_dir)

    assert reports(database, tmp_path / "after") == before


def test_a_failure_midway_through_an_ingest_leaves_no_rows_from_it(tmp_path, schemas_dir, monkeypatch):
    database = tmp_path / "ledger.db"
    ingest(database, [messy_drop(tmp_path / "drop_1")], schemas_dir)
    before = reports(database, tmp_path / "before")
    drop_2 = tmp_path / "drop_2"
    write_leads(drop_2, "motor_renewal", "batch_002", LEAD_HEADER, [motor_lead("9876500002", "POL-0004")])
    write_events(drop_2, call_events("b", "9876500002", "call.connected", "call.ended"))
    parse = rules.parse_event_line
    parsed_lines = 0

    def crash_on_the_second_line(line: bytes):
        nonlocal parsed_lines
        parsed_lines += 1
        if parsed_lines == 2:  # drop_2's lead and first event are already written by now
            raise RuntimeError("injected crash")
        return parse(line)

    monkeypatch.setattr(rules, "parse_event_line", crash_on_the_second_line)
    with pytest.raises(RuntimeError, match="injected crash"):
        ingest(database, [drop_2], schemas_dir)
    monkeypatch.undo()

    assert reports(database, tmp_path / "after") == before
    # Nothing from the failed run was recorded, so re-running it ingests every file.
    assert [r.status for r in ingest(database, [drop_2], schemas_dir)] == ["ingested", "ingested"]


def test_a_failure_while_writing_reports_leaves_the_previous_reports_in_place(
    tmp_path, schemas_dir, monkeypatch
):
    database = tmp_path / "ledger.db"
    out = tmp_path / "reports"
    ingest(database, [messy_drop(tmp_path / "drop_1")], schemas_dir)
    before = reports(database, out)
    drop_2 = tmp_path / "drop_2"
    write_leads(drop_2, "motor_renewal", "batch_002", LEAD_HEADER, [motor_lead("9876500002", "POL-0004")])
    write_events(drop_2, call_events("b", "9876500002", "call.connected"))
    ingest(database, [drop_2], schemas_dir)

    def crash(*args: object) -> str:
        raise RuntimeError("injected crash")

    # Crash while writing daily_overview.csv, after batch_summary.csv is already staged.
    monkeypatch.setattr(rules, "connectivity_rate", crash)
    with pytest.raises(RuntimeError, match="injected crash"):
        report(database, out)

    assert {p.name: p.read_text(encoding="utf-8") for p in sorted(out.iterdir())} == before
