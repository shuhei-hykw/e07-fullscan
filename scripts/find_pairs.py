#!/usr/bin/env python
"""Find ΛΛ-topology vertex pairs from merged vertex parquet.

Usage:
  python scripts/find_pairs.py \\
    --input  results/vertices_merged_v5.parquet \\
    --output results/vertex_pairs_v5.parquet

Candidate pairs: one high-multiplicity primary vertex (n_tracks_max >=
min_n_primary) and one secondary vertex (n_tracks_max >= min_n_secondary)
in the same view, separated by d_min–d_max px.
Pixel scale: 0.29 μm/px (FOV=594 μm/2048 px).
Default range: 310–1724 px ≈ 90–500 μm.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path


def main() -> None:
  ap = argparse.ArgumentParser(description="ΛΛ vertex pair finder")
  ap.add_argument("--input",   type=Path, required=True,
                  help="Merged vertex parquet (output of merge_vertices.py)")
  ap.add_argument("--output",  type=Path, required=True,
                  help="Output parquet for candidate pairs")
  ap.add_argument("--d-min",   type=float, default=310.0,
                  help="Min vertex separation (px, default 310 = 90 μm)")
  ap.add_argument("--d-max",   type=float, default=1724.0,
                  help="Max vertex separation (px, default 1724 = 500 μm)")
  ap.add_argument("--min-n-primary",    type=int,   default=5,
                  help="Min n_tracks_max for primary vertex")
  ap.add_argument("--max-n-primary",    type=int,   default=0,
                  help="Max n_tracks_max for primary (0=no limit)")
  ap.add_argument("--min-n-secondary",  type=int,   default=3,
                  help="Min n_tracks_max for secondary vertex")
  ap.add_argument("--min-sl-secondary", type=int,   default=2,
                  help="Min n_slices for secondary vertex")
  ap.add_argument("--max-dz-mm",        type=float, default=0.010,
                  help="Max Z separation between vertices in mm "
                       "(z_step≈0.003 mm; default 0.010=10 μm)")
  args = ap.parse_args()

  import pandas as pd
  sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
  from module.clustering import find_vertex_pairs
  from module.utils import (
    make_run_id, build_run_meta,
    save_run_json, save_parquet_with_meta,
  )

  run_id = make_run_id()
  run_params = {k: str(v) for k, v in vars(args).items()}
  run_meta = build_run_meta(run_id, __file__, run_params)

  print(f"Loading {args.input} …", flush=True)
  df = pd.read_parquet(args.input)
  n_views = df['view_id'].nunique()
  print(f"  {len(df):,} merged vertices, {n_views} views")

  print(f"Finding ΛΛ vertex pairs "
        f"(d={args.d_min:.0f}–{args.d_max:.0f} px, "
        f"n_primary>={args.min_n_primary}, "
        f"n_sec>={args.min_n_secondary} sl>={args.min_sl_secondary}, "
        f"dz<={args.max_dz_mm} mm) …", flush=True)

  pairs = find_vertex_pairs(
    df,
    d_min_px=args.d_min,
    d_max_px=args.d_max,
    min_n_primary=args.min_n_primary,
    min_n_secondary=args.min_n_secondary,
    min_sl_secondary=args.min_sl_secondary,
    max_dz_mm=args.max_dz_mm,
  )

  if pairs.empty:
    print("No pairs found.", file=sys.stderr)
    save_parquet_with_meta(pairs, args.output, run_meta)
    save_run_json(run_meta, args.output)
    return

  if args.max_n_primary > 0:
    pairs = pairs[pairs['p_ntracks'] <= args.max_n_primary]
    print(f"  After max_n_primary<={args.max_n_primary}: {len(pairs):,}")

  print(f"  Found {len(pairs):,} candidate pairs "
        f"in {pairs['view_id'].nunique()} views")
  print("  dist_um distribution:")
  bins = [0, 100, 200, 300, 500, 800, 1200, 2000]
  print(pairs['dist_um'].value_counts(bins=bins, sort=False).to_string())

  args.output.parent.mkdir(parents=True, exist_ok=True)
  save_parquet_with_meta(pairs, args.output, run_meta)
  json_path = save_run_json(run_meta, args.output)
  print(f"Saved → {args.output}")
  print(f"Run metadata → {json_path}")


if __name__ == "__main__":
  main()
