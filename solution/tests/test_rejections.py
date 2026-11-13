"""Rejections, field warnings and the lead counters, through the pipeline API."""

import json
from pathlib import Path

import pytest
from conftest import LEAD_HEADER

from ledger.pipeline import ingest, report

FEEDBACK_HEADER_WITHOUT_PHONE = "customer_name,order_id,product,order_date,preferred_language"


def write_lead_file(drop: Path, workflow_id: str, batch_id: str, lines: list[str]) -> None:
    folder = drop / "leads" / workflow_id
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{batch_id}.csv").write_text("\r\n".join(lines) + "\r\n", encoding="utf-8")


@pytest.fixture
def mixed_drops(tmp_path: Path) -> list[Path]:
    """Return two drops; drop_1 holds batch_002, so ingest order differs from sort order."""
    drop_1, drop_2 = tmp_path / "drop_1", tmp_path / "drop_2"

    # motor_renewal/batch_002: 10 rows, rows 2 and 10 rejected. Row 10 checks numeric sorting (10 after 2).
    batch_002 = [LEAD_HEADER]
    for row in range(1, 11):
        phone = f"98000000{row:02d}"
        if row == 2:
            phone = "+1 415 555 0134"
        premium = "-" if row == 5 else "1500"  # row 5: one field warning
        name = "Rejected Rohan" if row == 10 else f"Lead {row}"
        ref = "" if row == 10 else f"POL-2{row:02d}"
        batch_002.append(f"{name},{phone},{ref},2026-12-01,{premium},en")
    write_lead_file(drop_1, "motor_renewal", "batch_002", batch_002)
    events = drop_1 / "events"
    events.mkdir()
    (events / "events_0001.jsonl").write_text("", encoding="utf-8")

    write_lead_file(
        drop_2,
        "motor_renewal",
        "batch_001",
        [
            LEAD_HEADER,
            "Aarav Sharma,9876543210,POL-0001,soon,twelve thousand,en",  # 2 field warnings
            "   ,9876543211,POL-REJ-1,TBD,N/A,en",  # missing name; its warnings are not counted
            "Rejected Ishaan,N/A,POL-REJ-2,2026-12-01,1500,en",  # invalid phone
            ",,,,,",  # blank row: skipped, not numbered
            "Diya Patel,+91 98765 43212,POL-0004,01-Dec-2026,Rs. 1500,Hindi",  # 1 field warning
            "Rejected Kavya,9876543213,,2026-12-01,1500,hi",  # missing policy number
        ],
    )
    # A file with no phone column: every row is missing_required:phone.
    write_lead_file(
        drop_2,
        "policy_feedback",
        "batch_001",
        [
            FEEDBACK_HEADER_WITHOUT_PHONE,
            "Rejected Meera,ORD-REJ-1,Phone Case,31/02/2026,en",
            "Rejected Rohan,ORD-REJ-2,Screen Guard,2026-09-01,xx",
        ],
    )
    events = drop_2 / "events"
    events.mkdir()
    (events / "events_1001.jsonl").write_text("", encoding="utf-8")
    return [drop_1, drop_2]


def test_mixed_files_give_exact_rejections_and_lead_counters(
    tmp_path: Path, mixed_drops: list[Path], schemas_dir: Path
):
    database = tmp_path / "ledger.db"
    out = tmp_path / "reports"

    for drop in mixed_drops:  # separate runs, so the counters must sum across runs
        ingest(database, [drop], schemas_dir)
    report(database, out)

    assert (out / "rejections.csv").read_bytes() == (
        b"workflow_id,batch_id,row_number,reason\n"
        b"motor_renewal,batch_001,2,missing_required:customer_name\n"
        b"motor_renewal,batch_001,3,invalid_phone\n"
        b"motor_renewal,batch_001,5,missing_required:policy_number\n"
        b"motor_renewal,batch_002,2,invalid_phone\n"
        b"motor_renewal,batch_002,10,missing_required:policy_number\n"
        b"policy_feedback,batch_001,1,missing_required:phone\n"
        b"policy_feedback,batch_001,2,missing_required:phone\n"
    )
    quality_text = (out / "data_quality.json").read_text(encoding="utf-8")
    quality = json.loads(quality_text)
    assert quality["lead_rows_total"] == 17
    assert quality["lead_rows_rejected"] == 7
    assert quality["field_warnings"] == 4
    assert quality["rejections_by_reason"] == {
        "invalid_phone": 2,
        "missing_required:customer_name": 1,
        "missing_required:phone": 2,
        "missing_required:policy_number": 2,
    }
    assert list(quality["rejections_by_reason"]) == sorted(quality["rejections_by_reason"])
    assert list(quality)[:3] == ["lead_rows_total", "lead_rows_rejected", "rejections_by_reason"]
    assert quality_text.endswith("}\n")
