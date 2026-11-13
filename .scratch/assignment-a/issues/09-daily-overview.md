# 09: daily_overview.csv

**What to build:** One row per workflow per IST date with at least one counted call, sorted by workflow and date. A call's date is the IST date of its `call.initiated`, even if later events cross midnight. Columns: `total_calls`, `connected_calls`, `connectivity_rate` (connected ÷ total, exact decimal arithmetic rounded half-up, exactly 4 decimals), and `success_leads` (distinct leads with at least one call on that date whose effective disposition is a success).

**Blocked by:** 07 (Dispositions: catalogue, overrides, effective disposition)

**Status:** done

- [x] Seam B table tests: rate formatting `5/160` gives `0.0313`, `9/16` gives `0.5625`, `1/3` gives `0.3333`, `0/7` gives `0.0000`, `7/7` gives `1.0000`.
- [x] Seam A test: a call initiated at 23:59 IST that connects after midnight counts on the earlier date; a UTC timestamp that is the next day in IST counts on the IST date.
- [x] Seam A test: a lead with two successful calls on one date counts once in `success_leads`; a success via override counts; a success on another date does not.
- [x] Seam A test: dates with no counted calls produce no row.
