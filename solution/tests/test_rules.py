"""Business rules as table-driven tests of pure functions (no database).

One table per rule, one row per distinct behaviour.
"""

import json

import pytest
from conftest import SCHEMAS

from ledger import rules
from ledger.catalogue import Field, load_catalogue
from ledger.errors import DataError

CATALOGUE = load_catalogue(SCHEMAS)
MOTOR = CATALOGUE.schema("motor_renewal")

# Value normalisers: each returns the normalised value, or None if invalid.


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        # the six real-world formats
        ("9876543210", "+919876543210"),
        ("+91 98765 43210", "+919876543210"),
        ("09876543210", "+919876543210"),
        ("91-98765-43210", "+919876543210"),
        ("(+91) 9876543210", "+919876543210"),
        ("+919876543210", "+919876543210"),
        # not an Indian mobile
        ("N/A", None),
        ("022-2345-6789", None),  # landline
        ("+1 415 555 0134", None),  # foreign
        ("987654321", None),  # 9 digits
        ("5876543210", None),  # mobiles start with 6-9
        ("९८७६५४३२१०", None),  # non-ASCII digits
    ],
)
def test_phone(raw, expected):
    assert rules.normalise_phone(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("2026-12-01", "2026-12-01"),
        ("01/12/2026", "2026-12-01"),  # day first
        ("01-12-2026", "2026-12-01"),
        ("01-Dec-2026", "2026-12-01"),
        ("01-DEC-2026", "2026-12-01"),  # month name in any case
        ("31/02/2026", None),  # impossible date
        ("2026-13-01", None),
        ("soon", None),
        ("TBD", None),
    ],
)
def test_date(raw, expected):
    assert rules.normalise_date(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("1500", "1500.00"),
        ("₹12,500", "12500.00"),
        ("Rs 12500", "12500.00"),
        ("Rs. 12500", "12500.00"),
        ("INR 12500.5", "12500.50"),
        ("1,23,456.78", "123456.78"),  # Indian grouping
        ("10.005", "10.01"),  # half-up
        ("2.675", "2.68"),  # exact decimal, not binary float
        ("-500", None),
        ("-", None),
        ("N/A", None),
        ("twelve thousand", None),
        ("1,,000", None),  # commas only between digits
    ],
)
def test_amount(raw, expected):
    assert rules.normalise_decimal(raw) == expected


@pytest.mark.parametrize(("raw", "expected"), [("HI", "hi"), (" kn ", "kn"), ("Hindi", None), ("", None)])
def test_enum_is_case_insensitive_and_stored_lower_case(raw, expected):
    assert rules.normalise_enum(raw, ("en", "hi", "ta", "kn", "te", "mr")) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("2026-10-05T13:20:21Z", "2026-10-05T13:20:21Z"),
        ("2026-10-05T18:50:21+05:30", "2026-10-05T13:20:21Z"),
        ("2026-10-05 18:50:21", "2026-10-05T13:20:21Z"),  # naive means IST
        ("2026-10-06 02:00:00", "2026-10-05T20:30:00Z"),  # IST after midnight is the previous UTC day
        ("2026-10-05", None),  # a date, not an instant
        ("2026-10-05T25:00:00Z", None),
        ("2026-10-05T10:00:00.5Z", None),  # whole seconds only
        ("soon", None),
    ],
)
def test_event_timestamp_to_utc(raw, expected):
    assert rules.normalise_instant(raw) == expected


def test_instant_is_reported_in_ist():
    assert rules.format_ist(rules.parse_instant("2026-10-05T13:20:21Z")) == "2026-10-05T18:50:21+05:30"


# Event lines

EVENT = {
    "event_id": "evt_1",
    "event_type": "disposition.set",
    "workflow_id": "motor_renewal",
    "call_id": "call_1",
    "occurred_at": "2026-10-05 18:50:21",
    "phone": "+91 98765 43210",
    "payload": {"code": "RENEWED", "phone": "9123456780"},
}


def test_well_formed_event_is_parsed_with_canonical_phone_utc_instant_and_no_phone_in_payload():
    assert rules.parse_event_line(json.dumps(EVENT)) == rules.ParsedEvent(
        event_id="evt_1",
        event_type="disposition.set",
        workflow_id="motor_renewal",
        call_id="call_1",
        occurred_at="2026-10-05T13:20:21Z",
        occurred_at_raw="2026-10-05 18:50:21",
        phone="+919876543210",
        payload={"code": "RENEWED"},
    )


