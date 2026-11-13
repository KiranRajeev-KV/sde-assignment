"""Event lines classified, counted and stored in the append-only ledger."""

import csv
import json
import sqlite3
from pathlib import Path

import pytest
from conftest import LEAD_HEADER, LEAD_PHONE

from ledger.pipeline import ingest, report


def event(event_id: str, event_type: str = "call.initiated", **overrides: object) -> str:
    """Return one well-formed event line for LEAD_PHONE; `overrides` replace or add keys."""
    fields: dict[str, object] = {
        "event_id": event_id,
        "event_type": event_type,
        "workflow_id": "motor_renewal",
        "call_id": f"call_{event_id}",
        "occurred_at": "2026-10-05T13:20:21Z",
        "phone": LEAD_PHONE,
        "payload": {},
    }
    fields.update(overrides)
    return json.dumps(fields)


def write_drop(drop: Path, events: dict[str, list[str]], *, with_lead: bool = True) -> Path:
    """Write a drop with event files (file name → lines) and, optionally, one lead for LEAD_PHONE."""
    leads = drop / "leads" / "motor_renewal"
    leads.mkdir(parents=True)
    if with_lead:
        (leads / "batch_001.csv").write_text(
            f"{LEAD_HEADER}\r\nAarav Sharma,{LEAD_PHONE},POL-0001,2026-12-01,1500,en\r\n",
            encoding="utf-8",
        )
    (drop / "events").mkdir()
    for name, lines in events.items():
        (drop / "events" / name).write_text("\n".join(lines) + "\n", encoding="utf-8")
    return drop


def event_counters(out: Path) -> tuple[int, int, int]:
    quality = json.loads((out / "data_quality.json").read_text(encoding="utf-8"))
    return quality["events_total"], quality["malformed_events"], quality["duplicate_events_dropped"]


def total_calls(out: Path) -> int:
    with (out / "lead_report.csv").open(encoding="utf-8", newline="") as f:
        [row] = csv.DictReader(f)
    return int(row["total_calls"])


def test_each_kind_of_line_is_counted_once_as_total_malformed_or_duplicate(tmp_path: Path, schemas_dir: Path):
    database, out = tmp_path / "ledger.db", tmp_path / "reports"
    first = event("evt_1")
    drop = write_drop(
        tmp_path / "drop_1",
        {
            "events_0001.jsonl": [
                first,
                event("evt_2"),
                first[:25],  # truncated line
                "[" + first + "]",  # a JSON array, not an object
                json.dumps({"event_type": "call.initiated", "workflow_id": "motor_renewal"}),  # no event_id
                event("evt_3", "call.exploded"),  # unknown event_type
                "   ",  # whitespace only: ignored, not counted
                "",
                first,  # in-file duplicate
            ]
        },
    )

    ingest(database, [drop], schemas_dir)
    report(database, out)

    assert event_counters(out) == (7, 4, 1)
    assert total_calls(out) == 2


def test_event_redelivered_in_a_later_drop_is_counted_as_a_duplicate(tmp_path: Path, schemas_dir: Path):
    database, out = tmp_path / "ledger.db", tmp_path / "reports"
    drop_1 = write_drop(tmp_path / "drop_1", {"events_0001.jsonl": [event("evt_1")]})
    drop_2 = write_drop(
        tmp_path / "drop_2",
        {
            "events_1001.jsonl": [
                event("evt_1", occurred_at="2026-10-06T09:00:00Z"),  # same id, other content: first copy wins
            ]
        },
        with_lead=False,
    )

    ingest(database, [drop_1], schemas_dir)
    ingest(database, [drop_2], schemas_dir)
    report(database, out)

    assert event_counters(out) == (2, 0, 1)
    assert total_calls(out) == 1
    assert "2026-10-05T18:50:21+05:30" in (out / "lead_report.csv").read_text(encoding="utf-8")


def test_malformed_line_does_not_reserve_its_event_id(tmp_path: Path, schemas_dir: Path):
    database, out = tmp_path / "ledger.db", tmp_path / "reports"
    drop = write_drop(
        tmp_path / "drop_1",
        {
            "events_0001.jsonl": [
                event("evt_1", occurred_at="yesterday"),  # malformed
                event("evt_1"),  # the well-formed copy is stored, not a duplicate
            ]
        },
    )

    ingest(database, [drop], schemas_dir)
    report(database, out)

    assert event_counters(out) == (2, 1, 0)
    assert total_calls(out) == 1


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE events SET occurred_at = '2026-10-06T00:00:00Z'",
        "DELETE FROM events",
    ],
)
def test_ledger_refuses_update_and_delete_at_the_database_level(
    tmp_path: Path, schemas_dir: Path, statement: str
):
    database, out = tmp_path / "ledger.db", tmp_path / "reports"
    ingest(database, [write_drop(tmp_path / "drop_1", {"events_0001.jsonl": [event("evt_1")]})], schemas_dir)

    connection = sqlite3.connect(database)
    with pytest.raises(sqlite3.DatabaseError, match="append-only"):
        connection.execute(statement)
    connection.close()

    report(database, out)
    assert total_calls(out) == 1
