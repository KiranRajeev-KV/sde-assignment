"""Lead files with renamed, re-ordered or extra columns, BOMs and blank rows."""

from pathlib import Path

import pytest

from ledger.errors import DataError
from ledger.pipeline import ingest, report

REPORT_HEADER = (
    b"workflow_id,external_ref,batch_id,phone_masked,bucket,total_calls,"
    b"connected_calls,last_call_at,current_disposition,ever_success\n"
)


def lead_drop(root: Path, name: str, files: dict[str, bytes]) -> Path:
    """Write a drop holding only lead files, keyed by `<workflow>/<batch>.csv`."""
    drop = root / name
    for relative, content in files.items():
        path = drop / "leads" / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    return drop


def lead_report(tmp_path: Path, database: Path) -> bytes:
    out = tmp_path / "reports"
    report(database, out)
    return (out / "lead_report.csv").read_bytes()


def test_batch_with_aliased_reordered_and_extra_columns_loads(tmp_path: Path, schemas_dir: Path):
    drop = lead_drop(
        tmp_path,
        "drop_2",
        {
            "motor_renewal/batch_003.csv": (
                b"Language,Insured Name,Policy No,Mobile No,Expiry Date,Premium,agent_notes\r\n"
                b"hi,Aarav Sharma,POL-0003,98765 43210,2026-12-01,1500,VIP\r\n"
                b"en,Diya Patel,POL-0004,+91 91234 56789,2026-11-15,2200,\r\n"
            ),
            "policy_feedback/batch_003.csv": (
                b"Order ID,Name,Contact,Product,Order Date,Language,agent_notes\r\n"
                b"ORD-0007,Kabir Rao,08123456789,Phone case,2026-09-30,ta,\r\n"
            ),
        },
    )
    database = tmp_path / "ledger.db"

    ingest(database, [drop], schemas_dir)

    assert lead_report(tmp_path, database) == REPORT_HEADER + (
        b"motor_renewal,POL-0003,batch_003,+91******3210,yet_to_reach_out,0,0,,,false\n"
        b"motor_renewal,POL-0004,batch_003,+91******6789,yet_to_reach_out,0,0,,,false\n"
        b"policy_feedback,ORD-0007,batch_003,+91******6789,yet_to_reach_out,0,0,,,false\n"
    )


BOM = b"\xef\xbb\xbf"
MOTOR_HEADER = b"customer_name,phone,policy_number,policy_expiry,premium_amount,preferred_language\r\n"


def test_file_with_bom_and_blank_rows_loads_without_counting_them(tmp_path: Path, schemas_dir: Path):
    drop = lead_drop(
        tmp_path,
        "drop_1",
        {
            "motor_renewal/batch_001.csv": BOM
            + MOTOR_HEADER
            + (
                b"Aarav Sharma,9876543210,POL-0001,2026-12-01,1500,en\r\n"
                b",,,,,\r\n"
                b"  , ,\t,,,\r\n"
                b"\r\n"
                b"Diya Patel,9123456789,POL-0002,2026-11-15,2200,hi\r\n"
                b",,,,,\r\n"
            ),
        },
    )
    database = tmp_path / "ledger.db"

    [result] = ingest(database, [drop], schemas_dir)

    assert result.counts["rows"] == 2
    assert lead_report(tmp_path, database) == REPORT_HEADER + (
        b"motor_renewal,POL-0001,batch_001,+91******3210,yet_to_reach_out,0,0,,,false\n"
        b"motor_renewal,POL-0002,batch_001,+91******6789,yet_to_reach_out,0,0,,,false\n"
    )


GOOD_BATCH = MOTOR_HEADER + b"Aarav Sharma,9876543210,POL-0001,2026-12-01,1500,en\r\n"
GOOD_REPORT = REPORT_HEADER + (
    b"motor_renewal,POL-0001,batch_001,+91******3210,yet_to_reach_out,0,0,,,false\n"
)


def test_clashing_headers_fail_the_ingest_and_leave_the_database_unchanged(tmp_path: Path, schemas_dir: Path):
    database = tmp_path / "ledger.db"
    ingest(
        database, [lead_drop(tmp_path, "drop_1", {"motor_renewal/batch_001.csv": GOOD_BATCH})], schemas_dir
    )
    drop_2 = lead_drop(
        tmp_path,
        "drop_2",
        {
            "motor_renewal/batch_002.csv": MOTOR_HEADER + b"Diya Patel,9123456789,POL-0002,,,\r\n",
            "motor_renewal/batch_003.csv": (
                b"Insured Name,phone,Mobile No,Policy No\r\nKabir Rao,9012345678,9012345678,POL-0003\r\n"
            ),
        },
    )

    with pytest.raises(DataError) as error:
        ingest(database, [drop_2], schemas_dir)

    assert "'phone'" in str(error.value)
    assert "'Mobile No'" in str(error.value)
    assert "batch_003.csv" in str(error.value)
    assert lead_report(tmp_path, database) == GOOD_REPORT


def test_lead_folder_with_unknown_workflow_fails_the_ingest_and_leaves_the_database_unchanged(
    tmp_path: Path, schemas_dir: Path
):
    database = tmp_path / "ledger.db"
    ingest(
        database, [lead_drop(tmp_path, "drop_1", {"motor_renewal/batch_001.csv": GOOD_BATCH})], schemas_dir
    )
    drop_2 = lead_drop(
        tmp_path,
        "drop_2",
        {
            "motor_renewal/batch_002.csv": MOTOR_HEADER + b"Diya Patel,9123456789,POL-0002,,,\r\n",
            "travel_upsell/batch_002.csv": b"name,phone,booking\r\nKabir Rao,9012345678,BK-1\r\n",
        },
    )

    with pytest.raises(DataError, match="travel_upsell"):
        ingest(database, [drop_2], schemas_dir)

    assert lead_report(tmp_path, database) == GOOD_REPORT
