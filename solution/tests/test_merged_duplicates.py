"""Merged duplicate leads and stored values, through the pipeline API."""

import json
from pathlib import Path

from conftest import LEAD_HEADER

from ledger.pipeline import ingest, report
from ledger.store import Store


def write_drop(drop: Path, files: dict[str, list[str]]) -> Path:
    """Write a drop with motor_renewal lead files (batch_id → data rows) and no events."""
    folder = drop / "leads" / "motor_renewal"
    folder.mkdir(parents=True)
    for batch_id, rows in files.items():
        (folder / f"{batch_id}.csv").write_text("\r\n".join([LEAD_HEADER, *rows]) + "\r\n", encoding="utf-8")
    (drop / "events").mkdir()
    return drop


def lead_report(out: Path) -> list[list[str]]:
    lines = (out / "lead_report.csv").read_text(encoding="utf-8").splitlines()[1:]
    return [line.split(",") for line in lines]


def quality(out: Path) -> dict:
    return json.loads((out / "data_quality.json").read_text(encoding="utf-8"))


def stored_fields(database: Path) -> list[dict]:
    with Store.open(database) as store:
        return [lead.fields for lead in store.leads()]


def test_same_identity_in_two_batches_is_one_lead_from_the_first_batch(tmp_path: Path, schemas_dir: Path):
    database, out = tmp_path / "ledger.db", tmp_path / "reports"
    drop_1 = write_drop(
        tmp_path / "drop_1",
        {
            "batch_001": ["Aarav Sharma,9876543210,POL-0001,2026-12-01,1500,hi"],
        },
    )
    drop_2 = write_drop(
        tmp_path / "drop_2",
        {
            "batch_002": ["Aarav S,+91 98765 43210,POL-0001,,1800,"],  # same phone, other format
        },
    )

    ingest(database, [drop_1], schemas_dir)
    ingest(database, [drop_2], schemas_dir)
    report(database, out)

    [lead] = lead_report(out)
    assert lead[:3] == ["motor_renewal", "POL-0001", "batch_001"]
    assert stored_fields(database) == [
        {"policy_expiry": "2026-12-01", "premium_amount": "1800.00", "preferred_language": "hi"}
    ]
    assert quality(out)["lead_rows_total"] == 2
    assert quality(out)["duplicate_lead_rows_merged"] == 1


def test_merged_row_that_changes_the_external_reference_moves_the_lead_in_sort_order(
    tmp_path: Path, schemas_dir: Path
):
    database, out = tmp_path / "ledger.db", tmp_path / "reports"
    drop = write_drop(
        tmp_path / "drop_1",
        {
            "batch_001": [
                "Aarav Sharma,9876543210,POL-0001,,,",
                "Diya Patel,9876543211,POL-0002,,,",
            ],
            "batch_002": ["Aarav Sharma,9876543210,POL-0003,,,"],  # Aarav's policy renumbered
        },
    )

    ingest(database, [drop], schemas_dir)
    report(database, out)

    assert [(row[1], row[2], row[3]) for row in lead_report(out)] == [
        ("POL-0002", "batch_001", "+91******3211"),
        ("POL-0003", "batch_001", "+91******3210"),
    ]


def test_rejected_row_with_an_existing_identity_changes_nothing_and_is_not_merged(
    tmp_path: Path, schemas_dir: Path
):
    database, out = tmp_path / "ledger.db", tmp_path / "reports"
    drop = write_drop(
        tmp_path / "drop_1",
        {
            "batch_001": ["Aarav Sharma,9876543210,POL-0001,2026-12-01,1500,hi"],
            "batch_002": [",9876543210,POL-0009,2027-01-01,9999,ta"],  # missing name: rejected
        },
    )

    ingest(database, [drop], schemas_dir)
    report(database, out)

    assert [row[1] for row in lead_report(out)] == ["POL-0001"]
    assert stored_fields(database) == [
        {"policy_expiry": "2026-12-01", "premium_amount": "1500.00", "preferred_language": "hi"}
    ]
    assert quality(out)["lead_rows_rejected"] == 1
    assert quality(out)["duplicate_lead_rows_merged"] == 0
