"""Cross-view presence on real positives: for the 70 eye-good stars,
the presence multiplicity (n_match of n_cover overlapping views,
presence.parquet from cross_view_presence.py) of the star's matched
owner-view candidate, against all owner-view candidates. Checks
whether the sim two-view presence of captures (83-88 %, peer
crossview) is realistic for real vertices.

  python scripts/star_presence.py
  # -> results/fullscan_union/star_presence.txt
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.spatial import cKDTree

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))
import cross_view_presence as cv  # noqa: E402

R_UM = 12.0
DZ_UM = 30.0
OUT = cv.DIR / "star_presence.txt"


def summary(name, g):
  c = g[g.n_cover > 0]
  frac = c.n_match / c.n_cover
  dist = c.n_match.value_counts(normalize=True).sort_index()
  return [f"{name} (n={len(g)}, covered {len(c)}): any {(c.n_match > 0)
          .mean():.2f}, mean fraction {frac.mean():.2f}, mean n_cover "
          f"{c.n_cover.mean():.1f}",
          "  n_match share " + " ".join(f"{int(k)}:{v:.2f}"
                                        for k, v in dist.items())]


def main():
  d = cv.load()
  p = pd.read_parquet(cv.OUT)
  d["n_cover"], d["n_match"] = p.n_cover.to_numpy(), p.n_match.to_numpy()
  own = np.zeros(len(d), bool)
  own[pd.read_parquet(cv.OWNER).union_row.to_numpy()] = True
  q = d[own]
  st = pd.read_csv(cv.STARS)
  views = d.groupby("view")[["view_x_mm", "view_y_mm"]].first()
  sxy = (views.loc[st.view].to_numpy() * cv.UM_PER_MM
         + (st[["x_px", "y_px"]].to_numpy() - cv.CENTRE_PX)
         @ cv.PX_TO_UM.T)
  sz = st.z_best_mm.to_numpy() * cv.UM_PER_MM
  tree = cKDTree(q[["px", "py"]].to_numpy())
  z, frac = q.z.to_numpy(), (q.n_match / q.n_cover.clip(lower=1)).to_numpy()
  xy = q[["px", "py"]].to_numpy()
  best, near = [], []
  for pp, zz in zip(sxy, sz):
    i = np.array(tree.query_ball_point(pp, R_UM), dtype=int)
    i = i[np.abs(z[i] - zz) <= DZ_UM]
    if len(i):   # most-present (biased up) and closest matching candidate
      best.append(i[frac[i].argmax()])
      near.append(i[np.hypot(*(xy[i] - pp).T).argmin()])
  lines = (summary("stars, most-present match", q.iloc[best])
           + summary("stars, closest match", q.iloc[near])
           + summary("owner bg", q))
  for s, g in q.groupby("source"):
    lines += summary(f"owner bg {s}", g)
  print("\n".join(lines))
  OUT.write_text("\n".join(lines) + "\n")


if __name__ == "__main__":
  main()
