"""Business rules as pure functions: no I/O, no database (ADR-0007).

Every domain rule lives here, so each one can be tested with a plain table of
inputs and expected outputs (see tests/test_rules.py).
"""

from __future__ import annotations

import json
import re
from collections.abc import Collection, Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal
from typing import Literal

from ledger.catalogue import Field
from ledger.errors import DataError

IST = timezone(timedelta(hours=5, minutes=30))

_NON_DIGIT = re.compile(r"[^0-9]")
_HEADER_SEPARATORS = re.compile(r"[\s_]+")

# (pattern, order of its year/month/day groups). Slash and dash dates are day-first (Indian convention).
_DATE_FORMATS = (
    (re.compile(r"([0-9]{4})-([0-9]{1,2})-([0-9]{1,2})"), "ymd"),
    (re.compile(r"([0-9]{1,2})/([0-9]{1,2})/([0-9]{4})"), "dmy"),
    (re.compile(r"([0-9]{1,2})-([0-9]{1,2})-([0-9]{4})"), "dmy"),
    (re.compile(r"([0-9]{1,2})-([a-z]{3})-([0-9]{4})", re.IGNORECASE), "dmy"),
)
_MONTHS = {
    name: number
    for number, name in enumerate(
        ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"), start=1
    )
}
_CURRENCY_PREFIX = re.compile(r"(?:₹|rs\.?|inr)\s*", re.IGNORECASE)
# Commas are thousands separators, in Western (1,234,567) or Indian (12,34,567) grouping.
_AMOUNT = re.compile(r"(?:[0-9]+|[0-9]{1,3}(?:,[0-9]{3})+|[0-9]{1,2}(?:,[0-9]{2})+,[0-9]{3})(?:\.[0-9]+)?")
_CENTS = Decimal("0.01")
_RATE_PLACES = Decimal("0.0001")


def normalise_header(text: str) -> str:
    """Lower-case, trim, and collapse runs of `_` or whitespace to one space."""
    return _HEADER_SEPARATORS.sub(" ", text).strip().lower()


def map_headers(header: list[str], names: Mapping[str, Iterable[str]]) -> dict[str, int]:
    """Map each field to the column whose header matches its name or an alias.

    `names` gives each field's accepted headers. Matching is on normalised
    text. Columns that match no field are ignored; a field matched by two
    columns is a clash, and the error names both headers.
    """
    field_by_header = {
        normalise_header(text): field for field, accepted in names.items() for text in accepted
    }
    columns: dict[str, int] = {}
    for index, text in enumerate(header):
        field = field_by_header.get(normalise_header(text))
        if field is None:
            continue
        if field in columns:
            first = header[columns[field]]
            raise DataError(f"headers {first!r} and {text!r} both map to field {field!r}")
        columns[field] = index
    return columns


def normalise_phone(value: str | None) -> str | None:
    """Return the canonical `+91XXXXXXXXXX` form of an Indian mobile, or None if invalid."""
    if value is None:
        return None
    digits = _NON_DIGIT.sub("", value)
    if len(digits) == 12 and digits.startswith("91"):
        digits = digits[2:]
    elif len(digits) == 11 and digits.startswith("0"):
        digits = digits[1:]
    if len(digits) != 10 or digits[0] not in "6789":
        return None
    return "+91" + digits


def normalise_date(value: str) -> str | None:
    """Return the ISO `YYYY-MM-DD` form of an accepted date, or None if invalid or impossible."""
    for pattern, order in _DATE_FORMATS:
        match = pattern.fullmatch(value.strip())
        if match is None:
            continue
        parts = dict(zip(order, match.groups(), strict=True))
        month = _MONTHS.get(parts["m"].lower()) if parts["m"].isalpha() else int(parts["m"])
        if month is None:
            return None
        try:
            return date(int(parts["y"]), month, int(parts["d"])).isoformat()
        except ValueError:
            return None  # e.g. 31/02, month 13
    return None


def normalise_decimal(value: str) -> str | None:
    """Return a non-negative amount rounded half-up to 2 places (`"1234.50"`), or None if invalid.

    An optional `₹`, `Rs`, `Rs.` or `INR` prefix (any case, optional space) is
    dropped, and commas are thousands separators. Exact decimal arithmetic, so
    `2.675` rounds to `2.68`.
    """
    text = value.strip()
    prefix = _CURRENCY_PREFIX.match(text)
    if prefix:
        text = text[prefix.end() :]
    if not _AMOUNT.fullmatch(text):
        return None
    return str(Decimal(text.replace(",", "")).quantize(_CENTS, rounding=ROUND_HALF_UP))


def normalise_enum(value: str, allowed: Iterable[str]) -> str | None:
    """Return the lower-cased value if it is one of `allowed` (case-insensitive), else None."""
    lowered = value.strip().lower()
    return lowered if lowered in {a.lower() for a in allowed} else None


