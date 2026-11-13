"""Properties of the whole pipeline on realistic data.

The provided generator (unmodified) makes the input. These tests check our pipeline, not the
generator. There is no expected output to diff against, so they check properties that must
hold for any seed: re-runs change nothing, drop order doesn't matter, the counts add up, no
PII is stored, and the files follow the output contract.
"""

from __future__ import annotations

import csv
import json
import re
import sqlite3
import subprocess
import sys
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest
from conftest import SCHEMAS

from ledger.pipeline import ingest, report

GENERATOR = SCHEMAS.parent / "tools" / "generate_data.py"
SEEDS = [42, 2026]
REPORT_FILES = [
    "batch_summary.csv",
    "daily_overview.csv",
    "data_quality.json",
    "lead_report.csv",
    "rejections.csv",
]

# The output contract, copied from assignment-a-data/README.md.
CONTRACT_HEADERS = {
    "batch_summary.csv": "workflow_id,batch_id,total_leads,yet_to_reach_out,"
    "in_progress_telephony_failed,in_progress_dialed,completed",
    "daily_overview.csv": "workflow_id,date,total_calls,connected_calls,connectivity_rate,success_leads",
    "lead_report.csv": "workflow_id,external_ref,batch_id,phone_masked,bucket,total_calls,"
    "connected_calls,last_call_at,current_disposition,ever_success",
    "rejections.csv": "workflow_id,batch_id,row_number,reason",
}
CONTRACT_QUALITY_KEYS = [
    "lead_rows_total",
    "lead_rows_rejected",
    "rejections_by_reason",
    "duplicate_lead_rows_merged",
    "field_warnings",
    "events_total",
    "malformed_events",
    "duplicate_events_dropped",
    "orphan_events",
    "unknown_disposition_events",
]
BUCKETS = ["yet_to_reach_out", "in_progress_telephony_failed", "in_progress_dialed", "completed"]


@dataclass
class SeedRuns:
    """One seed's generated drops and the reports from each way of ingesting them."""

    data: Path
    at_once_db: Path  # ingest d1 d2
    stepwise_db: Path  # ingest d1; ingest d2; ingest d1
    at_once: dict[str, bytes]
    drop_by_drop: dict[str, bytes]  # stepwise_db before drop 1 was ingested again
    reingested: dict[str, bytes]


def report_bytes(database: Path, out: Path) -> dict[str, bytes]:
    report(database, out)
    return {p.name: p.read_bytes() for p in sorted(out.iterdir())}


@pytest.fixture(scope="module", params=SEEDS, ids=lambda s: f"seed{s}")
def seed(request: pytest.FixtureRequest, tmp_path_factory: pytest.TempPathFactory) -> SeedRuns:
    root = tmp_path_factory.mktemp(f"seed{request.param}")
    data = root / "data"
    subprocess.run(
        [
            sys.executable,
            str(GENERATOR),
            "--seed",
            str(request.param),
            "--scale",
            "small",
            "--out",
            str(data),
        ],
        check=True,
        capture_output=True,
        timeout=120,
    )
    d1, d2 = data / "drop_1", data / "drop_2"

    # The autouse no_key_env_vars fixture is function-scoped and does not apply to this
    # module-scoped fixture, so clear the key env vars here too.
    with pytest.MonkeyPatch.context() as mp:
        mp.delenv("LEDGER_MATCH_KEY", raising=False)
        mp.delenv("LEDGER_ENC_KEY", raising=False)

        at_once_db = root / "at_once" / "ledger.db"
        at_once_db.parent.mkdir()
        ingest(at_once_db, [d1, d2], SCHEMAS)
        at_once = report_bytes(at_once_db, root / "at_once" / "reports")

        stepwise_db = root / "stepwise" / "ledger.db"
        stepwise_db.parent.mkdir()
        ingest(stepwise_db, [d1], SCHEMAS)
        ingest(stepwise_db, [d2], SCHEMAS)
        drop_by_drop = report_bytes(stepwise_db, root / "stepwise" / "reports")
        ingest(stepwise_db, [d1], SCHEMAS)
        reingested = report_bytes(stepwise_db, root / "stepwise" / "reingested_reports")

    return SeedRuns(data, at_once_db, stepwise_db, at_once, drop_by_drop, reingested)


def csv_rows(content: bytes) -> list[dict[str, str]]:
    return list(csv.DictReader(content.decode("utf-8").splitlines()))


def generated_lead_files(data: Path) -> Iterator[tuple[str, list[str], list[list[str]]]]:
    """Yield (workflow_id, header, data rows) for every generated lead CSV."""
    for path in sorted(data.glob("drop_*/leads/*/*.csv")):
        with path.open(encoding="utf-8-sig", newline="") as f:
            header, *rows = csv.reader(f)
        yield path.parent.name, header, rows


def generated_event_lines(data: Path) -> Iterator[bytes]:
    for path in sorted(data.glob("drop_*/events/*.jsonl")):
        yield from path.read_bytes().splitlines()


def test_reingesting_a_drop_changes_no_report_byte(seed: SeedRuns):
    assert sorted(seed.drop_by_drop) == REPORT_FILES
    assert seed.reingested == seed.drop_by_drop


def test_drop_by_drop_gives_the_same_reports_as_all_at_once(seed: SeedRuns):
    assert seed.drop_by_drop == seed.at_once


