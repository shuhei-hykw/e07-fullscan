"""Merge Parquet chunks into a SQLite database (e07merge)."""
from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

import pandas as pd

_TABLE   = "tracks"
_INDICES = ("view_id", "z", "angle_deg")


def main() -> None:
  parser = argparse.ArgumentParser(
    prog="e07merge",
    description="Merge Parquet chunks into a SQLite database.",
  )
  parser.add_argument(
    "input", type=Path,
    help="Directory containing .parquet files.",
  )
  parser.add_argument(
    "-o", "--output", type=Path, required=True, metavar="FILE",
    help="Output SQLite database (.db).",
  )
  parser.add_argument(
    "--table", default=_TABLE, metavar="NAME",
    help=f"Table name (default: {_TABLE}).",
  )
  parser.add_argument(
    "-v", "--verbose", action="store_true",
    help="Print progress to stderr.",
  )
  args = parser.parse_args()

  parquets = sorted(args.input.glob("*.parquet"))
  if not parquets:
    print(
      f"No .parquet files found in {args.input}",
      file=sys.stderr,
    )
    sys.exit(1)

  if args.verbose:
    print(
      f"Merging {len(parquets)} file(s)...", file=sys.stderr
    )

  df = pd.concat(
    [pd.read_parquet(p) for p in parquets], ignore_index=True
  )

  if args.verbose:
    print(f"Total rows: {len(df):,}", file=sys.stderr)

  with sqlite3.connect(args.output) as conn:
    df.to_sql(
      args.table, conn, if_exists="replace", index=False
    )
    for col in _INDICES:
      if col in df.columns:
        conn.execute(
          f"CREATE INDEX IF NOT EXISTS idx_{col}"
          f" ON {args.table}({col})"
        )

  if args.verbose:
    print(f"Written to {args.output}", file=sys.stderr)


if __name__ == "__main__":
  main()
