import csv
import json
from pathlib import Path

import pytest

SCHEMAS = Path(__file__).resolve().parents[2] / "assignment-a-data" / "schemas"

LEAD_HEADER = "customer_name,phone,policy_number,policy_expiry,premium_amount,preferred_language"
FEEDBACK_HEADER = "customer_name,phone,order_id,product,order_date,preferred_language"
LEAD_PHONE = "9876543210"
LEAD_NAME = "Aarav Sharma"


@pytest.fixture(autouse=True)
def no_key_env_vars(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ignore the developer's own key env vars: tests use a key file per database unless they set keys."""
    monkeypatch.delenv("LEDGER_MATCH_KEY", raising=False)
    monkeypatch.delenv("LEDGER_ENC_KEY", raising=False)


@pytest.fixture
def schemas_dir() -> Path:
    return SCHEMAS


@pytest.fixture
def one_call_drop(tmp_path: Path) -> Path:
    """A drop with one motor_renewal lead and one call.initiated for its phone."""
    drop = tmp_path / "drop_1"
    leads = drop / "leads" / "motor_renewal"
    leads.mkdir(parents=True)
    (leads / "batch_001.csv").write_text(
        f"{LEAD_HEADER}\r\n{LEAD_NAME},{LEAD_PHONE},POL-0001,2026-12-01,1500,en\r\n",
        encoding="utf-8",
    )
    events = drop / "events"
    events.mkdir()
    event = {
        "event_id": "evt_00000001",
        "event_type": "call.initiated",
        "workflow_id": "motor_renewal",
        "call_id": "call_00000001",
        "occurred_at": "2026-10-05T13:20:21Z",
        "phone": LEAD_PHONE,
        "payload": {},
    }
    (events / "events_0001.jsonl").write_text(json.dumps(event) + "\n", encoding="utf-8")
    return drop


# Helpers for drops with one lead and one event file.


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


def write_drop(drop: Path, events: list[str], *, with_lead: bool = True) -> Path:
    """Write a drop with one event file and, optionally, one motor_renewal lead for LEAD_PHONE."""
    leads = drop / "leads" / "motor_renewal"
    leads.mkdir(parents=True)
    if with_lead:
        (leads / "batch_001.csv").write_text(
            f"{LEAD_HEADER}\r\nAarav Sharma,{LEAD_PHONE},POL-0001,2026-12-01,1500,en\r\n",
            encoding="utf-8",
        )
    (drop / "events").mkdir()
    (drop / "events" / "events_0001.jsonl").write_text("\n".join(events) + "\n", encoding="utf-8")
    return drop


def lead_rows(out: Path) -> list[dict[str, str]]:
    with (out / "lead_report.csv").open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def orphan_events(out: Path) -> int:
    return json.loads((out / "data_quality.json").read_text(encoding="utf-8"))["orphan_events"]


# Helpers for drops with several leads.


def write_leads(drop: Path, workflow_id: str, batch_id: str, header: str, rows: list[str]) -> None:
    leads = drop / "leads" / workflow_id
    leads.mkdir(parents=True, exist_ok=True)
    (leads / f"{batch_id}.csv").write_text("\r\n".join([header, *rows]) + "\r\n", encoding="utf-8")


def write_events(drop: Path, lines: list[str]) -> None:
    (drop / "events").mkdir(parents=True, exist_ok=True)
    (drop / "events" / "events_0001.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")


def motor_lead(phone: str, policy: str) -> str:
    return f"Test Customer,{phone},{policy},2026-12-01,1500,en"


def call_events(prefix: str, phone: str, *types: str, code: str = "") -> list[str]:
    """Return a call.initiated for `phone`, then one event per entry in `types` on the same call."""
    lines = [event(f"evt_{prefix}_0", call_id=f"call_{prefix}", phone=phone)]
    for n, event_type in enumerate(types, start=1):
        payload = {"disposition_code": code} if event_type == "disposition.set" else {}
        lines.append(
            event(
                f"evt_{prefix}_{n}",
                event_type,
                call_id=f"call_{prefix}",
                phone=phone,
                payload=payload,
            )
        )
    return lines
