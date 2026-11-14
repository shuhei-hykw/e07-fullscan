"""Truth-free check of the review rankers on the real full scan: does a
candidate a ranker puts in the top K of its view reappear in the top K
of an overlapping view?

Neighbouring views overlap by ~52 % per axis, so a plate spot is imaged
up to four times. Each top-K candidate lying at least EDGE_PX inside its
own view and inside a neighbour view (plate coordinates as in
segment_repro.py) is one trial; it reappears if that neighbour's top K
has a candidate within R_UM in xy and DZ_UM in stage z. Rankers:
the columns of the score files plus darkness and a random score (the
chance level of picking K points per view). A ranker that keeps stable
image structure reappears often; one that keeps noise or rendering-
specific traits does not. Stability is not truth: a persistent dark
blob reappears too.

  python scripts/rank_reappear.py   # -> results/fullscan_union/reappear.txt
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.spatial import cKDTree

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))
from segment_repro import (CENTRE_PX, IMAGE_PX, PX_TO_UM,  # noqa: E402
                           UM_TO_PX)

DIR = REPO / "results/fullscan_union"
UNION = DIR / "union.parquet"
SCORES = {"logistic": DIR / "scores_full.parquet",
          "logistic_no_mi": DIR / "scores_nomi.parquet"}
OUT = DIR / "reappear.txt"
KS = (1, 2, 4, 8, 16, 64)
R_UM = (6.0, 12.0)
DZ_UM = 15.0
EDGE_PX = 100       # synthetic vertices sit >= 100 px from the edge
UM_PER_MM = 1000.0
SEED = 0


def inside(xy, centre_um):
  px = (xy - centre_um) @ UM_TO_PX.T + CENTRE_PX
  return ((px >= EDGE_PX) & (px <= IMAGE_PX - 1 - EDGE_PX)).all(axis=1)


def reappear(d, col, k, r):
  top = (d.sort_values(col, ascending=False, kind="stable")
         .groupby("view", sort=False).head(k))
  xy, z = top[["px", "py"]].to_numpy(), top.z.to_numpy()
  vid = top.vid.to_numpy()
  own = inside(xy, top[["cx", "cy"]].to_numpy())
  tree = cKDTree(xy)
  hits = tree.query_ball_point(xy, r)
  centres = d.groupby("vid")[["cx", "cy"]].first()
  grid = d.groupby("vid")[["gx", "gy"]].first()
  at = {(a, b): v for v, (a, b) in grid.iterrows()}
  n = m = 0
  for i in np.flatnonzero(own):
    gx, gy = grid.loc[vid[i]]
    seen = {vid[j] for j in hits[i]
            if vid[j] != vid[i] and abs(z[j] - z[i]) <= DZ_UM}
    for dx in (-1, 0, 1):
      for dy in (-1, 0, 1):
        w = at.get((gx + dx, gy + dy))
        if w is None or w == vid[i]:
          continue
        if not inside(xy[i:i + 1], centres.loc[w].to_numpy()[None])[0]:
          continue
        n += 1
        m += w in seen
  return n, m


def main():
  d = pd.read_parquet(UNION, columns=["view", "vx_px", "vy_px", "z_mean",
                                      "view_x_mm", "view_y_mm",
                                      "darkness"])
  for c in ("view_x_mm", "view_y_mm"):
    d[c] = d.groupby("view")[c].transform("first")
  for name, f in SCORES.items():
    s = pd.read_parquet(f, columns=["union_row", "review_score"])
    d[name] = np.nan
    d.loc[s.union_row.to_numpy(), name] = s.review_score.to_numpy()
  d["random"] = np.random.default_rng(SEED).random(len(d))
  d["cx"] = d.view_x_mm * UM_PER_MM
  d["cy"] = d.view_y_mm * UM_PER_MM
  px = d[["vx_px", "vy_px"]].to_numpy() - CENTRE_PX
  xy = d[["cx", "cy"]].to_numpy() + px @ PX_TO_UM.T
  d["px"], d["py"] = xy[:, 0], xy[:, 1]
  d["z"] = d.z_mean * UM_PER_MM
  d["vid"] = pd.factorize(d.view)[0]
  g = d.view.str.extract(r"VX(\d+)_VY(\d+)").astype(int)
  d["gx"], d["gy"] = g[0], g[1]
  d = d.dropna(subset=list(SCORES) + ["darkness"])
  lines = [f"{UNION.name}: {len(d)} rows, dz {DZ_UM:g} um, edge "
           f"{EDGE_PX} px; reappeared / trials in the neighbour top K"]
  for r in R_UM:
    for k in KS:
      row = [f"r {r:g} um K {k:3d}:"]
      for col in list(SCORES) + ["darkness", "random"]:
        n, m = reappear(d, col, k, r)
        row.append(f"{col} {m}/{n} ({m / max(n, 1):.3f})")
      lines.append("  ".join(row))
      print(lines[-1], flush=True)
  OUT.write_text("\n".join(lines) + "\n")


if __name__ == "__main__":
  main()
