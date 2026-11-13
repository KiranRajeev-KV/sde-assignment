"""Command-line interface: a thin argument parser over the pipeline API.

Settings come from environment variables, which an optional `.env` file (in the working
directory or the nearest parent) can supply; variables already set win over the file.

Exit codes: 0 success, 1 data error, 2 usage error (argparse's own code).
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from dotenv import find_dotenv, load_dotenv

from ledger import pipeline
from ledger.errors import DataError

DEFAULT_DB = "ledger.db"
# The provided schemas, found relative to this package (`solution/ledger/` -> `assignment-a-data/schemas/`),
# so the CLI works from any working directory.
DEFAULT_SCHEMAS = Path(__file__).resolve().parents[2] / "assignment-a-data" / "schemas"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m ledger",
        description="Interaction ledger: ingest lead and event drops, then report.",
    )
    parser.add_argument(
        "--db",
        type=Path,
        default=Path(os.environ.get("LEDGER_DB") or DEFAULT_DB),  # an empty LEDGER_DB= means unset
        help=f"SQLite database file (default: $LEDGER_DB, else ./{DEFAULT_DB})",
    )
    parser.add_argument(
        "--schemas",
        type=Path,
        default=DEFAULT_SCHEMAS,
        help=f"directory of workflow schemas and dispositions.csv (default: {DEFAULT_SCHEMAS})",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    ingest = commands.add_parser("ingest", help="ingest one or more drop directories, in order")
    ingest.add_argument("drops", nargs="+", type=Path, metavar="DROP_DIR")

    report = commands.add_parser("report", help="write the report files")
    report.add_argument("--out", type=Path, required=True, metavar="DIR")
    return parser


def main(argv: list[str] | None = None) -> int:
    load_dotenv(find_dotenv(usecwd=True))  # before the parser reads LEDGER_DB
    args = build_parser().parse_args(argv)
    try:
        if args.command == "ingest":
            # Results are printed only after the transaction commits; a refused run prints none.
            for result in pipeline.ingest(args.db, args.drops, args.schemas):
                if result.status == "skipped":
                    detail = f"(already ingested from {result.same_as})"
                else:
                    detail = " ".join(f"{k}={v}" for k, v in result.counts.items())
                print(f"{result.status} {result.kind} {result.path} {detail}")
        else:
            pipeline.report(args.db, args.out)
            print(f"reports written to {args.out}")
    except DataError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    return 0
