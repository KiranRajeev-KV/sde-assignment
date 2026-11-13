"""PII at rest (ADR-0003) and key resolution (ADR-0004)."""

import json
import sqlite3
from pathlib import Path

import pytest
from conftest import LEAD_HEADER, LEAD_PHONE, write_events, write_leads
from cryptography.fernet import Fernet

from ledger.errors import DataError
from ledger.pipeline import ingest, report

MATCH_KEY = "test-match-key"
ENC_KEY = Fernet.generate_key().decode()


def test_encrypted_phone_and_name_decrypt_to_canonical_phone_and_trimmed_name(
    tmp_path: Path, schemas_dir: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv("LEDGER_MATCH_KEY", MATCH_KEY)
    monkeypatch.setenv("LEDGER_ENC_KEY", ENC_KEY)
    drop = tmp_path / "drop_1"
    write_leads(
        drop,
        "motor_renewal",
        "batch_001",
        LEAD_HEADER,
        [
            f"  Aarav Sharma  ,+91 {LEAD_PHONE[:5]} {LEAD_PHONE[5:]},POL-0001,2026-12-01,1500,en",
        ],
    )
    write_events(drop, [])
    database = tmp_path / "ledger.db"

    ingest(database, [drop], schemas_dir)

    with sqlite3.connect(database) as db:
        [(phone_enc, name_enc)] = db.execute("SELECT phone_enc, name_enc FROM leads").fetchall()
    fernet = Fernet(ENC_KEY.encode())
    assert fernet.decrypt(phone_enc).decode() == "+919876543210"
    assert fernet.decrypt(name_enc).decode() == "Aarav Sharma"


def test_a_new_database_without_key_env_vars_gets_an_owner_only_key_file(
    tmp_path: Path, one_call_drop: Path, schemas_dir: Path, capsys: pytest.CaptureFixture[str]
):
    database = tmp_path / "ledger.db"

    ingest(database, [one_call_drop], schemas_dir)

    key_file = tmp_path / "ledger.db.keys.json"
    assert key_file.stat().st_mode & 0o777 == 0o600
    keys = json.loads(key_file.read_text(encoding="utf-8"))
    with sqlite3.connect(database) as db:
        [phone_enc] = db.execute("SELECT phone_enc FROM leads").fetchone()
    assert Fernet(keys["enc_key"].encode()).decrypt(phone_enc).decode() == "+91" + LEAD_PHONE
    assert keys["match_key"] != keys["enc_key"]
    assert "warning" in capsys.readouterr().err


def test_an_existing_database_whose_key_file_was_deleted_is_refused(
    tmp_path: Path, one_call_drop: Path, schemas_dir: Path
):
    database = tmp_path / "ledger.db"
    ingest(database, [one_call_drop], schemas_dir)
    (tmp_path / "ledger.db.keys.json").unlink()

    with pytest.raises(DataError, match=r"exists but its keys were not found.*LEDGER_MATCH_KEY"):
        report(database, tmp_path / "reports")
    with pytest.raises(DataError, match="exists but its keys were not found"):
        ingest(database, [one_call_drop], schemas_dir)
    assert not (tmp_path / "ledger.db.keys.json").exists()
    assert not (tmp_path / "reports").exists()


@pytest.mark.parametrize(
    ("env_var", "other_key"),
    [
        ("LEDGER_MATCH_KEY", "a-different-match-key"),
        ("LEDGER_ENC_KEY", Fernet.generate_key().decode()),
    ],
)
def test_a_key_other_than_the_databases_is_refused_by_fingerprint(
    tmp_path: Path,
    one_call_drop: Path,
    schemas_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    env_var: str,
    other_key: str,
):
    monkeypatch.setenv("LEDGER_MATCH_KEY", MATCH_KEY)
    monkeypatch.setenv("LEDGER_ENC_KEY", ENC_KEY)
    database = tmp_path / "ledger.db"
    ingest(database, [one_call_drop], schemas_dir)
    before = database.read_bytes()
    monkeypatch.setenv(env_var, other_key)

    with pytest.raises(DataError, match="fingerprint mismatch"):
        ingest(database, [one_call_drop], schemas_dir)
    with pytest.raises(DataError, match="fingerprint mismatch"):
        report(database, tmp_path / "reports")
    assert database.read_bytes() == before
    assert not (tmp_path / "reports").exists()
