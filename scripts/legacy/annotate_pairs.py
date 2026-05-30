#!/usr/bin/env python
"""Annotate ΛΛ pair candidates with connecting-track properties.

For each pair in the input parquet, finds the best connecting track
and records: length, mean_intens, grain_density, angle_diff (deviation
from the P→S axis).  These properties help discriminate heavy-particle
false positives from genuine ΛΛ events.

Heavy-particle signature:
  - connecting track nearly co-linear with P→S axis (small angle_diff)
  - high mean_intens (bright thick track)
  - length ≈ dist_px  (track spans exactly the vertex separation)

Usage:
  python scripts/annotate_pairs.py \\
    --pairs   results/vertex_pairs_v7_strong.parquet \\
    --output  results/vertex_pairs_v7_strong_ann.parquet \\
    --tol     50
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


TOL_DEFAULT = 50.0


def _load_chunk(chunk_dir: Path, chunk_id: int) -> "pd.DataFrame | None":
  cp = chunk_dir / f"chunk_{chunk_id:04d}.parquet"
  if not cp.exists():
    return None
  import pandas as pd
  cols = ['view_id', 'px1', 'py1', 'px2', 'py2',
          'mean_intens', 'grain_density']
  try:
    df = pd.read_parquet(cp, columns=cols)
    return df
  except Exception:
    try:
      df = pd.read_parquet(cp,
                           columns=['view_id','px1','py1','px2','py2',
                                    'mean_intens'])
      df['grain_density'] = 0.0
      return df
    except Exception:
      return None


def _view_num(vid: str) -> int:
  m = re.search(r'V(\d+)_L0', vid)
  return int(m.group(1)) if m else -1


def _annotate_row(
  view_tracks: "pd.DataFrame",
  pvx: float, pvy: float,
  svx: float, svy: float,
  dist_px: float,
  tol: float,
) -> dict:
  """Return connecting-track properties for one pair."""
  import numpy as np

  x1 = view_tracks['px1'].values.astype(np.float32)
  y1 = view_tracks['py1'].values.astype(np.float32)
  x2 = view_tracks['px2'].values.astype(np.float32)
  y2 = view_tracks['py2'].values.astype(np.float32)

  ep1_near_p = np.hypot(x1 - pvx, y1 - pvy) < tol
  ep2_near_s = np.hypot(x2 - svx, y2 - svy) < tol
  ep1_near_s = np.hypot(x1 - svx, y1 - svy) < tol
  ep2_near_p = np.hypot(x2 - pvx, y2 - pvy) < tol

  mask = (ep1_near_p & ep2_near_s) | (ep1_near_s & ep2_near_p)
  if not mask.any():
    return {
      'conn_found': False,
      'conn_length': 0.0,
      'conn_mean_intens': 0.0,
      'conn_grain_density': 0.0,
      'conn_angle_diff': 0.0,
      'conn_len_ratio': 0.0,
    }

  # P→S direction vector
  ps_dx = svx - pvx
  ps_dy = svy - pvy
  ps_angle = float(np.arctan2(ps_dy, ps_dx))

  ct = view_tracks[mask]

  # pick the longest connecting track as the primary candidate
  cx1 = ct['px1'].values.astype(np.float32)
  cy1 = ct['py1'].values.astype(np.float32)
  cx2 = ct['px2'].values.astype(np.float32)
  cy2 = ct['py2'].values.astype(np.float32)
  lengths = np.hypot(cx2 - cx1, cy2 - cy1)
  best_i  = int(np.argmax(lengths))

  tr_dx = cx2[best_i] - cx1[best_i]
  tr_dy = cy2[best_i] - cy1[best_i]
  tr_angle = float(np.arctan2(tr_dy, tr_dx))

  # smallest angle between the two directions (0°–90°)
  diff = abs(ps_angle - tr_angle)
  diff = min(diff, np.pi - diff)
  angle_diff_deg = float(np.degrees(diff))

  length = float(lengths[best_i])
  mi = float(ct['mean_intens'].iloc[best_i])
  gd = float(ct['grain_density'].iloc[best_i]) \
      if 'grain_density' in ct.columns else 0.0

  return {
    'conn_found': True,
    'conn_length': length,
    'conn_mean_intens': mi,
    'conn_grain_density': gd,
    'conn_angle_diff': angle_diff_deg,
    'conn_len_ratio': length / dist_px if dist_px > 0 else 0.0,
  }


def main() -> None:
  ap = argparse.ArgumentParser(
    description="Annotate ΛΛ pairs with connecting-track properties")
  ap.add_argument("--pairs",  type=Path, required=True)
  ap.add_argument("--output", type=Path, required=True)
  ap.add_argument("--tol",    type=float, default=TOL_DEFAULT)
  args = ap.parse_args()

  import numpy as np
  import pandas as pd
  sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

  proj_root = Path(__file__).resolve().parents[2]
  chunk_dir = proj_root / 'results'

  print(f"Loading {args.pairs} …", flush=True)
  pairs = pd.read_parquet(args.pairs)
  n = len(pairs)
  print(f"  {n} pairs", flush=True)

  chunk_cache: dict[int, "pd.DataFrame | None"] = {}
  records: list[dict] = []

  for i, (_, row) in enumerate(pairs.iterrows()):
    if i % 20 == 0:
      print(f"  {i}/{n} …", flush=True)

    vid      = row['view_id']
    vn       = _view_num(vid)
    chunk_id = vn // 15 + 1

    if chunk_id not in chunk_cache:
      chunk_cache[chunk_id] = _load_chunk(chunk_dir, chunk_id)

    chunk_df = chunk_cache[chunk_id]
    if chunk_df is None:
      records.append({})
      continue

    view_tracks = chunk_df[chunk_df['view_id'] == vid]
    if view_tracks.empty:
      records.append({})
      continue

    props = _annotate_row(
      view_tracks,
      float(row['p_vx']), float(row['p_vy']),
      float(row['s_vx']), float(row['s_vy']),
      float(row['dist_px']),
      args.tol,
    )
    records.append(props)

  # merge into dataframe
  ann_df = pd.DataFrame(records, index=pairs.index)
  result = pd.concat([pairs, ann_df], axis=1)

  args.output.parent.mkdir(parents=True, exist_ok=True)
  result.to_parquet(args.output, index=False)
  print(f"Saved → {args.output}")

  # print summary table
  print(
    f"\n{'Rank':>4}  {'View':<22}  {'Pn':>3}  {'Sn':>3}  "
    f"{'dist':>6}  {'len':>5}  {'gd':>6}  {'intens':>6}  "
    f"{'adiff':>5}  {'lrat':>5}"
  )
  print("-" * 80)
  for rank, (_, row) in enumerate(result.iterrows()):
    vid_short = row['view_id'].split('/') [-1].replace('_L0_VX.json', '')
    found = bool(row.get('conn_found', False))
    if found:
      print(
        f"{rank+1:>4}  {vid_short:<22}  "
        f"{int(row['p_ntracks']):>3}  {int(row['s_ntracks']):>3}  "
        f"{row['dist_um']:>6.0f}μm  "
        f"{row['conn_length']:>5.0f}  "
        f"{row['conn_grain_density']:>6.3f}  "
        f"{row['conn_mean_intens']:>6.1f}  "
        f"{row['conn_angle_diff']:>5.1f}°  "
        f"{row['conn_len_ratio']:>5.2f}"
      )
    else:
      print(
        f"{rank+1:>4}  {vid_short:<22}  "
        f"{int(row['p_ntracks']):>3}  {int(row['s_ntracks']):>3}  "
        f"{row['dist_um']:>6.0f}μm  "
        f"{'--':>5}  {'--':>6}  {'--':>6}  {'--':>5}  {'--':>5}"
      )


if __name__ == "__main__":
  main()