def normalise_value(field: Field, value: str) -> str | None:
    """Return a present value normalised for the field's type, or None if it is invalid."""
    if field.type == "string":
        return value.strip() or None
    if field.type == "phone":
        return normalise_phone(value)
    if field.type == "date":
        return normalise_date(value)
    if field.type == "decimal":
        return normalise_decimal(value)
    if field.type == "enum":
        return normalise_enum(value, field.allowed_values)
    raise DataError(f"field {field.name!r} has unknown type {field.type!r}")


@dataclass(frozen=True)
class Rejection:
    reason: str


@dataclass(frozen=True)
class ValidRow:
    values: dict[str, str | None]  # every schema field, normalised; None where missing or invalid
    field_warnings: int


def validate_row(fields: Iterable[Field], values: Mapping[str, str | None]) -> Rejection | ValidRow:
    """Validate a lead row's trimmed values (None for missing) against its schema fields.

    Fields are walked in schema order and the first failure is the single
    reason: a missing required field gives `missing_required:<field>`, a
    present but invalid phone gives `invalid_phone`, and any other required
    field that is present but invalid gives `invalid:<field>` (an assumption:
    no provided schema has one). An invalid optional value becomes None and
    counts one field warning.
    """
    normalised: dict[str, str | None] = {}
    warnings = 0
    for field in fields:
        raw = values.get(field.name)
        if raw is None or not raw.strip():
            if field.required:
                return Rejection(f"missing_required:{field.name}")
            normalised[field.name] = None
            continue
        value = normalise_value(field, raw)
        if value is None:
            if field.type == "phone":
                return Rejection("invalid_phone")
            if field.required:
                return Rejection(f"invalid:{field.name}")
            warnings += 1
        normalised[field.name] = value
    return ValidRow(normalised, warnings)


def merge_lead_values(
    existing: Mapping[str, str | None], incoming: Mapping[str, str | None]
) -> dict[str, str | None]:
    """Merge a duplicate row into a lead: each non-null incoming value wins (last write wins)."""
    merged = dict(existing)
    merged.update({name: value for name, value in incoming.items() if value is not None})
    return merged


def apply_defaults(fields: Iterable[Field], values: Mapping[str, str | None]) -> dict[str, str | None]:
    """Fill each null field with its schema default, if it has one.

    Applied on read, never stored, so "the client sent en" stays distinct from
    "we assumed en" (ADR-0006).
    """
    defaulted = dict(values)
    for field in fields:
        if field.default is not None and defaulted.get(field.name) is None:
            defaulted[field.name] = field.default
    return defaulted


def mask_phone(last4: str) -> str:
    return "+91******" + last4


_INSTANT = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}[T ][0-9]{2}:[0-9]{2}:[0-9]{2}(?:Z|[+-][0-9]{2}:[0-9]{2})?")


def normalise_instant(value: object) -> str | None:
    """Return an event timestamp's UTC storage form (`YYYY-MM-DDTHH:MM:SSZ`), or None if invalid.

    Accepted: `YYYY-MM-DD[T ]HH:MM:SS` followed by `Z`, an `±HH:MM` offset, or
    nothing (naive means IST). Whole seconds only; anything else, including an
    impossible date or time, is invalid.
    """
    if not isinstance(value, str) or not _INSTANT.fullmatch(value):
        return None
    try:
        return format_utc(parse_instant(value))
    except ValueError:
        return None  # matches the pattern but is impossible, e.g. month 13 or hour 25


EVENT_TYPES = (
    "call.initiated",
    "call.telephony_failed",
    "call.connected",
    "call.ended",
    "disposition.set",
    "disposition.override",
)


@dataclass(frozen=True)
class ParsedEvent:
    """A well-formed event line, normalised for the ledger. Holds no raw text."""

    event_id: str
    event_type: str
    workflow_id: str
    call_id: str
    occurred_at: str  # UTC storage form
    occurred_at_raw: str
    phone: str | None  # canonical, or None if absent or invalid
    payload: object  # as sent, minus any `phone` key: phones are stored as HMAC only
    disposition_code: str | None = None  # `disposition.*` events only; None if absent or not text


