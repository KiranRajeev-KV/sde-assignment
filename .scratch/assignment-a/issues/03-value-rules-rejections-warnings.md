# 03: Value rules, rejections and field warnings

**What to build:** Every lead value is validated and normalised per the README's field types: `string` (trimmed), `phone` (strip non-digits, drop leading `91` from 12 digits or `0` from 11, valid only if 10 digits starting 6–9, canonical `+91XXXXXXXXXX`), `date` (the four day-first formats, case-insensitive month name, impossible dates invalid), `decimal` (optional `₹`/`Rs`/`Rs.`/`INR` prefix, commas as thousands separators, ≥ 0, rounded half-up to 2 places), `enum` (case-insensitive, stored lower-case). Empty values count as missing. Rows are rejected by walking fields in schema order: the first missing required field gives `missing_required:<field>`, and a present-but-invalid phone gives `invalid_phone`. A required non-string, non-phone field that is present but invalid is rejected with a reason named after the field (documented assumption; no such field exists in the provided schemas). Invalid optional values become null and count one field warning, but only on rows that are not rejected. The user gets `rejections.csv` (no PII, sorted by workflow, batch, row number) and the lead counters in `data_quality.json`. Counters are recorded per ingested file and summed at report time.

**Blocked by:** 01 (Walking skeleton)

**Status:** done

- [x] Seam B table tests, phone: all six generator formats, `N/A`, a landline, a `+1` number, 9 digits, bad leading digit.
- [x] Seam B table tests, date: all four formats, `DEC`/`dec`, `31/02/2026`, `2026-13-01`, `soon`, `TBD`.
- [x] Seam B table tests, decimal: each prefix with and without a space, commas, `-500`, `-`, `N/A`, `twelve thousand`, half-up rounding at the 3rd decimal.
- [x] Seam B table tests, enum: case, surrounding whitespace, `Hindi` invalid, empty is missing.
- [x] Seam B table tests, rejection: schema-order walk; a missing name plus a bad phone gives `missing_required:customer_name`; `N/A` gives `invalid_phone`; a file lacking the phone column rejects every row with `missing_required:phone`.
- [x] Seam A test: a mixed file produces the exact `rejections.csv` and the lead counters `lead_rows_total`, `lead_rows_rejected`, `rejections_by_reason` (only reasons that occurred, keys sorted) and `field_warnings` in `data_quality.json`.
- [x] Rejected rows store no row content anywhere in the database.
