#!/usr/bin/env python
"""Filter vertex pairs by searching for a connecting track.

For each (primary, secondary) pair, looks in the track data for a track
that starts within tol_px of the primary and ends within tol_px of the
secondary (or vice versa).  Pairs with a connecting track are likely
genuine ΛΛ candidates.

Usage:
  python scripts/filter_pairs_by_track.py \\
    --pairs   results/vertex_pairs_v5.parquet \\
    --chunks  results \\
    --output  results/vertex_pairs_v5_connected.parquet \\
    --min-n-primary 5 --tol 50
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


def _build_view_chunk_map(chunk_dir: Path) -> dict[int, int]:
  import pandas as pd
  mapping: dict[int, int] = {}
  for i in range(1, 200):
    cp = chunk_dir / f"chunk_{i:04d}.parquet"
    if not cp.exists():
      break
    try:
      df = pd.read_parquet(cp, columns=['view_id'])
      for v in df['view_id'].unique():
        m = re.search(r'V(\d+)_L0', v)
        if m:
          mapping[int(m.group(1))] = i
    except Exception:
      pass
  return mapping


def _has_connecting_track(
  track_df: "pd.DataFrame",
  pvx: float, pvy: float,
  svx: float, svy: float,
  tol: float,
) -> bool:
  import numpy as np
  x1 = track_df['px1'].values.astype(np.float32)
  y1 = track_df['py1'].values.astype(np.float32)
  x2 = track_df['px2'].values.astype(np.float32)
  y2 = track_df['py2'].values.astype(np.float32)

  # endpoint-1 near primary AND endpoint-2 near secondary
  ep1_near_p = np.hypot(x1 - pvx, y1 - pvy) < tol
  ep2_near_s = np.hypot(x2 - svx, y2 - svy) < tol
  ep1_near_s = np.hypot(x1 - svx, y1 - svy) < tol
  ep2_near_p = np.hypot(x2 - pvx, y2 - pvy) < tol

  return bool(
    ((ep1_near_p & ep2_near_s) | (ep1_near_s & ep2_near_p)).any()
  )


def main() -> None:
  ap = argparse.ArgumentParser(
    description="Filter ΛΛ pairs by connecting track")
  ap.add_argument("--pairs",          type=Path, required=True)
  ap.add_argument("--chunks",         type=Path,
                  default=Path("results"),
                  help="Directory containing chunk_NNNN.parquet")
  ap.add_argument("--output",         type=Path, required=True)
  ap.add_argument("--min-n-primary",  type=int, default=5)
  ap.add_argument("--max-n-primary",  type=int, default=0)
  ap.add_argument("--tol",            type=float, default=50.0,
                  help="Endpoint proximity tolerance (px)")
  ap.add_argument("--min-intens",     type=float, default=8.0,
                  help="min_intens for connecting track candidates")
  args = ap.parse_args()

  import pandas as pd
  import numpy as np
  sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

  print(f"Loading {args.pairs} …", flush=True)
  pairs = pd.read_parquet(args.pairs)
  pairs = pairs[pairs['p_ntracks'] >= args.min_n_primary]
  if args.max_n_primary > 0:
    pairs = pairs[pairs['p_ntracks'] <= args.max_n_primary]
  print(f"  {len(pairs):,} pairs to check", flush=True)

  print("Building view→chunk map …", flush=True)
  v2c = _build_view_chunk_map(args.chunks)
  print(f"  {len(v2c)} views in {len(set(v2c.values()))} chunks")

  # group by chunk to load each chunk only once
  def view_num(vid: str) -> int:
    m = re.search(r'V(\d+)_L0', vid)
    return int(m.group(1)) if m else -1

  pairs = pairs.copy()
  pairs['_view_num'] = pairs['view_id'].map(view_num)
  pairs['_chunk']    = pairs['_view_num'].map(lambda n: v2c.get(n, -1))

  connected: list[int] = []
  chunk_cache: dict[int, "pd.DataFrame"] = {}

  print("Searching connecting tracks …", flush=True)
  for row_idx, row in pairs.iterrows():
    chunk_id = int(row['_chunk'])
    if chunk_id < 0:
      continue

    if chunk_id not in chunk_cache:
      cp = args.chunks / f"chunk_{chunk_id:04d}.parquet"
      try:
        df = pd.read_parquet(cp)
        if args.min_intens > 0:
          df = df[df['mean_intens'] >= args.min_intens]
        chunk_cache[chunk_id] = df
      except Exception as e:
        print(f"  WARNING chunk {chunk_id}: {e}", file=sys.stderr)
        continue

    chunk_df = chunk_cache[chunk_id]
    view_tracks = chunk_df[chunk_df['view_id'] == row['view_id']]
    if view_tracks.empty:
      continue

    if _has_connecting_track(
      view_tracks,
      float(row['p_vx']), float(row['p_vy']),
      float(row['s_vx']), float(row['s_vy']),
      args.tol,
    ):
      connected.append(int(row_idx))

  print(f"  Found {len(connected):,} pairs with connecting track "
        f"({100*len(connected)/max(len(pairs),1):.1f}%)")

  result = pairs.loc[connected].drop(
    columns=['_view_num', '_chunk'], errors='ignore'
  )

  args.output.parent.mkdir(parents=True, exist_ok=True)
  result.to_parquet(args.output, index=False)
  print(f"Saved → {args.output}")


if __name__ == "__main__":
  main()
