# ledger

This is the Assignment A solution. It is a command-line pipeline that turns daily drops of lead CSVs and
call-event JSONL into the five report files. It stores everything in one SQLite database.

The design, the decisions behind it and the results are in [`../SUBMISSION.md`](../SUBMISSION.md).
The reasoning for the larger choices is in [`../docs/adr/`](../docs/adr/), and the terms used here are
defined in [`../docs/GLOSSARY.md`](../docs/GLOSSARY.md).

## Setup

Needs Python 3.11 or newer. From the repo root:

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e "solution[dev]"
cd solution
```

The runtime dependencies are `cryptography` and `python-dotenv`. The `dev` extra adds `pytest` and `ruff`.

## Usage

```bash
python ../assignment-a-data/tools/generate_data.py --seed 42 --scale small --out data
python -m ledger ingest data/drop_1
python -m ledger ingest data/drop_2
python -m ledger report --out reports
```

| Command | What it does |
|---|---|
| `ingest DROP_DIR [DROP_DIR ...]` | Ingests drops in the order given, all in one transaction. Prints one line per file, `ingested` with its counts or `skipped` if it was already ingested. |
| `report --out DIR` | Writes `batch_summary.csv`, `daily_overview.csv`, `lead_report.csv`, `rejections.csv` and `data_quality.json` into `DIR`. |

| Option | Default |
|---|---|
| `--db PATH` | `$LEDGER_DB`, else `./ledger.db` |
| `--schemas DIR` | `../assignment-a-data/schemas` |

Exit codes: `0` success, `1` bad data (the error says what was wrong), `2` bad arguments.

### Keys

The pipeline uses two keys: one to hash phone numbers for matching and one to encrypt phones and
names. It reads them from `LEDGER_MATCH_KEY` and `LEDGER_ENC_KEY` if those are set. Otherwise it creates
`<db>.keys.json` next to a new database, readable only by you, and prints a warning.

Keep the key file with its database. The pipeline refuses to open a database with a missing or
different key, because a different key would quietly break the matching of every earlier event. To
start over, delete the database and its key file together.

To make your own keys:

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

### Environment file

All settings can also go in a `.env` file. [`.env.example`](.env.example) lists them:

```bash
cp .env.example .env
```

The CLI reads `.env` automatically from the directory you run it in, or the nearest parent. A
variable already set in your shell wins over the file. The file is optional, and the pipeline runs
without it.

`.env` is git-ignored. Never commit it once it holds keys.

## Code layout

| File | Responsibility |
|---|---|
| `ledger/cli.py` | Argument parsing and exit codes. |
| `ledger/pipeline.py` | `ingest()` and `report()`, the API that the CLI and most tests use. |
| `ledger/rules.py` | Every business rule as a pure function: normalising values, validating rows, merging, effective disposition, buckets, rounding. |
| `ledger/catalogue.py` | Loads the workflow schemas and `dispositions.csv`. |
| `ledger/vault.py` | Key handling, phone HMAC and encryption. |
| `ledger/store.py` | The SQLite schema and all SQL. |
| `bench.py` | Times ingest and report on generated data. |

To change a business rule, edit `rules.py` and its table in `tests/test_rules.py`. The other files
only move data around.

## Tests

```bash
pytest
```

The 60 tests (135 cases, counting each table row) take about 4 seconds. They work at four levels:

| Level | Files |
|---|---|
| Rules, as table-driven tests with no database | `test_rules.py` |
| Scenarios on small drops built inside each test | `test_header_mapping.py`, `test_rejections.py`, `test_merged_duplicates.py`, `test_event_ingestion.py`, `test_linking.py`, `test_dispositions.py`, `test_batch_summary.py`, `test_daily_overview.py`, `test_idempotency.py`, `test_pii.py` |
| Properties on realistic data from the provided generator, for seeds 42 and 2026 | `test_properties.py` |
| The real command run as a subprocess | `test_cli.py` |

The tests check only outputs: report contents, counts, exit codes and refusals. You can change the SQL
without touching them.

## Lint and format

[Ruff](https://docs.astral.sh/ruff/) does both jobs. It comes with the `dev` extra and is configured
in `pyproject.toml`. Run it from `solution/` before committing:

```bash
ruff format .     # reformat in place
ruff check .      # lint; add --fix for the safe automatic fixes
```

To check without changing anything, run `ruff format --check . && ruff check .`.

## Benchmark

```bash
python bench.py                                   # --scale large --seed 42
python bench.py --scale small --workdir /tmp/x    # quick check
```

Each run generates fresh data into `bench/run-<timestamp>/` and times `ingest drop_1`, `ingest drop_2`
and `report` as separate processes. At large scale the whole run takes about 26 seconds on a laptop.
SUBMISSION.md has the full results.
