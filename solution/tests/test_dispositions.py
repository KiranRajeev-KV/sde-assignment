"""Disposition catalogue, overrides linked through call_id, and the effective disposition."""

import json
from pathlib import Path

from conftest import event, lead_rows, orphan_events, write_drop

from ledger.pipeline import ingest, report


def disposition(event_id: str, code: str, *, override: bool = False, **fields: object) -> str:
    """Return a disposition event. An override has no phone, as in the real feed."""
    if override:
        line = json.loads(event(event_id, "disposition.override", **fields))
        del line["phone"]
        line["payload"] = {"disposition_code": code, "overridden_by": "sup_01", "reason": "correction"}
        return json.dumps(line)
    return event(event_id, "disposition.set", payload={"disposition_code": code}, **fields)


def unknown_disposition_events(out: Path) -> int:
    return json.loads((out / "data_quality.json").read_text(encoding="utf-8"))["unknown_disposition_events"]


def test_override_in_a_later_drop_changes_current_disposition(tmp_path: Path, schemas_dir: Path):
    database = tmp_path / "ledger.db"
    drop_1 = write_drop(
        tmp_path / "drop_1",
        [
            event("evt_1", call_id="call_A"),
            event("evt_2", "call.connected", call_id="call_A"),
            disposition("evt_3", "callback_requested", call_id="call_A"),
        ],
    )
    drop_2 = write_drop(
        tmp_path / "drop_2",
        [
            disposition("evt_4", "renewed", override=True, call_id="call_A"),
        ],
        with_lead=False,
    )

    ingest(database, [drop_1], schemas_dir)
    report(database, tmp_path / "after_1")
    ingest(database, [drop_2], schemas_dir)
    report(database, tmp_path / "after_2")

    [lead] = lead_rows(tmp_path / "after_1")
    assert (lead["current_disposition"], lead["ever_success"]) == ("callback_requested", "false")
    [lead] = lead_rows(tmp_path / "after_2")
    assert (lead["current_disposition"], lead["ever_success"]) == ("renewed", "true")
    assert orphan_events(tmp_path / "after_2") == 0


def test_unknown_disposition_events_counts_linked_unknown_codes_and_not_orphan_ones(
    tmp_path: Path, schemas_dir: Path
):
    database, out = tmp_path / "ledger.db", tmp_path / "reports"
    drop = write_drop(
        tmp_path / "drop_1",
        [
            event("evt_1", call_id="call_A"),
            disposition("evt_2", "RENEWD", call_id="call_A"),  # linked, unknown
            disposition("evt_3", "feedback_captured", override=True, call_id="call_A"),  # other workflow's
            disposition("evt_4", "renewed", call_id="call_A"),  # linked, valid
            disposition("evt_5", "RENEWD", call_id="call_B", phone="9123456780"),  # orphan
            disposition("evt_6", "RENEWD", override=True, call_id="call_B"),  # orphan
        ],
    )

    ingest(database, [drop], schemas_dir)
    report(database, out)

    assert unknown_disposition_events(out) == 2
    assert orphan_events(out) == 2
    [lead] = lead_rows(out)
    assert lead["current_disposition"] == "renewed"
