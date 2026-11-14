"""Renderer-free recall check on the eye-judged real stars: for each
"good" star of the 2026-05-27 sp x nsl crop round
(results/real_vertices_good_v6.csv), do the candidates of an overlapping
neighbour view contain it?

The star was picked by v6 method A in its own view, so the neighbour
view is a second, independent image of the same spot. A trial is a
(star, neighbour) pair with the star at least EDGE_PX inside both views
(plate coordinates as in segment_repro.py); it is recalled by a source
(A, B' top 770, union) if a candidate lies within R_UM in xy and DZ_UM
of the star's z (nearest v7 A candidate in its own view). For recalled
trials the best rank of a match in the neighbour view is reported per
ranker. A control repeats the trials with the star moved by
CONTROL_SHIFT_UM.

  python scripts/star_recall.py   # -> results/fullscan_union/star_recall.txt
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))
from rank_reappear import DIR, SCORES, UM_PER_MM, inside  # noqa: E402
from segment_repro import CENTRE_PX, PX_TO_UM  # noqa: E402

STARS = REPO / "results/real_vertices_good_v6.csv"
UNION = DIR / "union.parquet"
OUT = DIR / "star_recall.txt"
R_UM = (6.0, 12.0)
DZ_UM = 30.0        # star z is the nearest v7 A candidate's, +-5-10 um
CONTROL_SHIFT_UM = 40.0
RANK_CUTS = (1, 4, 16, 64)


def main():
  d = pd.read_parquet(UNION, columns=["view", "vx_px", "vy_px", "z_mean",
                                      "view_x_mm", "view_y_mm", "source",
                                      "darkness"])
  for c in ("view_x_mm", "view_y_mm"):
    d[c] = d.groupby("view")[c].transform("first")
  for name, f in SCORES.items():
    s = pd.read_parquet(f, columns=["union_row", "review_score"])
    d.loc[s.union_row.to_numpy(), name] = s.review_score.to_numpy()
  rankers = list(SCORES) + ["darkness"]
  for r in rankers:
    d["rk_" + r] = d.groupby("view")[r].rank(ascending=False,
                                            method="first")
  c = d[["view_x_mm", "view_y_mm"]].to_numpy() * UM_PER_MM
  d["px"], d["py"] = (c + (d[["vx_px", "vy_px"]].to_numpy() - CENTRE_PX)
                      @ PX_TO_UM.T).T
  d["z"] = d.z_mean * UM_PER_MM
  g = d.view.str.extract(r"VX(\d+)_VY(\d+)").astype(int)
  d["gx"], d["gy"] = g[0], g[1]
  views = d.groupby("view")[["view_x_mm", "view_y_mm", "gx", "gy"]].first()
  at = {(a, b): v for v, (a, b) in views[["gx", "gy"]].iterrows()}
  by_view = dict(list(d.groupby("view")))

  st = pd.read_csv(STARS)
  lines = [f"{STARS.name}: {len(st)} stars, dz {DZ_UM:g} um, edge from "
           "rank_reappear.py; recalled / trials"]
  for shift in (0.0, CONTROL_SHIFT_UM):
    for r in R_UM:
      n = 0
      hit = {"A": 0, "Bprime": 0, "union": 0}
      best = {k: [] for k in rankers}
      for s in st.itertuples():
        v = views.loc[s.view]
        cen = np.array([v.view_x_mm, v.view_y_mm]) * UM_PER_MM
        xy = cen + (np.array([s.x_px, s.y_px]) - CENTRE_PX) @ PX_TO_UM.T
        xy = xy + [shift, 0.0]
        if not inside(xy[None], cen[None])[0]:
          continue
        for dx in (-1, 0, 1):
          for dy in (-1, 0, 1):
            w = at.get((v.gx + dx, v.gy + dy))
            if w is None or w == s.view:
              continue
            wv = views.loc[w]
            wc = np.array([wv.view_x_mm, wv.view_y_mm]) * UM_PER_MM
            if not inside(xy[None], wc[None])[0]:
              continue
            n += 1
            q = by_view[w]
            m = q[(np.hypot(q.px - xy[0], q.py - xy[1]) <= r)
                  & ((q.z - s.z_best_mm * UM_PER_MM).abs() <= DZ_UM)]
            for src in ("A", "Bprime"):
              hit[src] += bool((m.source == src).any())
            hit["union"] += bool(len(m))
            for k in rankers:
              best[k].append(m["rk_" + k].min() if len(m) else np.inf)
      row = [f"shift {shift:g} um r {r:g} um: trials {n}"]
      row += [f"{k} {h} ({h / max(n, 1):.2f})" for k, h in hit.items()]
      lines.append("  ".join(row))
      for k in rankers:
        b = np.array(best[k])
        lines.append(f"    best rank {k}: " + "  ".join(
          f"<={c} {(b <= c).mean():.2f}" for c in RANK_CUTS))
      print("\n".join(lines[-1 - len(rankers):]), flush=True)
  OUT.write_text("\n".join(lines) + "\n")


if __name__ == "__main__":
  main()
