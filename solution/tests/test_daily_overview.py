"""daily_overview.csv: one row per workflow per IST date with a counted call."""

from pathlib import Path

from conftest import LEAD_HEADER, event, motor_lead, write_events, write_leads

from ledger.pipeline import ingest, report

DAILY_OVERVIEW_HEADER = "workflow_id,date,total_calls,connected_calls,connectivity_rate,success_leads"


def daily_overview(tmp_path: Path, schemas_dir: Path, drop: Path) -> bytes:
    ingest(tmp_path / "ledger.db", [drop], schemas_dir)
    report(tmp_path / "ledger.db", tmp_path / "out")
    return (tmp_path / "out" / "daily_overview.csv").read_bytes()


def disposition_set(event_id: str, call_id: str, code: str, at: str, phone: str) -> str:
    return event(
        event_id,
        "disposition.set",
        call_id=call_id,
        occurred_at=at,
        phone=phone,
        payload={"disposition_code": code},
    )


def disposition_override(event_id: str, call_id: str, code: str, at: str) -> str:
    """Return an override event. Like the real feed, it has no phone and links through its call."""
    return event(
        event_id,
        "disposition.override",
        call_id=call_id,
        occurred_at=at,
        phone=None,
        payload={"disposition_code": code},
    )


def test_a_call_counts_on_the_ist_date_it_was_initiated(tmp_path: Path, schemas_dir: Path):
    drop = tmp_path / "drop_1"
    phone = "9000000001"
    write_leads(drop, "motor_renewal", "batch_001", LEAD_HEADER, [motor_lead(phone, "POL-1")])
    write_events(
        drop,
        [
            # starts 23:59 IST on 5 Oct, connects 00:01 IST on 6 Oct: counts on 5 Oct
            event("evt_1", call_id="call_1", occurred_at="2026-10-05T18:29:00Z", phone=phone),
            event(
                "evt_2", "call.connected", call_id="call_1", occurred_at="2026-10-05T18:31:00Z", phone=phone
            ),
            # 19:00 UTC on 5 Oct is 00:30 IST on 6 Oct
            event("evt_3", call_id="call_2", occurred_at="2026-10-05T19:00:00Z", phone=phone),
            # a naive timestamp is already IST
            event("evt_4", call_id="call_3", occurred_at="2026-10-06 23:30:00", phone=phone),
            event(
                "evt_5", "call.connected", call_id="call_3", occurred_at="2026-10-06 23:31:00", phone=phone
            ),
        ],
    )

    assert (
        daily_overview(tmp_path, schemas_dir, drop)
        == (
            f"{DAILY_OVERVIEW_HEADER}\n"
            "motor_renewal,2026-10-05,1,1,1.0000,0\n"
            "motor_renewal,2026-10-06,2,1,0.5000,0\n"
        ).encode()
    )


def test_success_leads_counts_distinct_leads_with_a_success_on_that_date(tmp_path: Path, schemas_dir: Path):
    drop = tmp_path / "drop_1"
    a, b, c = "9000000001", "9000000002", "9000000003"
    write_leads(
        drop,
        "motor_renewal",
        "batch_001",
        LEAD_HEADER,
        [
            motor_lead(a, "POL-A"),
            motor_lead(b, "POL-B"),
            motor_lead(c, "POL-C"),
        ],
    )
    oct_5, oct_6 = "2026-10-05T06:00:00Z", "2026-10-06T06:00:00Z"
    write_events(
        drop,
        [
            # A: two successful calls on 5 Oct count once
            event("evt_a1", call_id="call_a1", occurred_at=oct_5, phone=a),
            disposition_set("evt_a1d", "call_a1", "renewed", oct_5, a),
            event("evt_a2", call_id="call_a2", occurred_at=oct_5, phone=a),
            disposition_set("evt_a2d", "call_a2", "renewed", oct_5, a),
            # B: not_interested on 5 Oct, overridden to renewed on 6 Oct: counts on the call's date
            event("evt_b1", call_id="call_b1", occurred_at=oct_5, phone=b),
            disposition_set("evt_b1d", "call_b1", "not_interested", oct_5, b),
            disposition_override("evt_b1o", "call_b1", "renewed", oct_6),
            # C: a non-success call on 5 Oct, its success on 6 Oct
            event("evt_c1", call_id="call_c1", occurred_at=oct_5, phone=c),
            disposition_set("evt_c1d", "call_c1", "callback_requested", oct_5, c),
            event("evt_c2", call_id="call_c2", occurred_at=oct_6, phone=c),
            disposition_set("evt_c2d", "call_c2", "renewed", oct_6, c),
        ],
    )

    assert (
        daily_overview(tmp_path, schemas_dir, drop)
        == (
            f"{DAILY_OVERVIEW_HEADER}\n"
            "motor_renewal,2026-10-05,4,0,0.0000,2\n"
            "motor_renewal,2026-10-06,1,0,0.0000,1\n"
        ).encode()
    )
