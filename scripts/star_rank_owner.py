"""Eye-good star ranks under owner-view assignment and the blob veto.

For the 70 eye-good stars, the best in-view rank of any matching
candidate (within R_UM in xy and DZ_UM in z, any view) when each view
ranks only its owner-view candidates (owner_view.py), optionally after
dropping blob_thick_px above each VETO_PX cut (fullscan_blob.py), and
the fraction of stars with any match in the pool. Rankers: darkness,
both logistic models, n_tracks_max and random; a CONTROL_SHIFT_UM
shifted star is the chance control. Also reports the blob and edge
share of each ranker's top 16 over all candidates.

  python scripts/star_rank_owner.py
  # -> results/fullscan_union/star_rank_owner.txt
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

BLOB = cv.DIR / "blob.parquet"
OUT = cv.DIR / "star_rank_owner.txt"
R_UM = 12.0
DZ_UM = 30.0
VETO_PX = (5.0, 6.0, 8.0, 10.0)   # v26 captures are <= 5 px (ac46411)
EDGE_PX = 100
TOP = 16
CONTROL_SHIFT_UM = 40.0
RANK_CUTS = (1, 4, 16, 64, 256)
RANKERS = ["darkness"] + list(SCORES) + ["n_tracks_max", "random"]


def best_ranks(q, sxy, sz):
  tree = cKDTree(q[["px", "py"]].to_numpy())
  z = q.z.to_numpy()
  out = {}
  for r in RANKERS:
    rk = q["rk_" + r].to_numpy()
    b = []
    for p, zz in zip(sxy, sz):
      i = np.array(tree.query_ball_point(p, R_UM), dtype=int)
      i = i[np.abs(z[i] - zz) <= DZ_UM]
      b.append(rk[i].min() if len(i) else np.inf)
    out[r] = np.array(b)
  return out


def main():
  d = cv.load()
  rng = np.random.default_rng(SEED)
  u = pd.read_parquet(cv.UNION, columns=["n_tracks_max"])
  d["n_tracks_max"] = u.n_tracks_max + JITTER * rng.random(len(d))
  d["random"] = rng.random(len(d))
  for name, f in SCORES.items():
    s = pd.read_parquet(f, columns=["union_row", "review_score"])
    d.loc[s.union_row.to_numpy(), name] = s.review_score.to_numpy()
  b = pd.read_parquet(BLOB, columns=["union_row", "blob_thick_px"])
  d.loc[b.union_row.to_numpy(), "thick"] = b.blob_thick_px.to_numpy()
  f = pd.read_parquet(cv.FEATURES, columns=["union_row", "edge_px"])
  d.loc[f.union_row.to_numpy(), "edge"] = f.edge_px.to_numpy()
  own = np.zeros(len(d), bool)
  own[pd.read_parquet(cv.OWNER).union_row.to_numpy()] = True

  lines = []
  for v in VETO_PX:
    lines.append(f"blob_thick_px > {v:g}: " + ", ".join(
      f"{s} {(g.thick > v).mean():.3f}" for s, g in d.groupby("source")))
  for r in RANKERS:
    t = d.sort_values(r, ascending=False).groupby("view").head(TOP)
    lines.append(f"  top {TOP} {r}: blob > " + " / ".join(
      f"{v:g} {(t.thick > v).mean():.2f}" for v in VETO_PX)
      + f"  edge<{EDGE_PX} {(t.edge < EDGE_PX).mean():.2f}")

  st = pd.read_csv(cv.STARS)
  views = d.groupby("view")[["view_x_mm", "view_y_mm"]].first()
  sxy = (views.loc[st.view].to_numpy() * cv.UM_PER_MM
         + (st[["x_px", "y_px"]].to_numpy() - cv.CENTRE_PX) @ cv.PX_TO_UM.T)
  sz = st.z_best_mm.to_numpy() * cv.UM_PER_MM
  lines.append(f"{len(st)} stars, r {R_UM:g} um, dz {DZ_UM:g} um; best "
               "in-view rank over any view, fraction <= " +
               "/".join(map(str, RANK_CUTS)))
  sets = [("all", np.ones(len(d), bool)), ("owner", own)]
  sets += [(f"owner+veto{v:g}", own & (d.thick.to_numpy() <= v))
           for v in VETO_PX]
  for label, mask in sets:
    q = d[mask].copy()
    for r in RANKERS:
      q["rk_" + r] = q.groupby("view")[r].rank(ascending=False,
                                               method="first")
    for shift in (0.0, CONTROL_SHIFT_UM):
      best = best_ranks(q, sxy + [shift, 0.0], sz)
      anym = np.isfinite(best["random"]).mean()
      lines.append(f"  {label} ({len(q)} rows) shift {shift:g} um: "
                   f"any match {anym:.2f}")
      for r, v in best.items():
        lines.append(f"    {r:15s} " + " ".join(
          f"{(v <= c).mean():.2f}" for c in RANK_CUTS))
  print("\n".join(lines))
  OUT.write_text("\n".join(lines) + "\n")


if __name__ == "__main__":
  main()
