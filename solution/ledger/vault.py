"""PII vault: keyed HMAC for matching, Fernet for recovery (ADR-0003, ADR-0004).

Two independent keys. The match key makes the phone HMAC that leads and events
join on; the encryption key encrypts the full phone and name. Each key comes
from its environment variable, else from `<db path>.keys.json`, which is
created (owner-only, with a warning) only for a new database. An existing
database with no keys found is refused. Each key's fingerprint is stored in the
database and checked on every run, so a different key is refused rather than
silently orphaning every earlier event.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import sys
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

from ledger.errors import DataError

MATCH_KEY_ENV = "LEDGER_MATCH_KEY"
ENC_KEY_ENV = "LEDGER_ENC_KEY"
_KEY_ENTRIES = {"match_key": MATCH_KEY_ENV, "enc_key": ENC_KEY_ENV}  # key file entry -> env var
_KEY_NAMES = {"match_key": "match key", "enc_key": "encryption key"}

# A fingerprint is an HMAC of this constant under the key: it identifies the key without revealing it.
_FINGERPRINT_MESSAGE = b"ledger key fingerprint v1"


def key_file_for(database: Path) -> Path:
    return database.with_name(database.name + ".keys.json")


class Vault:
    def __init__(self, match_key: bytes, enc_key: bytes):
        if not match_key:
            raise DataError("the match key is empty")
        try:
            self._fernet = Fernet(enc_key)
        except (ValueError, TypeError):
            raise DataError(
                "the encryption key is not a valid Fernet key (32 url-safe base64-encoded bytes);"
                f" see {ENC_KEY_ENV}"
            ) from None
        self._keys = {"match_key": match_key, "enc_key": enc_key}

    @classmethod
    def for_database(cls, database: Path) -> Vault:
        """Build a vault for `database`, taking each key from its env var, else from the key file."""
        from_env = {entry: os.environ.get(var, "") for entry, var in _KEY_ENTRIES.items()}
        from_file = _read_or_create_key_file(database) if not all(from_env.values()) else {}
        keys = {entry: from_env[entry] or from_file[entry] for entry in _KEY_ENTRIES}
        # Encode a non-ASCII encryption key as "?"s, so Fernet rejects it with the friendly
        # DataError in __init__ instead of a UnicodeEncodeError here.
        return cls(keys["match_key"].encode("utf-8"), keys["enc_key"].encode("ascii", "replace"))

    def fingerprints(self) -> dict[str, str]:
        """Return, per key, a value that identifies it without revealing it, for storing in the database."""
        return {
            _fingerprint_name(entry): hmac.new(key, _FINGERPRINT_MESSAGE, hashlib.sha256).hexdigest()
            for entry, key in self._keys.items()
        }

    def check_fingerprints(self, stored: dict[str, str]) -> None:
        """Refuse keys other than those the database was created with. Nothing stored: nothing to check."""
        if not stored:
            return
        mine = self.fingerprints()
        for entry, var in _KEY_ENTRIES.items():
            if stored.get(_fingerprint_name(entry)) != mine[_fingerprint_name(entry)]:
                raise DataError(
                    f"the {_KEY_NAMES[entry]} differs from the one this database was created with"
                    f" (fingerprint mismatch); set {var} or restore the original key file"
                )

    def phone_hmac(self, canonical_phone: str) -> bytes:
        return hmac.new(self._keys["match_key"], canonical_phone.encode("utf-8"), hashlib.sha256).digest()

    @staticmethod
    def last4(canonical_phone: str) -> str:
        """Return the last four digits, kept in plaintext for masking (not identifying on their own)."""
        return canonical_phone[-4:]

    def encrypt(self, value: str) -> bytes:
        return self._fernet.encrypt(value.encode("utf-8"))

    def decrypt(self, token: bytes) -> str:
        try:
            return self._fernet.decrypt(token).decode("utf-8")
        except InvalidToken:
            raise DataError("stored PII cannot be decrypted with this encryption key") from None


def _fingerprint_name(entry: str) -> str:
    return f"{entry}_fingerprint"


def _read_or_create_key_file(database: Path) -> dict[str, str]:
    path = key_file_for(database)
    if not path.exists():
        if database.exists():
            raise DataError(
                f"database {database} exists but its keys were not found: set {MATCH_KEY_ENV} and"
                f" {ENC_KEY_ENV}, or restore {path}"
            )
        fresh = {"match_key": secrets.token_hex(32), "enc_key": Fernet.generate_key().decode()}
        _write_owner_only(path, fresh)
        print(f"warning: created new key file {path}; keep it with the database", file=sys.stderr)
    try:
        content = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise DataError(f"key file {path} is unreadable: {error}") from None
    if not isinstance(content, dict) or not all(isinstance(content.get(e), str) for e in _KEY_ENTRIES):
        raise DataError(f"key file {path} must hold {' and '.join(_KEY_ENTRIES)} as strings")
    return content


def _write_owner_only(path: Path, content: dict[str, str]) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(content, f)