def test_event_with_an_invalid_phone_is_kept_without_a_phone():
    parsed = rules.parse_event_line(json.dumps({**EVENT, "phone": "N/A"}))

    assert parsed is not None
    assert parsed.phone is None


@pytest.mark.parametrize(
    "line",
    [
        "not json",
        json.dumps([EVENT]),  # not an object
        json.dumps({k: v for k, v in EVENT.items() if k != "event_id"}),
        json.dumps({k: v for k, v in EVENT.items() if k != "workflow_id"}),
        json.dumps({**EVENT, "call_id": ""}),
        json.dumps({**EVENT, "event_type": "call.exploded"}),
        json.dumps({**EVENT, "occurred_at": "soon"}),
    ],
)
def test_malformed_event_line(line):
    assert rules.parse_event_line(line) is None


# Headers


@pytest.mark.parametrize("raw", ["Mobile No", "MOBILE_NO", "  mobile __ no  "])
def test_header_ignores_case_spaces_and_underscores(raw):
    assert rules.normalise_header(raw) == "mobile no"


@pytest.mark.parametrize(
    ("header", "mapping"),
    [
        (
            [
                "customer_name",
                "phone",
                "policy_number",
                "policy_expiry",
                "premium_amount",
                "preferred_language",
            ],
            {
                "customer_name": 0,
                "phone": 1,
                "policy_number": 2,
                "policy_expiry": 3,
                "premium_amount": 4,
                "preferred_language": 5,
            },
        ),
        # aliases, a new order and an unknown column
        (
            ["Policy No", "agent_notes", "Mobile No", "Insured Name"],
            {"policy_number": 0, "phone": 2, "customer_name": 3},
        ),
    ],
)
def test_headers_map_by_name_or_alias(header, mapping):
    assert rules.map_headers(header, MOTOR.accepted_headers) == mapping


def test_two_headers_for_one_field_is_an_error_naming_both():
    with pytest.raises(DataError, match=r"'phone'.*'Mobile No'"):
        rules.map_headers(["phone", "name", "Mobile No"], MOTOR.accepted_headers)


# Lead rows

ROW = {
    "customer_name": "Aarav Sharma",
    "phone": "+91 98765 43210",
    "policy_number": "MOT/2026/100001",
    "policy_expiry": "01-Dec-2026",
    "premium_amount": "₹12,500",
    "preferred_language": "HI",
}
NO_COLUMN = object()


def row(**changes: object) -> dict[str, str | None]:
    values = {**ROW, **changes}
    return {k: v for k, v in values.items() if v is not NO_COLUMN}


def test_valid_row_is_normalised():
    assert rules.validate_row(MOTOR.fields, row()) == rules.ValidRow(
        values={
            "customer_name": "Aarav Sharma",
            "phone": "+919876543210",
            "policy_number": "MOT/2026/100001",
            "policy_expiry": "2026-12-01",
            "premium_amount": "12500.00",
            "preferred_language": "hi",
        },
        field_warnings=0,
    )


@pytest.mark.parametrize(
    ("changes", "reason"),
    [
        ({"customer_name": None}, "missing_required:customer_name"),
        ({"phone": "   "}, "missing_required:phone"),
        ({"phone": NO_COLUMN}, "missing_required:phone"),  # file has no phone column
        ({"phone": "N/A"}, "invalid_phone"),
        # the first failure in schema order: the name comes before the phone
        ({"customer_name": None, "phone": "N/A"}, "missing_required:customer_name"),
        # a bad optional value does not hide a later required failure
        ({"policy_expiry": "soon", "policy_number": None}, "missing_required:policy_number"),
    ],
)
def test_rejection_reason(changes, reason):
    assert rules.validate_row(MOTOR.fields, row(**changes)) == rules.Rejection(reason)


def test_invalid_optional_value_becomes_null_with_a_warning_and_a_missing_one_without():
    result = rules.validate_row(MOTOR.fields, row(policy_expiry="31/02/2026", premium_amount=None))

    assert isinstance(result, rules.ValidRow)
    assert result.values["policy_expiry"] is None
    assert result.values["premium_amount"] is None
    assert result.field_warnings == 1


