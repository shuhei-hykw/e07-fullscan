"""Why do eye-good real stars rank high while sim captures do not?

Compares the review features of three populations:
  capture  sim capture candidates of the v26 embedded set (union cut,
           labelled within LABEL_R of the capture, peer simlabels)
  sim bg   all other union candidates of the same embedded set
  star     full-scan union candidates matching the 70 eye-good stars
           (within R_UM in xy and DZ_UM in z, best darkness per star)
  real bg  all full-scan owner-view union candidates
Prints the median and the 10th/90th percentiles per feature and the
percentile of each population's median within its own background.

  python scripts/star_vs_capture.py
  # -> results/sim_eval/star_vs_capture.txt
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.spatial import cKDTree

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))
import cross_view_presence as cv  # noqa: E402
import oracle_rank as orc  # noqa: E402

SET = "v26_embed_nagara_dz4"
LABEL_R = "is_capture_12um"
R_UM = 12.0
DZ_UM = 30.0
COLS = ["n_tracks_max", "n_slices", "mean_intens", "angle_spread_best",
        "darkness", "z_span_um", "dist_other_um"]
QS = (10, 50, 90)
OUT = orc.SIM / "star_vs_capture.txt"


def star_rows(d, f):
  """Best-darkness matching union row for each eye-good star."""
  st = pd.read_csv(cv.STARS)
  views = d.groupby("view")[["view_x_mm", "view_y_mm"]].first()
  sxy = (views.loc[st.view].to_numpy() * cv.UM_PER_MM
         + (st[["x_px", "y_px"]].to_numpy() - cv.CENTRE_PX)
         @ cv.PX_TO_UM.T)
  sz = st.z_best_mm.to_numpy() * cv.UM_PER_MM
  tree = cKDTree(d[["px", "py"]].to_numpy())
  z, dark = d.z.to_numpy(), d.darkness.fillna(-np.inf).to_numpy()
  rows = []
  for p, zz in zip(sxy, sz):
    i = np.array(tree.query_ball_point(p, R_UM), dtype=int)
    i = i[np.abs(z[i] - zz) <= DZ_UM]
    if len(i):
      rows.append(i[dark[i].argmax()])
  return f.set_index("union_row").loc[rows].reset_index()


def describe(name, g, bg):
  out = [f"{name} (n={len(g)})"]
  for c in COLS:
    x = g[c].replace(np.inf, np.nan).dropna()
    b = bg[c].replace(np.inf, np.nan).dropna()
    q = np.percentile(x, QS) if len(x) else [np.nan] * len(QS)
    pct = (b < np.median(x)).mean() if len(x) else np.nan
    out.append(f"  {c:18s} p10/50/90 " + " / ".join(f"{v:.1f}" for v in q)
               + f"   median at bg pct {pct:.2f}")
  return out


def main():
  emb = orc.load(SET, f"{SET}_emb.parquet")
  cap, sbg = emb[emb[LABEL_R]], emb[~emb[LABEL_R]]
  d = cv.load()
  f = pd.read_parquet(cv.FEATURES)
  own = pd.read_parquet(cv.OWNER).union_row
  rbg = f[f.union_row.isin(own)]
  star = star_rows(d, f)
  lines = []
  for name, g, bg in (("capture", cap, sbg), ("sim bg", sbg, sbg),
                      ("star", star, rbg), ("real bg", rbg, rbg)):
    lines += describe(name, g, bg)
    lines.append(f"  A share {(g.source == 'A').mean():.2f}")
  print("\n".join(lines))
  OUT.write_text("\n".join(lines) + "\n")


if __name__ == "__main__":
  main()
