"""Cross-view presence of every union candidate: of the overlapping
views that also image its plate spot (at least EDGE_PX inside them),
how many have any union candidate within R_UM in xy and DZ_UM in z?

Writes n_cover and n_match per union row, then checks the feature on
the 70 eye-good stars: the in-view rank (among owner-view candidates,
owner_view.py) of the star's best owner candidate when ranked by
presence (n_match / n_cover, ties by darkness) versus darkness alone,
with a CONTROL_SHIFT_UM shifted control for the chance match.

  python scripts/cross_view_presence.py
  # -> results/fullscan_union/presence.{parquet,txt}
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.spatial import cKDTree

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))
from rank_reappear import (DIR, FEATURES, UM_PER_MM,  # noqa: E402
                           inside)
from segment_repro import CENTRE_PX, PX_TO_UM  # noqa: E402

UNION = DIR / "union.parquet"
OWNER = DIR / "owner_view.parquet"
STARS = REPO / "results/real_vertices_good_v6.csv"
OUT = DIR / "presence.parquet"
TXT = DIR / "presence.txt"
R_UM = 12.0
DZ_UM = 30.0        # A vertex z differs ~11 um between views
STAR_R_UM = 12.0
RANK_CUTS = (1, 4, 16, 64)


def load():
  d = pd.read_parquet(UNION, columns=["view", "source", "vx_px", "vy_px",
                                      "z_mean", "view_x_mm", "view_y_mm"])
  for c in ("view_x_mm", "view_y_mm"):
    d[c] = d.groupby("view")[c].transform("first")
  f = pd.read_parquet(FEATURES, columns=["union_row", "darkness"])
  d["darkness"] = np.nan
  d.loc[f.union_row.to_numpy(), "darkness"] = f.darkness.to_numpy()
  c = d[["view_x_mm", "view_y_mm"]].to_numpy() * UM_PER_MM
  d["px"], d["py"] = (c + (d[["vx_px", "vy_px"]].to_numpy() - CENTRE_PX)
                      @ PX_TO_UM.T).T
  d["z"] = d.z_mean * UM_PER_MM
  g = d.view.str.extract(r"VX(\d+)_VY(\d+)").astype(int)
  d["gx"], d["gy"] = g[0], g[1]
  d["vid"] = pd.factorize(d.view)[0]
  return d


def covering(d):
  """(row, w) pairs: neighbour view w also images row's spot."""
  views = d.groupby("vid")[["view_x_mm", "view_y_mm", "gx", "gy"]].first()
  at = {(a, b): v for v, (a, b) in views[["gx", "gy"]].iterrows()}
  xy = d[["px", "py"]].to_numpy()
  gx, gy = d.gx.to_numpy(), d.gy.to_numpy()
  cover = []
  for dx in (-1, 0, 1):
    for dy in (-1, 0, 1):
      if dx == dy == 0:
        continue
      w = np.array([at.get((a + dx, b + dy), -1)
                    for a, b in zip(gx, gy)])
      ok = w >= 0
      cen = np.zeros_like(xy)
      cen[ok] = views.loc[w[ok], ["view_x_mm", "view_y_mm"]].to_numpy() \
        * UM_PER_MM
      ok[ok] = inside(xy[ok], cen[ok])
      cover.append(np.where(ok, w, -1))
  cover = np.stack(cover, axis=1)
  cov = pd.DataFrame({"row": np.repeat(np.arange(len(d)), cover.shape[1]),
                      "w": cover.ravel()})
  return cov[cov.w >= 0]


def matches(d, r_um=R_UM, dz_um=DZ_UM):
  """(row, other) index pairs in different views within r_um, dz_um."""
  vid, z = d.vid.to_numpy(), d.z.to_numpy()
  pairs = cKDTree(d[["px", "py"]].to_numpy()).query_pairs(
    r_um, output_type="ndarray")
  pairs = pairs[(vid[pairs[:, 0]] != vid[pairs[:, 1]])
                & (np.abs(z[pairs[:, 0]] - z[pairs[:, 1]]) <= dz_um)]
  return np.concatenate([pairs, pairs[:, ::-1]])


def presence(d):
  cov = covering(d)
  both = matches(d)
  # unique (row, other view) matches, counted only for covering views
  hit = pd.DataFrame({"row": both[:, 0], "w": d.vid.to_numpy()[both[:, 1]]})
  m = cov.merge(hit.drop_duplicates(), on=["row", "w"])
  n_cover = np.bincount(cov.row, minlength=len(d))
  n_match = np.bincount(m.row, minlength=len(d))
  return n_cover, n_match


def star_ranks(d, own, shift):
  st = pd.read_csv(STARS)
  views = d.groupby("view")[["view_x_mm", "view_y_mm"]].first()
  sc = views.loc[st.view].to_numpy() * UM_PER_MM
  sxy = sc + (st[["x_px", "y_px"]].to_numpy() - CENTRE_PX) @ PX_TO_UM.T
  sxy = sxy + [shift, 0.0]
  sz = st.z_best_mm.to_numpy() * UM_PER_MM
  q = d[own]
  tree = cKDTree(q[["px", "py"]].to_numpy())
  best = {"presence": [], "darkness": []}
  for p, zz in zip(sxy, sz):
    idx = np.array(tree.query_ball_point(p, STAR_R_UM), dtype=int)
    idx = idx[np.abs(q.z.to_numpy()[idx] - zz) <= DZ_UM]
    for k in best:
      best[k].append(q["rk_" + k].to_numpy()[idx].min()
                     if len(idx) else np.inf)
  return best


def main():
  d = load()
  n_cover, n_match = presence(d)
  d["n_cover"], d["n_match"] = n_cover, n_match
  pd.DataFrame({"union_row": np.arange(len(d)), "n_cover": n_cover,
                "n_match": n_match}).to_parquet(OUT, index=False)
  own = np.zeros(len(d), bool)
  own[pd.read_parquet(OWNER).union_row.to_numpy()] = True
  frac = np.where(n_cover > 0, n_match / np.maximum(n_cover, 1), np.nan)
  d["pres"] = frac
  q = d[own].copy()
  q["key"] = q.pres.fillna(-1) + q.darkness.rank(pct=True) * 1e-3
  for k, col in (("presence", "key"), ("darkness", "darkness")):
    d.loc[q.index, "rk_" + k] = q.groupby("view")[col].rank(
      ascending=False, method="first")
  lines = [f"{UNION.name}: r {R_UM:g} um, dz {DZ_UM:g} um"]
  for s, g in d.groupby("source"):
    c = g.n_cover > 0
    lines.append(f"  {s}: covered {c.mean():.3f}, present in >=1 "
                 f"covering view {(g.n_match[c] > 0).mean():.3f}, "
                 f"mean fraction {frac[g.index][c].mean():.3f}")
  for shift in (0.0, 40.0):
    best = star_ranks(d, own, shift)
    for k, b in best.items():
      b = np.array(b)
      lines.append(f"  stars shift {shift:g} um, owner rank by {k}: "
                   + "  ".join(f"<={c} {(b <= c).mean():.2f}"
                               for c in RANK_CUTS)
                   + f"  any {np.isfinite(b).mean():.2f}")
  print("\n".join(lines))
  TXT.write_text("\n".join(lines) + "\n")


if __name__ == "__main__":
  main()
