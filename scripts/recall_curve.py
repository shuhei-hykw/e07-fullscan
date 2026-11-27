"""Eye-good star recall versus review budget on the owner-view pool.

Each view ranks its owner-view candidates (owner_view.py) and the top K
are reviewed, so K * n_views unique plate sites are reviewed. A star is
recalled at K if an owner candidate within R_UM in xy and DZ_UM in z
has in-view rank <= K. Rankers: darkness, both logistic models,
n_tracks_max, random (mean over N_RANDOM seeds) and the cross-view
fused scores
  fused_<model> = mean of the candidate's in-view percentile of <model>
                  and, for each covering neighbour view, the best
                  percentile of a match there (0 when none)
(percentiles over all union candidates of a view; matches within R_UM
and DZ_UM, as in cross_view_presence.py). A CONTROL_SHIFT_UM shifted
star gives the chance level. Paired bootstrap over stars gives
intervals for the differences listed in PAIRS.

  python scripts/recall_curve.py
  # -> results/fullscan_union/recall_curve.txt
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.spatial import cKDTree

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))
import cross_view_presence as cv  # noqa: E402
from rank_reappear import JITTER, SCORES, SEED  # noqa: E402

OUT = cv.DIR / "recall_curve.txt"
R_UM = 12.0
DZ_UM = 30.0
KS = (1, 2, 4, 8, 16, 64, 256)
N_RANDOM = 20
N_BOOT = 2000
CI = (2.5, 97.5)
CONTROL_SHIFT_UM = 40.0
AREA_CM2 = 5.0625   # 45 x 45 views at 0.5 mm steps
PAIRS = (("fused_logistic", "logistic"), ("logistic", "darkness"),
         ("fused_logistic", "darkness"), ("logistic", "n_tracks_max"),
         ("logistic", "logistic_no_mi"))
BOOT_KS = (2, 4, 16)


def fused(d, col, cov, both):
  """Mean of own and covering-view best percentiles of col."""
  pct = d.groupby("vid")[col].rank(pct=True).to_numpy()
  vid = d.vid.to_numpy()
  m = pd.DataFrame({"row": both[:, 0], "w": vid[both[:, 1]],
                    "p": pct[both[:, 1]]})
  m = m.groupby(["row", "w"]).p.max().reset_index()
  m = cov.merge(m, on=["row", "w"], how="left").fillna({"p": 0.0})
  s = np.bincount(m.row, weights=m.p, minlength=len(d))
  n = np.bincount(cov.row, minlength=len(d))
  return (pct + s) / (1 + n)


def star_best(q, col, sxy, sz):
  rk = q.groupby("view")[col].rank(ascending=False,
                                   method="first").to_numpy()
  tree = cKDTree(q[["px", "py"]].to_numpy())
  z = q.z.to_numpy()
  out = []
  for p, zz in zip(sxy, sz):
    i = np.array(tree.query_ball_point(p, R_UM), dtype=int)
    i = i[np.abs(z[i] - zz) <= DZ_UM]
    out.append(rk[i].min() if len(i) else np.inf)
  return np.array(out)


def main():
  d = cv.load()
  rng = np.random.default_rng(SEED)
  u = pd.read_parquet(cv.UNION, columns=["n_tracks_max"])
  d["n_tracks_max"] = u.n_tracks_max + JITTER * rng.random(len(d))
  for name, f in SCORES.items():
    s = pd.read_parquet(f, columns=["union_row", "review_score"])
    d.loc[s.union_row.to_numpy(), name] = s.review_score.to_numpy()
  cov, both = cv.covering(d), cv.matches(d, R_UM, DZ_UM)
  for name in SCORES:
    d["fused_" + name] = fused(d, name, cov, both)
  own = np.zeros(len(d), bool)
  own[pd.read_parquet(cv.OWNER).union_row.to_numpy()] = True
  q = d[own].copy()
  n_views = q.view.nunique()

  st = pd.read_csv(cv.STARS)
  views = d.groupby("view")[["view_x_mm", "view_y_mm"]].first()
  sxy = (views.loc[st.view].to_numpy() * cv.UM_PER_MM
         + (st[["x_px", "y_px"]].to_numpy() - cv.CENTRE_PX) @ cv.PX_TO_UM.T)
  sz = st.z_best_mm.to_numpy() * cv.UM_PER_MM
  rankers = (["darkness"] + list(SCORES) + ["fused_" + n for n in SCORES]
             + ["n_tracks_max"])
  lines = [f"owner pool {len(q)} rows, {n_views} views, {len(st)} stars, "
           f"r {R_UM:g} um, dz {DZ_UM:g} um; recall at K per view",
           "K: " + "  ".join(f"{k} ({k * n_views} sites, "
                             f"{k * n_views / AREA_CM2:.0f}/cm2)"
                             for k in KS)]
  best = {}
  for shift in (0.0, CONTROL_SHIFT_UM):
    p = sxy + [shift, 0.0]
    lines.append(f"shift {shift:g} um")
    for r in rankers:
      b = star_best(q, r, p, sz)
      if shift == 0.0:
        best[r] = b
      lines.append(f"  {r:22s} " + " ".join(
        f"{(b <= k).mean():.2f}" for k in KS))
    rec = np.zeros(len(KS))
    for i in range(N_RANDOM):
      q["random"] = np.random.default_rng(SEED + 1 + i).random(len(q))
      b = star_best(q, "random", p, sz)
      rec += np.array([(b <= k).mean() for k in KS])
    lines.append(f"  {'random (mean)':22s} " + " ".join(
      f"{v:.2f}" for v in rec / N_RANDOM))

  boot = np.random.default_rng(SEED).integers(
    0, len(st), size=(N_BOOT, len(st)))
  lines.append(f"paired bootstrap over stars ({N_BOOT}), difference "
               f"[{CI[0]:g}, {CI[1]:g}] %")
  for a, b in PAIRS:
    row = [f"  {a} - {b}:"]
    for k in BOOT_KS:
      diff = (best[a] <= k).astype(float) - (best[b] <= k)
      lo, hi = np.percentile(diff[boot].mean(axis=1), CI) * 100
      row.append(f"K {k} {diff.mean() * 100:+.0f} [{lo:+.0f}, {hi:+.0f}]")
    lines.append("  ".join(row))
  print("\n".join(lines))
  OUT.write_text("\n".join(lines) + "\n")


if __name__ == "__main__":
  main()