def test_invalid_required_field_of_another_type_is_rejected_by_name():
    # No provided schema has a required non-phone field that can be invalid, so this reason is our choice.
    fields = (
        Field("phone", "phone", required=True, pii=True, reference=False),
        Field("due", "date", required=True, pii=False, reference=True),
    )

    assert rules.validate_row(fields, {"phone": "9876543210", "due": "soon"}) == rules.Rejection(
        "invalid:due"
    )


@pytest.mark.parametrize(
    ("existing", "incoming", "merged"),
    [
        ({"premium_amount": "1500.00"}, {"premium_amount": "1800.00"}, {"premium_amount": "1800.00"}),
        ({"premium_amount": "1500.00"}, {"premium_amount": None}, {"premium_amount": "1500.00"}),
        ({"policy_number": "POL-0001"}, {"policy_number": "POL-9999"}, {"policy_number": "POL-9999"}),
    ],
)
def test_merge_overwrites_only_non_null_fields(existing, incoming, merged):
    assert rules.merge_lead_values(existing, incoming) == merged


def test_defaults_fill_only_null_fields():
    values = {"preferred_language": None, "premium_amount": "1500.00"}

    assert rules.apply_defaults(MOTOR.fields, values) == {
        "preferred_language": "en",
        "premium_amount": "1500.00",
    }


# Calls and leads


def disposition(event_id: str, kind: str, code: str, at: str) -> rules.DispositionEvent:
    return rules.DispositionEvent(event_id, kind, code, rules.parse_instant(at))


@pytest.mark.parametrize(
    ("events", "effective"),
    [
        # an override beats a set, even a later set
        (
            [
                disposition("evt_1", "set", "callback_requested", "2026-10-05T10:00:00Z"),
                disposition("evt_2", "override", "renewed", "2026-10-05T09:00:00Z"),
            ],
            "renewed",
        ),
        # an override with an unknown code falls back to the set
        (
            [
                disposition("evt_1", "set", "callback_requested", "2026-10-05T10:00:00Z"),
                disposition("evt_2", "override", "RENEWD", "2026-10-05T11:00:00Z"),
            ],
            "callback_requested",
        ),
        # equal times: the larger event_id wins
        (
            [
                disposition("evt_2", "set", "not_interested", "2026-10-05T11:00:00Z"),
                disposition("evt_1", "set", "renewed", "2026-10-05T11:00:00Z"),
            ],
            "not_interested",
        ),
        ([disposition("evt_1", "set", "RENEWD", "2026-10-05T10:00:00Z")], None),
    ],
)
def test_effective_disposition(events, effective):
    assert (
        rules.effective_disposition(events, {"renewed", "callback_requested", "not_interested"}) == effective
    )


def call(call_id: str, at: str, disposition: str | None = None, *, failed: bool = False) -> rules.Call:
    return rules.Call(call_id, rules.parse_instant(at), False, disposition, telephony_failed=failed)


@pytest.mark.parametrize(
    ("calls", "current"),
    [
        # the latest call that has a disposition
        (
            [call("call_A", "2026-10-05T09:00:00Z", "renewed"), call("call_B", "2026-10-06T09:00:00Z")],
            "renewed",
        ),
        # equal times: the larger call_id wins
        (
            [
                call("call_2", "2026-10-05T09:00:00Z", "not_interested"),
                call("call_1", "2026-10-05T09:00:00Z", "renewed"),
            ],
            "not_interested",
        ),
    ],
)
def test_current_disposition(calls, current):
    assert rules.current_disposition(calls) == current


T = "2026-10-05T09:00:00Z"


@pytest.mark.parametrize(
    ("calls", "bucket"),
    [
        ([], "yet_to_reach_out"),
        ([call("c", T, "renewed")], "completed"),
        ([call("c", T, failed=True), call("d", T, failed=True)], "in_progress_telephony_failed"),
        ([call("c", T, failed=True), call("d", T)], "in_progress_dialed"),
        ([call("c", T, "callback_requested")], "in_progress_dialed"),  # not terminal
        ([call("c", T, "renewed", failed=True)], "completed"),  # completed is checked first
    ],
)
def test_bucket(calls, bucket):
    assert rules.bucket(calls, {"renewed", "not_interested"}) == bucket


@pytest.mark.parametrize(
    ("connected", "total", "rate"),
    [(5, 160, "0.0313"), (1, 3, "0.3333"), (0, 7, "0.0000")],  # 0.03125 rounds half-up
)
def test_connectivity_rate(connected, total, rate):
    assert rules.connectivity_rate(connected, total) == rate