def test_counters_add_up(seed: SeedRuns):
    counts = json.loads(seed.at_once["data_quality.json"])
    leads = csv_rows(seed.at_once["lead_report.csv"])
    batches = csv_rows(seed.at_once["batch_summary.csv"])
    non_blank_rows = sum(
        any(cell.strip() for cell in row) for _, _, rows in generated_lead_files(seed.data) for row in rows
    )
    non_empty_lines = sum(bool(line.strip()) for line in generated_event_lines(seed.data))
    # No report shows the stored event count, so it is read from the ledger.
    with sqlite3.connect(seed.at_once_db) as db:
        [(stored_events,)] = db.execute("SELECT count(*) FROM events").fetchall()

    # leads
    assert counts["lead_rows_total"] == non_blank_rows
    assert non_blank_rows == counts["lead_rows_rejected"] + counts["duplicate_lead_rows_merged"] + len(leads)
    assert sum(counts["rejections_by_reason"].values()) == counts["lead_rows_rejected"]
    assert len(csv_rows(seed.at_once["rejections.csv"])) == counts["lead_rows_rejected"]
    assert sum(int(b["total_leads"]) for b in batches) == len(leads)
    for batch in batches:
        assert sum(int(batch[b]) for b in BUCKETS) == int(batch["total_leads"])
    # events
    assert counts["events_total"] == non_empty_lines
    assert non_empty_lines == counts["malformed_events"] + counts["duplicate_events_dropped"] + stored_events


def _normalise_header(header: str) -> str:
    """Apply the README's header rule, written separately so the test does not reuse the code under test."""
    return re.sub(r"[_\s]+", " ", header.strip().lower())


def generated_pii(data: Path) -> set[str]:
    """Return every phone (in each format it was given) and every name the generator wrote."""
    pii_columns: dict[str, dict[str, str]] = {}  # workflow -> normalised header -> field
    for path in SCHEMAS.glob("*.json"):
        schema = json.loads(path.read_text(encoding="utf-8"))
        pii_columns[schema["workflow_id"]] = {
            _normalise_header(name): field["name"]
            for field in schema["fields"]
            if field.get("pii")
            for name in [field["name"], *field.get("aliases", [])]
        }
    names: set[str] = set()
    phones: set[str] = set()
    for workflow_id, header, rows in generated_lead_files(data):
        fields = [pii_columns[workflow_id].get(_normalise_header(h)) for h in header]
        for row in rows:
            for field, value in zip(fields, row, strict=False):
                if field == "customer_name" and value.strip():
                    names.add(value.strip())
                elif field == "phone":
                    phones.add(value)
    for line in generated_event_lines(data):
        try:
            phone = json.loads(line).get("phone")
        except (ValueError, AttributeError):
            continue
        if isinstance(phone, str):
            phones.add(phone)
    for phone in list(phones):
        digits = re.sub(r"\D", "", phone)[-10:]
        if len(digits) == 10:
            phones |= {digits, "+91" + digits}
    # Values this short ("N/A", "") are not phones and would match unrelated bytes.
    return names | {p.strip() for p in phones if sum(c.isdigit() for c in p) >= 9}


def leaks(pii: set[str], blob: bytes) -> list[str]:
    """Return the values of `pii` that occur in `blob`.

    A plain `in` per value over megabytes is slow, so values are first filtered by
    whether their first `n` bytes occur as any `n`-byte window of the blob.
    """
    values = [value.encode("utf-8") for value in pii]
    n = min(map(len, values))
    windows = {blob[i : i + n] for i in range(len(blob) - n + 1)}
    return sorted(value.decode("utf-8") for value in values if value[:n] in windows and value in blob)


def test_no_phone_or_name_is_stored_or_reported(seed: SeedRuns):
    pii = generated_pii(seed.data)
    assert len(pii) > 1000  # guards against a scan that passes because it found nothing to look for

    for database in (seed.at_once_db, seed.stepwise_db):
        # the database file plus any WAL or journal, but not the key file
        files = [p for p in database.parent.iterdir() if p.name.startswith(database.name)]
        stored = b"".join(p.read_bytes() for p in files if not p.name.endswith(".keys.json"))
        assert leaks(pii, stored) == []
    assert leaks(pii, b"".join(seed.at_once.values())) == []


def test_reports_follow_the_output_contract(seed: SeedRuns):
    for name, content in seed.at_once.items():
        content.decode("utf-8")  # raises if not UTF-8
        assert not content.startswith(b"\xef\xbb\xbf"), name
        assert b"\r" not in content, name
        assert content.endswith(b"\n"), name
        assert not content.endswith(b"\n\n"), name
        if name in CONTRACT_HEADERS:
            assert content.split(b"\n", 1)[0].decode() == CONTRACT_HEADERS[name]

    quality_text = seed.at_once["data_quality.json"].decode()
    quality = json.loads(quality_text)
    assert list(quality) == CONTRACT_QUALITY_KEYS
    assert list(quality["rejections_by_reason"]) == sorted(quality["rejections_by_reason"])
    assert quality_text.startswith('{\n  "lead_rows_total": ')  # 2-space indent

    leads = csv_rows(seed.at_once["lead_report.csv"])
    for lead in leads:
        assert re.fullmatch(r"\+91\*{6}\d{4}", lead["phone_masked"])
        assert lead["bucket"] in BUCKETS
        assert lead["ever_success"] in {"true", "false"}
        if lead["total_calls"] != "0":
            assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\+05:30", lead["last_call_at"])
    assert [(r["workflow_id"], r["external_ref"]) for r in leads] == sorted(
        (r["workflow_id"], r["external_ref"]) for r in leads
    )

    days = csv_rows(seed.at_once["daily_overview.csv"])
    for day in days:
        assert re.fullmatch(r"[01]\.\d{4}", day["connectivity_rate"])
    assert [(d["workflow_id"], d["date"]) for d in days] == sorted(
        {(d["workflow_id"], d["date"]) for d in days}
    )

    rejections = csv_rows(seed.at_once["rejections.csv"])
    keys = [(r["workflow_id"], r["batch_id"], int(r["row_number"])) for r in rejections]
    assert keys == sorted(keys)
