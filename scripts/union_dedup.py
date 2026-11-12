"""How many full-scan union candidates are the same object seen twice.

Neighbouring views overlap by ~52 % per axis, so a plate spot is imaged
about four times. Candidates go to plate coordinates (stage x/y x 1000 +
segment_repro.PX_TO_UM @ (px - centre), z = stage z) and are linked when
they come from different views and lie within R_UM in xy and DZ_UM in z;
connected groups count as one object. The same link with view b moved
by CONTROL_SHIFT_UM gives the chance level.

  python scripts/union_dedup.py   # -> results/fullscan_union/dedup.txt
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components
from scipy.spatial import cKDTree

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))
from segment_repro import CENTRE_PX, PX_TO_UM  # noqa: E402

UNION = REPO / "results/fullscan_union/union.parquet"
OUT = REPO / "results/fullscan_union/dedup.txt"
R_UM = (5.0, 10.0)
DZ_UM = 15.0
CONTROL_SHIFT_UM = 40.0
UM_PER_MM = 1000.0


def main():
  d = pd.read_parquet(UNION, columns=["view", "vx_px", "vy_px", "z_mean",
                                      "view_x_mm", "view_y_mm", "source"])
  # B' rows carry no stage position; take the view's from its A rows
  for c in ("view_x_mm", "view_y_mm"):
    d[c] = d.groupby("view")[c].transform("first")
  px = d[["vx_px", "vy_px"]].to_numpy() - CENTRE_PX
  xy = (d[["view_x_mm", "view_y_mm"]].to_numpy() * UM_PER_MM
        + px @ PX_TO_UM.T)
  z = d.z_mean.to_numpy() * UM_PER_MM
  vid = pd.factorize(d.view)[0]
  lines = [f"{UNION.name}: dz {DZ_UM:g} um, control shift "
           f"{CONTROL_SHIFT_UM:g} um"]
  for src in ("A", "Bprime", "all"):
    m = (np.ones(len(d), bool) if src == "all"
         else (d.source == src).to_numpy())
    a, za, va, n = xy[m], z[m], vid[m], int(m.sum())
    for r in R_UM:
      out = []
      for shift in (0.0, CONTROL_SHIFT_UM):
        pr = cKDTree(a).sparse_distance_matrix(
          cKDTree(a + [shift, 0.0]), r, output_type="coo_matrix")
        i, j = pr.row, pr.col
        ok = (va[i] != va[j]) & (np.abs(za[i] - za[j]) <= DZ_UM)
        g = coo_matrix((np.ones(ok.sum()), (i[ok], j[ok])), shape=(n, n))
        out.append(connected_components(g, directed=False)[0])
      lines.append(f"{src} r {r:g} um: {n} -> {out[0]} objects "
                   f"({out[0] / n:.3f}; control {out[1] / n:.3f})")
      print(lines[-1], flush=True)
  OUT.write_text("\n".join(lines) + "\n")


if __name__ == "__main__":
  main()
