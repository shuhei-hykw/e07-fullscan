#!/usr/bin/env python
"""Spatial distribution map of merged vertex candidates.

Usage:
  python scripts/vertex_map.py \
    --input  results/vertices_merged.parquet \
    --output results/vertex_map.png \
    --min-slices 3 \
    --min-tracks 5
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path


def main() -> None:
  ap = argparse.ArgumentParser(
    description="Vertex spatial distribution map")
  ap.add_argument("--input",       type=Path,
                  default=Path("results/vertices_merged.parquet"))
  ap.add_argument("--output",      type=Path,
                  default=Path("results/vertex_map.png"))
  ap.add_argument("--min-slices",  type=int,   default=3,
                  help="Min n_slices to include")
  ap.add_argument("--min-tracks",  type=int,   default=5,
                  help="Min n_tracks_max to include")
  ap.add_argument("--vmax",        type=int,   default=None,
                  help="Color scale max (n_tracks_max)")
  args = ap.parse_args()

  import sys
  import numpy as np
  import pandas as pd
  import matplotlib
  matplotlib.use('Agg')
  import matplotlib.pyplot as plt
  import matplotlib.colors as mcolors

  sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
  from module.run_info import (
    make_run_id, build_run_meta, save_run_json,
  )

  run_id = make_run_id()
  run_params = {k: str(v) for k, v in vars(args).items()}
  run_meta = build_run_meta(run_id, __file__, run_params)
  print(f"run_id: {run_id}")

  df = pd.read_parquet(args.input)
  sel = df[
    (df['n_slices']     >= args.min_slices) &
    (df['n_tracks_max'] >= args.min_tracks)
  ]
  print(f"Total merged vertices  : {len(df):,}")
  print(f"After cuts (sl>={args.min_slices}, n>={args.min_tracks}): "
        f"{len(sel):,}")

  if len(sel) == 0:
    print("No vertices to plot.", file=sys.stderr)
    return

  vmax = args.vmax or int(sel['n_tracks_max'].quantile(0.99))

  fig, axes = plt.subplots(1, 2, figsize=(14, 6))

  # --- left: scatter plot coloured by n_tracks_max ---
  ax = axes[0]
  sc = ax.scatter(
    sel['view_x_mm'], sel['view_y_mm'],
    c=sel['n_tracks_max'], cmap='hot_r',
    vmin=args.min_tracks, vmax=vmax,
    s=4, alpha=0.6, linewidths=0,
  )
  plt.colorbar(sc, ax=ax, label='n_tracks_max')
  ax.set_xlabel('view_x_mm')
  ax.set_ylabel('view_y_mm')
  ax.set_title(f'Vertex positions  n>={args.min_tracks}  sl>={args.min_slices}'
               f'  N={len(sel):,}')
  ax.set_aspect('equal')
  ax.invert_yaxis()

  # --- right: 2D histogram (density map) ---
  ax2 = axes[1]
  nx = max(10, int((sel['view_x_mm'].max() - sel['view_x_mm'].min())
                   / 0.31) + 1)
  ny = max(10, int((sel['view_y_mm'].max() - sel['view_y_mm'].min())
                   / 0.31) + 1)
  h, xedge, yedge = np.histogram2d(
    sel['view_x_mm'], sel['view_y_mm'], bins=[nx, ny])
  im = ax2.imshow(
    h.T, origin='upper',
    extent=[xedge[0], xedge[-1], yedge[-1], yedge[0]],
    cmap='viridis', aspect='equal',
    norm=mcolors.LogNorm(vmin=1),
  )
  plt.colorbar(im, ax=ax2, label='vertex count per FOV')
  ax2.set_xlabel('view_x_mm')
  ax2.set_ylabel('view_y_mm')
  ax2.set_title('Vertex density map')

  plt.tight_layout()
  args.output.parent.mkdir(parents=True, exist_ok=True)
  plt.savefig(args.output, dpi=120)
  print(f"Saved → {args.output}")
  json_path = save_run_json(run_meta, args.output)
  print(f"Run metadata → {json_path}")

  # text summary
  print(f"\nn_tracks_max stats:")
  print(sel['n_tracks_max'].describe().to_string())
  print(f"\nn_slices stats:")
  print(sel['n_slices'].describe().to_string())


if __name__ == "__main__":
  main()
