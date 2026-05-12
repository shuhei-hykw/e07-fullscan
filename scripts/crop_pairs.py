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

  # map global → crop coords
  def g2c(gx: int, gy: int):
    return (gx - x0, gy - y0)

  pc = g2c(pvx, pvy)
  sc = g2c(svx, svy)

  # primary vertex: large green circle
  cv2.circle(vis, pc, 18, (0, 220, 0), 2)
  cv2.putText(vis, f"P n={p_ntracks}", (pc[0]+20, pc[1]-10),
              cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 220, 0), 1)

  # secondary vertex: cyan circle
  cv2.circle(vis, sc, 14, (255, 200, 0), 2)
  cv2.putText(vis, f"S n={s_ntracks}", (sc[0]+16, sc[1]-10),
              cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 200, 0), 1)

  # arrow from primary to secondary
  cv2.arrowedLine(vis, pc, sc, (180, 180, 255), 1, tipLength=0.1)

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

  sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
  from e07fullscan.io import SpngReader

  print(f"Loading {args.pairs} …", flush=True)
  pairs = pd.read_parquet(args.pairs)
  print(f"  {len(pairs):,} pairs total")

  pairs = pairs[pairs['p_ntracks'] >= args.min_n_primary]
  print(f"  {len(pairs):,} after p_ntracks >= {args.min_n_primary}")
  if args.max_n_primary > 0:
    pairs = pairs[pairs['p_ntracks'] <= args.max_n_primary]
    print(f"  {len(pairs):,} after p_ntracks <= {args.max_n_primary}")

  # sort by primary n_tracks_max desc, then secondary n_tracks desc
  pairs = pairs.sort_values(
    ['p_ntracks', 's_ntracks', 'dist_px'],
    ascending=[False, False, True]
  ).head(args.top)
  print(f"  Generating {len(pairs)} crops → {args.output}")

  args.output.mkdir(parents=True, exist_ok=True)
  saved = 0

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
    img = stack[lo:hi + 1].mean(axis=0).astype(np.uint8)

    pvx = int(round(row['p_vx']))
    pvy = int(round(row['p_vy']))
    svx = int(round(row['s_vx']))
    svy = int(round(row['s_vy']))

    vis = _draw_pair_crop(
      img, pvx, pvy, svx, svy,
      int(row['p_ntracks']), int(row['s_ntracks']),
      half=args.crop_half,
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
