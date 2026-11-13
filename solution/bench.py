"""Timing command for the `--scale large` performance target: ingest both drops, then report.

    python bench.py                      # --scale large --seed 42, under solution/bench/
    python bench.py --scale small --workdir /tmp/x

Each run generates data into a fresh `<workdir>/run-<timestamp>/` with the provided
generator, then times the real CLI (`python -m ledger`), one process per step, as a
user would run it: `ingest drop_1`, `ingest drop_2`, `report`. Wall-clock seconds
include interpreter start-up. The run directory is left in place for inspection.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

SOLUTION = Path(__file__).resolve().parent  # `solution/`: the ledger package's home
GENERATOR = SOLUTION.parent / "assignment-a-data" / "tools" / "generate_data.py"


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--scale", default="large", choices=["small", "large"])
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--workdir", type=Path, default=SOLUTION / "bench")
    args = parser.parse_args()

    run_dir = args.workdir.resolve() / time.strftime("run-%Y%m%dT%H%M%S")
    run_dir.mkdir(parents=True)  # no exist_ok: never reuse an earlier run's database
    data_dir = run_dir / "data"
    subprocess.run(
        [
            sys.executable,
            str(GENERATOR),
            "--seed",
            str(args.seed),
            "--scale",
            args.scale,
            "--out",
            str(data_dir),
        ],
        check=True,
        stdout=subprocess.DEVNULL,
    )
    ledger_cmd = [sys.executable, "-m", "ledger", "--db", str(run_dir / "ledger.db")]
    # Drop LEDGER_* settings so the run uses its own database and a fresh key file.
    env = {k: v for k, v in os.environ.items() if not k.startswith("LEDGER_")}
    steps = [
        ("ingest_drop_1", ["ingest", str(data_dir / "drop_1")]),
        ("ingest_drop_2", ["ingest", str(data_dir / "drop_2")]),
        ("report", ["report", "--out", str(run_dir / "reports")]),
    ]
    print(f"scale={args.scale} seed={args.seed} dir={run_dir}", flush=True)
    total = 0.0
    for name, step_args in steps:
        start = time.perf_counter()
        # stderr is not captured, so a failing step shows the ledger's own error message.
        subprocess.run(ledger_cmd + step_args, check=True, env=env, cwd=SOLUTION, stdout=subprocess.DEVNULL)
        elapsed = time.perf_counter() - start
        total += elapsed
        print(f"{name:<14} {elapsed:7.2f}s", flush=True)
    print(f"{'total':<14} {total:7.2f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