def parse_event_line(line: str | bytes) -> ParsedEvent | None:
    """Parse one non-blank event line, or None if it is malformed.

    Bytes are decoded as JSON text (UTF-8, optional BOM); bytes that are not
    valid text make the line malformed.

    Malformed: not valid JSON, not a JSON object, no `event_id`, an unknown
    `event_type`, an unparseable `occurred_at`, or a missing `call_id` or
    `workflow_id`. Identifiers must be non-empty strings. An unknown workflow
    or an invalid phone is not malformed: such events are stored and become
    orphans.
    """
    try:
        raw = json.loads(line)
    except ValueError:  # includes UnicodeDecodeError
        return None
    if not isinstance(raw, dict):
        return None
    identifiers = [raw.get(key) for key in ("event_id", "workflow_id", "call_id")]
    if not all(isinstance(value, str) and value for value in identifiers):
        return None
    occurred_at = normalise_instant(raw.get("occurred_at"))
    if occurred_at is None or raw.get("event_type") not in EVENT_TYPES:
        return None
    phone = raw.get("phone")
    payload = raw.get("payload")
    if payload is None:
        payload = {}
    elif isinstance(payload, dict):
        payload = {key: value for key, value in payload.items() if key != "phone"}
    code = payload.get("disposition_code") if isinstance(payload, dict) else None
    return ParsedEvent(
        event_id=raw["event_id"],
        event_type=raw["event_type"],
        workflow_id=raw["workflow_id"],
        call_id=raw["call_id"],
        occurred_at=occurred_at,
        occurred_at_raw=raw["occurred_at"],
        phone=normalise_phone(phone) if isinstance(phone, str) else None,
        payload=payload,
        disposition_code=code
        if raw["event_type"].startswith("disposition.") and isinstance(code, str)
        else None,
    )


def parse_instant(text: str) -> datetime:
    """Parse an event timestamp into an aware UTC datetime; a naive timestamp is IST."""
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=IST)
    return parsed.astimezone(UTC)


def format_utc(instant: datetime) -> str:
    """Format an instant for storage as UTC, so stored values sort correctly as text."""
    return instant.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def format_ist(instant: datetime) -> str:
    """Format an instant for reports: ISO-8601 in IST, e.g. `2026-10-14T17:55:24+05:30`."""
    return instant.astimezone(IST).strftime("%Y-%m-%dT%H:%M:%S+05:30")


def ist_date(instant: datetime) -> str:
    """Return the IST calendar date of an instant as `YYYY-MM-DD`."""
    return instant.astimezone(IST).date().isoformat()


def connectivity_rate(connected: int, total: int) -> str:
    """Return connected ÷ total, computed exactly and rounded half-up to 4 places (`5/160` → `0.0313`)."""
    return str((Decimal(connected) / Decimal(total)).quantize(_RATE_PLACES, rounding=ROUND_HALF_UP))


@dataclass(frozen=True)
class Call:
    """A counted call, as the report rules see it."""

    call_id: str
    initiated_at: datetime
    connected: bool
    disposition: str | None = None  # effective disposition
    telephony_failed: bool = False  # the call has a `call.telephony_failed` event


def current_disposition(calls: Iterable[Call]) -> str | None:
    """Return the effective disposition of the most recent call that has one.

    Most recent is by initiated time; a tie goes to the larger `call_id` so the result is deterministic.
    """
    with_one = [c for c in calls if c.disposition is not None]
    if not with_one:
        return None
    return max(with_one, key=lambda c: (c.initiated_at, c.call_id)).disposition


def ever_success(calls: Iterable[Call], success_codes: Collection[str]) -> bool:
    """Return whether any call's effective disposition is a success code."""
    return any(c.disposition in success_codes for c in calls)


# Order matters: it is the column order of batch_summary.csv.
BUCKETS = ("yet_to_reach_out", "in_progress_telephony_failed", "in_progress_dialed", "completed")


def bucket(calls: Collection[Call], terminal_codes: Collection[str]) -> str:
    """Return a lead's progress bucket. Rules are checked in order and the first match wins:

    1. no calls                         -> yet_to_reach_out
    2. any call has a terminal outcome  -> completed
    3. every call failed in telephony   -> in_progress_telephony_failed
    4. otherwise                        -> in_progress_dialed
    """
    if not calls:
        return "yet_to_reach_out"
    if any(c.disposition in terminal_codes for c in calls):
        return "completed"
    if all(c.telephony_failed for c in calls):
        return "in_progress_telephony_failed"
    return "in_progress_dialed"


@dataclass(frozen=True)
class DispositionEvent:
    """A `disposition.set` (kind "set") or `disposition.override` (kind "override") of one call."""

    event_id: str
    kind: Literal["set", "override"]
    code: str | None  # None if the event carried no code
    occurred_at: datetime


def effective_disposition(events: Iterable[DispositionEvent], valid_codes: Collection[str]) -> str | None:
    """Return a call's outcome: its latest valid override, else its latest valid set, else None.

    Valid means the code is in the workflow's catalogue. Latest is by `occurred_at`;
    a tie goes to the larger `event_id` so the result is deterministic.
    """
    valid = [e for e in events if e.code in valid_codes]
    for kind in ("override", "set"):
        of_kind = [e for e in valid if e.kind == kind]
        if of_kind:
            return max(of_kind, key=lambda e: (e.occurred_at, e.event_id)).code
    return None
