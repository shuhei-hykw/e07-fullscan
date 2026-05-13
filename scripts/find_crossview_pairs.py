#!/usr/bin/env python3
"""Find ΛΛ-topology vertex pairs that span adjacent views (cross-view pairs).

The primary vertex may be in one view while the secondary is in an
adjacent view.  This happens when the Ξ⁻ decay vertex falls near the
boundary of a scan view, leaving insufficient tracks on one side.

Usage:
  python scripts/find_crossview_pairs.py \\
    --vertices results/vertices_merged_v5.parquet \\
    --output   results/vertex_pairs_xview_v1.parquet

Algorithm:
  1. Compute stage (mm) coordinates for every vertex using Convention C:
       stage_x = view_cx - (vx_px - 1024) * PX_SCALE_MM
       stage_y = view_cy + (vy_px - 1024) * PX_SCALE_MM
  2. Build a KDTree on stage coords.
  3. For each primary vertex (n_tracks_max >= min_n_primary), query
     all vertices within d_max_mm.
  4. Keep cross-view pairs (different view_id) in [d_min_mm, d_max_mm].
  5. Apply n_tracks, n_slices, and Z-separation cuts.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.spatial import cKDTree


PX_SCALE_MM  = 0.00029   # mm/pixel (0.29 μm/px)
D_MIN_UM     = 90.0      # μm
D_MAX_UM     = 500.0     # μm
D_MIN_MM     = D_MIN_UM  / 1000.0
D_MAX_MM     = D_MAX_UM  / 1000.0
MAX_DZ_MM    = 0.200     # 200 μm — allows dip angles up to ~45° at 500 μm


def _stage_xy(df: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
  """Return (stage_x_mm, stage_y_mm) arrays using Convention C."""
  sx = df['view_x_mm'].values - (df['vx_px'].values - 1024) * PX_SCALE_MM
  sy = df['view_y_mm'].values + (df['vy_px'].values - 1024) * PX_SCALE_MM
  return sx.astype(np.float64), sy.astype(np.float64)


def find_crossview_pairs(
  df: pd.DataFrame,
  min_n_primary:   int   = 5,
  min_n_secondary: int   = 3,
  min_sl_secondary: int  = 2,
  d_min_mm: float        = D_MIN_MM,
  d_max_mm: float        = D_MAX_MM,
  max_dz_mm: float       = MAX_DZ_MM,
) -> pd.DataFrame:
  """Cross-view vertex pair finder.

  Returns DataFrame with one row per candidate pair, same schema as
  find_vertex_pairs() plus stage-coordinate columns.
  """
  sx, sy = _stage_xy(df)
  nt  = df['n_tracks_max'].values
  nsl = df['n_slices'].values if 'n_slices' in df.columns else np.ones(len(df))
  zv  = df['z_mean'].values.astype(np.float32) if 'z_mean' in df.columns \
        else df['z'].values.astype(np.float32)
  view_ids = df['view_id'].values
  vx = df['vx_px'].values
  vy = df['vy_px'].values
  view_cx = df['view_x_mm'].values
  view_cy = df['view_y_mm'].values

  has_spread = 'angle_spread_best' in df.columns
  sp = df['angle_spread_best'].values if has_spread else None

  coords = np.column_stack([sx, sy])
  tree = cKDTree(coords)

  primary_idx = np.where(nt >= min_n_primary)[0]
  secondary_mask = (
    (nt >= min_n_secondary) & (nsl >= min_sl_secondary)
  )

  PX_SCALE_UM = PX_SCALE_MM * 1000.0  # mm → μm

  records: list[dict] = []
  seen: set[tuple[int, int]] = set()

  for pi in primary_idx:
    neighbors = tree.query_ball_point(coords[pi], r=d_max_mm)
    for si in neighbors:
      if si == pi:
        continue
      if view_ids[pi] == view_ids[si]:
        continue  # intra-view pairs handled elsewhere
      if not secondary_mask[si]:
        continue
      # NOTE: do NOT require nt[pi] >= nt[si]; at a view boundary the
      # primary vertex is truncated and may appear weaker than secondary.

      key = (min(pi, si), max(pi, si))
      if key in seen:
        continue
      seen.add(key)

      d_mm = float(np.hypot(sx[pi]-sx[si], sy[pi]-sy[si]))
      if d_mm < d_min_mm:
        continue
      dz = abs(float(zv[pi]) - float(zv[si]))
      if dz > max_dz_mm:
        continue

      d_um = d_mm * 1000.0
      rec = {
        'view_id_p':    view_ids[pi],
        'view_id_s':    view_ids[si],
        'view_x_mm':    float(view_cx[pi]),
        'view_y_mm':    float(view_cy[pi]),
        'p_vx':         float(vx[pi]),
        'p_vy':         float(vy[pi]),
        'p_sx':         float(sx[pi]),
        'p_sy':         float(sy[pi]),
        'p_ntracks':    int(nt[pi]),
        'p_nslices':    int(nsl[pi]),
        'p_z':          float(zv[pi]),
        's_vx':         float(vx[si]),
        's_vy':         float(vy[si]),
        's_sx':         float(sx[si]),
        's_sy':         float(sy[si]),
        's_ntracks':    int(nt[si]),
        's_nslices':    int(nsl[si]),
        's_z':          float(zv[si]),
        'dist_um':      d_um,
        'dist_px':      d_um / PX_SCALE_UM,
        'dz_mm':        dz,
      }
      if has_spread and sp is not None:
        rec['p_angle_spread'] = (
          float(sp[pi]) if not np.isnan(sp[pi]) else 0.0)
        sp_si = df['angle_spread_best'].iloc[si]
        rec['s_angle_spread'] = (
          float(sp_si) if not np.isnan(sp_si) else 0.0)
      records.append(rec)

  if not records:
    return pd.DataFrame()
  return pd.DataFrame(records)


def main() -> None:
  ap = argparse.ArgumentParser(description="Cross-view ΛΛ pair finder")
  ap.add_argument("--vertices",       type=Path, required=True)
  ap.add_argument("--output",         type=Path, required=True)
  ap.add_argument("--min-n-primary",  type=int,  default=5)
  ap.add_argument("--min-n-secondary",type=int,  default=3)
  ap.add_argument("--min-sl-secondary",type=int, default=2)
  ap.add_argument("--d-min-um",       type=float,default=D_MIN_UM)
  ap.add_argument("--d-max-um",       type=float,default=D_MAX_UM)
  ap.add_argument("--max-dz-mm",      type=float,default=MAX_DZ_MM)
  args = ap.parse_args()

  print(f"Loading {args.vertices} …", flush=True)
  df = pd.read_parquet(args.vertices)
  print(f"  {len(df):,} vertices")

  pairs = find_crossview_pairs(
    df,
    min_n_primary   = args.min_n_primary,
    min_n_secondary = args.min_n_secondary,
    min_sl_secondary= args.min_sl_secondary,
    d_min_mm        = args.d_min_um / 1000.0,
    d_max_mm        = args.d_max_um / 1000.0,
    max_dz_mm       = args.max_dz_mm,
  )

  print(f"  {len(pairs):,} cross-view pairs found")
  if len(pairs):
    args.output.parent.mkdir(parents=True, exist_ok=True)
    pairs.to_parquet(args.output, index=False)
    print(f"Saved → {args.output}")
    # Summary stats
    print(f"  p_ntracks: {pairs['p_ntracks'].describe()['min']:.0f}"
          f" – {pairs['p_ntracks'].describe()['max']:.0f}")
    print(f"  s_ntracks: {pairs['s_ntracks'].describe()['min']:.0f}"
          f" – {pairs['s_ntracks'].describe()['max']:.0f}")
    print(f"  dist_um:   {pairs['dist_um'].min():.1f}"
          f" – {pairs['dist_um'].max():.1f}")
  else:
    print("  No pairs found.")


if __name__ == "__main__":
  main()
