"""Would any feature we already compute rank the truth better?

scripts/rank_specials.py showed the true vertex sits at a median rank
of 6 when the list is ordered by n_tracks_max. The catalogue holds
1,516,569 vertices, so anything that moves that rank up is worth
knowing about before building a new one.

This is deliberately descriptive, not a fit. Seven confirmed E07
vertices is far too few to train anything on -- a model chosen by
these seven would be measuring itself. All it asks is: taking each
feature the merge step already produces, one at a time and in the
direction physics says should help, where does the true vertex land?

Every feature here is "higher should be better": more tracks, more
slices, brighter, a wider spread of directions, a longer z extent. A
chance crossing of two nearly parallel tracks is low on all of them.

  python scripts/rank_features.py [--merged DIR] [--cuts production]
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

_MERGED = Path(__file__).resolve().parents[1] / "results" / "specials_merged"
_GT_PATH = Path(__file__).resolve().parents[1] / "tests" / "specials_gt.json"
_E07 = {"D005", "D013", "IBUKI", "IRRAWADY", "MINO", "T004", "T011"}
# Columns to try, all in the "larger is better" direction.
_FEATURES = ["n_tracks_max", "n_slices", "mean_intens",
             "angle_spread_best", "angle_spread_max", "z_extent"]


def truth_row(df: pd.DataFrame, gt: dict, tol_xy: float,
              tol_z: float) -> int | None:
  d = ((df.vx_px - gt["vx"]) ** 2 + (df.vy_px - gt["vy"]) ** 2) ** 0.5
  near = d <= tol_xy
  if "z_mean" in df:
    near &= (df.z_mean - gt["z_um"]).abs() <= tol_z
  hit = np.flatnonzero(near.to_numpy())
  if hit.size == 0:
    return None
  # Of the candidates matching the truth, the strongest is the one a
  # human would land on.
  return int(hit[int(np.argmax(df.n_tracks_max.to_numpy()[hit]))])


def main() -> int:
  ap = argparse.ArgumentParser()
  ap.add_argument("--merged", type=Path, default=_MERGED)
  ap.add_argument("--cuts", default="production")
  args = ap.parse_args()

  gt_all = json.loads(_GT_PATH.read_text())
  tol_xy = float(gt_all.get("tolerance_xy_px", 200))
  tol_z = float(gt_all.get("tolerance_z_um", 30))

  rows = []
  for event in sorted(gt_all["events"]):
    path = args.merged / f"{event}__{args.cuts}.parquet"
    if not path.exists():
      continue
    df = pd.read_parquet(path)
    df["z_extent"] = df.z_max - df.z_min
    i = truth_row(df, gt_all["events"][event], tol_xy, tol_z)
    if i is None:
      print(f"{event}: truth not among {len(df)} candidates")
      continue
    row = {"event": event, "plate": "E07" if event in _E07 else "E373",
           "n_cand": len(df)}
    for f in _FEATURES:
      if f not in df:
        continue
      v = df[f].to_numpy()
      # Rank of the truth: how many candidates score strictly higher,
      # plus one. Ties do not inflate the rank.
      row[f] = int((v > v[i]).sum()) + 1
    rows.append(row)

  if not rows:
    print(f"no merged tables in {args.merged}")
    return 1
  out = pd.DataFrame(rows)
  print(out.to_string(index=False))
  e07 = out[out.plate == "E07"]
  print("\nE07 median rank per feature (lower is better):")
  for f in _FEATURES:
    if f in e07:
      print(f"  {f:<20} median {e07[f].median():6.0f}   "
            f"worst {e07[f].max():6.0f}   "
            f"top-10 {int((e07[f] <= 10).sum())}/{len(e07)}")
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
