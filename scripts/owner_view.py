"""Owner-view assignment: keep each union candidate only in the view
whose centre is nearest to it in plate xy (the central ~0.5 mm square
of each view), so every plate spot is reviewed in one view and the
dark vignetted corners drop out.

Reports the kept counts per source and the recall of the 70 eye-good
stars (any kept candidate of any view within R_UM in xy and DZ_UM of
the star z), with all candidates as the reference and a star moved by
CONTROL_SHIFT_UM as the chance control.

  python scripts/owner_view.py
  # -> results/fullscan_union/owner_view.txt, owner_view.parquet
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.spatial import cKDTree

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))
from rank_reappear import DIR, UM_PER_MM  # noqa: E402
from segment_repro import CENTRE_PX, PX_TO_UM  # noqa: E402

UNION = DIR / "union.parquet"
STARS = REPO / "results/real_vertices_good_v6.csv"
OUT = DIR / "owner_view.txt"
KEEP = DIR / "owner_view.parquet"
R_UM = (6.0, 12.0)
DZ_UM = 30.0        # as in star_recall.py
CONTROL_SHIFT_UM = 40.0


def main():
  d = pd.read_parquet(UNION, columns=["view", "source", "vx_px", "vy_px",
                                      "z_mean", "view_x_mm", "view_y_mm"])
  for c in ("view_x_mm", "view_y_mm"):
    d[c] = d.groupby("view")[c].transform("first")
  c = d[["view_x_mm", "view_y_mm"]].to_numpy() * UM_PER_MM
  xy = c + (d[["vx_px", "vy_px"]].to_numpy() - CENTRE_PX) @ PX_TO_UM.T
  views = d.groupby("view")[["view_x_mm", "view_y_mm"]].first()
  names = views.index.to_numpy()
  _, near = cKDTree(views.to_numpy() * UM_PER_MM).query(xy)
  d["own"] = names[near] == d.view.to_numpy()
  d["px"], d["py"] = xy[:, 0], xy[:, 1]
  d["z"] = d.z_mean * UM_PER_MM
  pd.DataFrame({"union_row": np.flatnonzero(d.own.to_numpy())}).to_parquet(
    KEEP, index=False)

  lines = [f"{UNION.name}: {len(d)} rows, kept {d.own.sum()} "
           f"({d.own.mean():.3f})"]
  for s, g in d.groupby("source"):
    lines.append(f"  {s}: {len(g)} -> {g.own.sum()} ({g.own.mean():.3f})")

  st = pd.read_csv(STARS)
  sc = views.loc[st.view].to_numpy() * UM_PER_MM
  sxy = sc + (st[["x_px", "y_px"]].to_numpy() - CENTRE_PX) @ PX_TO_UM.T
  sz = st.z_best_mm.to_numpy() * UM_PER_MM
  lines.append(f"{STARS.name}: {len(st)} stars, dz {DZ_UM:g} um; "
               "recalled by any view")
  for shift in (0.0, CONTROL_SHIFT_UM):
    for r in R_UM:
      row = [f"  shift {shift:g} um r {r:g} um:"]
      for label, q in (("all", d), ("owner", d[d.own])):
        tree = cKDTree(q[["px", "py"]].to_numpy())
        z = q.z.to_numpy()
        src = q.source.to_numpy()
        hit = {"A": 0, "Bprime": 0, "union": 0}
        for p, zz in zip(sxy + [shift, 0.0], sz):
          idx = np.array(tree.query_ball_point(p, r), dtype=int)
          idx = idx[np.abs(z[idx] - zz) <= DZ_UM]
          for k in ("A", "Bprime"):
            hit[k] += bool((src[idx] == k).any())
          hit["union"] += bool(len(idx))
        row.append(f"{label} " + " ".join(
          f"{k} {v / len(st):.2f}" for k, v in hit.items()))
      lines.append("  ".join(row))
  print("\n".join(lines))
  OUT.write_text("\n".join(lines) + "\n")


if __name__ == "__main__":
  main()
