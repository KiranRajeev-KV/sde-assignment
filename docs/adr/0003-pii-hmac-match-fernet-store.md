# PII: HMAC for matching, Fernet for recovery, last-4 for masking

Phones are matched by `HMAC-SHA256(match_key, "+91XXXXXXXXXX")`, a deterministic keyed hash, so leads carry `UNIQUE(workflow_id, phone_hmac)` and events join on it without plaintext anywhere. A plain SHA-256 was rejected because the Indian mobile space (~4×10⁹) is brute-forceable in minutes. Full phone and customer name are additionally stored encrypted (`phone_enc`, `name_enc`, Fernet/AES via the `cryptography` package, separate `enc_key`) so the lead store stays usable as a system of record (a dialler must be able to recover the number); `phone_masked` is built from a stored plaintext `phone_last4`, which is not considered identifying on its own.

## Considered Options

- **Store only HMAC + last-4, drop name and full phone:** stdlib-only and maximally minimal, but makes the store useless to anything downstream that must call or greet the customer.
- **Encrypt only, match by decrypting:** cannot be indexed or uniquely constrained; O(n) per lookup.

## Consequences

- No PII in the ledger (events keep `phone_hmac` only, never the raw JSON line), and none in `rejections` (no row content stored).
- Two keys, kept apart: leaking `enc_key` does not enable phone lookup, and leaking `match_key` does not decrypt names.
- Rotating `match_key` invalidates every stored HMAC and requires a re-hash from decrypted phones; key rotation is out of scope.
- Adds one third-party dependency (`cryptography`).
