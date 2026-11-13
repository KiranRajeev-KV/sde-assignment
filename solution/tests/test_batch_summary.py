"""Each lead's bucket, and the batch_summary.csv counts per workflow and batch."""

from pathlib import Path

from conftest import (
    FEEDBACK_HEADER,
    LEAD_HEADER,
    call_events,
    lead_rows,
    motor_lead,
    write_events,
    write_leads,
)

from ledger.pipeline import ingest, report

BATCH_SUMMARY_HEADER = (
    "workflow_id,batch_id,total_leads,yet_to_reach_out,in_progress_telephony_failed,"
    "in_progress_dialed,completed"
)


def batch_summary(out: Path) -> bytes:
    return (out / "batch_summary.csv").read_bytes()


def test_batch_summary_counts_each_bucket_per_workflow_and_batch(tmp_path: Path, schemas_dir: Path):
    drop = tmp_path / "drop_1"
    # batch_002 is written first to show the summary is sorted, not in ingestion order.
    write_leads(
        drop,
        "motor_renewal",
        "batch_002",
        LEAD_HEADER,
        [
            motor_lead("9000000004", "POL-4"),  # dialled, no outcome
            motor_lead("9000000005", "POL-5"),  # one failed call, one not: dialled
            motor_lead("9000000006", "POL-6"),  # failed, then a terminal outcome on another call
        ],
    )
    write_leads(
        drop,
        "motor_renewal",
        "batch_001",
        LEAD_HEADER,
        [
            motor_lead("9000000001", "POL-1"),  # no calls
            motor_lead("9000000002", "POL-2"),  # renewed
            motor_lead("9000000003", "POL-3"),  # every call failed
            motor_lead("9000000007", "POL-7"),  # non-terminal outcome
        ],
    )
    write_leads(
        drop,
        "policy_feedback",
        "batch_001",
        FEEDBACK_HEADER,
        [
            "Test Customer,9000000008,ORD-8,,,",  # no calls
        ],
    )
    write_events(
        drop,
        [
            *call_events("2", "9000000002", "call.connected", "disposition.set", code="renewed"),
            *call_events("3a", "9000000003", "call.telephony_failed"),
            *call_events("3b", "9000000003", "call.telephony_failed"),
            *call_events("4", "9000000004", "call.connected"),
            *call_events("5a", "9000000005", "call.telephony_failed"),
            *call_events("5b", "9000000005"),
            *call_events("6a", "9000000006", "call.telephony_failed"),
            *call_events("6b", "9000000006", "call.connected", "disposition.set", code="not_interested"),
            *call_events("7", "9000000007", "call.connected", "disposition.set", code="callback_requested"),
        ],
    )

    ingest(tmp_path / "ledger.db", [drop], schemas_dir)
    report(tmp_path / "ledger.db", tmp_path / "out")

    assert (
        batch_summary(tmp_path / "out")
        == (
            f"{BATCH_SUMMARY_HEADER}\n"
            "motor_renewal,batch_001,4,1,1,1,1\n"
            "motor_renewal,batch_002,3,0,0,2,1\n"
            "policy_feedback,batch_001,1,1,0,0,0\n"
        ).encode()
    )
    buckets = {row["external_ref"]: row["bucket"] for row in lead_rows(tmp_path / "out")}
    assert buckets == {
        "POL-1": "yet_to_reach_out",
        "POL-2": "completed",
        "POL-3": "in_progress_telephony_failed",
        "POL-4": "in_progress_dialed",
        "POL-5": "in_progress_dialed",
        "POL-6": "completed",
        "POL-7": "in_progress_dialed",
        "ORD-8": "yet_to_reach_out",
    }
    for line in batch_summary(tmp_path / "out").decode().splitlines()[1:]:
        total, *bucket_counts = map(int, line.split(",")[2:])
        assert sum(bucket_counts) == total
