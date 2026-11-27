"""Why do the top n_tracks_max sites of a view not reappear in the top K
of an overlapping view? Match each top-K method A site against ALL A
candidates of each overlapping neighbour view (not only its top K).

For each (site, neighbour) trial with the site at least EDGE_PX inside
both views, report the fraction matched within R_UM in xy at dz
DZ_UM (z_best) or with no dz limit, and for matched trials the
neighbour candidate's in-view n_tracks_max rank and z_best difference.
  - matched only without dz  -> z of the merged vertex is unstable
  - matched but ranked low   -> rank instability (heavy-tailed counts)
  - unmatched even at 25 um  -> a view-specific vertex
Populations: the top TOP_K per view, TOP_K random A candidates per
view (a generic A vertex), the top TOP_K moved by CONTROL_SHIFT_UM
(chance matches at that density) and the 70 eye-good stars (their
nearest own-view A candidate).

  python scripts/ntracks_match.py
  # -> results/fullscan_union/ntracks_match.txt
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.spatial import cKDTree

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))
from rank_reappear import (DIR, JITTER, SEED, UM_PER_MM,  # noqa: E402
                           inside)
from segment_repro import CENTRE_PX, PX_TO_UM, UM_TO_PX  # noqa: E402

UNION = DIR / "union.parquet"
STARS = REPO / "results/real_vertices_good_v6.csv"
OUT = DIR / "ntracks_match.txt"
TOP_K = 16
R_UM = (6.0, 12.0, 25.0)
DZ_UM = 15.0
RANK_CUTS = (16, 64, 256)
CONTROL_SHIFT_UM = 40.0


def load():
  d = pd.read_parquet(UNION, columns=["view", "source", "vx_px", "vy_px",
                                      "z_best", "n_tracks_max",
                                      "view_x_mm", "view_y_mm"])
  d = d[d.source == "A"].copy()
  for c in ("view_x_mm", "view_y_mm"):
    d[c] = d.groupby("view")[c].transform("first")
  rng = np.random.default_rng(SEED)
  d["nt"] = d.n_tracks_max + JITTER * rng.random(len(d))
  d["rk"] = d.groupby("view").nt.rank(ascending=False, method="first")
  c = d[["view_x_mm", "view_y_mm"]].to_numpy() * UM_PER_MM
  d["px"], d["py"] = (c + (d[["vx_px", "vy_px"]].to_numpy() - CENTRE_PX)
                      @ PX_TO_UM.T).T
  d["z"] = d.z_best * UM_PER_MM
  g = d.view.str.extract(r"VX(\d+)_VY(\d+)").astype(int)
  d["gx"], d["gy"] = g[0], g[1]
  return d


def trials(d, sites):
  """Yield (site, neighbour candidates) for neighbours covering it."""
  views = d.groupby("view")[["view_x_mm", "view_y_mm", "gx", "gy"]].first()
  at = {(a, b): v for v, (a, b) in views[["gx", "gy"]].iterrows()}
  by_view = {v: (q, cKDTree(q[["px", "py"]].to_numpy()))
             for v, q in d.groupby("view")}
  for s in sites.itertuples():
    v = views.loc[s.view]
    cen = np.array([v.view_x_mm, v.view_y_mm]) * UM_PER_MM
    xy = np.array([s.px, s.py])
    if not inside(xy[None], cen[None])[0]:
      continue
    for dx in (-1, 0, 1):
      for dy in (-1, 0, 1):
        w = at.get((v.gx + dx, v.gy + dy))
        if w is None or w == s.view:
          continue
        wv = views.loc[w]
        wc = np.array([wv.view_x_mm, wv.view_y_mm]) * UM_PER_MM
        if inside(xy[None], wc[None])[0]:
          yield s, by_view[w]


def table(d, sites, label):
  rows = {(r, lim): [] for r in R_UM for lim in ("dz", "any")}
  n = 0
  for s, (q, tree) in trials(d, sites):
    n += 1
    for r in R_UM:
      idx = tree.query_ball_point([s.px, s.py], r)
      m = q.iloc[idx]
      for lim in ("dz", "any"):
        mm = m[(m.z - s.z).abs() <= DZ_UM] if lim == "dz" else m
        if len(mm):
          j = (mm.z - s.z).abs().idxmin() if lim == "any" else \
            mm.rk.idxmin()
          rows[r, lim].append((mm.rk.min(), mm.z[j] - s.z))
        else:
          rows[r, lim].append((np.inf, np.nan))
  out = [f"{label}: trials {n}"]
  for (r, lim), v in rows.items():
    a = np.array(v, dtype=float)
    hit = np.isfinite(a[:, 0])
    dz = np.abs(a[hit, 1])
    out.append(
      f"  r {r:4g} um {lim:3s}: matched {hit.mean():.2f}"
      + "".join(f"  rank<={c} {(a[:, 0] <= c).mean():.2f}"
                for c in RANK_CUTS)
      + f"  |dz| median {np.median(dz) if len(dz) else np.nan:.1f} um")
  return out


def main():
  d = load()
  top = d[d.rk <= TOP_K]
  st = pd.read_csv(STARS)
  stars = []
  for s in st.itertuples():
    q = d[d.view == s.view]
    dist = (np.hypot(q.vx_px - s.x_px, q.vy_px - s.y_px)
            + np.abs(q.z_best - s.z_best_mm) * UM_PER_MM
            * np.abs(UM_TO_PX).max())
    stars.append(q.loc[dist.idxmin()])
  stars = pd.DataFrame(stars)
  lines = [f"{UNION.name} A rows {len(d)}; neighbour = all A candidates; "
           f"dz {DZ_UM:g} um on z_best; rank = in-view n_tracks_max rank"]
  lines += table(d, top, f"top {TOP_K} n_tracks_max per view")
  rnd = d.sample(frac=1.0, random_state=SEED).groupby("view").head(TOP_K)
  lines += table(d, rnd, f"random {TOP_K} A per view")
  lines += table(d, top.assign(px=top.px + CONTROL_SHIFT_UM),
                 f"top {TOP_K} shifted {CONTROL_SHIFT_UM:g} um")
  lines += table(d, stars, f"eye-good stars ({len(stars)})")
  print("\n".join(lines))
  OUT.write_text("\n".join(lines) + "\n")


if __name__ == "__main__":
  main()
