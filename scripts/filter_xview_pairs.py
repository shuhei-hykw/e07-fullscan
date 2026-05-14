#!/usr/bin/env python
"""Filter cross-view vertex pairs by searching for a connecting track.

For ΛΛ cross-view events, the Ξ⁻ track spans a view boundary:
  - In the primary view: one endpoint near P vertex, the other
    endpoint near the view edge that faces the secondary view.
  - In the secondary view: one endpoint near S vertex, the other
    endpoint near the view edge that faces the primary view.

View-edge direction is inferred from VX/VY indices. Due to the
convention C coordinate flip (stage_x = view_cx − (vx−1024)·scale),
higher VX ↔ higher stage_x ↔ lower pixel_x. So:
  - secondary at higher VX → P exits LEFT (x < EDGE),
                               S enters RIGHT (x > W − EDGE)
  - secondary at lower  VX → P exits RIGHT, S enters LEFT
  - secondary at higher VY → P exits TOP (y < EDGE),
                               S enters BOTTOM (y > H − EDGE)
  - secondary at lower  VY → P exits BOTTOM, S enters TOP

Usage:
  python scripts/filter_xview_pairs.py \\
    --pairs  results/vertex_pairs_xview_v1_filtered.parquet \\
    --chunks results \\
    --output results/vertex_pairs_xview_v1_conn.parquet \\
    --tol 60 --edge 250
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


VIEW_W = 2048
VIEW_H = 2048


def _vxvy(view_id: str) -> tuple[int, int]:
  m = re.search(r'_VX(\d+)_VY(\d+)_', view_id)
  if m:
    return int(m.group(1)), int(m.group(2))
  return -1, -1


def _exit_edge(p_vxvy: tuple, s_vxvy: tuple) -> tuple[str, str]:
  """Return (p_exit_side, s_exit_side) based on VX/VY difference."""
  dx = s_vxvy[0] - p_vxvy[0]
  dy = s_vxvy[1] - p_vxvy[1]
  if abs(dx) >= abs(dy):
    if dx > 0:
      return 'left', 'right'
    else:
      return 'right', 'left'
  else:
    if dy > 0:
      return 'top', 'bottom'
    else:
      return 'bottom', 'top'


def _near_edge(
  x: "np.ndarray", y: "np.ndarray", side: str, edge: float
) -> "np.ndarray":
  if side == 'left':
    return x < edge
  elif side == 'right':
    return x > VIEW_W - edge
  elif side == 'top':
    return y < edge
  else:  # bottom
    return y > VIEW_H - edge


def _has_exit_track(
  view_tracks: "pd.DataFrame",
  vx: float, vy: float,
  exit_side: str,
  tol: float,
  edge: float,
) -> bool:
  import numpy as np

  x1 = view_tracks['px1'].values.astype(np.float32)
  y1 = view_tracks['py1'].values.astype(np.float32)
  x2 = view_tracks['px2'].values.astype(np.float32)
  y2 = view_tracks['py2'].values.astype(np.float32)

  near_v1 = np.hypot(x1 - vx, y1 - vy) < tol
  near_v2 = np.hypot(x2 - vx, y2 - vy) < tol

  # endpoint-1 near vertex, endpoint-2 near exit edge
  e2_at_edge = _near_edge(x2, y2, exit_side, edge)
  # endpoint-2 near vertex, endpoint-1 near exit edge
  e1_at_edge = _near_edge(x1, y1, exit_side, edge)

  return bool(((near_v1 & e2_at_edge) | (near_v2 & e1_at_edge)).any())


def main() -> None:
  ap = argparse.ArgumentParser(
    description="Filter cross-view ΛΛ pairs by boundary-crossing track")
  ap.add_argument("--pairs",  type=Path, required=True)
  ap.add_argument("--chunks", type=Path, default=Path("results"))
  ap.add_argument("--output", type=Path, required=True)
  ap.add_argument("--tol",    type=float, default=60.0,
                  help="Vertex endpoint tolerance (px)")
  ap.add_argument("--edge",   type=float, default=250.0,
                  help="View-edge proximity threshold (px)")
  ap.add_argument("--min-n-primary", type=int, default=6)
  args = ap.parse_args()

  import pandas as pd
  import numpy as np
  sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

  print(f"Loading {args.pairs} …", flush=True)
  pairs = pd.read_parquet(args.pairs)
  pairs = pairs[pairs['p_ntracks'] >= args.min_n_primary]
  n_total = len(pairs)
  print(f"  {n_total:,} pairs to check", flush=True)

  def _vnum(path: str) -> int:
    m = re.search(r'V(\d+)_L0', path)
    return int(m.group(1)) if m else -1

  chunk_cache: dict[int, "pd.DataFrame | None"] = {}

  def _get_tracks(view_path: str) -> "pd.DataFrame | None":
    vn = _vnum(view_path)
    chunk_id = vn // 15 + 1
    if chunk_id not in chunk_cache:
      cp = args.chunks / f"chunk_{chunk_id:04d}.parquet"
      if not cp.exists():
        chunk_cache[chunk_id] = None
      else:
        try:
          chunk_cache[chunk_id] = pd.read_parquet(
            cp, columns=['view_id', 'px1', 'py1', 'px2', 'py2'])
        except Exception:
          chunk_cache[chunk_id] = None
    if chunk_cache[chunk_id] is None:
      return None
    df = chunk_cache[chunk_id]
    vt = df[df['view_id'] == view_path]
    return vt if len(vt) else None

  connected: list[int] = []

  for i, (idx, row) in enumerate(pairs.iterrows()):
    if i % 2000 == 0:
      print(f"  {i}/{n_total} …", flush=True)

    p_vid = str(row['view_id_p'])
    s_vid = str(row['view_id_s'])

    pvxvy = _vxvy(p_vid)
    svxvy = _vxvy(s_vid)
    if pvxvy[0] < 0 or svxvy[0] < 0:
      continue

    p_exit, s_exit = _exit_edge(pvxvy, svxvy)

    # Check primary view: track from P vertex heading toward view boundary
    p_tracks = _get_tracks(p_vid)
    if p_tracks is None:
      continue
    p_ok = _has_exit_track(
      p_tracks,
      float(row['p_vx']), float(row['p_vy']),
      p_exit, args.tol, args.edge,
    )
    if not p_ok:
      continue

    # Check secondary view: track from S vertex heading back toward boundary
    s_tracks = _get_tracks(s_vid)
    if s_tracks is None:
      continue
    s_ok = _has_exit_track(
      s_tracks,
      float(row['s_vx']), float(row['s_vy']),
      s_exit, args.tol, args.edge,
    )
    if s_ok:
      connected.append(int(idx))

  print(f"  Found {len(connected):,} pairs with boundary-crossing tracks "
        f"({100*len(connected)/max(n_total, 1):.1f}%)", flush=True)

  result = pairs.loc[connected]
  args.output.parent.mkdir(parents=True, exist_ok=True)
  result.to_parquet(args.output, index=False)
  print(f"Saved → {args.output}")


if __name__ == "__main__":
  main()
