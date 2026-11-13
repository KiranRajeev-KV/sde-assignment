"""Events linked to leads at report time: counted calls and orphans."""

from pathlib import Path

from conftest import event, lead_rows, orphan_events, write_drop

from ledger.pipeline import ingest, report


def test_orphan_from_drop_1_counts_towards_its_lead_once_it_arrives_in_drop_2(
    tmp_path: Path, schemas_dir: Path
):
    database = tmp_path / "ledger.db"
    drop_1 = write_drop(
        tmp_path / "drop_1",
        [
            event("evt_1"),
            event("evt_2", "call.connected", call_id="call_evt_1"),
        ],
        with_lead=False,
    )
    drop_2 = write_drop(tmp_path / "drop_2", [event("evt_3", phone="+91 77187 50036")])

    ingest(database, [drop_1], schemas_dir)
    report(database, tmp_path / "after_1")
    ingest(database, [drop_2], schemas_dir)
    report(database, tmp_path / "after_2")

    assert lead_rows(tmp_path / "after_1") == []
    assert orphan_events(tmp_path / "after_1") == 2
    [lead] = lead_rows(tmp_path / "after_2")
    assert (lead["total_calls"], lead["connected_calls"]) == ("1", "1")
    assert orphan_events(tmp_path / "after_2") == 1  # only drop 2's never-uploaded number


def test_events_with_invalid_phone_unknown_number_or_unknown_workflow_are_orphans(
    tmp_path: Path, schemas_dir: Path
):
    database, out = tmp_path / "ledger.db", tmp_path / "reports"
    drop = write_drop(
        tmp_path / "drop_1",
        [
            event("evt_1", phone="N/A"),  # invalid phone: stored without one
            event("evt_2", phone="9123456780"),  # valid, but never uploaded
            event("evt_3", workflow_id="travel_insurance"),  # the lead's phone, an unknown workflow
            event("evt_4", "call.ended", call_id="call_evt_3", workflow_id="travel_insurance"),
            event("evt_5"),  # linked
        ],
    )

    ingest(database, [drop], schemas_dir)
    report(database, out)

    assert orphan_events(out) == 4
    [lead] = lead_rows(out)
    assert lead["total_calls"] == "1"


def test_call_whose_events_carry_the_phone_in_different_formats_is_one_counted_call(
    tmp_path: Path, schemas_dir: Path
):
    database, out = tmp_path / "ledger.db", tmp_path / "reports"
    drop = write_drop(
        tmp_path / "drop_1",
        [
            event("evt_1", call_id="call_A", phone="+91 98765 43210"),
            event("evt_2", "call.connected", call_id="call_A", phone="098765-43210"),
            event("evt_3", "call.ended", call_id="call_A", phone="919876543210"),
        ],
    )

    ingest(database, [drop], schemas_dir)
    report(database, out)

    [lead] = lead_rows(out)
    assert (lead["total_calls"], lead["connected_calls"]) == ("1", "1")
    assert orphan_events(out) == 0


def test_call_without_initiated_adds_no_call_and_its_events_are_not_orphans(
    tmp_path: Path, schemas_dir: Path
):
    database, out = tmp_path / "ledger.db", tmp_path / "reports"
    drop = write_drop(
        tmp_path / "drop_1",
        [
            event("evt_1", "call.connected", call_id="call_A"),
            event("evt_2", "call.ended", call_id="call_A"),
        ],
    )

    ingest(database, [drop], schemas_dir)
    report(database, out)

    [lead] = lead_rows(out)
    assert (lead["total_calls"], lead["connected_calls"], lead["last_call_at"]) == ("0", "0", "")
    assert orphan_events(out) == 0
