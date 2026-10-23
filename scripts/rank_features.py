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

Which candidate is "the truth" must not depend on the feature being
judged. The candidate nearest the click in XY (within the XY
tolerance, and whose z span reaches the clicked depth) is taken as
the truth for every feature; the best rank of any matching candidate
is reported alongside, since it is equally generous to every feature. Ties are reported as a rank range.

  python scripts/rank_features.py [--merged DIR] [--cuts production]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from module.reader import load_spng

_SPECIALS = Path(os.environ.get(
  "E07_SPECIALS_DIR",
  str(Path(__file__).resolve().parents[2] / "specials_x20")))
_MERGED = Path(__file__).resolve().parents[1] / "results" / "specials_merged"
_GT_PATH = Path(__file__).resolve().parents[1] / "tests" / "specials_gt.json"
_E07 = {"D005", "D013", "IBUKI", "IRRAWADY", "MINO", "T004", "T011"}
# Columns to try, all in the "larger is better" direction.
_FEATURES = ["n_tracks_max", "n_slices", "mean_intens",
             "angle_spread_best", "angle_spread_max", "z_extent"]
_UM_PER_MM = 1000.0
_TOP_N = 10


def true_z_mm(event: str, gt: dict) -> float | None:
  """Stage z (mm) of the clicked slice; z_um in the truth file is that
  value rounded to 0.1 mm, too coarse for the tolerance."""
  path = _SPECIALS / event / "image.json"
  if gt.get("z_slice") is None or not path.exists():
    return None
  return float(load_spng(path).z_positions()[int(gt["z_slice"])])


def z_inside(df: pd.DataFrame, z_mm: float, tol_z_um: float) -> pd.Series:
  """Whether the clicked depth lies in the candidate's z span (+tol).

  A star's tracks leave the vertex towards one side in z, so the
  crossing shows on the slices of that side and z_mean sits off the
  vertex by about half the span; the span itself does contain it."""
  tol = tol_z_um / _UM_PER_MM
  return (df.z_min - tol <= z_mm) & (z_mm <= df.z_max + tol)


def matches(df: pd.DataFrame, gt: dict, z_mm: float | None,
            tol_xy: float, tol_z_um: float) -> tuple[np.ndarray, np.ndarray]:
  """Indices of candidates matching the truth, and their XY distance."""
  d = ((df.vx_px - gt["vx"]) ** 2 + (df.vy_px - gt["vy"]) ** 2) ** 0.5
  near = d <= tol_xy
  if z_mm is not None:
    near &= z_inside(df, z_mm, tol_z_um)
  hit = np.flatnonzero(near.to_numpy())
  return hit, d.to_numpy()[hit]


def rank_range(v: np.ndarray, i: int) -> tuple[int, int]:
  """Best and worst 1-based rank of candidate i, ties included."""
  return int((v > v[i]).sum()) + 1, int((v >= v[i]).sum())


def main() -> int:
  ap = argparse.ArgumentParser()
  ap.add_argument("--merged", type=Path, default=_MERGED)
  ap.add_argument("--cuts", default="production")
  args = ap.parse_args()

  gt_all = json.loads(_GT_PATH.read_text())
  tol_xy = float(gt_all.get("tolerance_xy_px", 200))
  tol_z = float(gt_all.get("tolerance_z_um", 30))
  print(f"truth = nearest candidate within {tol_xy:.0f} px XY whose z "
        f"span is within {tol_z:.0f} um (stage) of the click; ranks are "
        f"best-worst over ties\n")

  rows = []
  for event in sorted(gt_all["events"]):
    path = args.merged / f"{event}__{args.cuts}.parquet"
    if not path.exists():
      continue
    df = pd.read_parquet(path)
    df["z_extent"] = df.z_max - df.z_min
    gt = gt_all["events"][event]
    hit, dist = matches(df, gt, true_z_mm(event, gt), tol_xy, tol_z)
    if hit.size == 0:
      print(f"{event}: truth not among {len(df)} candidates")
      continue
    i = int(hit[np.argmin(dist)])
    row = {"event": event, "plate": "E07" if event in _E07 else "E373",
           "n_cand": len(df), "n_match": int(hit.size),
           "dist_px": round(float(dist.min()))}
    for f in _FEATURES:
      if f not in df:
        continue
      v = df[f].to_numpy()
      lo, hi = rank_range(v, i)
      row[f] = lo
      row[f"{f}_txt"] = f"{lo}" if lo == hi else f"{lo}-{hi}"
      row[f"{f}_any"] = min(rank_range(v, int(j))[0] for j in hit)
    rows.append(row)

  if not rows:
    print(f"no merged tables in {args.merged}")
    return 1
  out = pd.DataFrame(rows)
  shown = ["event", "plate", "n_cand", "n_match", "dist_px"] + [
    f"{f}_txt" for f in _FEATURES if f"{f}_txt" in out]
  print(out[shown].rename(columns=lambda c: c.removesuffix("_txt"))
        .to_string(index=False))
  e07 = out[out.plate == "E07"]
  print("\nE07 rank per feature (lower is better; 'any' = best rank of "
        "any matching candidate):")
  for f in _FEATURES:
    if f in e07:
      print(f"  {f:<20} median {e07[f].median():6.0f}   "
            f"worst {e07[f].max():6.0f}   "
            f"top-{_TOP_N} {int((e07[f] <= _TOP_N).sum())}/{len(e07)}   "
            f"any: median {e07[f + '_any'].median():5.0f} "
            f"top-{_TOP_N} {int((e07[f + '_any'] <= _TOP_N).sum())}"
            f"/{len(e07)}")
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
