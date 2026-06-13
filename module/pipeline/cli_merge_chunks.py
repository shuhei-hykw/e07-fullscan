#!/usr/bin/env python
"""Merge chunk_NNNN.parquet files produced by KEKCC array jobs.

Usage:
  python scripts/merge_chunks.py \
    --input  test_results \
    --output test_results/merged.parquet
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path


def main() -> None:
    ap = argparse.ArgumentParser(description="Merge chunk parquet files")
    ap.add_argument("--input",  type=Path, default=Path("test_results"),
                    help="Directory containing chunk_NNNN.parquet files")
    ap.add_argument("--output", type=Path,
                    default=Path("test_results/merged.parquet"),
                    help="Output merged parquet path")
    ap.add_argument("--pattern", default="chunk_*.parquet",
                    help="Glob pattern for chunk files")
    args = ap.parse_args()

    import pandas as pd

    chunks = sorted(args.input.glob(args.pattern))
    if not chunks:
        print(f"No files matching {args.input}/{args.pattern}",
              file=sys.stderr)
        sys.exit(1)

    print(f"Merging {len(chunks)} chunk file(s)…", file=sys.stderr)

    dfs = []
    for p in chunks:
        try:
            dfs.append(pd.read_parquet(p))
            print(f"  {p.name}: {len(dfs[-1]):,} rows", file=sys.stderr)
        except Exception as e:
            print(f"  WARNING: {p.name}: {e}", file=sys.stderr)

    if not dfs:
        print("No valid chunks to merge.", file=sys.stderr)
        sys.exit(1)

    merged = pd.concat(dfs, ignore_index=True)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    merged.to_parquet(args.output, index=False)

    print(
        f"\nTotal: {len(merged):,} rows → {args.output}",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()
