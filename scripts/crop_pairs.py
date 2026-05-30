#!/usr/bin/env python
"""Generate two-vertex crop images for ΛΛ pair candidates.

For each candidate pair (primary + secondary vertex), outputs a single
PNG showing both vertices in context with a connecting arrow.

Usage:
  python scripts/crop_pairs.py \\
    --pairs   results/vertex_pairs_v5.parquet \\
    --output  results/pair_crops_v5 \\
    --top     200 \\
    --min-n-primary 10
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np


def _draw_pair_crop(
  img: np.ndarray,
  pvx: int, pvy: int, svx: int, svy: int,
  p_ntracks: int, s_ntracks: int,
  half: int = 320,
  conn_tracks: "list[tuple] | None" = None,
  dist_um: float = 0.0,
  rank: int = 0,
  p_spread: float = 0.0,
  s_spread: float = 0.0,
  conn_intens: float = 0.0,
  conn_gd: float = 0.0,
) -> np.ndarray:
  import cv2

  # bounding box that contains both vertices + half margin
  cx = (pvx + svx) // 2
  cy = (pvy + svy) // 2
  x0 = max(0,              cx - half)
  y0 = max(0,              cy - half)
  x1 = min(img.shape[1],   cx + half)
  y1 = min(img.shape[0],   cy + half)
  crop = img[y0:y1, x0:x1].copy()
  vis  = cv2.cvtColor(crop, cv2.COLOR_GRAY2BGR)

  def g2c(gx: int, gy: int):
    return (gx - x0, gy - y0)

  # draw connecting tracks (Λ flight paths) in orange
  if conn_tracks:
    for (cx1, cy1, cx2, cy2) in conn_tracks:
      cv2.line(vis, g2c(cx1, cy1), g2c(cx2, cy2), (0, 128, 255), 1)

  # arrow from primary to secondary (Λ flight direction)
  pc = g2c(pvx, pvy)
  sc = g2c(svx, svy)
  cv2.arrowedLine(vis, pc, sc, (200, 200, 255), 1, tipLength=0.08)

  # primary vertex: large green circle
  cv2.circle(vis, pc, 18, (0, 220, 0), 2)
  p_label = (f"P n={p_ntracks} sp={p_spread:.0f}"
             if p_spread > 0 else f"P n={p_ntracks}")
  cv2.putText(vis, p_label, (pc[0]+20, pc[1]-10),
              cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 220, 0), 1)

  # secondary vertex: cyan circle
  cv2.circle(vis, sc, 14, (255, 200, 0), 2)
  s_label = (f"S n={s_ntracks} sp={s_spread:.0f}"
             if s_spread > 0 else f"S n={s_ntracks}")
  cv2.putText(vis, s_label, (sc[0]+16, sc[1]-10),
              cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 200, 0), 1)

  # info text
  if dist_um > 0:
    cv2.putText(vis, f"#{rank} d={dist_um:.0f}um", (4, 18),
                cv2.FONT_HERSHEY_SIMPLEX, 0.45, (200, 200, 200), 1)
  if conn_intens > 0:
    flag_col = (0, 80, 255) if conn_intens > 35 else (160, 160, 160)
    cv2.putText(vis, f"I={conn_intens:.1f} gd={conn_gd:.2f}", (4, 36),
                cv2.FONT_HERSHEY_SIMPLEX, 0.4, flag_col, 1)

  return vis


def main() -> None:
  ap = argparse.ArgumentParser(description="Crop ΛΛ pair candidates")
  ap.add_argument("--pairs",          type=Path, required=True)
  ap.add_argument("--output",         type=Path, required=True)
  ap.add_argument("--top",            type=int,  default=200,
                  help="Max number of crops to generate")
  ap.add_argument("--min-n-primary",  type=int,  default=10)
  ap.add_argument("--max-n-primary",  type=int,  default=0,
                  help="Max n_tracks_max for primary (0=no limit)")
  ap.add_argument("--crop-half",      type=int,  default=320,
                  help="Half-size (px) of crop window around midpoint")
  ap.add_argument("--n-z-project",    type=int,  default=9,
                  help="Number of z-slices for projection (±half around z_mean)")
  args = ap.parse_args()

  import cv2
  import pandas as pd

  import re

  sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
  from module.io import SpngReader

  print(f"Loading {args.pairs} …", flush=True)
  pairs = pd.read_parquet(args.pairs)
  print(f"  {len(pairs):,} pairs total")

  pairs = pairs[pairs['p_ntracks'] >= args.min_n_primary]
  print(f"  {len(pairs):,} after p_ntracks >= {args.min_n_primary}")
  if args.max_n_primary > 0:
    pairs = pairs[pairs['p_ntracks'] <= args.max_n_primary]
    print(f"  {len(pairs):,} after p_ntracks <= {args.max_n_primary}")

  # sort by primary n_tracks_max desc, then secondary n_tracks desc
  # add score column if not present
  if 'score' not in pairs.columns:
    pairs = pairs.copy()
    pairs['score'] = (pairs['p_ntracks'] * pairs['s_ntracks']
                      / np.log1p(pairs['dist_px']))

  pairs = pairs.sort_values('score', ascending=False).head(args.top)
  print(f"  Generating {len(pairs)} crops → {args.output}")

  # build chunk lookup for connecting track overlay
  chunk_dir = Path(args.pairs).parent.parent if 'results/' in str(args.pairs) \
              else Path('results')
  # guess chunk dir as project/results
  import sys as _sys
  proj_root = Path(__file__).resolve().parents[1]
  chunk_dir = proj_root / 'results'

  def _view_num(vid: str) -> int:
    m = re.search(r'V(\d+)_L0', vid)
    return int(m.group(1)) if m else -1

  chunk_cache: dict[int, "pd.DataFrame"] = {}

  def _get_view_tracks(vid: str) -> "pd.DataFrame | None":
    vn = _view_num(vid)
    if vn < 0:
      return None
    # each chunk has 15 views in order
    chunk_id = vn // 15 + 1
    if chunk_id not in chunk_cache:
      cp = chunk_dir / f"chunk_{chunk_id:04d}.parquet"
      if not cp.exists():
        return None
      try:
        chunk_cache[chunk_id] = pd.read_parquet(
          cp, columns=['view_id','px1','py1','px2','py2','mean_intens'])
      except Exception:
        return None
    df = chunk_cache[chunk_id]
    vt = df[df['view_id'] == vid]
    return vt if len(vt) else None

  args.output.mkdir(parents=True, exist_ok=True)
  saved = 0
  CONN_TOL = 30.0  # px tolerance for connecting track endpoints

  for rank, (_, row) in enumerate(pairs.iterrows()):
    json_path = Path(row['view_id'])
    if not json_path.exists():
      continue
    try:
      reader = SpngReader(json_path)
      stack  = reader.read_stack()
    except Exception as e:
      print(f"  WARNING {json_path.name}: {e}", file=sys.stderr)
      continue

    # z-projection around primary vertex z_mean
    z_vals = np.array([e.z for e in reader.entries])
    best   = int(np.argmin(np.abs(z_vals - row['p_z'])))
    half_z = args.n_z_project // 2
    lo = max(0, best - half_z)
    hi = min(len(stack) - 1, best + half_z)
    proj = stack[lo:hi + 1].mean(axis=0)
    # CLAHE for local contrast enhancement before annotation
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    img = clahe.apply(proj.astype(np.uint8))

    pvx = int(round(row['p_vx']))
    pvy = int(round(row['p_vy']))
    svx = int(round(row['s_vx']))
    svy = int(round(row['s_vy']))

    # find connecting tracks for overlay
    conn_tracks = None
    vt = _get_view_tracks(row['view_id'])
    if vt is not None and len(vt):
      x1 = vt['px1'].values.astype(np.float32)
      y1 = vt['py1'].values.astype(np.float32)
      x2 = vt['px2'].values.astype(np.float32)
      y2 = vt['py2'].values.astype(np.float32)
      near_p1 = np.hypot(x1-pvx, y1-pvy) < CONN_TOL
      near_s2 = np.hypot(x2-svx, y2-svy) < CONN_TOL
      near_p2 = np.hypot(x2-pvx, y2-pvy) < CONN_TOL
      near_s1 = np.hypot(x1-svx, y1-svy) < CONN_TOL
      mask = ((near_p1 & near_s2) | (near_p2 & near_s1))
      if mask.any():
        conn_tracks = [
          (int(x1[i]), int(y1[i]), int(x2[i]), int(y2[i]))
          for i in np.where(mask)[0]
        ]

    # auto-expand crop window to ensure both vertices are visible
    dist_px_row = float(row['dist_px'])
    half = max(args.crop_half, int(dist_px_row / 2) + 80)
    half = min(half, 1000)  # cap at 1000 px to limit file size

    vis = _draw_pair_crop(
      img, pvx, pvy, svx, svy,
      int(row['p_ntracks']), int(row['s_ntracks']),
      half=half,
      conn_tracks=conn_tracks,
      dist_um=float(row.get('dist_um', 0)),
      rank=rank + 1,
      p_spread=float(row.get('p_angle_spread', 0)),
      s_spread=float(row.get('s_angle_spread', 0)),
      conn_intens=float(row.get('conn_mean_intens', 0)),
      conn_gd=float(row.get('conn_grain_density', 0)),
    )

    dist_px = int(round(row['dist_px']))
    stem    = json_path.stem.split('_L0')[0]
    fname   = (f"rank{rank+1:04d}_{stem}"
               f"_pn{int(row['p_ntracks'])}"
               f"_sn{int(row['s_ntracks'])}"
               f"_d{dist_px}px.png")
    cv2.imwrite(str(args.output / fname), vis)
    saved += 1
    if saved % 50 == 0:
      print(f"  … {saved} crops saved", flush=True)

  print(f"Done. {saved} crops saved to {args.output}")


if __name__ == "__main__":
  main()
