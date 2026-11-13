"""CLI smoke test: the installed `python -m ledger` entry point, run as a subprocess."""

import os
import subprocess
import sys
from pathlib import Path


def run_ledger(*args: str, cwd: Path, **extra_env: str) -> subprocess.CompletedProcess:
    env = {k: v for k, v in os.environ.items() if not k.startswith("LEDGER_")} | extra_env
    return subprocess.run(
        [sys.executable, "-m", "ledger", *args],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )


def test_ingest_then_report_writes_lead_report(tmp_path: Path, one_call_drop: Path):
    database = tmp_path / "cli.db"

    ingest = run_ledger("--db", str(database), "ingest", str(one_call_drop), cwd=tmp_path)
    assert ingest.returncode == 0, ingest.stderr

    report = run_ledger("--db", str(database), "report", "--out", "reports", cwd=tmp_path)
    assert report.returncode == 0, report.stderr

    lines = (tmp_path / "reports" / "lead_report.csv").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    assert lines[1].startswith("motor_renewal,POL-0001,batch_001,+91******3210,")


def test_data_error_exits_1(tmp_path: Path):
    result = run_ledger("--db", "x.db", "ingest", "no_such_drop", cwd=tmp_path)

    assert result.returncode == 1
    assert "drop directory not found" in result.stderr


def test_usage_error_exits_2(tmp_path: Path):
    result = run_ledger("ingest", cwd=tmp_path)

    assert result.returncode == 2


def test_rerun_reports_each_file_as_skipped_and_exits_0(tmp_path: Path, one_call_drop: Path):
    run_ledger("--db", "cli.db", "ingest", str(one_call_drop), cwd=tmp_path)

    result = run_ledger("--db", "cli.db", "ingest", str(one_call_drop), cwd=tmp_path)

    assert result.returncode == 0, result.stderr
    lead_file = one_call_drop / "leads" / "motor_renewal" / "batch_001.csv"
    event_file = one_call_drop / "events" / "events_0001.jsonl"
    assert result.stdout.splitlines() == [
        f"skipped leads {lead_file} (already ingested from {lead_file})",
        f"skipped events {event_file} (already ingested from {event_file})",
    ]
